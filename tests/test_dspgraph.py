"""dspgraph 通用框架回归：计划校验、schema 修复、逐块与整链 RTL 逐位一致、CIC 交叉验证。"""

import random
import sys
import unittest
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

import dspgraph  # noqa: E402
from dspgraph import hw, search  # noqa: E402
from dspgraph.core import PlanError  # noqa: E402
from dspgraph.rx_family import build_rx, evaluate, scenario  # noqa: E402
from dspgraph.rx_spec import SPECS  # noqa: E402

SPEC = SPECS["dev_r32_wide"]
PLAN_A = {"blocks": [
    {"type": "nco_mixer", "params": {"nco_kind": "lut", "phase_bits": 10, "amp_bits": 14, "out_bits": 16}},
    {"type": "cic_decim", "params": {"decim": 8, "order": 4, "prune_margin_bits": 0, "out_bits": 18,
                                     "gain_shift": 1}},
    {"type": "fir_decim", "params": {"decim": 2, "taps": 21, "coef_bits": 14, "out_bits": 18,
                                     "compensate_upstream": True, "fold": 4}},
    {"type": "fir_decim", "params": {"filter_kind": "halfband", "decim": 2, "taps": 23, "coef_bits": 14,
                                     "out_bits": 16, "gain_shift": 1}}]}
PLAN_B = {"blocks": [
    {"type": "nco_mixer", "params": {"nco_kind": "lut_interp", "phase_bits": 8, "interp_bits": 4,
                                     "amp_bits": 13, "out_bits": 15, "rounding": "trunc"}},
    {"type": "cic_decim", "params": {"decim": 4, "order": 3, "diff_delay": 2, "prune_margin_bits": -1,
                                     "out_bits": 17, "rounding": "round"}},
    {"type": "fir_decim", "params": {"filter_kind": "halfband", "decim": 2, "taps": 11, "coef_bits": 12,
                                     "out_bits": 17, "fold": 3}},
    {"type": "fir_decim", "params": {"decim": 4, "taps": 31, "coef_bits": 13, "out_bits": 16, "fold": 1,
                                     "rounding": "trunc", "gain_shift": 2}}]}


def _inputs(chain, x):
    xs = [x]
    for st in chain.stages:
        x = st.block.run(x, st.params, st.ctx, st.aux, exact=True, ideal_coef=False, stats={})
        xs.append(x)
    return xs


class PlanTests(unittest.TestCase):
    def test_decimation_product_enforced(self):
        bad = {"blocks": [PLAN_A["blocks"][0], PLAN_A["blocks"][1], PLAN_A["blocks"][3]]}
        with self.assertRaises(PlanError) as cm:
            build_rx(bad, SPEC)
        self.assertEqual(cm.exception.code, "decimation")

    def test_halfband_constraints(self):
        p = {"blocks": [dict(b) for b in PLAN_A["blocks"]]}
        p["blocks"][3] = {"type": "fir_decim", "params": {"filter_kind": "halfband", "decim": 2,
                                                          "taps": 21, "out_bits": 16}}
        with self.assertRaises(PlanError):
            build_rx(p, SPEC)

    def test_random_plans_repairable(self):
        rng = random.Random(3)
        ok = sum(1 for _ in range(60) if _try(search.random_plan(SPEC, rng)))
        self.assertGreater(ok, 15)

    def test_evaluate_runs(self):
        q = evaluate(build_rx(PLAN_A, SPEC), attribution=True)
        self.assertIn("attribution", q)
        self.assertTrue(np.isfinite(q["snr_db"]))


def _try(plan):
    try:
        build_rx(plan, SPEC)
        return True
    except PlanError:
        return False


class RtlTests(unittest.TestCase):
    def test_blocks_bit_exact(self):
        sc = scenario(SPEC)
        x = sc.x_codes[:4000] / float(1 << (SPEC.input_bits - 1))
        for plan in (PLAN_A, PLAN_B):
            ch = build_rx(plan, SPEC)
            xs = _inputs(ch, x)
            for i in range(len(ch.stages)):
                r = hw.check_block(ch, i, xs[i][: (2000 if i == 0 else 300)])
                self.assertTrue(r["passed"], r)

    def test_chain_bit_exact(self):
        sc = scenario(SPEC)
        x = sc.x_codes[:4096] / float(1 << (SPEC.input_bits - 1))
        for plan in (PLAN_A, PLAN_B):
            r = hw.check_chain(build_rx(plan, SPEC), x)
            self.assertTrue(r["passed"], r)


class CicCrossCheck(unittest.TestCase):
    def test_matches_legacy_cic_without_pruning(self):
        from chains.cic.bittrue import CICBitTrue
        from dspgraph.blocks.cic import CicDecim, full_width
        rng = np.random.default_rng(1)
        x = rng.integers(-2048, 2048, 800)
        for n, r in ((2, 2), (3, 4)):
            legacy = CICBitTrue({"name": "t", "R": r, "N": n, "B": [0] * (2 * n),
                                 "B_fmt": full_width(12, n, r, 1) - 16, "overflow": "wrap",
                                 "rounding": "trunc"})
            ref, _ = legacy.run(x.tolist())
            blk = CicDecim()
            p = {"decim": r, "order": n, "diff_delay": 1, "prune_margin_bits": None, "out_bits": 16,
                 "rounding": "trunc", "gain_shift": 0}
            ctx = {"width_in": 12, "rate_in": 1, "spec": SPEC, "path": "t"}
            y = blk.run(x / 2048.0 + 0j, p, ctx, None, exact=True, ideal_coef=False, stats={})
            got = np.round(y.real * (1 << 15)).astype(int)
            self.assertEqual(got.tolist(), ref)


if __name__ == "__main__":
    unittest.main()
