import json
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.architecture_plan import architecture_plan
from search_ir.canonicalize import candidate_hash
from search_ir.formula_contract import ddc_formula_request
from search_ir.planning_loop import run_planning_loop
from search_ir.run_archive import PlanningRunArchive


def _plan(formula, depth):
    return architecture_plan(
        formula,
        nco={
            "strategy": "lut",
            "depth": depth,
            "interpolation": "linear",
            "phase_bits": 12,
        },
        filter_decimator={
            "strategy": "polyphase",
            "coefficient_bits": 16,
            "product_drop": 0,
            "accumulator_bits": 0,
            "rounding": "nearest_ties_to_pos_inf",
        },
    )


def _contract():
    return {
        "name": "public-development-quality-v1",
        "scope": "one fixed public synthetic case",
        "formal_truth_allowed": False,
    }


def test_archive_caches_duplicate_candidate_and_exports_selected_rtl(tmp_path):
    formula = ddc_formula_request()
    archive = PlanningRunArchive(
        tmp_path, "cached", formula, max_attempts=3, evaluation_contract=_contract()
    )
    calls = []

    def proposer(context):
        return _plan(formula, 256 if context["attempt"] < 3 else 512)

    def measured(candidate, request):
        del request
        calls.append(candidate_hash(candidate))
        if candidate["nco"]["depth"] == 256:
            return {
                "status": "rejected",
                "measurements": {"Q_dev": 2e-4},
                "feedback": {"reason": "quality_limit"},
            }
        return {"status": "accepted", "measurements": {"Q_dev": 2e-6}}

    result = run_planning_loop(
        formula,
        proposer,
        max_attempts=3,
        candidate_evaluator=lambda candidate, request: archive.cached_evaluate(
            candidate, request, measured
        ),
        attempt_recorder=archive.record_attempt,
    )
    assert result["status"] == "success" and result["attempt_count"] == 3
    assert len(calls) == 2
    assert result["transcript"][0]["candidate_evaluation"]["cache"]["hit"] is False
    assert result["transcript"][1]["candidate_evaluation"]["cache"]["hit"] is True
    archive.finalize(result)
    target = archive.export_selected()
    exported = json.loads((target / "manifest.json").read_text())
    assert exported["candidate_hash"] == candidate_hash(result["compile_result"]["candidate"])
    assert "\nmodule top" in (target / "design.v").read_text()
    assert archive.budget_status() == {"limit": 3, "charged": 3, "remaining": 0}


def test_interrupted_nonterminal_run_resumes_without_recharging_attempt(tmp_path):
    formula = ddc_formula_request()
    first = PlanningRunArchive(
        tmp_path, "resume", formula, max_attempts=3, evaluation_contract=_contract()
    )

    rejected = run_planning_loop(
        formula,
        lambda _: _plan(formula, 256),
        max_attempts=1,
        candidate_evaluator=lambda candidate, request: first.cached_evaluate(
            candidate,
            request,
            lambda *_: {
                "status": "rejected",
                "measurements": {"Q_dev": 3e-4},
                "feedback": {"reason": "quality_limit"},
            },
        ),
        attempt_recorder=first.record_attempt,
    )
    assert rejected["status"] == "exhausted"
    assert first.budget_status()["charged"] == 1

    resumed = PlanningRunArchive(
        tmp_path, "resume", formula, max_attempts=3,
        evaluation_contract=_contract(), resume=True,
    )
    seen = []

    def proposer(context):
        seen.append(context)
        return _plan(formula, 512)

    result = run_planning_loop(
        formula,
        proposer,
        max_attempts=3,
        candidate_evaluator=lambda *_: {
            "status": "accepted", "measurements": {"Q_dev": 1e-6}
        },
        resume_transcript=resumed.transcript(),
        attempt_recorder=resumed.record_attempt,
    )
    assert result["status"] == "success" and result["attempt_count"] == 2
    assert seen[0]["attempt"] == 2
    assert seen[0]["previous_feedback"]["detail"]["feedback"]["reason"] == "quality_limit"
    assert resumed.budget_status() == {"limit": 3, "charged": 2, "remaining": 1}
    resumed.finalize(result)


def test_resume_rejects_manifest_or_attempt_drift(tmp_path):
    formula = ddc_formula_request()
    archive = PlanningRunArchive(tmp_path, "drift", formula, max_attempts=2)
    run_planning_loop(
        formula,
        lambda _: _plan(formula, 63),
        max_attempts=1,
        attempt_recorder=archive.record_attempt,
    )
    attempt = archive.path / "attempts/attempt-0001.json"
    attempt.write_text(attempt.read_text() + " ")
    with pytest.raises(RuntimeError, match="drifted"):
        PlanningRunArchive(tmp_path, "drift", formula, max_attempts=2, resume=True)


def test_completed_or_colliding_runs_and_exports_never_overwrite(tmp_path):
    formula = ddc_formula_request()
    archive = PlanningRunArchive(tmp_path, "closed", formula, max_attempts=1)
    result = run_planning_loop(
        formula, lambda _: _plan(formula, 256), max_attempts=1,
        attempt_recorder=archive.record_attempt,
    )
    archive.finalize(result)
    with pytest.raises(ValueError, match="completed"):
        PlanningRunArchive(tmp_path, "closed", formula, max_attempts=1, resume=True)
    archive.export_selected()
    with pytest.raises(FileExistsError):
        archive.export_selected()
