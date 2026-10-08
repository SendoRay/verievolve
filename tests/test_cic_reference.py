import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.cic import reference, scenarios_v1


def test_three_reference_paths_match_on_long_sequences():
    rng = np.random.default_rng(20261008)
    codes = rng.integers(-2048, 2048, size=13_312, dtype=np.int64)
    for R, N in ((2, 3), (2, 4), (4, 3), (4, 4)):
        report = reference.cross_validate(codes, R, N)
        assert report["fir_equals_unbounded"] is True
        assert report["fir_equals_float64"] is True
        assert report["n_output"] == (len(codes) + R - 1) // R


def test_normalized_reference_has_expected_dc_gain():
    for R, N in ((2, 3), (2, 4), (4, 3), (4, 4)):
        x = np.full(256, 1024, dtype=np.int64)
        y, _ = reference.normalized_iq(x, np.zeros_like(x), R, N)
        assert np.allclose(y[-16:].real, 0.5, atol=0.0, rtol=0.0)
        assert np.all(y[-16:].imag == 0.0)


def test_frozen_scenario_generation_is_deterministic_and_in_range():
    spec = scenarios_v1.all_specs("main")[7]
    a = scenarios_v1.generate(spec)
    b = scenarios_v1.generate(spec)
    assert np.array_equal(a.i_codes, b.i_codes)
    assert np.array_equal(a.q_codes, b.q_codes)
    assert len(a.i_codes) == 13_312
    assert -2048 <= int(a.i_codes.min()) <= int(a.i_codes.max()) <= 2047
    assert -2048 <= int(a.q_codes.min()) <= int(a.q_codes.max()) <= 2047
    assert a.levels["noise_calibration_N"] == 4
    assert abs(a.levels["snr_calibration_output_db"] - 30.0) < 1e-10


def test_every_frozen_scenario_key_is_unique():
    specs = scenarios_v1.all_specs()
    keys = [row["scenario_key"] for row in specs]
    assert len(specs) == 72
    assert len(set(keys)) == 72
