"""Control-plane tests for the real joint-CMUL search entry point."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from cmul_graph import expert_direct_graph  # noqa: E402
import run_joint_cmul_search as runner  # noqa: E402


def _proposal(*, threshold=998.0, drop=8):
    graph = expert_direct_graph()
    body = deepcopy(graph["nodes"][4:-4])
    products = [node["id"] for node in body if node["op"] == "multiply"]
    return {
        "schema_version": runner.RESPONSE_SCHEMA_VERSION,
        "body_nodes": body,
        "outputs": {
            "y_re": graph["nodes"][-4]["input"],
            "y_im": graph["nodes"][-3]["input"],
        },
        "multiply_drops": {node_id: drop for node_id in products},
        "rounding": "rne",
        "minimum_sqnr_db": threshold,
    }


def _provider_for(proposal, messages_seen):
    def generate(messages, **kwargs):
        messages_seen.append(deepcopy(messages))
        return {
            "status": "ok",
            "text": json.dumps(proposal, sort_keys=True, separators=(",", ":")),
            "raw_response": {"id": f"fake-{len(messages_seen)}"},
            "usage": {
                "status": "reported",
                "reported": True,
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_tokens": 0,
                "total_tokens": 150,
                "actual_billed_cost": None,
            },
            "elapsed_seconds": 0.01,
            "error": None,
        }

    return generate


def _unexpected_area(_rtl):
    raise AssertionError("quality-failing proposal must not start synthesis")


def _prompt_request(messages):
    return json.loads(messages[1]["content"])


def _restore_body_projection(parsed):
    rows = parsed["normalization"]["body_id_map"]
    inverse = {row["normalized"]: row["original"] for row in rows}
    count = len(rows)
    restored = []
    for node in parsed["constructed_graph"]["nodes"][4 : 4 + count]:
        restored.append(
            {
                "id": inverse[node["id"]],
                "op": node["op"],
                "inputs": [inverse.get(ref, ref) for ref in node["inputs"]],
            }
        )
    return restored


def test_parse_binds_structure_precision_rounding_and_frozen_constraint():
    parsed = runner.parse_proposal(
        json.dumps(_proposal(threshold=60.0, drop=4)), minimum_sqnr_db=60.0
    )
    candidate = parsed["candidate"]
    product_nodes = {
        node["id"]: node for node in candidate["nodes"] if node["op"] == "multiply"
    }
    assert len(product_nodes) == 4
    assert {node["fixed_point"]["drop_lsb"] for node in product_nodes.values()} == {4}
    assert {node["fixed_point"]["rounding"] for node in product_nodes.values()} == {"rne"}
    assert candidate["quality_contract"]["threshold"] == 60.0


def test_alpha_renaming_projection_restores_body_and_only_adds_fixed_shell():
    proposal = _proposal(threshold=140.0, drop=6)
    # Natural arithmetic names may be the same as public output-port names.
    proposal["body_nodes"][-2]["id"] = "y_re"
    proposal["body_nodes"][-1]["id"] = "y_im"
    proposal["outputs"] = {"y_re": "y_re", "y_im": "y_im"}
    original_body = deepcopy(proposal["body_nodes"])
    parsed = runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=140.0)
    graph = parsed["constructed_graph"]
    assert proposal["body_nodes"] == original_body
    assert _restore_body_projection(parsed) == original_body
    normalized_body = graph["nodes"][4 : 4 + len(original_body)]
    assert [node["op"] for node in normalized_body] == [
        node["op"] for node in original_body
    ]
    assert all(node["id"].startswith("joint_body_") for node in normalized_body)
    assert graph["nodes"][:4] == [
        {"id": name, "op": "input"} for name in ("a", "b", "c", "d")
    ]
    assert graph["nodes"][-2:] == [
        {"id": "y_re", "op": "output", "input": "joint_y_re_reg"},
        {"id": "y_im", "op": "output", "input": "joint_y_im_reg"},
    ]
    mapping = {
        row["original"]: row["normalized"]
        for row in parsed["normalization"]["body_id_map"]
    }
    assert graph["nodes"][-4:-2] == [
        {
            "id": "joint_y_re_reg",
            "op": "register",
            "input": mapping["y_re"],
        },
        {
            "id": "joint_y_im_reg",
            "op": "register",
            "input": mapping["y_im"],
        },
    ]
    assert graph["name"].startswith("joint_cmul_model_")


def test_wrong_body_formula_is_rejected_without_arithmetic_repair():
    proposal = _proposal(threshold=140.0, drop=6)
    proposal["outputs"]["y_re"] = "p_ac"
    with pytest.raises(runner.ProposalError) as caught:
        runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=140.0)
    assert caught.value.code == "formula_mismatch"


def test_parse_rejects_model_attempt_to_relax_quality_constraint():
    with pytest.raises(runner.ProposalError, match="frozen experiment threshold") as caught:
        runner.parse_proposal(
            json.dumps(_proposal(threshold=20.0)), minimum_sqnr_db=60.0
        )
    assert caught.value.code == "quality_constraint"


def test_feedback_arms_have_same_budget_and_only_reason_differs(tmp_path):
    seen_with, seen_without = [], []
    proposal = _proposal()
    with_result = runner.run(
        tmp_path / "with",
        2,
        verified_feedback=True,
        minimum_sqnr_db=998.0,
        generate_fn=_provider_for(proposal, seen_with),
        area_evaluator=_unexpected_area,
    )
    without_result = runner.run(
        tmp_path / "without",
        2,
        verified_feedback=False,
        minimum_sqnr_db=998.0,
        generate_fn=_provider_for(proposal, seen_without),
        area_evaluator=_unexpected_area,
    )

    # Attempt one is byte-for-byte the same logical request.  Attempt two has
    # the same measured feedback; the control removes only verified_reason.
    assert seen_with[0] == seen_without[0]
    request_with = _prompt_request(seen_with[1])
    request_without = _prompt_request(seen_without[1])
    feedback_with = request_with["prior_evaluations"][0]
    feedback_without = request_without["prior_evaluations"][0]
    reason = feedback_with.pop("verified_reason")
    assert reason["code"] == "quality_threshold"
    assert feedback_with["candidate_summary"] == {
        "body_nodes": proposal["body_nodes"],
        "outputs": proposal["outputs"],
        "multiply_drops": proposal["multiply_drops"],
        "rounding": proposal["rounding"],
    }
    assert feedback_with == feedback_without
    assert request_with == request_without

    results_with = json.loads(with_result.read_text())
    results_without = json.loads(without_result.read_text())
    assert results_with["budget_totals"] == results_without["budget_totals"] == {
        "proposal_count": 2,
        "evaluation_request_count": 2,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 1,
    }
    assert results_with["proposal_calls"] == results_without["proposal_calls"] == 2
    assert results_with["reported_input_tokens"] == 200
    assert results_with["reported_output_tokens"] == 100


def test_prompt_uses_only_three_most_recent_evaluations():
    prior = []
    for index in range(5):
        prior.append(
            {
                "status": "quality_failed",
                "decision": "rejected",
                "measured_metrics": {"sqnr_db": 130.0 + index},
                "area": None,
                "budget_event": {"proposal_count": 1},
                "cache_hit": False,
                "verified_reason": {"code": f"reason-{index}"},
                "candidate_summary": {
                    "body_nodes": [{"id": f"node_{index}"}],
                    "outputs": {"y_re": f"node_{index}", "y_im": f"node_{index}"},
                    "multiply_drops": {},
                    "rounding": "rne",
                },
            }
        )
    messages = runner.build_messages(
        6,
        prior,
        minimum_sqnr_db=140.0,
        include_verified_reason=True,
    )
    history = _prompt_request(messages)["prior_evaluations"]
    assert len(history) == 3
    assert [row["verified_reason"]["code"] for row in history] == [
        "reason-2",
        "reason-3",
        "reason-4",
    ]
    assert [row["candidate_summary"]["body_nodes"][0]["id"] for row in history] == [
        "node_2",
        "node_3",
        "node_4",
    ]
    assert runner.llm_client.conservative_input_token_bound(messages)["within_limit"] is True


def test_run_persists_full_evidence_and_never_overwrites(tmp_path):
    output = tmp_path / "run"
    result_path = runner.run(
        output,
        1,
        verified_feedback=True,
        minimum_sqnr_db=998.0,
        generate_fn=_provider_for(_proposal(), []),
        area_evaluator=_unexpected_area,
    )
    assert result_path == output / "results.json"
    call = output / "llm_calls/call-001"
    assert {
        "prompt.json",
        "raw_response.json",
        "parsed.json",
        "evaluation.json",
        "tokens.json",
        "cost.json",
        "record.json",
    }.issubset(path.name for path in call.iterdir())
    record = json.loads((call / "record.json").read_text())
    for field in (
        "prompt_sha256",
        "raw_response_sha256",
        "parsed_sha256",
        "evaluation_sha256",
        "tokens_sha256",
        "cost_sha256",
    ):
        assert len(record[field]) == 64
    with pytest.raises(FileExistsError):
        runner.run(
            output,
            1,
            verified_feedback=True,
            generate_fn=_provider_for(_proposal(threshold=60.0), []),
            area_evaluator=_unexpected_area,
        )


def test_parse_rejection_charges_proposal_but_not_evaluation(tmp_path):
    def invalid_provider(messages, **kwargs):
        return {
            "status": "ok",
            "text": "not-json",
            "raw_response": {"id": "invalid"},
            "usage": {
                "status": "reported",
                "reported": True,
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_tokens": 0,
                "total_tokens": 12,
                "actual_billed_cost": None,
            },
        }

    result_path = runner.run(
        tmp_path / "parse-rejection",
        1,
        verified_feedback=True,
        generate_fn=invalid_provider,
        area_evaluator=_unexpected_area,
    )
    results = json.loads(result_path.read_text())
    evaluation = json.loads(
        (tmp_path / "parse-rejection/llm_calls/call-001/evaluation.json").read_text()
    )
    assert evaluation["budget_event"] == {
        "proposal_count": 1,
        "evaluation_request_count": 0,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 0,
    }
    assert evaluation["budget_totals"] == results["budget_totals"] == {
        "proposal_count": 1,
        "evaluation_request_count": 0,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 0,
    }


@pytest.mark.parametrize(
    ("provider_status", "expected_status"),
    [
        ("timeout", "timeout"),
        ("api_error", "tool_failure"),
        ("invalid_request", "tool_failure"),
        ("invalid_response", "tool_failure"),
        ("truncated", "unknown"),
        ("incomplete", "unknown"),
    ],
)
def test_provider_failure_is_undetermined_not_candidate_rejection(
    tmp_path, provider_status, expected_status
):
    def failed_provider(messages, **kwargs):
        return {
            "status": provider_status,
            "text": None,
            "raw_response": None,
            "usage": {
                "status": "unknown",
                "reported": False,
                "input_tokens": None,
                "output_tokens": None,
                "cache_tokens": None,
                "actual_billed_cost": None,
            },
            "error": {"type": "ProviderFailure", "message": "preserved detail"},
        }

    output = tmp_path / provider_status
    result_path = runner.run(
        output,
        1,
        verified_feedback=True,
        generate_fn=failed_provider,
        area_evaluator=_unexpected_area,
    )
    evaluation = json.loads(
        (output / "llm_calls/call-001/evaluation.json").read_text()
    )
    parsed = json.loads((output / "llm_calls/call-001/parsed.json").read_text())
    results = json.loads(result_path.read_text())
    assert evaluation["status"] == expected_status
    assert evaluation["decision"] == "undetermined"
    assert evaluation["verified_reason"] is None
    assert evaluation["diagnostic"] == {
        "type": "ProviderFailure",
        "message": "preserved detail",
    }
    assert evaluation["budget_event"] == {
        "proposal_count": 1,
        "evaluation_request_count": 0,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 0,
    }
    assert parsed["status"] == "not_parsed_provider_undetermined"
    assert parsed["verified_reason"] is None
    assert results["rejected_candidates"] == 0
    assert results["undetermined_candidates"] == 1
    assert results["parse_rejections"] == 0
    assert results["provider_undetermined"] == 1
    assert results["budget_totals"] == evaluation["budget_totals"]


def test_qualified_joint_candidate_reaches_area_evaluation_once(tmp_path):
    rtl_seen = []

    def area(rtl):
        rtl_seen.append(rtl)
        return {
            "status": "ok",
            "value": {
                "status": "ok",
                "area_um2": 1234.5,
                "num_cells": 99,
                "timing": "unverified",
                "power": "unverified",
            },
            "tool_executions": 1,
        }

    result_path = runner.run(
        tmp_path / "qualified",
        2,
        verified_feedback=True,
        minimum_sqnr_db=60.0,
        generate_fn=_provider_for(_proposal(threshold=60.0, drop=4), []),
        area_evaluator=area,
    )
    results = json.loads(result_path.read_text())
    evaluation = json.loads(
        (tmp_path / "qualified/llm_calls/call-001/evaluation.json").read_text()
    )
    assert len(rtl_seen) == 1
    assert "module top" in rtl_seen[0]
    assert evaluation["status"] == "qualified"
    assert evaluation["area"]["area_um2"] == 1234.5
    assert results["qualified_candidates"] == 2
    assert results["budget_totals"]["tool_execution_count"] == 1
    assert results["budget_totals"]["duplicate_proposal_count"] == 1
    assert results["best_qualified_by_area"]["proposal_index"] == 1
    assert results["best_qualified_by_area"]["area"]["area_um2"] == 1234.5
    assert results["best_qualified_by_area"]["measured_metrics"]["sqnr_db"] > 60.0
    proposed = _proposal(threshold=60.0, drop=4)
    assert results["records"][0]["candidate_summary"] == {
        key: proposed[key]
        for key in ("body_nodes", "outputs", "multiply_drops", "rounding")
    }
    second = json.loads(
        (tmp_path / "qualified/llm_calls/call-002/evaluation.json").read_text()
    )
    assert second["cache_hit"] is True


def test_cli_is_dry_by_default(capsys, tmp_path):
    output = tmp_path / "must-not-exist"
    assert runner.main(["--output", str(output), "--calls", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "dry_run"
    assert report["minimum_sqnr_db"] == 140.0
    request = _prompt_request(report["first_messages"])
    assert set(request["response_schema"]) == {
        "schema_version",
        "body_nodes",
        "outputs",
        "multiply_drops",
        "rounding",
        "minimum_sqnr_db",
    }
    assert "graph" not in request["response_schema"]
    assert request["optimization_objective"] == {
        "constraint": "sqnr_db >= 140.0",
        "objective": "minimize strict Nangate45 mapped area among feasible candidates",
        "precision_policy": (
            "precision is negotiable: deliberately explore nonzero product-LSB drops "
            "when the SQNR constraint permits; an exact point remains legal"
        ),
    }
    assert not output.exists()
