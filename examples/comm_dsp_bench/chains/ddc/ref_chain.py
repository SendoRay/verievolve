"""DDC float64 参考链（数学功能定义，spec.py 冻结）。

参考链 = 理想余弦/正弦混频 + 理想原型 FIR + 抽取。
所有合法候选都必须逼近这同一个参考功能（近似要求由 FIR 掩码与
NCO/混频功能检查界定，见 candidates.py）。
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import firwin

from . import spec
from .scenarios import ScenarioData


def prototype_taps() -> np.ndarray:
    """理想低通原型（汉明窗firwin，33 抽头对称，DC 增益 1）。

    截止 0.3 MHz（Nyquist 归一 0.3）：通带 ≈0.2 MHz 内，阻带 ≈0.4 MHz 起。
    """
    h = firwin(spec.N_TAPS, spec.SB_EDGE_MHZ - 0.15, window="hamming")
    return h / float(np.sum(h))


def mixer_ideal(x: np.ndarray, f_off_mhz: float, n: int) -> np.ndarray:
    """理想混频：x·e^{−jθ}，θ_n = 2π·f_off·n/Fs_in。"""
    theta = 2 * math.pi * f_off_mhz * 1e6 * np.arange(n) / spec.FS_IN
    return x * np.exp(-1j * theta)


def fir_float(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """因果卷积 y[n] = Σ h[k]·x[n−k]，取 n ≥ N−1 的有效段。"""
    conv = np.convolve(x, h, mode="full")
    return conv[spec.N_TAPS - 1: len(x)]


def run_reference(sd: ScenarioData, h: np.ndarray | None = None):
    """跑参考链，返回各级理想中间量（局部指标的参考基准）。

    返回 dict：
      cos/sin   : float 理想 NCO 输出（无量纲，幅度满幅 1）
      mix       : float 理想混频输出（复，ADC 刻度）
      y_out     : float 参考输出 IQ（复，抽取后）
      h         : 原型系数
    """
    if h is None:
        h = prototype_taps()
    n = len(sd.x_adc)
    theta = 2 * math.pi * sd.scen.f_off_mhz * 1e6 * np.arange(n) / spec.FS_IN
    cos_i = np.cos(theta)
    sin_i = np.sin(theta)
    mix = mixer_ideal(sd.x_adc, sd.scen.f_off_mhz, n)
    y_fir = fir_float(mix, h)
    y_out = y_fir[::spec.R]
    return {"cos": cos_i, "sin": sin_i, "mix": mix, "y_fir": y_fir,
            "y_out": y_out, "h": h}
