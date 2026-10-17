"""dspc 原语与双重解释的单元测试。"""
import sys
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from dspc import ContractError, Prog, run  # noqa: E402


def prog(**kw):
    d = dict(in_bits=12, out_bits=16, in_kind="real", out_kind="real", out_rate=Fraction(1))
    d.update(kw)
    return Prog(**d)


def rnd_codes(rng, bits=12, shape=(2, 400)):
    return rng.integers(-(1 << (bits - 1)), 1 << (bits - 1), size=shape)


class TestQuantize(unittest.TestCase):
    def ref_q(self, codes, s, w, rnd, ovf):
        """独立实现：丢 s 位小数后按 w 位有符号处理溢出。"""
        v = codes.astype(np.int64)
        if s > 0:
            v = (v + (1 << (s - 1))) >> s if rnd == "round" else v >> s
        lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
        if ovf == "sat":
            return np.clip(v, lo, hi)
        return ((v - lo) % (1 << w)) + lo

    def test_q_modes_match_reference(self):
        rng = np.random.default_rng(0)
        x = rnd_codes(rng)
        for rnd in ("round", "trunc"):
            for ovf in ("sat", "wrap"):
                g = prog(out_bits=8)
                a = g.input()
                y = g.q(g.shift(a, 3), 8, 7, rnd, ovf)   # 输入 s12.11 左移 3 → s12.8；量化到 s8.7
                g.output(y)
                r = run(g, [x], "fixed")
                got = r.values[g.outputs[0]]
                np.testing.assert_array_equal(got, self.ref_q(x, 1, 8, rnd, ovf), err_msg=f"{rnd}/{ovf}")

    def test_ideal_q_is_exact_except_wrap(self):
        rng = np.random.default_rng(1)
        x = rnd_codes(rng)
        g = prog(out_bits=6)
        a = g.input()
        g.output(g.q(a, 6, 5, "round", "sat"))
        ri = run(g, [x], "ideal")
        np.testing.assert_allclose(ri.y, x / 2048.0)           # 理想解释：不舍入、不饱和

        g = prog(out_bits=12)
        a = g.input()
        big = g.shift(a, 2)                                     # 值域 [-4, 4)
        g.output(g.q(big, 12, 11, "trunc", "wrap"))
        ri = run(g, [x], "ideal")
        want = np.mod(x / 2048.0 * 4 + 1.0, 2.0) - 1.0          # 模 2 回绕到 [-1, 1)
        np.testing.assert_allclose(ri.y, want)
        rf = run(g, [x], "fixed", keep="all")
        np.testing.assert_allclose(rf.y, want)                  # 不丢小数位时，wrap 两种解释一致


class TestExactOps(unittest.TestCase):
    def test_exact_program_has_identical_interpretations(self):
        rng = np.random.default_rng(2)
        x = rnd_codes(rng, shape=(3, 640))
        g = prog(out_bits=40, out_rate=Fraction(1, 4))
        a = g.input()
        c = g.const(0.375, 8, 6)                                 # 可精确表示
        y = g.add(g.mul(a, c), g.delay(g.neg(a), 3))
        y = g.sub(y, g.shift(g.delay(a, 1), -2))
        y = g.decimate(g.add(y, g.decimate(g.interpolate(g.decimate(y, 2, 1), 2), 1)), 4, 3)
        g.output(g.q(g.shift(y, -2), 40, 39, "round", "sat"))   # 先缩小，保证不饱和
        rf, ri = run(g, [x], "fixed", keep="all"), run(g, [x], "ideal", keep="all")
        self.assertEqual(rf.sat, {})
        np.testing.assert_allclose(rf.y, ri.y, rtol=0, atol=0)

    def test_rate_mismatch_is_rejected(self):
        g = prog()
        a = g.input()
        with self.assertRaises(ContractError) as cm:
            g.add(a, g.decimate(a, 2))
        self.assertEqual(cm.exception.code, "rate_mismatch")

    def test_decimation_phases_pair_by_sample_index(self):
        g = prog(out_bits=14, out_rate=Fraction(1, 2))
        a = g.input()
        y = g.add(g.decimate(a, 2, 0), g.decimate(a, 2, 1))     # 多相和：x[2m] + x[2m+1]
        g.output(g.q(g.shift(y, -1), 14, 13))
        x = np.arange(-50, 50).reshape(1, -1)
        rf = run(g, [x], "fixed", keep="all")
        want = (x[:, 0::2] + x[:, 1::2]) / 2.0 / 2048.0
        np.testing.assert_allclose(rf.y, want)

    def test_reframe_inserts_cyclic_prefix(self):
        g = prog(out_rate=Fraction(80, 64), out_bits=12)
        a = g.input()
        g.output(g.reframe(a, 64, list(range(48, 64)) + list(range(64))))
        x = np.arange(128).reshape(1, -1) - 64
        rf = run(g, [x], "fixed", keep="all")
        codes = np.round(rf.y * 2048).astype(int)[0]
        frame0 = list(range(48, 64)) + list(range(64))
        self.assertEqual(codes[:80].tolist(), [v - 64 for v in frame0])
        self.assertEqual(codes[80:96].tolist(), [64 + v - 64 for v in range(48, 64)])


class TestBlocks(unittest.TestCase):
    def test_reframe_and_interleave_roundtrip(self):
        """串并转换后再按逆序并串：每帧内样点顺序反转。"""
        g = prog(out_bits=12)
        a = g.input()
        parts = [g.reframe(a, 8, [s]) for s in range(8)]
        g.output(g.interleave(parts[::-1]))
        x = np.arange(32).reshape(1, -1) - 16
        rf = run(g, [x], "fixed", keep="all")
        codes = np.round(rf.y * 2048).astype(int)[0]
        want = np.concatenate([x[0, 8 * f:8 * f + 8][::-1] for f in range(4)])
        np.testing.assert_array_equal(codes, want)


class TestFeedback(unittest.TestCase):
    def test_counter(self):
        g = prog(out_bits=12)
        a = g.input()
        cnt = g.counter(7, 5, like=a)
        g.output(g.q(g.add(g.shift(cnt, 6), g.const(0, 2, 0)), 12, 11, "trunc", "wrap"))
        x = np.zeros((2, 50), dtype=int)
        rf = run(g, [x], "fixed", keep="all")
        want_cnt = (np.arange(50) * 7) % 32
        np.testing.assert_array_equal(rf.values[cnt.i][0], want_cnt)

    def test_integrator_fast_path_matches_manual(self):
        rng = np.random.default_rng(3)
        x = rnd_codes(rng, shape=(2, 3000))
        g = prog(out_bits=12)
        a = g.input()
        acc = g.integrate(a, 14)                               # 模 2^14 回绕的累加
        g.output(g.q(acc, 12, 11, "trunc", "wrap"))
        rf = run(g, [x], "fixed", keep="all")
        cs = np.cumsum(x, axis=1)
        want = ((cs + (1 << 13)) % (1 << 14)) - (1 << 13)
        np.testing.assert_array_equal(rf.values[acc.i], want)

    def test_generic_loop_iir(self):
        """一阶 IIR：s[m+1] = q(s[m]·a + x[m])，饱和、截位在环内，走逐样点求值。"""
        rng = np.random.default_rng(4)
        x = rnd_codes(rng, shape=(2, 300))
        g = prog(out_bits=16)
        xin = g.input()
        s = g.state(16, 15, 0.0, like=xin)
        nxt = g.q(g.add(g.mul(s, g.const(0.75, 4, 2)), g.shift(xin, -2)), 16, 15, "trunc", "sat")
        g.close(s, nxt)
        g.output(s)
        rf = run(g, [x], "fixed", keep="all")
        sv = np.zeros(2, dtype=np.int64)
        want = []
        for m in range(300):
            want.append(sv.copy())
            v = sv * 3 + (x[:, m].astype(np.int64) << 4)          # s·0.75 为 F=17；x/4 为 F=13，左移 4 对齐
            v = v >> 2                                               # 截到 F=15
            sv = np.clip(v, -(1 << 15), (1 << 15) - 1)
        np.testing.assert_array_equal(rf.values[s.i], np.stack(want, axis=1))


class TestApproxPoints(unittest.TestCase):
    def test_lut_ideal_vs_fixed(self):
        g = prog(out_bits=14)
        a = g.input()
        y = g.lut(a, lambda v: np.sin(np.pi * v), 8, 14, 13, mid=True)
        g.output(y)
        x = np.arange(-2048, 2048, 7).reshape(1, -1)
        rf, ri = run(g, [x], "fixed", keep="all"), run(g, [x], "ideal", keep="all")
        np.testing.assert_allclose(ri.y, np.sin(np.pi * x / 2048.0))
        self.assertLess(np.max(np.abs(rf.y - ri.y)), np.pi / 256 + 2 ** -13)   # 地址截断 + 表值舍入

    def test_const_rounding_is_an_approximation(self):
        g = prog(out_bits=24)
        a = g.input()
        g.output(g.q(g.mul(a, g.const(1 / 3, 10, 9)), 24, 23))
        x = np.full((1, 4), 1000)
        rf, ri = run(g, [x], "fixed", keep="all"), run(g, [x], "ideal", keep="all")
        self.assertGreater(np.max(np.abs(rf.y - ri.y)), 0)
        np.testing.assert_allclose(ri.y, x / 2048.0 / 3)


class TestLayers(unittest.TestCase):
    def build(self, fold=None, mix_w=14):
        g = prog(out_bits=16)
        a = g.input()
        with g.scope("mix"):
            y = g.q(g.mul(a, g.const(0.5, 4, 3)), mix_w, mix_w - 1)
            if fold is not None:
                g.commit(fold=fold, mul_max=1)
        g.output(g.q(y, 16, 15))
        return g

    def test_b_layer_changes_keep_a_hash(self):
        self.assertEqual(self.build().a_hash(), self.build(fold=4).a_hash())
        self.assertNotEqual(self.build().b_hash(), self.build(fold=4).b_hash())

    def test_a_layer_changes_change_a_hash(self):
        self.assertNotEqual(self.build(mix_w=14).a_hash(), self.build(mix_w=13).a_hash())

    def test_unknown_commitment_rejected(self):
        g = prog()
        g.input()
        with g.scope("s"):
            with self.assertRaises(ContractError):
                g.commit(speed=3)

    def test_output_interface_checked(self):
        g = prog(out_bits=16)
        a = g.input()
        with self.assertRaises(ContractError) as cm:
            g.output(a)
        self.assertEqual(cm.exception.code, "interface")


if __name__ == "__main__":
    unittest.main()
