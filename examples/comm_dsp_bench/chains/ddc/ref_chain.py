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


def ideal_nco(f_off_mhz: float, n: int) -> tuple[np.ndarray, np.ndarray, int]:
    """按冻结 32-bit FCW 生成理想 cos/sin 与整数 FCW。

    FCW 量化是所有候选共享的接口条件，不应被计入候选实现误差。
    """
    fcw = int(round(f_off_mhz * 1e6 / spec.FS_IN * (1 << spec.W_P_ACC)))
    theta = 2 * math.pi * fcw * np.arange(n, dtype=np.float64) / (1 << spec.W_P_ACC)
    return np.cos(theta), np.sin(theta), fcw


def mixer_ideal(x: np.ndarray, f_off_mhz: float, n: int) -> np.ndarray:
    """理想混频：使用与候选相同的整数 FCW，计算 x·e^{-jθ_FCW}。"""
    cos_i, sin_i, _ = ideal_nco(f_off_mhz, n)
    return x * (cos_i - 1j * sin_i)


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
    cos_i, sin_i, fcw = ideal_nco(sd.scen.f_off_mhz, n)
    mix = mixer_ideal(sd.x_adc, sd.scen.f_off_mhz, n)
    y_fir = fir_float(mix, h)
    y_out = y_fir[::spec.R]
    return {"cos": cos_i, "sin": sin_i, "fcw": fcw, "mix": mix,
            "y_fir": y_fir, "y_out": y_out, "h": h}
