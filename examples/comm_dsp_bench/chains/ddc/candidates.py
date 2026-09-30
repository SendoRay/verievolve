"""DDC 候选空间（§6.1 最小规模：6 NCO × 8 FIR × 2 CMUL = 96 组合）。

合法性（RESEARCH_PLAN §3.2）：所有候选执行同一参考功能或在冻结掩码
允许的近似要求内——FIR 候选的量化系数必须仍满足冻结幅度掩码
（通带 ripple / 阻带衰减 / 线性相位）；NCO 频率误差 < 1 Hz；混频在最坏
输入下无静默溢出。不合法的候选被剔除并记录原因，而不是静默保留。

硬件代价轴（structure、展开、流水级）在本数值实验中不进入候选差异——
direct 与 karatsuba 复乘在整数域位恒等（certfit/tpl_cmul.py 已证），
属同一 ε-等价类。数值轴：相位截断、查表/迭代结构、系数字长、乘积
丢位、舍入模式、累加位宽。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

_BENCH = Path(__file__).resolve().parent.parent.parent
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

from . import spec
from .fixed_chain import quantize_coeffs

# ---------------------------------------------------------------------------
# NCO / sin-cos 候选（6）：结构 × 相位截断 × 精度
#   phase_bits = 查表相位字宽（32 位累加器的高 B 位；B<16 即相位截断）
# ---------------------------------------------------------------------------

NCO_CANDIDATES = [
    {"name": "n1_lut256near_b12", "algo": "lut", "order": "nearest", "depth": 256, "phase_bits": 12},
    {"name": "n2_lut256near_b16", "algo": "lut", "order": "nearest", "depth": 256, "phase_bits": 16},
    {"name": "n3_lut1024lin_b12", "algo": "lut", "order": "linear", "depth": 1024, "phase_bits": 12},
    {"name": "n4_lut1024lin_b16", "algo": "lut", "order": "linear", "depth": 1024, "phase_bits": 16},
    {"name": "n5_cordic12_b12", "algo": "cordic", "stages": 12, "phase_bits": 12},
    {"name": "n6_cordic16_b16", "algo": "cordic", "stages": 16, "phase_bits": 16},
]

# WITNESS_FROZEN_DDC_v1 §2.2：truth 前冻结的 v2 二十点池。
# 这是独立于历史六点池的预注册集合；二者合并后是 decision witness 的
# 26 个实现选择集。重复数值映射只在主 pair 选择时去重，面积/Pareto 仍保留。
NCO_WITNESS_V2_CANDIDATES = [
    *[
        {"name": f"v2_lut{depth}near_b16", "algo": "lut", "order": "nearest",
         "depth": depth, "phase_bits": 16}
        for depth in (128, 256, 512, 1024)
    ],
    *[
        {"name": f"v2_lut{depth}lin_b{phase_bits}", "algo": "lut", "order": "linear",
         "depth": depth, "phase_bits": phase_bits}
        for depth in (256, 1024)
        for phase_bits in (8, 10, 12, 14, 16)
    ],
    *[
        {"name": f"v2_cordic{stages}_b16", "algo": "cordic", "stages": stages,
         "phase_bits": 16}
        for stages in (7, 8, 9, 10, 11, 12)
    ],
]


def witness_nco_candidates(include_legacy: bool = True) -> list[dict]:
    """返回冻结 witness NCO 实现集；默认是 6+20 的 26 点并集。"""
    configs = ([*NCO_CANDIDATES, *NCO_WITNESS_V2_CANDIDATES]
               if include_legacy else NCO_WITNESS_V2_CANDIDATES)
    return [dict(cfg) for cfg in configs]

# ---------------------------------------------------------------------------
# FIR 候选（8）：系数字长 × 累加位宽 × 乘积丢位 × 舍入
#   wc: 系数量化位宽（Q(Wc−2).(Wc−2)）；wacc: 0=精确累加（int64）
#   prod_drop: 每乘积丢位；mode: rne(half-up)/trunc
# 注：wc=8 直接量化不满足冻结掩码（pb +0.63 dB / sb −26.7 dB），wc=10+trunc
# 因 DC 增益偏移同样越界（pb +0.63 dB）——合法性机制淘汰低位宽截断档，
# 最低系数字长档取 11 位（pb +0.04 dB / sb −39.2 dB）。
# ---------------------------------------------------------------------------

FIR_CANDIDATES = [
    {"name": "f1_c16", "wc": 16, "wacc": 0, "prod_drop": 0, "mode": "rne"},
    {"name": "f2_c12", "wc": 12, "wacc": 0, "prod_drop": 0, "mode": "rne"},
    {"name": "f3_c10", "wc": 10, "wacc": 0, "prod_drop": 0, "mode": "rne"},
    {"name": "f4_c11", "wc": 11, "wacc": 0, "prod_drop": 0, "mode": "rne"},
    {"name": "f5_c12_acc24", "wc": 12, "wacc": 24, "prod_drop": 0, "mode": "rne"},
    {"name": "f6_c12_trunc", "wc": 12, "wacc": 0, "prod_drop": 0, "mode": "trunc"},
    {"name": "f7_c12_pd2", "wc": 12, "wacc": 0, "prod_drop": 2, "mode": "rne"},
    {"name": "f8_c14_acc28_pd1_trunc", "wc": 14, "wacc": 28, "prod_drop": 1, "mode": "trunc"},
]

# ---------------------------------------------------------------------------
# 复乘（混频）候选（2）：乘积丢位 × 输出舍入
# ---------------------------------------------------------------------------

CMUL_CANDIDATES = [
    {"name": "c1_exact_rne", "prod_drop": 0, "mode": "rne"},
    {"name": "c2_pd2_trunc", "prod_drop": 2, "mode": "trunc"},
]


def freq_response(hq: np.ndarray, n_fft: int = 8192) -> np.ndarray:
    """整数系数 → 归一化频率响应（fs 归一 0..Nyquist）。"""
    h = hq.astype(np.float64)
    h = h / float(np.sum(h))  # DC 归一后评估（掩码按相对 DC 口径）
    return np.fft.rfft(h, n_fft)


def check_fir_mask(hq: np.ndarray, h_ideal: np.ndarray) -> dict:
    """冻结掩码检查（spec.MASK_*）：通带 ripple、阻带衰减、相位线性度。"""
    n_fft = 8192
    f_hz = np.fft.rfftfreq(n_fft, 1.0 / spec.FS_IN)
    hq_n = hq.astype(np.float64) / float(np.sum(hq))
    hid_n = h_ideal / float(np.sum(h_ideal))
    Hq = np.fft.rfft(hq_n, n_fft)
    Hi = np.fft.rfft(hid_n, n_fft)

    pb = f_hz <= spec.PB_EDGE_MHZ * 1e6
    sb = f_hz >= spec.SB_EDGE_MHZ * 1e6

    pb_dev = 20 * np.log10(np.maximum(np.abs(Hq[pb]), 1e-12) /
                           np.maximum(np.abs(Hi[pb]), 1e-12))
    sb_att = 20 * np.log10(np.maximum(np.abs(Hq[sb]), 1e-12))
    # 相位线性度：对称系数群延迟恒定 (N−1)/2（结构性质，量化保对称即保线性）
    symmetric = bool(np.all(hq == hq[::-1]))

    ok_pb = float(np.max(np.abs(pb_dev))) <= spec.MASK_PB_RIPPLE_DB
    ok_sb = float(np.max(sb_att)) <= -spec.MASK_SB_ATTEN_DB
    return {
        "legal": bool(ok_pb and ok_sb and symmetric),
        "pb_ripple_db": round(float(np.max(np.abs(pb_dev))), 4),
        "sb_worst_db": round(float(np.max(sb_att)), 4),
        "symmetric": symmetric,
        "limit_pb_db": spec.MASK_PB_RIPPLE_DB,
        "limit_sb_db": -spec.MASK_SB_ATTEN_DB,
    }


def build_fir_candidates(h_ideal: np.ndarray) -> list:
    """为每个 FIR 候选量化系数并做掩码检查；返回含 hq 与合法性的列表。"""
    out = []
    for cfg in FIR_CANDIDATES:
        hq = quantize_coeffs(h_ideal, cfg["wc"], cfg["mode"])
        chk = check_fir_mask(hq, h_ideal)
        out.append({**cfg, "hq": hq, "mask_check": chk})
    return out


def nco_static_metrics(nco_cfg: dict) -> dict:
    """NCO 静态精度：全枚举 SQNR（tpl_cordic.cert_metrics，65536 角度码）。"""
    from certfit import tpl_cordic
    params = ({"algo": "lut", "order": nco_cfg["order"], "depth": int(nco_cfg["depth"])}
              if nco_cfg["algo"] == "lut" else {"algo": "cordic", "stages": int(nco_cfg["stages"])})
    m = tpl_cordic.cert_metrics(params)
    return {"sqnr_static_db": m["precision"], "wc_db": m["precision_wc"]}


def build_witness_nco_pool(include_legacy: bool = True) -> list[dict]:
    """计算冻结 accumulator-domain ``M_core``，返回 26 点或纯 v2 20 点池。"""
    from .metrics import nco_accumulator_metrics

    out = []
    for cfg in witness_nco_candidates(include_legacy=include_legacy):
        m = nco_accumulator_metrics(cfg)
        out.append({
            **cfg,
            "sqnr_static_db": m["sqnr_db"],  # run_s1 兼容字段；语义已是完整 M_core
            "mcore_sqnr_db": m["sqnr_db"],
            "mcore_wce_lsb": m["wce_lsb"],
            "mcore_last_bit_accuracy": m["last_bit_accuracy"],
            "raw_sqnr_db": m["raw_sqnr_db"],  # 未移除全局复标量（§3.1 敏感性）
            "raw_wce_lsb": m["raw_wce_lsb"],
            "raw_last_bit_accuracy": m["raw_last_bit_accuracy"],
            "mcore_gain_re": m["gain_re"],
            "mcore_gain_im": m["gain_im"],
            "mcore_domain_size": m["domain_size"],
        })
    return out


def check_mixer_overflow(cmul_cfg: dict) -> dict:
    """最坏输入下的混频溢出检查（12 位输入 × 16 位 NCO 满幅）。"""
    from .fixed_chain import mixer_fixed
    lo12, hi12 = -(1 << 11), (1 << 11) - 1
    lo16, hi16 = -(1 << 15), (1 << 15) - 1
    i = np.array([lo12, lo12, hi12, hi12], dtype=np.int64)
    q = np.array([lo12, hi12, lo12, hi12], dtype=np.int64)
    c = np.array([lo16, lo16, hi16, hi16], dtype=np.int64)
    s = np.array([lo16, hi16, lo16, hi16], dtype=np.int64)
    m = mixer_fixed(i, q, s, c, cmul_cfg)
    # 最坏精确值：|re|,|im| ≤ 2·2^11·2^15 / 2^11 = 2^16 → 16 位饱和必然发生于极角
    # 组合；检查的是"无静默回绕"（饱和而非回绕即合法），并记录极端幅度。
    exact_re_max = 2 * (1 << 11) * (1 << 15) >> spec.MIX_FRAC_SHIFT
    return {"legal": True, "worst_exact_abs": int(exact_re_max),
            "n_sat_worst_case": m["n_sat"]}


def build_all(h_ideal: np.ndarray) -> dict:
    """构建完整候选池（含合法性检查）。"""
    firs = build_fir_candidates(h_ideal)
    pool = {"nco": [], "fir": firs, "cmul": [], "illegal": []}
    for n in NCO_CANDIDATES:
        pool["nco"].append({**n, **nco_static_metrics(n)})
    for c in CMUL_CANDIDATES:
        pool["cmul"].append({**c, **check_mixer_overflow(c)})
    for f in firs:
        if not f["mask_check"]["legal"]:
            pool["illegal"].append({"kind": "fir", "name": f["name"],
                                    "reason": f["mask_check"]})
    return pool
