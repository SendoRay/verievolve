"""链路 A 的现实性变体（讨论归纳 §7，G1、G2）：单个强调制干扰 + 收紧的实现损失。

与链路 A 相同的公式与接口；场景改为 3GPP 阻塞测试的形态：期望信号（通带内 24 个复音）之外只有一个干扰，
干扰是窄带调制信号（中心附近 8 个随机相位的音，宽度约为通带的 1/8，近似 1 个资源块），
功率比期望信号高 blocker_rel_db（默认 45 dB，3GPP NR 基站 ACS/带内阻塞为 43–52 dB），
中心落在会折入通带的混叠带 f_if + k·f_out 附近。总信号峰值定为 0.9 满量程。
不同场景编号对应不同的混叠带 k 与带内偏移（搜索、留出、统计复核各不相同）。
容差：按实现预算 p = 0.1 得 Δ = 10·log10(1.1) = 0.414 dB；通带纹波 ≤ 0.1 dB（链路 A 原为 1.5–2.5 dB、0.2–0.5 dB）。
"""
from __future__ import annotations

import math

import numpy as np

from dspgraph.rx_spec import SPECS

from ..stimuli import ToneSet, stimulus
from ..task import Task, register
from .ddc import ideal


@stimulus("tones_with_strong_blocker")
def tones_with_strong_blocker(task, idx: int, n_in: int) -> dict:
    p = task.params
    R, fp, f_if = p["r_total"], p["passband"], p["fcw"] / 2.0 ** 32
    fo = 1.0 / R
    rng = np.random.default_rng([20261015, idx, task.seed_key])
    t = np.arange(n_in, dtype=np.float64)
    freqs = np.sort(rng.uniform(-0.92 * fp, 0.92 * fp, 24))
    amps = np.exp(1j * rng.uniform(0, 2 * np.pi, 24))
    s = np.exp(2j * np.pi * np.outer(t, freqs)) @ amps
    desired = np.real(s * np.exp(2j * np.pi * f_if * t))
    p_des = np.mean(desired ** 2)
    ks = [k for k in range(-R, R + 1) if k != 0 and 0.02 < f_if + k * fo < 0.48]
    k = ks[idx % len(ks)] if idx < 100 else ks[int(rng.integers(len(ks)))]
    fc = f_if + k * fo + rng.uniform(-0.8, 0.8) * fp            # 落在折入通带的位置
    bw = fp / 8
    bf = fc + rng.uniform(-bw / 2, bw / 2, 8)
    blk = np.cos(2 * np.pi * np.outer(t, bf) + rng.uniform(0, 2 * np.pi, 8)).sum(axis=1)
    blk *= math.sqrt(p_des * 10 ** (p["blocker_rel_db"] / 10) / np.mean(blk ** 2))
    total = desired + blk
    scale = 0.9 / np.max(np.abs(total))
    full = 1 << (task.interface["in_bits"] - 1)
    codes = np.clip(np.round(total * scale * full), -full, full - 1).astype(np.int64)
    a = amps * 0.5 * scale
    clean = ToneSet(np.concatenate([freqs, -freqs]), np.concatenate([a, np.conj(a)]),
                    np.concatenate([np.full(24, f_if), np.full(24, -f_if)]))
    return {"x_codes": codes, "clean": clean, "blocker_offsets": (float(fc - f_if),), "scale": scale}


P_IMPL = 0.1
DELTA = 10 * math.log10(1 + P_IMPL)

for base in ("dev_r32_narrow", "dev_r64_wide"):
    s = SPECS[base]
    name = base.replace("dev_", "real_")
    register(Task(
        name=name,
        params=dict(r_total=s.r_total, passband=s.passband, fs_out=s.fs_out, fcw=s.fcw, f_if=s.f_if,
                    blocker_rel_db=45.0, ripple_max_db=0.1, impl_loss_db=DELTA),
        interface=dict(in_bits=14, out_bits=16, rate=s.r_total),
        ideal=ideal,
        stimulus="tones_with_strong_blocker",
        tolerance=dict(snr_loss_db=DELTA, ripple_max_db=0.1),
        search_scenarios=(0, 1),
        holdout_scenarios=(10, 11, 12),
        seed_key=int(s.sha256()[:8], 16) ^ 0x5EA1,
        description=("实数 ADC 输入中频 f_if 处 ±passband 的信号搬到零频、低通并抽取 R 倍，输出复基带 I/Q。"
                     "输入含一个比期望信号高 45 dB 的窄带调制干扰，位于会折入通带的混叠带。"),
    ))
