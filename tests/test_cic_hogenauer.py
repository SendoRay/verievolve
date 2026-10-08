"""CONTRACT_CIC_WITNESS_v1 §4.1-5：Hogenauer 1981 §IV-C 程序（式 21）的复现测试。

钉定条款：
- 论文标准设计例（N=4、M=1、R=25、Bin=Bout=16）：B_j = [1, 6, 9, 13, 14, 15, 16, 17]，
  输出源 B_(2N+1) = 19；
- 非退化 N=3 独立例（R=5、N=3、Win=16、Wout=12）：B_j = [4, 6, 7, 7, 8, 9]
  （不被 clamp 掩盖）；
- 逐级断言最终 B_j 满足式 (21)：G_j·(2N)·2^(2 B_j) ≤ 2^(2 B_fmt)；
- G_j 由直接多项式卷积独立实现核对。
"""

import sys
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.cic.gen_candidates_v1 import eq21_gain, hogenauer_profile

CASES = [(25, 4, 16, 16), (5, 3, 16, 12), (2, 3, 12, 16), (2, 4, 12, 16),
         (4, 3, 12, 16), (4, 4, 12, 16)]


def eq21_gain_indep(R: int, N: int, source: int) -> int:
    """独立实现：numpy int64 直接多项式卷积核对 G_j。"""
    if source <= N:
        a, b = source - 1, N
    else:
        a, b = 2 * N - source + 1, 0
    h = np.ones(R, dtype=np.int64) if b > 0 else np.ones(1, dtype=np.int64)
    for _ in range(b - 1):
        h = np.convolve(h, np.ones(R, dtype=np.int64))
    for _ in range(a):
        h = np.convolve(h, np.array([1, -1], dtype=np.int64))
    return int(np.sum(h * h))


def test_hogenauer_1981_worked_example():
    B, B_fmt, W_full, clamps = hogenauer_profile(25, 4, W_ADC=16, W_OUT=16)
    assert (W_full, B_fmt) == (35, 19)
    assert B == [1, 6, 9, 13, 14, 15, 16, 17]
    assert clamps == []


def test_hogenauer_n3_undiagnosed_by_clamp():
    # codex 诊断例：N=3 不退化，(2N)=6 的预算依赖必须成立
    B, B_fmt, W_full, _ = hogenauer_profile(5, 3, W_ADC=16, W_OUT=12)
    assert (W_full, B_fmt) == (23, 11)
    assert B == [4, 6, 7, 7, 8, 9]


def test_contract_combos_profiles():
    # (2,3)/(2,4)/(4,3) 输出格式宽于裁剪预算，H 档无裁剪空间，钳到全 0（预期并登记）；
    # (4,4) 仅后两级保留裁剪。
    B23, Bf23, _, cl23 = hogenauer_profile(2, 3)
    assert (B23, Bf23) == ([0] * 6, -1) and len(cl23) == 6
    B24, Bf24, _, _ = hogenauer_profile(2, 4)
    assert (B24, Bf24) == ([0] * 8, 0)
    B43, Bf43, _, _ = hogenauer_profile(4, 3)
    assert (B43, Bf43) == ([0] * 6, 2)
    B44, Bf44, _, _ = hogenauer_profile(4, 4)
    assert (B44, Bf44) == ([0, 0, 0, 0, 0, 0, 1, 2], 4)


def test_eq21_satisfied_per_stage():
    # 逐级断言：实际发生裁剪的级（B_j > B_{j-1}，B_0 = 0）满足式 (21)；
    # 无裁剪的级该源不存在，约束空真。B 非递减、不超过输出格式位。
    for R, N, w_adc, w_out in CASES:
        B, B_fmt, W_full, _ = hogenauer_profile(R, N, W_ADC=w_adc, W_OUT=w_out)
        assert len(B) == 2 * N
        assert all(B[i] <= B[i + 1] for i in range(len(B) - 1))
        assert B[-1] <= max(B_fmt, 0)
        for j in range(1, 2 * N + 1):
            prev = B[j - 2] if j > 1 else 0
            if B[j - 1] > prev:  # 该级确实裁剪
                assert B_fmt >= B[j - 1], (R, N, j)
                G = eq21_gain(R, N, j)
                assert G * (2 * N) <= (1 << (2 * (B_fmt - B[j - 1]))), (R, N, j)


def test_gain_independent_crosscheck():
    for R, N in ((2, 3), (2, 4), (4, 3), (4, 4), (5, 3), (25, 4)):
        for j in range(1, 2 * N + 1):
            assert eq21_gain(R, N, j) == eq21_gain_indep(R, N, j), (R, N, j)


def test_profiles_monotone_nonneg_widths():
    for R, N, w_adc, w_out in CASES:
        B, B_fmt, W_full, _ = hogenauer_profile(R, N, W_ADC=w_adc, W_OUT=w_out)
        assert all(b >= 0 for b in B)
        for b in B:  # 锁存窗口 [B_j, B_max] 至少 1 位
            assert 1 <= W_full - b <= W_full
