import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.cic import metrics_v1
from chains.cic.gen_candidates_v1 import expand


def _candidate(name: str) -> dict:
    return next(row for row in expand() if row["name"] == name)


def test_local_model_keeps_declared_blind_spots():
    h = metrics_v1.local_metrics(_candidate("comp_H_R4N4"))
    o = metrics_v1.local_metrics(_candidate("comp_O_R4N4"))
    rnd = metrics_v1.local_metrics(_candidate("comp_RND_R4N4"))
    for field in ("hogenauer_predicted_snr_db", "worst_stage_sqnr_db",
                  "total_cumulative_pruning_bits"):
        assert h[field] == o[field] == rnd[field]


def test_exact_local_candidates_use_null_plus_explicit_flag():
    row = metrics_v1.local_metrics(_candidate("comp_H_R2N3"))
    assert row["exact_under_local_model"] is True
    assert row["hogenauer_predicted_snr_db"] is None
    assert row["worst_stage_sqnr_db"] is None
    assert row["predicted_error_power"] == 0.0


def test_q_threshold_reproduces_frozen_derivation():
    cal = metrics_v1.exact_zero_q_calibration()
    assert cal["q_cal"] == 0.0
    assert math.isclose(cal["epsilon_q"], 2.32929922807541e-6,
                        rel_tol=0.0, abs_tol=1e-18)


def test_order_analysis_detects_strict_reversal_and_collapse():
    local = [
        {"name": "a", "R": 2, "N": 3, "hogenauer_predicted_snr_db": 50.0,
         "worst_stage_sqnr_db": 50.0, "total_cumulative_pruning_bits": 0},
        {"name": "b", "R": 2, "N": 3, "hogenauer_predicted_snr_db": 40.0,
         "worst_stage_sqnr_db": 50.0, "total_cumulative_pruning_bits": 1},
    ]
    agg = [
        {"candidate": "a", "Q": 2e-5},
        {"candidate": "b", "Q": 1e-5},
    ]
    got = metrics_v1.analyze_order(local, agg, 1e-6)
    assert got["metrics"]["hogenauer_predicted_snr_db"]["by_R"]["R2"]["n_strict"] == 1
    assert got["metrics"]["worst_stage_sqnr_db"]["by_R"]["R2"]["n_collapse"] == 1
