import sys
from pathlib import Path

import numpy as np


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.cic.bittrue import CICBitTrue, round_shift, run_iq
from chains.cic.gen_candidates_v1 import expand


def _candidate(name: str) -> dict:
    return next(row for row in expand() if row["name"] == name)


def _fir_coefficients(R: int, N: int) -> np.ndarray:
    h = np.ones(R, dtype=np.int64)
    for _ in range(N - 1):
        h = np.convolve(h, np.ones(R, dtype=np.int64))
    return h


def _sat16(value: int) -> int:
    return min(max(value, -32768), 32767)


def test_round_shift_matches_frozen_half_up_semantics():
    assert [round_shift(x, 1, "rne") for x in (-3, -2, -1, 0, 1, 2, 3)] == [
        -1, -1, 0, 0, 1, 1, 2
    ]
    assert [round_shift(x, 1, "trunc") for x in (-3, -2, -1, 0, 1, 2, 3)] == [
        -2, -1, -1, 0, 0, 1, 1
    ]


def test_zero_input_is_zero_and_phase0_length_is_exact():
    for row in expand():
        model = CICBitTrue(row)
        out, events = model.run([0] * 65)
        assert out == [0] * ((65 + row["R"] - 1) // row["R"])
        assert events["output_sat"] == 0


def test_full_width_wrap_matches_equivalent_fir_for_all_contract_combos():
    rng = np.random.default_rng(20261004)
    x = rng.integers(-256, 256, size=192, dtype=np.int64)
    for R, N in ((2, 3), (2, 4), (4, 3), (4, 4)):
        row = _candidate(f"comp_U0_R{R}N{N}")
        got, _ = CICBitTrue(row).run(x.tolist())
        causal = np.convolve(x, _fir_coefficients(R, N))[: len(x)]
        exact = causal[::R]
        d = row["B_fmt"]
        expected = [_sat16(round_shift(int(v), d, "rne")) for v in exact]
        assert got == expected, (R, N)


def test_wrap_and_sat_are_not_merged_when_internal_overflow_occurs():
    wrap = _candidate("comp_H_R2N3")
    sat = _candidate("comp_O_R2N3")
    x = [2047] * 256
    y_wrap, ev_wrap = CICBitTrue(wrap).run(x)
    y_sat, ev_sat = CICBitTrue(sat).run(x)
    assert y_wrap != y_sat
    assert sum(ev_wrap["internal_wrap_event"]) > 0
    assert sum(ev_sat["internal_sat_event"]) > 0


def test_wrap_event_uses_the_frozen_absolute_value_boundary():
    row = _candidate("comp_H_R2N3")
    model = CICBitTrue(row)
    # lock j=2 的 width=15；预置状态使下一次写入恰为 -2^14。
    model.state.integrators[0] = -(1 << 14)
    model.push(0)
    assert model.state.integrators[0] == -(1 << 14)
    assert model.state.events.internal_wrap_event[0] == 1


def test_iq_paths_are_independent_copies_of_the_same_model():
    row = _candidate("comp_T2_R4N4")
    i = [((k * 37) & 0xFFF) - 2048 for k in range(97)]
    q = [-x - 1 for x in i]
    got = run_iq(row, i, q)
    i_ref, _ = CICBitTrue(row).run(i)
    q_ref, _ = CICBitTrue(row).run(q)
    assert got["i"] == i_ref
    assert got["q"] == q_ref
