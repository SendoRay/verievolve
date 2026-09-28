"""DDC 整数 bit-true 候选链（与未来 RTL 逐位对应的整数域模型）。

位语义约定（全部冻结于 spec.py）：
  输入   : 12 位 Q1.11（场景统一 ADC 口径，rne 量化）
  NCO    : 32 位相位累加器 → 高 B 位为查表相位字 → tpl_cordic 位精确
           sin/cos（16 位 Q1.15；LUT 深度/插值或 CORDIC 级数由候选定）
  混频   : 12×16 位乘积（Q2.26）→ 候选可选乘积丢位 → 求和 → 右移 11 位
           回 Q1.15（16 位，饱和计数）
  FIR    : 对称 33 抽头；系数量化 Q(Wc−2).(Wc−2)（rne）；乘积可选丢位；
           精确累加后按候选累加位宽饱和；输出右移 (Wc−2) 位回 Q1.15
  抽取   : 每 R 样点取 1（无额外数值操作）
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import spec

_BENCH = None


def _tpl_cordic():
    global _BENCH
    if _BENCH is None:
        import sys
        from pathlib import Path
        _BENCH = Path(__file__).resolve().parent.parent.parent
        if str(_BENCH) not in sys.path:
            sys.path.insert(0, str(_BENCH))
    from certfit import tpl_cordic
    return tpl_cordic


# ---------------------------------------------------------------------------
# 基础整数运算（与 certfit/common.py 量化语义一致）
# ---------------------------------------------------------------------------

def shr_round(v: np.ndarray, s: int, mode: str) -> np.ndarray:
    """算术右移 s 位；rne = half-up（与 common.quant_rne 一致）。"""
    if s <= 0:
        return v
    if mode == "trunc":
        return v >> s
    return (v + (1 << (s - 1))) >> s


def drop_low(v: np.ndarray, s: int, mode: str) -> np.ndarray:
    """丢低 s 位（保持 2^s 倍数，语义同 common.quant_*）。"""
    if s <= 0:
        return v
    return shr_round(v, s, mode) << s


def sat16(v: np.ndarray) -> tuple:
    """饱和到 16 位有符号，返回 (饱和值, 饱和事件数)。"""
    lo, hi = -(1 << 15), (1 << 15) - 1
    n_sat = int(np.sum((v < lo) | (v > hi)))
    return np.clip(v, lo, hi), n_sat


# ---------------------------------------------------------------------------
# 各级整数模型
# ---------------------------------------------------------------------------

def nco_phase_word(n: int, f_off_mhz: float, phase_bits: int) -> np.ndarray:
    """32 位相位累加器的前 phase_bits 位（经典 DDS 相位截断语义）。

    acc(n) = (n·FCW) mod 2^32；相位字 = acc >> (32−B)。
    """
    fcw = int(round(f_off_mhz * 1e6 / spec.FS_IN * (1 << spec.W_P_ACC)))
    n_vec = np.arange(n, dtype=np.int64)
    acc = (n_vec * fcw) & 0xFFFFFFFF
    return acc >> (spec.W_P_ACC - phase_bits)


def nco_sincos(nco_cfg: dict, n: int, f_off_mhz: float):
    """候选 NCO 的 16 位 sin/cos（复用 certfit/tpl_cordic 位精确模型）。

    模型契约：角度码为 16 位**有符号**补码（[−2^15, 2^15)）——无符号相位字
    须先转有符号域再进模型，否则 z > 49152 落入折叠后的 CORDIC 发散区。
    """
    z = nco_phase_word(n, f_off_mhz, int(nco_cfg["phase_bits"])) << (16 - int(nco_cfg["phase_bits"]))
    z_signed = np.where(z >= (1 << 15), z - (1 << 16), z).astype(np.int64)
    params = ({"algo": "lut", "order": nco_cfg["order"], "depth": int(nco_cfg["depth"])}
              if nco_cfg["algo"] == "lut" else {"algo": "cordic", "stages": int(nco_cfg["stages"])})
    sin_v, cos_v = _tpl_cordic().emulate(params, z_signed)
    return sin_v.astype(np.int64), cos_v.astype(np.int64)


def mixer_fixed(i12: np.ndarray, q12: np.ndarray,
                sin16: np.ndarray, cos16: np.ndarray,
                cmul_cfg: dict) -> dict:
    """复数混频：re = I·cos + Q·sin，im = Q·cos − I·sin。

    候选 cmul_cfg：prod_drop（乘积丢位）、mode（rne/trunc）。
    结构（direct/karatsuba）在整数域位恒等，只影响硬件代价（见
    certfit/tpl_cmul.py 关键代数事实），不进入数值候选空间。
    """
    pd, mode = int(cmul_cfg["prod_drop"]), cmul_cfg["mode"]
    pic = drop_low(i12 * cos16, pd, mode)
    qsc = drop_low(q12 * sin16, pd, mode)
    isc = drop_low(i12 * sin16, pd, mode)
    qcc = drop_low(q12 * cos16, pd, mode)
    re_pre = pic + qsc
    im_pre = qcc - isc
    re_q = shr_round(re_pre, spec.MIX_FRAC_SHIFT, mode)
    im_q = shr_round(im_pre, spec.MIX_FRAC_SHIFT, mode)
    re_q, sat_re = sat16(re_q)
    im_q, sat_im = sat16(im_q)
    return {"re": re_q, "im": im_q, "re_pre": re_pre, "im_pre": im_pre,
            "n_sat": sat_re + sat_im}


def quantize_coeffs(h: np.ndarray, wc: int, mode: str) -> np.ndarray:
    """原型系数 → Q(Wc−2).(Wc−2) 整数（保持对称性）。"""
    scale = float(1 << (wc - 2))
    hq = np.floor(h * scale + 0.5).astype(np.int64) if mode == "rne" else \
        np.floor(h * scale).astype(np.int64)
    return hq


_FIR_IDX_CACHE = {}


def _fir_idx(n: int, taps: int):
    """滑窗索引矩阵缓存（同一形状只构建一次）。"""
    key = (n, taps)
    if key not in _FIR_IDX_CACHE:
        idx = np.arange(n)[:, None] - np.arange(taps)[None, :]
        _FIR_IDX_CACHE[key] = (idx, idx >= 0)
    return _FIR_IDX_CACHE[key]


def fir_fixed(x_re: np.ndarray, x_im: np.ndarray, hq: np.ndarray,
              fir_cfg: dict) -> dict:
    """整数 FIR：乘积（可选丢位）→ 精确累加 → 累加位宽饱和 → 输出量化。

    返回 re/im 整数输出（Q1.15）与饱和计数。real/imag 两路用同一系数。
    """
    pd, mode = int(fir_cfg["prod_drop"]), fir_cfg["mode"]
    wc = int(fir_cfg["wc"])
    wacc = int(fir_cfg.get("wacc", 0))
    n = len(x_re)
    taps = len(hq)
    idx, valid = _fir_idx(n, taps)
    idx_c = np.clip(idx, 0, None)

    def run_channel(x: np.ndarray) -> tuple:
        cols = x[idx_c]                      # n×taps
        prod = cols * hq[None, :]
        prod = np.where(valid, drop_low(prod, pd, mode), 0)
        acc = prod.sum(axis=1, dtype=np.int64)
        n_sat = 0
        if wacc:
            lo, hi = -(1 << (wacc - 1)), (1 << (wacc - 1)) - 1
            n_sat = int(np.sum((acc < lo) | (acc > hi)))
            acc = np.clip(acc, lo, hi)
        y = shr_round(acc, wc - 2, mode)
        y, s2 = sat16(y)
        return y, n_sat + s2

    yr, sat_r = run_channel(x_re)
    yi, sat_i = run_channel(x_im)
    return {"re": yr, "im": yi, "n_sat": sat_r + sat_i}


def decimate(y_re: np.ndarray, y_im: np.ndarray) -> tuple:
    return y_re[::spec.R], y_im[::spec.R]


# ---------------------------------------------------------------------------
# 候选链整体
# ---------------------------------------------------------------------------

def adc_quantize(x_adc_float: np.ndarray) -> tuple:
    """float ADC 口径 → 整数（Q1.11）。"""
    s = float(1 << (spec.W_ADC - 1))
    i12 = np.floor(x_adc_float.real * s + 0.5).astype(np.int64)
    q12 = np.floor(x_adc_float.imag * s + 0.5).astype(np.int64)
    lo, hi = -(1 << (spec.W_ADC - 1)), (1 << (spec.W_ADC - 1)) - 1
    return np.clip(i12, lo, hi), np.clip(q12, lo, hi)


def run_candidate(nco_cfg: dict, fir_cfg: dict, cmul_cfg: dict,
                  sd, hq: np.ndarray, pre: dict | None = None) -> dict:
    """跑一个候选组合（NCO × FIR × CMUL），返回输出与各级中间量。

    sd: scenarios.ScenarioData；hq: 已量化的候选系数。
    pre: 可选预计算 {'i12','q12','sin','cos'}（同一 (NCO,场景) 被多个
    FIR/CMUL 组合共享时避免重复仿真）。
    FIR 无效前缀（前 N_TAPS−1 样点）与参考链同规则裁剪后再抽取，
    保证两条链输出逐样点对齐。
    """
    n = len(sd.x_adc)
    if pre is None:
        i12, q12 = adc_quantize(sd.x_adc)
        sin16, cos16 = nco_sincos(nco_cfg, n, sd.scen.f_off_mhz)
    else:
        i12, q12 = pre["i12"], pre["q12"]
        sin16, cos16 = pre["sin"], pre["cos"]
    mix = mixer_fixed(i12, q12, sin16, cos16, cmul_cfg)
    fir = fir_fixed(mix["re"], mix["im"], hq, fir_cfg)
    yo_re, yo_im = decimate(fir["re"][spec.N_TAPS - 1:], fir["im"][spec.N_TAPS - 1:])
    # FIR 有效段上的级误差（谱加权模型用，长度为 R 的整数倍）
    n_valid = n - (spec.N_TAPS - 1)
    return {
        "i12": i12, "q12": q12,
        "sin": sin16, "cos": cos16,
        "mix_re": mix["re"], "mix_im": mix["im"],
        "mix_re_pre": mix["re_pre"], "mix_im_pre": mix["im_pre"],
        "fir_re": fir["re"], "fir_im": fir["im"],
        "y_re": yo_re, "y_im": yo_im,
        "n_sat_mix": mix["n_sat"], "n_sat_fir": fir["n_sat"],
        "n_valid": n_valid,
    }
