"""测试信号库。每个信号返回：带损伤的输入码、干净信号的解析描述、其余元数据。按名字在 Task 里选用。"""
from __future__ import annotations

import math

import numpy as np

from .tones import ToneSet

LIB = {}


def stimulus(name):
    def deco(fn):
        LIB[name] = fn
        return fn
    return deco


@stimulus("tones_with_dense_blockers")
def tones_with_dense_blockers(task, idx: int, n_in: int) -> dict:
    """实数带通输入：中频 f_if 处 ±passband 内 24 个复音（期望信号），外加覆盖全部混叠频带
    k·fs_out ± passband（k≠0）的阻塞音（每带 2 个随机频点），经输入位宽量化。"""
    p = task.params
    R, fp, f_if = p["r_total"], p["passband"], p["fcw"] / 2.0 ** 32
    fo = 1.0 / R
    rng = np.random.default_rng([20261010, idx, task.seed_key])
    t = np.arange(n_in, dtype=np.float64)
    freqs = np.sort(rng.uniform(-0.92 * fp, 0.92 * fp, 24))
    amps = np.exp(1j * rng.uniform(0, 2 * np.pi, 24))
    s = np.zeros(n_in, dtype=np.complex128)
    for f, a in zip(freqs, amps):
        s += a * np.exp(2j * np.pi * f * t)
    desired = np.real(s * np.exp(2j * np.pi * f_if * t))
    p_des = np.mean(desired ** 2)
    offs = []
    for k in range(-R, R + 1):
        if k == 0:
            continue
        for _ in range(2):
            f = k * fo + rng.uniform(-fp, fp)
            if 0.02 < f_if + f < 0.48:
                offs.append(float(f))
    p_each = 3.0 * p_des * 10 ** (p["blocker_rel_db"] / 10) / len(offs)
    blk = np.zeros(n_in)
    for f in offs:
        blk += math.sqrt(2 * p_each) * np.cos(2 * np.pi * (f_if + f) * t + rng.uniform(0, 2 * np.pi))
    total = desired + blk
    scale = 0.9 / np.max(np.abs(total))
    full = 1 << (task.interface["in_bits"] - 1)
    codes = np.clip(np.round(total * scale * full), -full, full - 1).astype(np.int64)
    # 干净信号 = scale·Re{s·e^{j2π f_if t}}：写成共轭对称的复指数之和
    a = amps * 0.5 * scale
    clean = ToneSet(np.concatenate([freqs, -freqs]), np.concatenate([a, np.conj(a)]),
                     np.concatenate([np.full(24, f_if), np.full(24, -f_if)]))
    return {"x_codes": codes, "clean": clean, "blocker_offsets": tuple(offs), "scale": scale}


@stimulus("baseband_tones")
def baseband_tones(task, idx: int, n_in: int) -> dict:
    """复基带输入：±passband 内 24 个复音，I/Q 各自量化到输入位宽（无干扰；损伤只有输入量化）。"""
    p = task.params
    rng = np.random.default_rng([20261011, idx, task.seed_key])
    t = np.arange(n_in, dtype=np.float64)
    freqs = np.sort(rng.uniform(-p["passband"], p["passband"], 24))
    amps = np.exp(1j * rng.uniform(0, 2 * np.pi, 24))
    s = np.exp(2j * np.pi * np.outer(t, freqs)) @ amps
    scale = 0.9 / max(np.max(np.abs(s.real)), np.max(np.abs(s.imag)))
    full = 1 << (task.interface["in_bits"] - 1)
    ci = np.clip(np.round(s.real * scale * full), -full, full - 1).astype(np.int64)
    cq = np.clip(np.round(s.imag * scale * full), -full, full - 1).astype(np.int64)
    return {"x_codes": ci, "xq_codes": cq, "clean": ToneSet(freqs, amps * scale), "scale": scale}
