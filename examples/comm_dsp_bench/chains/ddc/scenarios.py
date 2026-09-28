"""DDC 场景生成：float 输入波形（seed 冻结，可复现）。

信号模型（spec.py 冻结）：
  x(t) = QPSK(RRC 成形, 符号率 0.25 Msps) 搬移到 +f_off
         + 带外单音干扰（以混频后频率描述）
         + AWGN
ADC 口径：所有候选共用同一 12 位（Q1.11）rne 量化输入——ADC 量化误差
属于场景定义，不属于候选差异。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import spec
from .spec import Scenario


def rrc_taps(sps: int, beta: float, span: int = 10) -> np.ndarray:
    """根升余弦冲激响应（float，能量归一）。"""
    t = (np.arange(-span * sps // 2, span * sps // 2 + 1)) / sps
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-10:
            h[i] = 1.0 - beta + 4 * beta / math.pi
        elif abs(abs(ti) - 1 / (4 * beta)) < 1e-10:
            h[i] = (beta / math.sqrt(2)) * (
                (1 + 2 / math.pi) * math.sin(math.pi / (4 * beta))
                + (1 - 2 / math.pi) * math.cos(math.pi / (4 * beta)))
        else:
            h[i] = (math.sin(math.pi * ti * (1 - beta))
                    + 4 * beta * ti * math.cos(math.pi * ti * (1 + beta))) / (
                    math.pi * ti * (1 - (4 * beta * ti) ** 2))
    return h / np.sqrt(float(np.sum(h ** 2)))


def qpsk_symbols(n: int, seed: int) -> np.ndarray:
    """QPSK 符号（归一化平均功率 1）。"""
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 4, size=n)
    return np.exp(1j * (math.pi / 4 + bits * math.pi / 2)) / math.sqrt(2.0)


@dataclass
class ScenarioData:
    """一个场景的全部 float 数据。"""
    scen: Scenario
    x: np.ndarray            # 输入复基带（含 f_off 搬移、干扰、噪声）
    symbols: np.ndarray      # 发送符号（evm_total 参考用）
    x_adc: np.ndarray        # 12 位量化后的复输入（候选共用的真实输入）
    n_pre: int               # 前导样点数（对齐/校准段）


def generate_scenario(scen: Scenario, n_warmup_sym: int = spec.N_WARMUP_SYM,
                      n_sym: int = spec.N_SYM) -> ScenarioData:
    """生成一个冻结场景。波形长度 = (warmup + n_sym)·SPS_IN。"""
    sps = int(round(spec.SPS_IN))
    n_pre = n_warmup_sym * sps
    n_tot = (n_warmup_sym + n_sym) * sps

    # 每场景独立 seed 派生：符号 / 噪声 / 干扰相位分开冻结
    root = np.random.default_rng(scen.seed)
    sym_seed = int(root.integers(0, 2**31))
    noise_seed = int(root.integers(0, 2**31))
    blk_seed = int(root.integers(0, 2**31))

    syms = qpsk_symbols(n_warmup_sym + n_sym, sym_seed)
    # 上采样 + RRC 成形（发射端，能量归一 → 平均符号功率 1）
    up = np.zeros(n_tot, dtype=complex)
    up[::sps] = syms
    h_tx = rrc_taps(sps, spec.RRC_BETA)
    base = np.convolve(up, h_tx, mode="same")  # 平均功率 ≈ 1

    t = np.arange(n_tot) / spec.FS_IN
    # 信号搬移到 +f_off
    x = base * np.exp(1j * 2 * math.pi * scen.f_off_mhz * 1e6 * t)

    # 带外单音干扰（幅度相对信号平均功率）
    if scen.has_blocker:
        rng_b = np.random.default_rng(blk_seed)
        ph = float(rng_b.uniform(0, 2 * math.pi))
        # 干扰频率 = f_off + blocker_off（"混频后频率"描述）
        f_blk = (scen.f_off_mhz + scen.blocker_off_mhz) * 1e6
        amp = 10 ** (scen.blocker_rel_db / 20.0) * math.sqrt(
            float(np.mean(np.abs(base) ** 2)))
        x = x + amp * np.exp(1j * (2 * math.pi * f_blk * t + ph))

    # AWGN（全带内，按信号平均功率定 SNR）
    rng_n = np.random.default_rng(noise_seed)
    p_sig = float(np.mean(np.abs(x) ** 2))
    n0 = p_sig / (2 * 10 ** (scen.snr_db / 10.0))
    noise = np.sqrt(n0) * (rng_n.standard_normal(n_tot)
                           + 1j * rng_n.standard_normal(n_tot))
    x = x + noise

    # ADC：12 位 Q1.11 量化（候选共用；floor(x+0.5) 逐字段确定性取整）
    scale = float(1 << (spec.W_ADC - 1))
    peak = np.max(np.abs(x))
    if peak >= 1.0:  # 场景幅度保护：归一到 |x|<1（记录在案，同口径用于参考链）
        x = x / peak * 0.95
    lo, hi = -(1 << (spec.W_ADC - 1)), (1 << (spec.W_ADC - 1)) - 1
    xi = np.clip(np.floor(x.real * scale + 0.5), lo, hi) / scale
    xq = np.clip(np.floor(x.imag * scale + 0.5), lo, hi) / scale
    x_adc = xi + 1j * xq

    return ScenarioData(scen=scen, x=x, symbols=syms, x_adc=x_adc, n_pre=n_pre)
