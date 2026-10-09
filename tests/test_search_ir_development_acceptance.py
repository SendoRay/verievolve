from pathlib import Path
import sys


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.dev_fixtures import development_candidate_evaluator, make_candidate
from search_ir.formula_contract import ddc_formula_request


def test_development_evaluator_applies_formula_quality_limit():
    candidate = make_candidate("lut")
    permissive = development_candidate_evaluator(
        candidate, ddc_formula_request(max_aligned_nmse=1.0)
    )
    strict = development_candidate_evaluator(
        candidate, ddc_formula_request(max_aligned_nmse=1e-20)
    )
    assert permissive["status"] == "accepted"
    assert permissive["measurements"]["quality"]["requirement_status"] == "satisfied"
    assert permissive["measurements"]["quality"]["deployment_acceptance"] is False
    assert strict["status"] == "rejected"
    assert strict["feedback"]["reason"] == "quality_limit_not_satisfied"
    assert strict["measurements"]["quality"]["observed"] > 1e-20
