"""Behavioral contract for the task-independent joint-search state machine.

All evaluators are in-memory fakes.  These tests exercise classification,
short-circuiting, accounting, duplicate detection, and feedback-arm fairness;
they never invoke an RTL simulator, synthesis tool, or model API.
"""

import copy
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from joint_search import (  # noqa: E402
    SearchLedger,
    evaluate_candidate,
    feedback_payload,
)


CONTEXT_SHA256 = "a" * 64


def scalar_sum_candidate():
    """A non-cmul candidate keeps the search controller task independent."""
    return {
        "schema_version": "verievolve-joint-design-v1",
        "task": {"task_id": "scalar_sum_w8", "formula_id": "x_plus_y"},
        "inputs": [
            {"id": "x", "width": 8, "signed": True},
            {"id": "y", "width": 8, "signed": True},
        ],
        "outputs": [{"id": "z", "source": "sum", "width": 9, "signed": True}],
        "nodes": [
            {
                "id": "sum",
                "op": "add",
                "inputs": ["x", "y"],
                "fixed_point": {
                    "signed": True,
                    "width": 9,
                    "frac": 4,
                    "rounding": "rne",
                    "overflow": "wrap",
                    "drop_lsb": 1,
                },
                "microarchitecture": {
                    "pipeline_stage": 0,
                    "resource_group": "adder_0",
                    "latency": 1,
                },
            }
        ],
        "quality_contract": {
            "metric": "max_abs_error_lsb",
            "direction": "min",
            "threshold": 1.0,
            "aggregation": "max_over_outputs",
            "evaluation": "integer_domain_exact",
        },
        "metadata": {"label": "sum candidate"},
    }


class CallLog:
    def __init__(self, quality_result=None, rtl_result=None, area_result=None):
        self.calls = []
        self.quality_result = quality_result or {"max_abs_error_lsb": 0.5}
        self.rtl_result = rtl_result or "module top; endmodule\n"
        self.area_result = area_result or {"area_um2": 12.5}

    def quality(self, candidate):
        self.calls.append("quality")
        return copy.deepcopy(self.quality_result)

    def rtl(self, candidate):
        self.calls.append("rtl")
        return copy.deepcopy(self.rtl_result)

    def area(self, rtl):
        self.calls.append("area")
        assert isinstance(rtl, str) and rtl.strip()
        return copy.deepcopy(self.area_result)


def run_candidate(log, candidate=None, *, ledger=None, cache=None):
    return evaluate_candidate(
        candidate or scalar_sum_candidate(),
        context_sha256=CONTEXT_SHA256,
        quality_evaluator=log.quality,
        rtl_lowerer=log.rtl,
        area_evaluator=log.area,
        ledger=ledger,
        cache=cache,
    )


def test_invalid_structure_is_a_candidate_failure_before_any_evaluator_call():
    candidate = scalar_sum_candidate()
    candidate["nodes"][0]["inputs"][0] = "missing_value"
    log = CallLog()
    result = run_candidate(log, candidate)

    assert result["status"] == "invalid_structure"
    assert result["decision"] == "rejected"
    assert result["measured_metrics"] == {}
    assert result["verified_reason"]
    assert log.calls == []
    assert result["budget_event"]["proposal_count"] == 1
    assert result["budget_event"]["evaluation_request_count"] == 1


def test_quality_failure_is_verified_and_short_circuits_rtl_and_area():
    log = CallLog(quality_result={"max_abs_error_lsb": 1.25})
    result = run_candidate(log)

    assert result["status"] == "quality_failed"
    assert result["decision"] == "rejected"
    assert result["measured_metrics"] == {"max_abs_error_lsb": 1.25}
    assert result["verified_reason"]["measured"] == 1.25
    assert result["verified_reason"]["threshold"] == 1.0
    assert log.calls == ["quality"]


@pytest.mark.parametrize("status", ["tool_failure", "timeout", "unknown"])
def test_quality_evaluator_infrastructure_failures_remain_undecided(status):
    log = CallLog(
        quality_result={
            "status": status,
            "diagnostic": "infrastructure did not produce a measurement",
            "tool_executions": 1,
        }
    )
    result = run_candidate(log)

    assert result["status"] == status
    assert result["decision"] == "undetermined"
    assert result["verified_reason"] is None
    assert log.calls == ["quality"]


def test_unhandled_evaluator_exception_is_undetermined_not_candidate_failure():
    log = CallLog()

    def raise_from_evaluator(candidate):
        log.calls.append("quality")
        raise RuntimeError("mock evaluator process disappeared")

    result = evaluate_candidate(
        scalar_sum_candidate(),
        context_sha256=CONTEXT_SHA256,
        quality_evaluator=raise_from_evaluator,
        rtl_lowerer=log.rtl,
        area_evaluator=log.area,
    )

    assert result["status"] == "tool_failure"
    assert result["decision"] == "undetermined"
    assert result["verified_reason"] is None
    assert log.calls == ["quality"]


def test_rtl_and_area_are_requested_only_after_the_quality_gate_passes():
    log = CallLog()
    result = run_candidate(log)

    assert result["status"] == "qualified"
    assert result["decision"] == "accepted"
    assert result["measured_metrics"] == {"max_abs_error_lsb": 0.5}
    assert len(result["rtl_sha256"]) == 64
    assert result["area"]["area_um2"] == 12.5
    assert log.calls == ["quality", "rtl", "area"]
    assert result["budget_totals"] == {
        "proposal_count": 1,
        "evaluation_request_count": 1,
        "tool_execution_count": 0,
        "duplicate_proposal_count": 0,
    }


@pytest.mark.parametrize("stage,status", [("rtl", "tool_failure"), ("area", "timeout")])
def test_downstream_infrastructure_failure_is_still_undecided(stage, status):
    kwargs = {}
    if stage == "rtl":
        kwargs["rtl_result"] = {
            "status": status,
            "diagnostic": "mock rtl failure",
            "tool_executions": 1,
        }
    else:
        kwargs["area_result"] = {
            "status": status,
            "diagnostic": "mock area failure",
            "tool_executions": 1,
        }
    log = CallLog(**kwargs)
    result = run_candidate(log)

    assert result["status"] == status
    assert result["decision"] == "undetermined"
    assert result["verified_reason"] is None
    expected_calls = (
        ["quality", "rtl"] if stage == "rtl" else ["quality", "rtl", "area"]
    )
    assert log.calls == expected_calls


def test_feedback_ablation_uses_identical_evidence_and_budget():
    log = CallLog(quality_result={"max_abs_error_lsb": 1.25})
    result = run_candidate(log)

    with_feedback = feedback_payload(result, include_verified_reason=True)
    without_feedback = feedback_payload(result, include_verified_reason=False)

    assert with_feedback["measured_metrics"] == without_feedback["measured_metrics"]
    assert with_feedback["budget_event"] == without_feedback["budget_event"]
    assert with_feedback["status"] == without_feedback["status"]
    assert with_feedback["verified_reason"] == result["verified_reason"]
    assert "verified_reason" not in without_feedback


def test_unverified_tool_failure_never_turns_into_feedback_reason():
    log = CallLog(
        quality_result={
            "status": "tool_failure",
            "diagnostic": "yosys unavailable",
            "tool_executions": 1,
        }
    )
    result = run_candidate(log)
    payload = feedback_payload(result, include_verified_reason=True)
    assert payload.get("verified_reason") is None


def test_undetermined_tool_result_is_not_cached_as_candidate_truth():
    ledger = SearchLedger()
    cache = {}
    failed = CallLog(
        quality_result={
            "status": "timeout",
            "diagnostic": "first tool launch timed out",
            "tool_executions": 1,
        }
    )
    first = run_candidate(failed, ledger=ledger, cache=cache)
    recovered = CallLog()
    second = run_candidate(recovered, ledger=ledger, cache=cache)

    assert first["decision"] == "undetermined"
    assert second["status"] == "qualified"
    assert second["cache_hit"] is False
    assert recovered.calls == ["quality", "rtl", "area"]


def test_repository_style_ok_result_object_is_valid_area_payload():
    log = CallLog(area_result={"status": "ok", "area_um2": 9.75, "tool_executions": 1})
    result = run_candidate(log)
    assert result["status"] == "qualified"
    assert result["area"] == {"status": "ok", "area_um2": 9.75}
    assert result["budget_event"]["tool_execution_count"] == 1


def test_duplicate_hash_is_detected_but_still_charges_request_budget():
    log = CallLog(quality_result={"max_abs_error_lsb": 1.25})
    ledger = SearchLedger()
    cache = {}
    first = run_candidate(log, ledger=ledger, cache=cache)

    same_semantics = scalar_sum_candidate()
    same_semantics["metadata"] = {"label": "a different nonsemantic label"}
    second = run_candidate(log, same_semantics, ledger=ledger, cache=cache)

    assert first["duplicate_proposal"] is False
    assert second["duplicate_proposal"] is True
    assert first["candidate_sha256"] == second["candidate_sha256"]
    assert ledger.snapshot()["proposal_count"] == 2
    assert ledger.snapshot()["evaluation_request_count"] == 2
    assert ledger.snapshot()["duplicate_proposal_count"] == 1
    assert second["cache_hit"] is True
    # Archived accounting must be a snapshot, not a reference to mutable state.
    assert first["budget_totals"]["proposal_count"] == 1
    assert second["budget_totals"]["proposal_count"] == 2
