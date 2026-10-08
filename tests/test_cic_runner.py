import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.cic import run_witness_v1, scenarios_v1


def test_freeze_chain_is_valid_and_candidate_pool_is_23():
    preflight, second, metric = run_witness_v1.validate_freezes()
    assert second["status"] == "approved"
    assert metric["status"] == "approved"
    assert len(run_witness_v1._candidate_rows(preflight)) == 23


def test_zero_bit_pruning_tolerance_is_frozen_for_v2_only():
    freeze = run_witness_v1.validate_pruning_freeze()
    assert freeze["cumulative_pruning_tolerance_bits"] == 0
    assert run_witness_v1.LOCAL.name == "local_metrics_v2.json"
    assert run_witness_v1.EXECUTION.name == "execution_manifest_v2.json"


def test_nonfinite_db_is_serialized_as_null():
    assert run_witness_v1._finite_db_or_none(float("-inf")) is None
    assert run_witness_v1._finite_db_or_none(float("inf")) is None
    assert run_witness_v1._finite_db_or_none(-42.5) == -42.5


def test_one_candidate_scenario_smoke_has_finite_q_and_reference_audit():
    preflight, _, _ = run_witness_v1.validate_freezes()
    candidate = run_witness_v1._candidate_rows(preflight)[0]
    spec = next(row for row in scenarios_v1.all_specs("main")
                if row["R"] == candidate["R"])
    row = run_witness_v1._evaluate_one(candidate, spec)
    assert row["q_aligned"] >= 0.0
    assert row["reference_audit"]["i"]["fir_equals_unbounded"] is True
    assert row["reference_audit"]["i"]["fir_equals_float64"] is True
