"""接收（下变频 + 抽取）链族的规格与冻结场景。

频率全部按输入采样率归一化（fs_in = 1）。规格只描述“要什么”：
数学功能（把中频 f_if 处、带宽 ±passband 的信号搬到基带并抽取 r_total 倍）、
系统指标门槛与位宽接口；不包含任何实现选择。任何积木组合只要满足接口，
都由同一套场景与指标评价。

修改任何已冻结字段都必须 bump SPEC_VERSION。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass

import numpy as np

SPEC_VERSION = "rx-spec-v2"
PHASE_ACC_BITS = 32


@dataclass(frozen=True)
class ChainSpec:
    name: str
    r_total: int            # 总抽取倍率
    passband_frac: float    # 通带边缘 / (fs_out/2)
    input_bits: int         # ADC 位宽（Q1.(B-1)）
    output_bits: int        # 输出 I/Q 位宽
    ripple_max_db: float    # 通带纹波峰峰值上限
    alias_min_db: float     # 折入通带的最差混叠抑制下限
    impl_loss_db: float     # 允许的实现损失：SNR 下限 = 理想接收机 ADC 上限 - 该值
    fcw: int                # NCO 频率字（中频 = fcw / 2^32）
    blocker_rel_db: float   # 每个阻塞音相对期望信号总功率

    @property
    def fs_out(self) -> float:
        return 1.0 / self.r_total

    @property
    def passband(self) -> float:
        return self.passband_frac * self.fs_out / 2.0

    @property
    def f_if(self) -> float:
        return self.fcw / 2.0**PHASE_ACC_BITS

    @property
    def snr_min_db(self) -> float:
        return round(snr_ceiling(self) - self.impl_loss_db, 3)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fs_out"] = self.fs_out
        d["passband"] = self.passband
        d["f_if"] = self.f_if
        d["snr_ceiling_db"] = snr_ceiling(self)
        d["snr_min_db"] = self.snr_min_db
        return d

    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()


def _fcw(f: float) -> int:
    # 满熵频率字：避免低位恒零导致相位截断轴失效
    return int(round(f * 2**PHASE_ACC_BITS)) | 1


# 字段顺序：name, r_total, passband_frac, input_bits, output_bits, ripple_max_db,
#           alias_min_db, impl_loss_db, fcw, blocker_rel_db
DEV_SPECS = (
    ChainSpec("dev_r16_wide", 16, 0.80, 14, 16, 0.30, 75.0, 2.0, _fcw(0.1937), 15.0),
    ChainSpec("dev_r16_narrow", 16, 0.50, 12, 16, 0.50, 80.0, 1.5, _fcw(0.2213), 20.0),
    ChainSpec("dev_r32_wide", 32, 0.80, 14, 16, 0.20, 85.0, 2.0, _fcw(0.1711), 20.0),
    ChainSpec("dev_r32_narrow", 32, 0.40, 12, 16, 0.50, 70.0, 1.5, _fcw(0.2471), 10.0),
    ChainSpec("dev_r64_wide", 64, 0.70, 14, 16, 0.30, 85.0, 2.5, _fcw(0.1543), 25.0),
    ChainSpec("dev_r64_narrow", 64, 0.50, 12, 16, 0.40, 75.0, 2.0, _fcw(0.2089), 15.0),
)

# 留出规格：方法冻结前不得运行（见 manifest 冻结规则）
HELDOUT_SPECS = (
    ChainSpec("ho_r24_wide", 24, 0.75, 14, 16, 0.25, 75.0, 2.0, _fcw(0.1821), 15.0),
    ChainSpec("ho_r16_mid", 16, 0.65, 16, 18, 0.20, 90.0, 2.5, _fcw(0.2351), 25.0),
    ChainSpec("ho_r48_narrow", 48, 0.45, 12, 16, 0.50, 72.0, 1.5, _fcw(0.1619), 12.0),
    ChainSpec("ho_r32_mid", 32, 0.60, 14, 16, 0.30, 85.0, 2.0, _fcw(0.2147), 20.0),
    ChainSpec("ho_r64_mid", 64, 0.60, 14, 16, 0.25, 80.0, 2.5, _fcw(0.1977), 18.0),
    ChainSpec("ho_r96_narrow", 96, 0.50, 12, 16, 0.40, 70.0, 2.0, _fcw(0.1433), 10.0),
)

SPECS = {s.name: s for s in DEV_SPECS + HELDOUT_SPECS}


# ---------------------------------------------------------------------------
# 冻结测试场景
# ---------------------------------------------------------------------------
N_OUT = 1024          # 计入统计的输出样点
N_WARM_OUT = 160      # 输出域暖机样点（覆盖全部级的建立时间）
N_TONES = 24
DESIRED_PEAK_FRAC = 0.9


@dataclass(frozen=True)
class Scenario:
    x_codes: np.ndarray          # 量化后的 ADC 码（int64）
    tone_freqs: np.ndarray       # 期望信号基带复音频率（cycles/input sample）
    tone_amps: np.ndarray        # 复幅度（含相位），已含实混频 1/2 因子
    n_in: int
    seed: int


def blocker_offsets(spec: ChainSpec) -> list[float]:
    """与计划无关的阻塞音基带偏移：落在会折回通带的区间。"""
    fo, fp = spec.fs_out, spec.passband
    cand = [fo - 0.6 * fp, 2 * fo + 0.3 * fp, -(3 * fo - 0.2 * fp), 5 * fo + 0.5 * fp]
    # 实输入频率必须仍在 (0, 0.5)
    return [f for f in cand if 0.0 < spec.f_if + f < 0.5]


def make_scenario(spec: ChainSpec, seed: int = 20261009) -> Scenario:
    rng = np.random.default_rng(seed + int(spec.sha256()[:8], 16) % 100000)
    n_in = (N_OUT + N_WARM_OUT) * spec.r_total
    n = np.arange(n_in, dtype=np.float64)
    fp = spec.passband
    freqs = np.sort(rng.uniform(-0.92 * fp, 0.92 * fp, N_TONES))
    phases = rng.uniform(0, 2 * np.pi, N_TONES)
    amps = np.ones(N_TONES) * np.exp(1j * phases)
    # 期望信号：实带通 = Re{s(n) e^{j2π f_if n}}
    s = np.zeros(n_in, dtype=np.complex128)
    for f, a in zip(freqs, amps):
        s += a * np.exp(2j * np.pi * f * n)
    carrier = np.exp(2j * np.pi * spec.f_if * n)
    desired = np.real(s * carrier)
    p_des = np.mean(desired**2)
    blk = np.zeros(n_in)
    for f in blocker_offsets(spec):
        a_b = math.sqrt(2 * p_des * 10 ** (spec.blocker_rel_db / 10))
        blk += a_b * np.cos(2 * np.pi * (spec.f_if + f) * n + rng.uniform(0, 2 * np.pi))
    total = desired + blk
    scale = DESIRED_PEAK_FRAC / np.max(np.abs(total))
    full = (1 << (spec.input_bits - 1))
    codes = np.clip(np.round(total * scale * full), -full, full - 1).astype(np.int64)
    # 实混频后期望分量 = 0.5 * scale * s(n)
    return Scenario(codes, freqs, amps * 0.5 * scale, n_in, seed)


def reference_output(sc: Scenario, t: np.ndarray) -> np.ndarray:
    """期望信号在任意（可分数）输入时刻 t 的理想基带复值。"""
    out = np.zeros(len(t), dtype=np.complex128)
    for f, a in zip(sc.tone_freqs, sc.tone_amps):
        out += a * np.exp(2j * np.pi * f * t)
    return out


_CEILING: dict = {}


def snr_ceiling(spec: ChainSpec) -> float:
    """理想接收机（精确混频 + 长 Kaiser 低通 + 抽取）在冻结场景上的 SNR 上限。

    只受 ADC 量化与场景本身限制，与任何候选实现无关。
    """
    key = spec.sha256()
    if key in _CEILING:
        return _CEILING[key]
    from scipy import signal as sps
    sc = make_scenario(spec)
    n = np.arange(sc.n_in)
    x = sc.x_codes / float(1 << (spec.input_bits - 1))
    ph = 2 * np.pi * ((n * spec.fcw) % 2**PHASE_ACC_BITS) / 2.0**PHASE_ACC_BITS
    b = x * np.exp(-1j * ph)
    fp = spec.passband
    ntap = min(int(8 / (0.5 * fp)) | 1, 20001)
    h = sps.firwin(ntap, 1.25 * fp, window=("kaiser", 16), fs=1.0)
    y = sps.oaconvolve(b, h)[: len(b)][:: spec.r_total]
    m = np.arange(len(y))
    sel = m * spec.r_total >= ntap + N_WARM_OUT * spec.r_total
    r = reference_output(sc, m[sel] * spec.r_total - (ntap - 1) / 2)
    a = np.vdot(r, y[sel]) / np.vdot(r, r)
    e = y[sel] - a * r
    val = float(10 * np.log10(np.mean(np.abs(a * r) ** 2) / np.mean(np.abs(e) ** 2)))
    _CEILING[key] = val
    return val
