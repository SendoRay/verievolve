"""指标库：候选输出与参考（解析音调集）比较，统一做时延搜索与复增益对齐。"""
from __future__ import annotations

import math

import numpy as np

from .tones import ToneSet


def aligned_snr_ripple(y, ref: ToneSet, rate: int, warm: int, n_out: int, max_delay_out: int) -> dict:
    """带内 SNR 与通带纹波。
    SNR：在 [0, max_delay_out·rate) 内搜索群时延（粗网格 rate/4 + 黄金分割细化），只拟合一个复增益，
    其余（混叠、通带失真、量化）全部计为误差。纹波：各参考音调的最小二乘增益幅度的峰峰值。"""
    need = warm + n_out
    if len(y) < need:
        return {"valid_output": False, "outputs": int(len(y)), "needed": need, "snr_db": -99.0, "ripple_db": 99.0}
    m = np.arange(warm, need)
    ys = y[warm:need]
    if float(np.mean(np.abs(ys) ** 2)) <= 0:
        return {"valid_output": True, "snr_db": -99.0, "ripple_db": 99.0, "note": "all-zero output"}

    def snr_at(d):
        r = ref.at(m * rate - d)
        a = np.vdot(r, ys) / np.vdot(r, r)
        e = ys - a * r
        return 10 * math.log10(max(np.mean(np.abs(a * r) ** 2), 1e-300) / max(np.mean(np.abs(e) ** 2), 1e-300))
    grid = np.arange(0.0, max_delay_out * rate, rate / 4.0)
    vals = [snr_at(d) for d in grid]
    d0 = float(grid[int(np.argmax(vals))])
    lo, hi = d0 - rate / 4.0, d0 + rate / 4.0
    for _ in range(40):
        a1, a2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if snr_at(a1) < snr_at(a2):
            lo = a1
        else:
            hi = a2
    d = 0.5 * (lo + hi)
    snr = snr_at(d)
    basis = np.exp(2j * np.pi * np.outer(m * rate - d, ref.freqs))
    c, *_ = np.linalg.lstsq(basis, ys, rcond=None)
    g = np.abs(c) / np.abs(ref.amps)
    return {"valid_output": True, "snr_db": float(snr),
            "ripple_db": float(20 * np.log10(g.max() / max(g.min(), 1e-300))),
            "delay_in": float(d), "gain_db": float(20 * np.log10(np.mean(g)))}


def known_delay_snr(y, ref: ToneSet, rate: int, delay: float, settle: float) -> float:
    """理想版自身的成绩：时延已知，跳过建立段，只拟合一个复增益。"""
    m = np.arange(len(y))
    sel = m * rate >= settle
    r = ref.at(m[sel] * rate - delay)
    a = np.vdot(r, y[sel]) / np.vdot(r, r)
    e = y[sel] - a * r
    return float(10 * np.log10(np.mean(np.abs(a * r) ** 2) / np.mean(np.abs(e) ** 2)))


def aligned_snr_ripple_real(y, ref: ToneSet, rate: float, warm: int, n_out: int, max_delay_out: int,
                            env_bw: float) -> dict:
    """实带通输出的带内 SNR 与纹波。参考为解析信号 z(t)（ref），实信号 = Re{z}。
    用 y ≈ Re{a·z(t−d)} 拟合复增益 a（吸收载波相位），时延 d 只对齐包络：粗网格步长 1/(8·env_bw) 个输入样点。"""
    need = warm + n_out
    y = np.asarray(y, dtype=np.float64)
    if len(y) < need:
        return {"valid_output": False, "outputs": int(len(y)), "needed": need, "snr_db": -99.0, "ripple_db": 99.0}
    m = np.arange(warm, need)
    ys = y[warm:need]
    if float(np.mean(ys ** 2)) <= 0:
        return {"valid_output": True, "snr_db": -99.0, "ripple_db": 99.0, "note": "all-zero output"}

    def fit(d):
        z = ref.at(m * rate - d)
        A = np.stack([z.real, -z.imag], axis=1)
        c, *_ = np.linalg.lstsq(A, ys, rcond=None)
        f = A @ c
        return f, ys - f

    def snr_at(d):
        f, e = fit(d)
        return 10 * math.log10(max(np.mean(f ** 2), 1e-300) / max(np.mean(e ** 2), 1e-300))
    step = 1.0 / (8.0 * env_bw)
    grid = np.arange(0.0, max_delay_out * rate, step)
    vals = [snr_at(d) for d in grid]
    d0 = float(grid[int(np.argmax(vals))])
    lo, hi = d0 - step, d0 + step
    for _ in range(40):
        a1, a2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if snr_at(a1) < snr_at(a2):
            lo = a1
        else:
            hi = a2
    d = 0.5 * (lo + hi)
    snr = snr_at(d)
    ph = 2 * np.pi * np.outer(m * rate - d, ref.eff())
    c, *_ = np.linalg.lstsq(np.concatenate([np.cos(ph), np.sin(ph)], axis=1), ys, rcond=None)
    k = len(ref.freqs)
    g = np.hypot(c[:k], c[k:]) / np.abs(ref.amps)
    return {"valid_output": True, "snr_db": float(snr),
            "ripple_db": float(20 * np.log10(g.max() / max(g.min(), 1e-300))),
            "delay_in": float(d), "gain_db": float(20 * np.log10(np.mean(g)))}


def known_delay_snr_real(y, ref: ToneSet, rate: float, delay: float, settle: float) -> float:
    m = np.arange(len(y))
    sel = m * rate >= settle
    z = ref.at(m[sel] * rate - delay)
    A = np.stack([z.real, -z.imag], axis=1)
    c, *_ = np.linalg.lstsq(A, np.asarray(y)[sel], rcond=None)
    f = A @ c
    e = np.asarray(y)[sel] - f
    return float(10 * np.log10(np.mean(f ** 2) / np.mean(e ** 2)))
