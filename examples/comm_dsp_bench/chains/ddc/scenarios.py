"""DDC 场景生成：float 输入波形（seed 冻结，可复现）。

信号模型（spec.py 冻结）：
  x(t) = QPSK(RRC 成形, 符号率 0.25 Msps) 搬移到 +f_off
         + 带外单音干扰（以混频后频率描述）
         + AWGN
ADC 口径：所有候选共用同一 12 位（Q1.11）rne 量化输入——ADC 量化误差
属于场景定义，不属于候选差异。

两条口径（由 Scenario.split 区分）：
  - 旧清单（split 为空，build_scenarios）：保持 ddc-p0-v2 的逐位行为，
    仅用于复现旧产物；AWGN 功率按 desired+blocker 计算（已知缺陷）。
  - witness 清单（split 非空，WITNESS_FROZEN_DDC_v1 §4.1 / §7-7,8,9）：
    AWGN 按 desired-only、加 blocker 之前定 SNR，且 SNR 在 DDC 输出测量域
    成立（理想整数-FCW 混频 + 原型 FIR + 抽取，与 q 同一有效段）；desired / blocker /
    noise 三个分量与共同前端缩放 s 一并暴露，x = s·(d + b + n)。
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
    """QPSK 符号，单位圆 /√2 → 每符号功率 0.5（幅度 1/√2，I/Q 各 ±0.5）。"""
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 4, size=n)
    return np.exp(1j * (math.pi / 4 + bits * math.pi / 2)) / math.sqrt(2.0)


@dataclass
class ScenarioData:
    """一个场景的全部 float 数据。

    witness 清单下严格有 x == scale·(desired + blocker + noise)（逐样点，浮点
    舍入内）；desired/blocker/noise 均已乘同一前端缩放 scale。旧清单的
    分量字段为 None。
    """
    scen: Scenario
    x: np.ndarray            # 输入复基带（含 f_off 搬移、干扰、噪声）
    symbols: np.ndarray      # 发送符号（evm_total 参考用）
    x_adc: np.ndarray        # 12 位量化后的复输入（候选共用的真实输入）
    n_pre: int               # 前导样点数（对齐/校准段）
    desired: np.ndarray | None = None   # s·d：搬移后的 QPSK 分量
    blocker: np.ndarray | None = None   # s·b：单音干扰（clean 为全零）
    noise: np.ndarray | None = None     # s·n：AWGN
    scale: float = 1.0                  # 共同前端缩放 s
    levels: dict | None = None          # 缩放前实测功率等（写 manifest 用）


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
    # 上采样 + RRC 成形（发射端，能量归一 → 样点平均功率 ≈ 0.5/sps）
    up = np.zeros(n_tot, dtype=complex)
    up[::sps] = syms
    h_tx = rrc_taps(sps, spec.RRC_BETA)
    base = np.convolve(up, h_tx, mode="same")

    t = np.arange(n_tot) / spec.FS_IN
    # 信号搬移到 +f_off
    x = base * np.exp(1j * 2 * math.pi * scen.f_off_mhz * 1e6 * t)

    if scen.split:
        return _finish_witness(scen, syms, base, x, t, n_pre, noise_seed, blk_seed)

    # ---- 旧口径（ddc-p0-v2，逐位保持）----
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
    peak = np.max(np.abs(x))
    if peak >= 1.0:  # 场景幅度保护：归一到 |x|<1（记录在案，同口径用于参考链）
        x = x / peak * 0.95
    return ScenarioData(scen=scen, x=x, symbols=syms, x_adc=adc_quantize(x), n_pre=n_pre)


def adc_quantize(x: np.ndarray) -> np.ndarray:
    """12 位 Q1.11 量化：floor(x·2^11+0.5) 后饱和。"""
    scale = float(1 << (spec.W_ADC - 1))
    lo, hi = -(1 << (spec.W_ADC - 1)), (1 << (spec.W_ADC - 1)) - 1
    xi = np.clip(np.floor(x.real * scale + 0.5), lo, hi) / scale
    xq = np.clip(np.floor(x.imag * scale + 0.5), lo, hi) / scale
    return xi + 1j * xq


def measure_start_out(n_pre: int) -> int:
    """输出测量段起点：valid FIR（丢 N_TAPS−1）后 phase-0 抽取，丢弃前导。"""
    return (n_pre - (spec.N_TAPS - 1)) // spec.R


def ideal_output(v: np.ndarray, f_off_mhz: float) -> np.ndarray:
    """理想整数-FCW 混频 + 原型 FIR + R 抽取（仅供 SNR 校准，不量化）。"""
    from .ref_chain import fir_float, prototype_taps   # 延迟导入：ref_chain 依赖本模块
    theta = 2 * math.pi * spec.fcw_of(f_off_mhz) * np.arange(len(v)) / (1 << spec.W_P_ACC)
    return fir_float(v * np.exp(-1j * theta), prototype_taps())[spec.DECIM_PHASE::spec.R]


def _finish_witness(scen: Scenario, syms, base, d, t, n_pre,
                    noise_seed, blk_seed) -> ScenarioData:
    """witness 口径：SNR 相对 desired、blocker 之前；分量与缩放全部暴露。"""
    n_tot = len(d)
    p_des = float(np.mean(np.abs(d) ** 2))

    b = np.zeros(n_tot, dtype=complex)
    if scen.has_blocker:
        ph = float(np.random.default_rng(blk_seed).uniform(0, 2 * math.pi))
        f_blk = (scen.f_off_mhz + scen.blocker_off_mhz) * 1e6
        amp = 10 ** (scen.blocker_rel_db / 20.0) * math.sqrt(p_des)
        b = amp * np.exp(1j * (2 * math.pi * f_blk * t + ph))

    # AWGN：输出测量域 SNR = P_des_out / P_noise_out（不含 blocker）。
    # 同一冻结 realization 的单位噪声经理想链求比例；前端缩放 s 不改变该比值。
    rng_n = np.random.default_rng(noise_seed)
    n_unit = (rng_n.standard_normal(n_tot)
              + 1j * rng_n.standard_normal(n_tot)) / math.sqrt(2.0)
    meas0 = measure_start_out(n_pre)
    p_des_out = float(np.mean(np.abs(ideal_output(d, scen.f_off_mhz)[meas0:]) ** 2))
    p_unit_out = float(np.mean(np.abs(ideal_output(n_unit, scen.f_off_mhz)[meas0:]) ** 2))
    n = n_unit * math.sqrt(p_des_out / (p_unit_out * 10 ** (scen.snr_db / 10.0)))

    raw = d + b + n
    peak = float(np.max(np.abs(raw)))
    s = 0.95 / peak if peak >= 1.0 else 1.0
    x = s * raw
    p_noise = float(np.mean(np.abs(n) ** 2))
    p_noise_out = float(np.mean(np.abs(ideal_output(n, scen.f_off_mhz)[meas0:]) ** 2))
    levels = {"p_desired_in": p_des, "p_blocker_in": float(np.mean(np.abs(b) ** 2)),
              "p_noise_in": p_noise, "snr_in_fullband_db": 10 * math.log10(p_des / p_noise),
              "p_desired_out": p_des_out, "p_noise_out": p_noise_out,
              "snr_out_db": 10 * math.log10(p_des_out / p_noise_out),
              "meas_start_out": meas0, "peak_raw": peak, "scale": s}
    return ScenarioData(scen=scen, x=x, symbols=syms, x_adc=adc_quantize(x),
                        n_pre=n_pre, desired=s * d, blocker=s * b, noise=s * n,
                        scale=s, levels=levels)
