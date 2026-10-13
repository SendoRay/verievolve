"""与实现无关的裁判：只依据数学规格与实现的输入输出打分。

裁判不知道实现内部用了什么结构（CIC、半带、CORDIC 或任何别的东西），因此
- 手写专家积木链、搜索得到的链、LLM 写出的程序，全部走同一评分；
- 换一条链只需要换规格（参考公式 + 场景），不需要为任何算子写适配。

评分（每个场景）：
  snr_db   ：输出对理想基带期望信号的信噪比。时延未知，由裁判在网格上搜索并细化；
             只拟合一个复增益，因此通带幅度/相位失真、阻塞音混叠、量化全部计入误差。
  ripple_db：24 个期望复音各自最小二乘增益的幅度起伏（峰峰值）。
达标条件：所有搜索场景 snr ≥ 理想接收机上限 − impl_loss，且 ripple ≤ 上限。
阻塞音覆盖全部混叠频带（每带 2 个频点），因此任何一个频带上抑制不足都会被发现。
留出场景（阻塞音位置不同）只用于最终复验，搜索与 LLM 都看不到。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

from .rx_spec import PHASE_ACC_BITS, ChainSpec

N_OUT = 1024
N_WARM = 192
N_TONES = 24
SEARCH_SCENARIOS = (0, 1)
HOLDOUT_SCENARIOS = (10, 11, 12)
MAX_DELAY_OUT = 160          # 裁判接受的最大群时延（输出样点）
JUDGE_VERSION = "v2-dense-blockers"
BLOCKERS_PER_BAND = 2


@dataclass(frozen=True)
class Scene:
    idx: int
    x_codes: np.ndarray
    tone_freqs: np.ndarray
    tone_amps: np.ndarray
    blocker_offsets: tuple
    n_in: int
    ceiling_db: float


_CACHE: dict = {}


def n_in(spec: ChainSpec) -> int:
    return (N_OUT + N_WARM + MAX_DELAY_OUT) * spec.r_total


def scene(spec: ChainSpec, idx: int) -> Scene:
    key = (spec.sha256(), idx)
    if key in _CACHE:
        return _CACHE[key]
    rng = np.random.default_rng([20261010, idx, int(spec.sha256()[:8], 16)])
    n = n_in(spec)
    t = np.arange(n, dtype=np.float64)
    fp, fo = spec.passband, spec.fs_out
    freqs = np.sort(rng.uniform(-0.92 * fp, 0.92 * fp, N_TONES))
    amps = np.exp(1j * rng.uniform(0, 2 * np.pi, N_TONES))
    s = np.zeros(n, dtype=np.complex128)
    for f, a in zip(freqs, amps):
        s += a * np.exp(2j * np.pi * f * t)
    desired = np.real(s * np.exp(2j * np.pi * spec.f_if * t))
    p_des = np.mean(desired**2)
    # 阻塞音（v2）：覆盖全部会折回通带的频带 k·fs_out ± passband（k≠0），每个频带 2 个随机频点，
    # 总功率等于 3 个 blocker_rel_db 强度的单音。v1 每场景只有 3 个频点，搜索会只在这些频点上
    # 做抑制，换一组位置即失效（见 holdout_check_v1_20261010.json）。
    offs = []
    for k in range(-spec.r_total, spec.r_total + 1):
        if k == 0:
            continue
        for _ in range(BLOCKERS_PER_BAND):
            f = k * fo + rng.uniform(-fp, fp)
            if 0.02 < spec.f_if + f < 0.48:
                offs.append(float(f))
    p_each = 3.0 * p_des * 10 ** (spec.blocker_rel_db / 10) / len(offs)
    blk = np.zeros(n)
    for f in offs:
        blk += math.sqrt(2 * p_each) * np.cos(2 * np.pi * (spec.f_if + f) * t + rng.uniform(0, 2 * np.pi))
    total = desired + blk
    scale = 0.9 / np.max(np.abs(total))
    full = 1 << (spec.input_bits - 1)
    codes = np.clip(np.round(total * scale * full), -full, full - 1).astype(np.int64)
    sc = Scene(idx, codes, freqs, amps * 0.5 * scale, tuple(offs), n, 0.0)
    sc = Scene(idx, codes, freqs, sc.tone_amps, tuple(offs), n, _ceiling(spec, sc))
    _CACHE[key] = sc
    return sc


def _ref(sc: Scene, t: np.ndarray) -> np.ndarray:
    return np.exp(2j * np.pi * np.outer(t, sc.tone_freqs)) @ sc.tone_amps


def _ceiling(spec: ChainSpec, sc: Scene) -> float:
    """理想接收机（精确混频 + 长 Kaiser 低通 + 抽取）的 SNR：只受 ADC 量化限制。"""
    t = np.arange(sc.n_in)
    x = sc.x_codes / float(1 << (spec.input_bits - 1))
    ph = 2 * np.pi * ((t * spec.fcw) % 2**PHASE_ACC_BITS) / 2.0**PHASE_ACC_BITS
    fp = spec.passband
    ntap = min(int(40 / fp) | 1, 40001)
    h = sps.firwin(ntap, 0.5 * (fp + spec.fs_out - fp), window=("kaiser", 14), fs=1.0)
    y = sps.oaconvolve(x * np.exp(-1j * ph), h)[: len(x)][:: spec.r_total]
    d = (ntap - 1) / 2
    m = np.arange(len(y))
    sel = (m * spec.r_total >= ntap) & (m < len(y))
    r = _ref(sc, m[sel] * spec.r_total - d)
    a = np.vdot(r, y[sel]) / np.vdot(r, r)
    e = y[sel] - a * r
    return float(10 * np.log10(np.mean(np.abs(a * r) ** 2) / np.mean(np.abs(e) ** 2)))


def snr_min(spec: ChainSpec, idx: int) -> float:
    return scene(spec, idx).ceiling_db - spec.impl_loss_db


def score(spec: ChainSpec, idx: int, y: np.ndarray) -> dict:
    """y：实现输出的复数序列（归一化到 ±1）。"""
    sc = scene(spec, idx)
    need = N_WARM + N_OUT
    lim = snr_min(spec, idx)
    if len(y) < need:
        return {"scenario": idx, "valid_output": False, "outputs": int(len(y)), "needed": need,
                "snr_db": -99.0, "ripple_db": 99.0, "snr_min_db": lim,
                "ripple_max_db": spec.ripple_max_db, "passed": False}
    m = np.arange(N_WARM, need)
    ys = y[N_WARM:need]
    p_y = float(np.mean(np.abs(ys) ** 2))
    if p_y <= 0:
        return {"scenario": idx, "valid_output": True, "snr_db": -99.0, "ripple_db": 99.0,
                "snr_min_db": lim, "ripple_max_db": spec.ripple_max_db, "passed": False,
                "note": "all-zero output"}
    R = spec.r_total

    def snr_at(d: float) -> float:
        r = _ref(sc, m * R - d)
        a = np.vdot(r, ys) / np.vdot(r, r)
        e = ys - a * r
        return 10 * math.log10(max(np.mean(np.abs(a * r) ** 2), 1e-300) /
                               max(np.mean(np.abs(e) ** 2), 1e-300))
    grid = np.arange(0.0, MAX_DELAY_OUT * R, R / 4.0)
    vals = [snr_at(d) for d in grid]
    d0 = float(grid[int(np.argmax(vals))])
    lo, hi = d0 - R / 4.0, d0 + R / 4.0
    for _ in range(40):                       # 黄金分割细化
        a1, a2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if snr_at(a1) < snr_at(a2):
            lo = a1
        else:
            hi = a2
    d = 0.5 * (lo + hi)
    snr = snr_at(d)
    basis = np.exp(2j * np.pi * np.outer(m * R - d, sc.tone_freqs))
    c, *_ = np.linalg.lstsq(basis, ys, rcond=None)
    g = np.abs(c) / np.abs(sc.tone_amps)
    ripple = float(20 * np.log10(g.max() / max(g.min(), 1e-300)))
    return {"scenario": idx, "valid_output": True, "snr_db": float(snr), "ripple_db": ripple,
            "delay_in": float(d), "gain_db": float(20 * np.log10(np.mean(g))),
            "snr_min_db": lim, "ripple_max_db": spec.ripple_max_db,
            "passed": bool(snr >= lim and ripple <= spec.ripple_max_db)}


def combine(spec: ChainSpec, rows: list[dict]) -> dict:
    worst = min(rows, key=lambda r: r["snr_db"] - r["snr_min_db"])
    return {"passed": all(r["passed"] for r in rows),
            "snr_margin_db": float(worst["snr_db"] - worst["snr_min_db"]),
            "ripple_db": float(max(r["ripple_db"] for r in rows)),
            "ripple_max_db": spec.ripple_max_db,
            "scenarios": rows}


def violation(q: dict) -> float:
    return (max(0.0, -q["snr_margin_db"])
            + 3.0 * max(0.0, q["ripple_db"] - q["ripple_max_db"]) / max(q["ripple_max_db"], 1e-3))


def probe(spec: ChainSpec, idx: int, y: np.ndarray, period: int) -> dict:
    """中间信号观测：相对理想期望信号的带内 SNR（只计通带内残差）、带外残留、增益与时延。

    中间级尚未滤除阻塞音，所以用带内残差衡量“这一级之前是否已经损坏了期望信号”。
    """
    sc = scene(spec, idx)
    y = np.asarray(y, dtype=np.complex128)
    if not np.iscomplexobj(y) or np.all(y.imag == 0):
        note = "real-valued signal"
    else:
        note = None
    start = int(N_WARM * spec.r_total / period)
    L = min(len(y) - start, 4096)
    if L < 256:
        return {"error": f"too few samples ({len(y)}) for this rate"}
    m = np.arange(start, start + L)
    ys = y[start:start + L]
    win = sps.windows.blackmanharris(L)
    fr = np.fft.fftfreq(L)
    inb = np.abs(fr) <= spec.passband * period * 1.02

    def fit(d):
        r = _ref(sc, m * period - d)
        a = np.vdot(r, ys) / np.vdot(r, r)
        return a, r
    def corr(d):
        a, r = fit(d)
        return abs(a) ** 2 * np.vdot(r, r).real
    step = max(period / 4.0, 1.0)
    grid = np.arange(0.0, MAX_DELAY_OUT * spec.r_total, step)
    vals = [corr(d) for d in grid]
    d0 = float(grid[int(np.argmax(vals))])
    lo, hi = d0 - step, d0 + step
    for _ in range(30):
        a1, a2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if corr(a1) < corr(a2):
            lo = a1
        else:
            hi = a2
    d = 0.5 * (lo + hi)
    a, r = fit(d)
    e = ys - a * r
    S = np.fft.fft(win * a * r)
    E = np.fft.fft(win * e)
    ps, pe_in, pe_out = (np.sum(np.abs(S[inb]) ** 2), np.sum(np.abs(E[inb]) ** 2),
                         np.sum(np.abs(E[~inb]) ** 2))
    out = {"inband_snr_db": float(10 * np.log10(ps / max(pe_in, 1e-300))),
           "outband_residual_rel_db": float(10 * np.log10(max(pe_out, 1e-300) / ps)),
           "gain_db": float(20 * np.log10(max(abs(a), 1e-300))), "delay_in": d,
           "rate": f"input_rate/{period}"}
    if note:
        out["note"] = note
    return out
