import sys
from pathlib import Path


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.dev_fixtures import make_candidate
from search_ir.rtl_verify import verify_candidate_rtl


def test_standalone_rtl_verifier_matches_bittrue_model(tmp_path):
    result = verify_candidate_rtl(make_candidate("cordic"), tmp_path / "verify", samples=65)
    assert result["status"] == "ok"
    assert result["checked_output_samples"] == 17
    assert result["candidate_sha256"]
