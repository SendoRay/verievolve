"""Control-plane tests for the joint sin/cos search runner."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

import run_joint_sincos_search as runner  # noqa: E402


def _proposal(*, threshold=60.0, phase_bits=16, family="quarter_wave_lut"):
    if family == "quarter_wave_lut":
        algorithm = {
            "family": family,
            "table_depth": 256,
            "interpolation": "linear",
        }
        micro = {
            "datapath": "combinational_lookup",
            "pipeline_stages": 1,
            "latency_cycles": 1,
            "initiation_interval": 1,
            "resource_sharing": False,
        }
    else:
        algorithm = {"family": "iterative_cordic", "iterations": 12}
        micro = {
            "datapath": "iterative_shift_add",
            "pipeline_stages": 1,
            "latency_cycles": 13,
            "initiation_interval": 14,
            "resource_sharing": True,
        }
    return {
        "schema_version": runner.RESPONSE_SCHEMA_VERSION,
        "algorithm": algorithm,
        "precision": {
            "phase_bits": phase_bits,
            "output_width": 16,
            "output_frac": 15,
            "rounding": "nearest_ties_up",
            "overflow": "saturate",
        },
        "microarchitecture": micro,
        "minimum_sqnr_db": threshold,
        "name": f"test-{family}-{phase_bits}",
    }


def _provider(proposal, seen):
    def generate(messages, **kwargs):
        seen.append({"messages": deepcopy(messages), "kwargs": deepcopy(kwargs)})
        return {
            "status": "ok",
            "text": json.dumps(proposal, sort_keys=True, separators=(",", ":")),
            "raw_response": {"id": f"fake-{len(seen)}"},
            "usage": {
                "status": "reported",
                "reported": True,
                "input_tokens": 100,
                "output_tokens": 40,
                "cache_tokens": 0,
                "total_tokens": 140,
                "actual_billed_cost": None,
            },
            "elapsed_seconds": 0.01,
            "error": None,
        }

    return generate


def _request(seen, index):
    return json.loads(seen[index]["messages"][1]["content"])


def _unexpected_area(_rtl):
    raise AssertionError("quality failure must not start synthesis")


@pytest.mark.parametrize("family", ["quarter_wave_lut", "iterative_cordic"])
def test_parse_binds_algorithm_precision_microarchitecture_and_threshold(family):
    proposal = _proposal(family=family, phase_bits=14)
    parsed = runner.parse_proposal(json.dumps(proposal), minimum_sqnr_db=60.0)
    candidate = parsed["candidate"]
    assert candidate["algorithm"] == proposal["algorithm"]
    assert candidate["precision"]["phase_bits"] == 14
    assert candidate["microarchitecture"] == proposal["microarchitecture"]
    assert candidate["quality_contract"]["threshold"] == 60.0


def test_parse_rejects_constraint_relaxation_and_unsupported_schedule():
    relaxed = _proposal(threshold=20.0)
    with pytest.raises(runner.ProposalError) as caught:
        runner.parse_proposal(json.dumps(relaxed), minimum_sqnr_db=60.0)
    assert caught.value.code == "quality_constraint"

    unsupported = _proposal(family="iterative_cordic")
    unsupported["microarchitecture"] = {
        "datapath": "fully_pipelined_shift_add",
        "pipeline_stages": 12,
        "latency_cycles": 12,
        "initiation_interval": 1,
        "resource_sharing": False,
    }
    with pytest.raises(runner.ProposalError) as caught:
        runner.parse_proposal(json.dumps(unsupported), minimum_sqnr_db=60.0)
    assert caught.value.code == "candidate_validation"


def test_prompt_contains_both_families_and_all_three_axes():
    request = json.loads(
        runner.build_messages(
            1, [], minimum_sqnr_db=60.0, include_verified_reason=True
        )[1]["content"]
    )
    families = [row["family"] for row in request["joint_search_space"]["algorithm"]]
    assert families == ["quarter_wave_lut", "iterative_cordic"]
    assert "phase_bits" in request["joint_search_space"]["precision"]
    assert "required_microarchitecture" in request["joint_search_space"]["algorithm"][0]


def test_feedback_arms_match_except_verified_reason_and_cache_accounting(tmp_path):
    proposal = _proposal(threshold=200.0, phase_bits=8)
    seen_with, seen_without = [], []
    with_path = runner.run(
        tmp_path / "with",
        2,
        verified_feedback=True,
        minimum_sqnr_db=200.0,
        generate_fn=_provider(proposal, seen_with),
        area_evaluator=_unexpected_area,
    )
    without_path = runner.run(
        tmp_path / "without",
        2,
        verified_feedback=False,
        minimum_sqnr_db=200.0,
        generate_fn=_provider(proposal, seen_without),
        area_evaluator=_unexpected_area,
    )
    assert seen_with[0] == seen_without[0]
    with_feedback = _request(seen_with, 1)["prior_evaluation"][0]
    without_feedback = _request(seen_without, 1)["prior_evaluation"][0]
    assert with_feedback.pop("verified_reason")["code"] == "quality_threshold"
    assert with_feedback == without_feedback
    with_data = json.loads(with_path.read_text())
    without_data = json.loads(without_path.read_text())
    expected = {
        "proposal_count": 2,
        "evaluation_request_count": 2,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 1,
    }
    assert with_data["budget_totals"] == without_data["budget_totals"] == expected
    assert with_data["records"][1]["cache_hit"] is True


def test_qualified_candidate_maps_once_records_evidence_and_is_selected(tmp_path):
    seen = []
    area_calls = []

    def area(rtl):
        area_calls.append(rtl)
        return {
            "status": "ok",
            "value": {
                "status": "ok",
                "area_um2": 4321.5,
                "num_cells": 77,
                "timing": {"status": "unavailable"},
                "power": {"status": "unavailable"},
            },
            "tool_executions": 1,
        }

    path = runner.run(
        tmp_path / "qualified",
        2,
        verified_feedback=True,
        minimum_sqnr_db=-100.0,
        generate_fn=_provider(_proposal(threshold=-100.0), seen),
        area_evaluator=area,
    )
    data = json.loads(path.read_text())
    manifest = json.loads((tmp_path / "qualified/manifest.json").read_text())
    assert len(area_calls) == 1
    assert data["budget_totals"] == {
        "proposal_count": 2,
        "evaluation_request_count": 2,
        "tool_execution_count": 1,
        "duplicate_proposal_count": 1,
    }
    assert data["best_qualified_by_area"]["area"]["area_um2"] == 4321.5
    assert data["records"][0]["measured_metrics"]["enumerated_input_codes"] == 65536
    assert set(manifest["source_sha256"]) == {
        "run_joint_sincos_search.py",
        "joint_sincos.py",
        "joint_search.py",
    }
    assert (tmp_path / "qualified/llm_calls/call-001/record.json").is_file()


def test_provider_limit_failure_classification_new_output_and_dry_run(tmp_path, capsys):
    seen_limits = []

    def provider(_messages, **kwargs):
        seen_limits.append(kwargs["max_output_tokens"])
        return {
            "status": "timeout",
            "text": None,
            "usage": {"input_tokens": None, "output_tokens": None},
            "error": {"message": "deadline"},
        }

    output = tmp_path / "run"
    path = runner.run(
        output,
        1,
        verified_feedback=True,
        generate_fn=provider,
        area_evaluator=_unexpected_area,
    )
    data = json.loads(path.read_text())
    assert seen_limits == [4000]
    assert data["records"][0]["status"] == "timeout"
    assert data["records"][0]["decision"] == "undetermined"
    with pytest.raises(FileExistsError):
        runner.run(
            output,
            1,
            verified_feedback=True,
            generate_fn=provider,
            area_evaluator=_unexpected_area,
        )

    dry = tmp_path / "dry"
    assert runner.main(["--output", str(dry), "--calls", "2"]) == 0
    preview = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert preview["status"] == "dry_run"
    assert not dry.exists()
