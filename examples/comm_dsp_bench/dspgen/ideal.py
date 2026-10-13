"""理想版程序：用数学级运算写公式。每个信号同时带两种解释：
- 采样浮点：在带损伤的输入上逐样点计算（给出理想实现的成绩，即门槛的基准）；
- 音调域解析：对干净的多音信号精确推导输出（给出参考答案，可在任意时刻取值，用于时延对齐）。
另外累计群时延 delay 与建立长度 settle（均以链输入样点计）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

from .tones import ToneSet


@dataclass
class ISig:
    g: "Ideal"
    x: np.ndarray            # 采样值（带损伤输入上的理想处理结果）
    tones: ToneSet | None    # 干净信号的解析描述
    rate: float = 1          # 每个样点对应的链输入样点数（抽取后 >1，内插后 <1）
    delay: float = 0.0
    settle: float = 0.0
    real: bool = False       # True：实信号，等于 Re{tones}


class Ideal:
    def __init__(self, x: np.ndarray, clean: ToneSet):
        self._x, self._clean = x, clean

    def input(self) -> ISig:
        return ISig(self, self._x, self._clean)

    def mix(self, s: ISig, freq_word: int, acc_bits: int = 32) -> ISig:
        """乘以 exp(−j2π·f0·n)，f0 = freq_word / 2^acc_bits（频谱搬移）。"""
        t = np.arange(len(s.x))
        ph = 2 * np.pi * ((t * freq_word) % 2 ** acc_bits) / 2.0 ** acc_bits
        f0 = freq_word / 2.0 ** acc_bits
        tones = s.tones.shifted(-f0 / s.rate) if s.tones else None
        return ISig(self, s.x * np.exp(-1j * ph), tones, s.rate, s.delay, s.settle)

    def upconvert(self, s: ISig, freq_word: int, acc_bits: int = 32) -> ISig:
        """上变频取实部：Re{x·exp(+j2π·f0·n)}，f0 = freq_word / 2^acc_bits（按本信号的采样率计）。"""
        n = np.arange(len(s.x))
        ph = 2 * np.pi * ((n * freq_word) % 2 ** acc_bits) / 2.0 ** acc_bits
        f0 = freq_word / 2.0 ** acc_bits
        tones = s.tones.shifted(f0 / s.rate) if s.tones else None
        return ISig(self, np.real(s.x * np.exp(1j * ph)), tones, s.rate, s.delay, s.settle, real=True)

    def upsample(self, s: ISig, L: int) -> ISig:
        """零值内插并乘以 L（后接理想低通即为理想内插）。"""
        y = np.zeros(len(s.x) * L, dtype=s.x.dtype)
        y[::L] = s.x * L
        return ISig(self, y, s.tones, s.rate / L, s.delay, s.settle)

    def lowpass(self, s: ISig, passband: float, stopband: float, cutoff: float | None = None) -> ISig:
        """理想低通：通带增益 1，阻带全部滤除（频率以链输入采样率为单位）。
        采样解释用很长的 Kaiser 窗 FIR 逼近；音调域解释直接保留通带内的音调。"""
        fs = 1.0 / s.rate
        ntap = min(int(40 / (passband / fs)) | 1, 40001)
        h = sps.firwin(ntap, 0.5 * (passband + stopband) if cutoff is None else cutoff,
                       window=("kaiser", 14), fs=fs)
        y = sps.oaconvolve(s.x, h)[: len(s.x)]
        tones = None
        if s.tones:
            tones = s.tones.select(np.abs(s.tones.eff()) <= passband)
        return ISig(self, y, tones, s.rate, s.delay + (ntap - 1) / 2 * s.rate, s.settle + ntap * s.rate)

    def decimate(self, s: ISig, r: int) -> ISig:
        return ISig(self, s.x[::r], s.tones, s.rate * r, s.delay, s.settle, s.real)
