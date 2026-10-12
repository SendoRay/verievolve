"""Control-plane tests for the joint FIR search entry point."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from fir_decim_graph import (  # noqa: E402
    expert_direct_graph,
    expert_symmetric_preadd_graph,
)
import run_joint_fir_search as runner  # noqa: E402


def _proposal(*, threshold=60.0, drop=0, graph=None):
    graph = deepcopy(graph if graph is not None else expert_symmetric_preadd_graph())
    products = [
        node["id"] for node in graph["nodes"] if node["op"] == "constant_multiply"
    ]
    return {
        "schema_version": runner.RESPONSE_SCHEMA_VERSION,
        "graph": graph,
        "coefficient_drops": {node_id: drop for node_id in products},
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


def _prompt_request(messages):
    return json.loads(messages[1]["content"])


def _unexpected_area(_rtl):
    raise AssertionError("quality-failing proposal must not start synthesis")


def test_parse_binds_graph_precision_and_frozen_constraint():
    proposal = _proposal(threshold=60.0, drop=4)
    parsed = runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=60.0)
    candidate = parsed["candidate"]
    constants = [node for node in candidate["nodes"] if node["op"] == "constant"]
    assert len(constants) == 8
    assert {node["fixed_point"]["drop_lsb"] for node in constants} == {4}
    assert candidate["quality_contract"]["threshold"] == 60.0
    assert parsed["graph_validation"]["operation_counts"]["constant_multiply"] == 8


def test_parse_accepts_a_distinct_full_graph_not_a_template_name():
    proposal = _proposal(graph=expert_direct_graph())
    parsed = runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=60.0)
    assert parsed["graph_validation"]["operation_counts"]["constant_multiply"] == 16
    assert parsed["proposal"]["graph"] == proposal["graph"]


def test_parse_rejects_formula_mismatch_and_constraint_relaxation():
    wrong = _proposal()
    product = next(
        node for node in wrong["graph"]["nodes"] if node["op"] == "constant_multiply"
    )
    product["coefficient"] += 1
    with pytest.raises(runner.ProposalError) as mismatch:
        runner.parse_proposal(json.dumps(wrong), minimum_sqnr_db=60.0)
    assert mismatch.value.code == "formula_mismatch"

    relaxed = _proposal(threshold=20.0)
    with pytest.raises(runner.ProposalError) as constraint:
        runner.parse_proposal(json.dumps(relaxed), minimum_sqnr_db=60.0)
    assert constraint.value.code == "quality_constraint"


def test_parse_requires_precision_for_every_and_only_product():
    proposal = _proposal()
    proposal["coefficient_drops"].pop(next(iter(proposal["coefficient_drops"])))
    with pytest.raises(runner.ProposalError) as caught:
        runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=60.0)
    assert caught.value.code == "coefficient_drops"


def test_parse_rejects_exact_graph_that_exceeds_backend_integer_domain():
    graph = expert_symmetric_preadd_graph()
    register, output = graph["nodes"][-2:]
    graph["nodes"] = graph["nodes"][:-2]
    source = "fold_p7"
    for index in range(10):
        node_id = f"large_{index}"
        graph["nodes"].append({"id": node_id, "op": "add", "inputs": [source, source]})
        source = node_id
    graph["nodes"].extend(
        [
            {"id": "cancel_large", "op": "sub", "inputs": [source, source]},
            {
                "id": "same_formula",
                "op": "add",
                "inputs": [register["input"], "cancel_large"],
            },
            {**register, "input": "same_formula"},
            output,
        ]
    )
    proposal = _proposal(graph=graph)
    with pytest.raises(runner.ProposalError) as caught:
        runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=60.0)
    assert caught.value.code == "backend_numeric_envelope"


def test_parse_rejects_sample_tree_not_represented_by_current_17_bit_backend():
    graph = expert_symmetric_preadd_graph()
    insert_at = next(
        index for index, node in enumerate(graph["nodes"]) if node["id"] == "pre0"
    )
    graph["nodes"][insert_at:insert_at] = [
        {"id": "sample_pair", "op": "add", "inputs": ["x", "d1"]},
        {"id": "sample_restore", "op": "sub", "inputs": ["sample_pair", "d1"]},
    ]
    pre0 = next(node for node in graph["nodes"] if node["id"] == "pre0")
    pre0["inputs"][0] = "sample_restore"
    proposal = _proposal(graph=graph)
    with pytest.raises(runner.ProposalError) as caught:
        runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=60.0)
    assert caught.value.code == "unsupported_sample_tree"


def test_feedback_arms_have_same_evidence_and_budget_except_reason(tmp_path):
    proposal = _proposal(threshold=200.0, drop=6)
    seen_with, seen_without = [], []
    with_result = runner.run(
        tmp_path / "with",
        2,
        verified_feedback=True,
        minimum_sqnr_db=200.0,
        generate_fn=_provider_for(proposal, seen_with),
        area_evaluator=_unexpected_area,
    )
    without_result = runner.run(
        tmp_path / "without",
        2,
        verified_feedback=False,
        minimum_sqnr_db=200.0,
        generate_fn=_provider_for(proposal, seen_without),
        area_evaluator=_unexpected_area,
    )

    assert seen_with[0] == seen_without[0]
    request_with = _prompt_request(seen_with[1])
    request_without = _prompt_request(seen_without[1])
    feedback_with = request_with["prior_evaluation"][0]
    feedback_without = request_without["prior_evaluation"][0]
    assert feedback_with.pop("verified_reason")["code"] == "quality_threshold"
    assert feedback_with == feedback_without
    assert request_with == request_without

    with_data = json.loads(with_result.read_text())
    without_data = json.loads(without_result.read_text())
    assert with_data["budget_totals"] == without_data["budget_totals"] == {
        "proposal_count": 2,
        "evaluation_request_count": 2,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 1,
    }
    assert with_data["records"][1]["cache_hit"] is True


def test_qualified_candidate_maps_once_and_is_selected(tmp_path):
    calls = []

    def area(rtl):
        calls.append(rtl)
        return {
            "status": "ok",
            "value": {
                "status": "ok",
                "area_um2": 1234.5,
                "num_cells": 42,
                "timing": {"status": "unavailable"},
                "power": {"status": "unavailable"},
            },
            "tool_executions": 1,
        }

    result_path = runner.run(
        tmp_path / "qualified",
        2,
        verified_feedback=True,
        minimum_sqnr_db=60.0,
        generate_fn=_provider_for(_proposal(), []),
        area_evaluator=area,
    )
    data = json.loads(result_path.read_text())
    assert len(calls) == 1
    assert data["qualified_candidates"] == 2
    assert data["budget_totals"] == {
        "proposal_count": 2,
        "evaluation_request_count": 2,
        "tool_execution_count": 1,
        "duplicate_proposal_count": 1,
    }
    best = data["best_qualified_by_area"]
    assert best["proposal_index"] == 1
    assert best["area"]["area_um2"] == 1234.5
    assert best["candidate_summary"]["graph_name"] == "expert_symmetric_preadd"
    assert (tmp_path / "qualified/llm_calls/call-001/parsed.json").is_file()
    assert (tmp_path / "qualified/llm_calls/call-001/evaluation.json").is_file()


def test_provider_failure_is_undetermined_and_charged_as_proposal_only(tmp_path):
    def provider(_messages, **_kwargs):
        return {
            "status": "timeout",
            "text": None,
            "usage": {"input_tokens": None, "output_tokens": None},
            "error": {"message": "deadline"},
        }

    result_path = runner.run(
        tmp_path / "provider-timeout",
        1,
        verified_feedback=True,
        generate_fn=provider,
        area_evaluator=_unexpected_area,
    )
    data = json.loads(result_path.read_text())
    assert data["records"][0]["status"] == "timeout"
    assert data["records"][0]["decision"] == "undetermined"
    assert data["budget_totals"] == {
        "proposal_count": 1,
        "evaluation_request_count": 0,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 0,
    }


def test_provider_request_respects_client_output_limit(tmp_path):
    seen = []

    def provider(_messages, **kwargs):
        seen.append(kwargs["max_output_tokens"])
        return {
            "status": "api_error",
            "text": None,
            "usage": {"input_tokens": None, "output_tokens": None},
            "error": {"message": "diagnostic"},
        }

    runner.run(
        tmp_path / "provider-limit",
        1,
        verified_feedback=True,
        generate_fn=provider,
        area_evaluator=_unexpected_area,
    )

    assert seen == [4000]


def test_dry_run_does_not_create_output(tmp_path, capsys):
    output = tmp_path / "dry"
    assert runner.main(["--output", str(output), "--calls", "3"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["calls"] == 3
    assert not output.exists()
