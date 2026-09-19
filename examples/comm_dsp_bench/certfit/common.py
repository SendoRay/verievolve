"""certfit — 证书适应度引擎（CommDSP-Bench Arm C）

评估oracle层级（论文第4章的核心对象）：
  L2  确定性积分  : 固定 Sobol 格点 / 全枚举上的精确整数域模型仿真——零随机性、
                    可复现（同设计重评分数逐位一致），无采样噪声。
  L3  声明性最坏界 : 区间算术闭式最坏情况界——对全体输入成立的 sound bound。

证书适应度 = L2 均值 SQNR（排序用） + L3 最坏界（安全用），两者均为输入的
确定性函数。与之对照的 Arm S（OpenEvolve 原生评估器）用 fresh-seed 蒙特卡罗，
适应度本身是随机变量。

模分解引理（cmul 族）：整数域上 uniformly-scaled 量化误差只依赖
v mod 2^s，而 a·c mod 2^s 的分布可由 2-adic 赋值分解精确求出——
因此 cmul 的总体均值 SQNR 可以**精确**计算（零积分误差），见
exact_error_moment()。
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

import numpy as np

SQNR_CAP_DB = 999.0


# ---------------------------------------------------------------------------
# 确定性格点（L2 层）：Sobol 序列固定种子 → 同一设计永远同一组输入
# ---------------------------------------------------------------------------

_SOBOL_SEED = 20260920


def sobol_unit(n: int, dim: int) -> np.ndarray:
    """n×dim 的确定性 Sobol 点阵 ∈ [0,1)^dim（scipy 打乱固定种子）。"""
    from scipy.stats import qmc

    m = max(1, int(math.ceil(math.log2(max(n, 2)))))
    eng = qmc.Sobol(d=dim, scramble=True, seed=_SOBOL_SEED)
    pts = eng.random_base2(m)  # 2^m 个点（≥ n）
    return pts[:n]


def lattice_points(n: int, mods: List[int]) -> np.ndarray:
    """确定性 Sobol 点映射到各维整数格（0..mod-1），用于离散输入空间。

    返回 n×len(mods) 的 int64 数组。"""
    pts = sobol_unit(n, len(mods))
    return np.floor(pts * np.array(mods, dtype=np.float64)).astype(np.int64)


def gaussian_points(n: int, dim: int, sigma: float) -> np.ndarray:
    """确定性 Sobol + 逆 CDF → 标准高斯点阵（连续维度积分用）。"""
    from scipy.stats import norm

    pts = sobol_unit(n, dim)
    return norm.ppf(np.clip(pts, 1e-12, 1 - 1e-12)) * sigma


# ---------------------------------------------------------------------------
# SQNR 与量化器
# ---------------------------------------------------------------------------

def sqnr_db(signal_power: float, err_power: float) -> float:
    if err_power <= 0.0:
        return SQNR_CAP_DB
    if signal_power <= 0.0:
        return 0.0
    return 10.0 * math.log10(signal_power / err_power)


def quant_rne(v: int, drop: int) -> int:
    """整数 v 舍弃低 drop 位（round-to-nearest-half-up），返回量化后的整数。"""
    if drop <= 0:
        return v
    half = 1 << (drop - 1)
    return ((v + half) >> drop) << drop


def quant_trunc(v: int, drop: int) -> int:
    """整数 v 舍弃低 drop 位（floor / 算术右移）。"""
    if drop <= 0:
        return v
    return (v >> drop) << drop


# ---------------------------------------------------------------------------
# 模分解引理（cmul 族精确误差矩）
# ---------------------------------------------------------------------------

def _phi(r: int, s: int, mode: str) -> int:
    """残差 r = v mod 2^s 上的量化误差 φ(r) = Q(v) - v（只依赖 r 与模式）。

    rne（half-up）：r < 2^(s-1) → −r；r > 2^(s-1) → 2^s − r；平局 r = 2^(s-1) → +2^(s-1)。
    trunc（floor）：e = −r ∈ (−2^s, 0]。
    """
    if mode == "trunc":
        return -r
    half = 1 << (s - 1)
    if r < half:
        return -r
    if r > half:
        return (1 << s) - r
    return half  # 平局向上


def _residue_dist(s: int, nbits: int) -> np.ndarray:
    """A = a·c 的残差分布 P(A mod 2^s)，a,c 独立均匀于 2^nbits 个连续整数。

    精确性条件：s ≤ nbits-1（区间起点 −2^(nbits-1) 为 2^s 倍数且 2^s | 2^nbits
    → a mod 2^s 均匀于 Z/2^s）。由 (ν(a),ν(c)) 赋值混合给出：
      ν(a)=j, ν(c)=k, j+k<s → r 均匀分布于 ν(r)=j+k 的残差类
      j+k ≥ s 或 a≡0 → r = 0
    """
    if s > nbits - 1:
        raise ValueError(f"exact residue dist requires s <= nbits-1 ({s} > {nbits-1})")
    size = 1 << s
    r = np.arange(size, dtype=np.int64)
    lowbit = np.bitwise_and(r, -r)
    nu = np.zeros(size, dtype=np.int64)
    nz = r > 0
    nu[nz] = np.log2(lowbit[nz].astype(np.float64)).astype(np.int64)

    pnu = np.array([2.0 ** -(j + 1) for j in range(nbits)] + [2.0 ** -nbits])
    dist = np.zeros(size, dtype=np.float64)
    for j in range(nbits + 1):
        for k in range(nbits + 1):
            p = pnu[j] * pnu[k]
            t = j + k
            if t >= s:
                dist[0] += p  # A ≡ 0 (mod 2^s)
            else:
                mask = (nu == t)
                dist[mask] += p / float(mask.sum())
    return dist


def _phi_moments_over_dist(dist: np.ndarray, s: int, mode: str) -> Tuple[float, float]:
    """给定残差分布，计算 φ 的 (E, E²)。"""
    r = np.arange(len(dist), dtype=np.int64)
    phi = np.array([_phi(int(x), s, mode) for x in r], dtype=np.float64)
    mean = float((dist * phi).sum())
    mom2 = float((dist * phi * phi).sum())
    return mean, mom2


def _circular_conv(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """圆卷积（FFT，概率向量，误差 < 1e-12）。"""
    n = len(a)
    fa = np.fft.rfft(a)
    fb = np.fft.rfft(b)
    out = np.fft.irfft(fa * fb, n)
    return np.clip(out, 0.0, None)


def cmul_exact_err_moments(drop: int, mode: str = "rne",
                           karatsuba: bool = False) -> Dict[str, float]:
    """cmul 数据通路输出量化误差的精确矩（模分解引理，论文引理 4.1）。

    数据通路：乘积与累加在整数域精确，输出处一次性量化丢 `drop` 位。
    re = Q(A−B), im = Q(A'+B')（direct）或 im = Q(P1−A−B)（karatsuba）。
    关键点：Q(v) 的误差只依赖 v mod 2^drop，而 v mod 2^drop 的分布是
    乘积残差分布的**圆卷积**（wraparound 使 φ(A−B) ≠ φ(A)−φ(B)）。

    返回 re/im 各自的 (E[e], E[e^2])，精确。
    """
    s = drop
    if s <= 0:
        return {"re_mean": 0.0, "re_mom2": 0.0, "im_mean": 0.0, "im_mom2": 0.0}

    distA = _residue_dist(s, 16)          # 乘积 ac（16 位操作数）
    distV2 = _circular_conv(distA, distA)  # A − B（或 A + B）
    re_mean, re_mom2 = _phi_moments_over_dist(distV2, s, mode)
    im_mean, im_mom2 = re_mean, re_mom2    # direct: im = A' + B' 同分布

    if karatsuba:
        distA17 = _residue_dist(s, 17)     # P1 = (a+b)(c+d)（17 位和）
        distV3 = _circular_conv(_circular_conv(distA17, distA), distA)
        im_mean, im_mom2 = _phi_moments_over_dist(distV3, s, mode)

    return {"re_mean": re_mean, "re_mom2": re_mom2,
            "im_mean": im_mean, "im_mom2": im_mom2}


def cmul_exact_signal_power(karatsuba: bool = False) -> float:
    """E[v^2]（v = ac - bd，整数域）的精确值（Fraction 有理计算）。"""
    # a 均匀于 [-2^15, 2^15)：N=2^16 个连续整数
    n = 1 << 16
    mean = Fraction(-1, 2)  # sum = -32768
    ex2 = Fraction(n * n - 1, 12) + mean ** 2  # E[a^2]
    # E[v^2] = E[(ac)^2] + E[(bd)^2] - 2 E[a]E[c]E[b]E[d]
    ev2 = 2 * ex2 ** 2 - 2 * mean ** 4
    return float(ev2)


# ---------------------------------------------------------------------------
# 区间算术最坏界（L3 层）helper
# ---------------------------------------------------------------------------

def interval_mul_worst(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[int, int]:
    """整数区间乘法（端点组合）。"""
    prods = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]]
    return (min(prods), max(prods))


def wc_bound_bits(abs_max: float, drop: int, mode: str = "rne") -> float:
    """量化 |e| ≤（绝对值最大 |v| 与 drop 位、舍入模式的最坏误差）。"""
    q = float(1 << drop)
    if drop <= 0:
        return 0.0
    return q / 2.0 if mode == "rne" else q
