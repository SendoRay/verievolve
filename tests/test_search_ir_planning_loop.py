import copy
import sys
from pathlib import Path


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.architecture_plan import architecture_plan
from search_ir.formula_contract import ddc_formula_request
from search_ir.planning_loop import capability_manifest, planner_context, run_planning_loop


def _filter():
    return {
        "strategy": "polyphase",
        "coefficient_bits": 14,
        "product_drop": 1,
        "accumulator_bits": 28,
        "rounding": "nearest_ties_to_pos_inf",
    }


def _plan(formula, depth):
    return architecture_plan(
        formula,
        nco={
            "strategy": "lut",
            "depth": depth,
            "interpolation": "linear",
            "phase_bits": 12,
        },
        filter_decimator=_filter(),
    )


def test_context_exposes_formula_components_and_previous_feedback_without_rtl_escape():
    formula = ddc_formula_request()
    feedback = {"code": "schema", "path": "$plan.nco.depth", "message": "bad"}
    context = planner_context(formula, feedback, attempt=2)
    assert context["attempt"] == 2
    assert context["formula_request"]["nodes"][-1]["op"] == "decimate"
    assert context["capabilities"]["arbitrary_rtl_allowed"] is False
    assert context["previous_feedback"] == feedback
    feedback["path"] = "mutated"
    assert context["previous_feedback"]["path"] == "$plan.nco.depth"


def test_rejected_plan_is_counted_then_structured_feedback_enables_repair():
    formula = ddc_formula_request()
    seen = []

    def scripted_proposer(context):
        seen.append(copy.deepcopy(context))
        if context["attempt"] == 1:
            assert context["previous_feedback"] is None
            return _plan(formula, 63)
        assert context["previous_feedback"]["path"] == "$plan.nco.depth"
        return _plan(formula, 256)

    run = run_planning_loop(formula, scripted_proposer, max_attempts=3)
    assert run["status"] == "success"
    assert run["attempt_count"] == 2
    assert run["failed_attempts"] == 1
    assert run["transcript"][0]["result"]["status"] == "rejected"
    assert run["transcript"][1]["result"]["status"] == "ok"
    assert len(seen) == 2


def test_every_failed_attempt_is_preserved_when_budget_exhausts():
    formula = ddc_formula_request()
    run = run_planning_loop(formula, lambda _: _plan(formula, 63), max_attempts=3)
    assert run["status"] == "exhausted"
    assert run["attempt_count"] == run["failed_attempts"] == 3
    assert len(run["transcript"]) == 3
    assert all(row["result"]["status"] == "rejected" for row in run["transcript"])


def test_capability_manifest_is_proposer_neutral_and_bounded():
    manifest = capability_manifest()
    assert manifest["unknown_fields_allowed"] is False
    hybrid = manifest["nco_strategies"]["coarse_residual"]
    assert hybrid["coarse"]["strategy"] == "lut"
    assert hybrid["residual"]["strategy"] == "cordic"
    assert hybrid["coarse"]["depth"] == [64, 128, 256, 512, 1024]
    assert manifest["filter_strategies"] == ["direct_symmetric", "polyphase"]
    assert manifest["filter_numeric_domains"]["rounding"] == [
        "nearest_ties_to_pos_inf",
        "floor",
    ]
    assert manifest["numeric_semantics"]["legacy_aliases"] == {
        "rne": "nearest_ties_to_pos_inf",
        "trunc": "floor",
    }


def test_measured_candidate_rejection_is_fed_back_and_counted():
    formula = ddc_formula_request()
    seen = []

    def proposer(context):
        seen.append(copy.deepcopy(context))
        return _plan(formula, 256 if context["attempt"] == 1 else 512)

    def evaluator(candidate, request):
        del request
        depth = candidate["nco"]["depth"]
        if depth == 256:
            return {
                "status": "rejected",
                "measurements": {"Q_dev": 2e-4, "maximum": 1e-5},
                "feedback": {"reason": "quality_limit", "observed": 2e-4},
            }
        return {
            "status": "accepted",
            "measurements": {"Q_dev": 5e-6, "maximum": 1e-5},
            "feedback": None,
        }

    run = run_planning_loop(
        formula, proposer, max_attempts=3, candidate_evaluator=evaluator
    )
    assert run["status"] == "success"
    assert run["attempt_count"] == 2
    assert run["failed_attempts"] == 1
    assert run["evaluation_result"]["status"] == "accepted"
    assert seen[1]["previous_feedback"]["code"] == "candidate_not_accepted"
    assert seen[1]["previous_feedback"]["detail"]["measurements"]["Q_dev"] == 2e-4
    assert run["transcript"][0]["candidate_evaluation"]["status"] == "rejected"


def test_evaluator_exception_is_inconclusive_and_does_not_consume_more_proposals():
    formula = ddc_formula_request()
    calls = []

    def proposer(context):
        calls.append(context["attempt"])
        return _plan(formula, 256)

    def broken_evaluator(candidate, request):
        del candidate, request
        raise RuntimeError("tool unavailable")

    run = run_planning_loop(
        formula, proposer, max_attempts=3, candidate_evaluator=broken_evaluator
    )
    assert run["status"] == "inconclusive"
    assert run["attempt_count"] == 1
    assert run["failed_attempts"] == 0
    assert calls == [1]
    assert run["evaluation_result"]["feedback"]["code"] == "candidate_evaluator_exception"
