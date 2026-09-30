"""DDC 子链冻结参数（RESEARCH_PLAN §3.1 最小子链，P0 预实验口径）。

所有数值一经提交即冻结：场景、候选空间、指标口径、seed 全部由本模块
唯一导出。修改任何参数都必须 bump CHAIN_VERSION 并在
experiments_system/ 留存新旧 manifest（RESEARCH_PLAN §9.2 缓存键要求）。

处理链（float 参考与整数候选同构）：
    输入 IQ(Fs_in) ──→ 复数混频(NCO×CMUL) ──→ 接收 FIR(33 抽头对称) ──→ 抽取 R ──→ 输出 IQ(Fs_out)
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field, asdict

CHAIN_VERSION = "ddc-p0-v2"
# v1 教训（2026-09-27）：v1 的 f_off 网格 {0.375, 0.5, 0.625} 均为 1/16 MHz
# 的精确倍数 → FCW 是 2^20 的倍数 → 相位累加器低 20 位恒为零 → 相位截断轴
# 完全失效、轨迹只访问 16 个相位点、LUT 插值轴失效。v2 改用满熵频移。

# ---------------------------------------------------------------------------
# 速率与时钟
# ---------------------------------------------------------------------------
FS_IN = 2_000_000.0        # 输入采样率 2 MHz
R = 2                      # 抽取倍率
FS_OUT = FS_IN / R         # 输出采样率 1 MHz

# ---------------------------------------------------------------------------
# 信号与场景（§6.1：无强干扰 / 带外干扰 / 近抽取混叠边界 三类）
# ---------------------------------------------------------------------------
SYM_RATE = 250_000.0       # QPSK 符号率 0.25 Msps
SPS_IN = FS_IN / SYM_RATE  # 8 样点/符号（输入域）
RRC_BETA = 0.35            # 根升余弦滚降
SIGNAL_BW = SYM_RATE * (1 + RRC_BETA)   # 占用带宽 0.3375 MHz

# 频移网格：满熵 FCW（避免 v1 的精确可表示相位——见 CHAIN_VERSION 注释），
# 且混频后信号 ±0.17 MHz 完整落入输出带 ±0.25 MHz
F_OFF_GRID_MHZ = (0.39, 0.51, 0.63)

# 干扰频率：以"混频后频率"描述（直接决定与滤波/抽取边界的相对位置）
#   obb  : 落在 FIR 过渡带/阻带边缘（0.30 / 0.42 MHz）
#   alias: 落在抽取折叠区（混频后 0.55 MHz → 折叠回 0.45 MHz，输出带内）
BLOCKER_OFFSET_MHZ = {"obb": (0.30, 0.42), "alias": (0.55,)}
BLOCKER_REL_DB = (-3.0, +6.0)   # 相对信号功率（两档幅度）
AWGN_SNR_DB = 30.0              # 旧清单：逐样点全带 SNR；witness 清单：输出测量域 SNR（见 scenarios）

N_SYM = 1600                    # 符号数 → 输入 12800 样点
N_WARMUP_SYM = 64               # 前导/滤波器建立保护符号
SEED_BASE = 20260927            # 场景 seed 冻结基址

# ---------------------------------------------------------------------------
# 接收 FIR 原型与合法性掩码（冻结：来自应用需求，非来自候选表现）
# ---------------------------------------------------------------------------
N_TAPS = 33                     # 对称奇数抽头
PB_EDGE_MHZ = 0.20              # 通带边缘（覆盖信号 ±0.169 MHz）
SB_EDGE_MHZ = 0.45              # 阻带边缘
MASK_PB_RIPPLE_DB = 0.5         # 通带 ripple（相对原型，应用允许值）
MASK_SB_ATTEN_DB = 35.0         # 阻带衰减（−10 dB 强干扰 → ≤ −45 dB 落地）

# ---------------------------------------------------------------------------
# 字长约定
# ---------------------------------------------------------------------------
W_ADC = 12                      # 输入 IQ 位宽（Q1.11，场景统一量化口径）
W_NCO = 16                      # NCO 幅度输出位宽（Q1.15，tpl_cordic 域）
W_MIX = 16                      # 混频输出位宽（Q1.15）
W_P_ACC = 32                    # NCO 相位累加器位宽（频率精确到 mHz 级）
W_FIR_OUT = 16                  # FIR 输出位宽（Q1.15）

# 混频乘积域：Q1.11 × Q1.15 = Q2.26，求和后须右移 11 位回 Q1.15
MIX_FRAC_SHIFT = 11


@dataclass(frozen=True)
class Scenario:
    """一个冻结的评估场景（float 输入波形 + 元数据）。"""
    name: str
    klass: str            # clean | obb | alias
    f_off_mhz: float
    blocker_off_mhz: float   # 混频后频率描述；clean 场景为 0
    blocker_rel_db: float    # 相对信号功率；clean 为 -inf
    snr_db: float
    seed: int
    split: str = ""          # witness 场景集：main | heldout | stress；旧清单为空

    @property
    def has_blocker(self) -> bool:
        return self.klass != "clean"


@dataclass(frozen=True)
class ChainParams:
    """聚合导出用。"""
    version: str = CHAIN_VERSION
    fs_in: float = FS_IN
    r: int = R
    sym_rate: float = SYM_RATE
    rrc_beta: float = RRC_BETA
    n_taps: int = N_TAPS
    pb_edge_mhz: float = PB_EDGE_MHZ
    sb_edge_mhz: float = SB_EDGE_MHZ
    mask_pb_ripple_db: float = MASK_PB_RIPPLE_DB
    mask_sb_atten_db: float = MASK_SB_ATTEN_DB
    w_adc: int = W_ADC
    w_nco: int = W_NCO
    w_mix: int = W_MIX
    w_fir_out: int = W_FIR_OUT


def build_scenarios() -> list:
    """枚举冻结场景清单：3 类 × 3 频移 × 幅度档，seed 由基址派生。"""
    scenarios = []
    k = 0
    for f in F_OFF_GRID_MHZ:
        # clean：无干扰
        scenarios.append(Scenario(
            name=f"clean_f{int(f*1000)}", klass="clean", f_off_mhz=f,
            blocker_off_mhz=0.0, blocker_rel_db=-999.0,
            snr_db=AWGN_SNR_DB, seed=SEED_BASE + k))
        k += 1
        # 带外干扰：两个干扰频点 × 一个幅度档（−3 dB）
        for bo in BLOCKER_OFFSET_MHZ["obb"]:
            scenarios.append(Scenario(
                name=f"obb_f{int(f*1000)}_b{int(bo*1000)}", klass="obb",
                f_off_mhz=f, blocker_off_mhz=bo,
                blocker_rel_db=BLOCKER_REL_DB[0],
                snr_db=AWGN_SNR_DB, seed=SEED_BASE + k))
            k += 1
        # 近混叠边界：折叠后落入输出带的强干扰（+6 dB 与 −3 dB 两档）
        for i, rel in enumerate(BLOCKER_REL_DB):
            bo = BLOCKER_OFFSET_MHZ["alias"][0]
            scenarios.append(Scenario(
                name=f"alias_f{int(f*1000)}_b{int(bo*1000)}_r{int(rel)}", klass="alias",
                f_off_mhz=f, blocker_off_mhz=bo,
                blocker_rel_db=rel,
                snr_db=AWGN_SNR_DB, seed=SEED_BASE + k))
            k += 1
    return scenarios


# ---------------------------------------------------------------------------
# witness 场景集（WITNESS_FROZEN_DDC_v1 §4.1；旧 build_scenarios 保留不动）
# ---------------------------------------------------------------------------
SCENARIO_VERSION = "ddc-witness-scen-v1"
W_F_MAIN_MHZ = (0.390, 0.420, 0.450, 0.480, 0.510, 0.540, 0.570, 0.600, 0.630)
W_F_HELDOUT_MHZ = (0.405, 0.435, 0.465, 0.495, 0.525, 0.555, 0.585, 0.615)
W_OBB_MHZ = (0.300, 0.420)
W_ALIAS_MHZ = 0.555
W_REL_DB = -3.0
W_STRESS_REL_DB = +6.0
DECIM_PHASE = 0
NCO_INIT_PHASE = 0


def scenario_key(klass: str, f_off_mhz: float, blocker_off_mhz: float,
                 blocker_rel_db: float, snr_db: float) -> str:
    """完整场景键：含场景版本号，不含列表位置。"""
    return (f"{SCENARIO_VERSION}|{SEED_BASE}|{klass}|f={f_off_mhz:.3f}|b={blocker_off_mhz:.3f}"
            f"|r={blocker_rel_db:+.1f}|snr={snr_db:.1f}")


def seed_from_key(key: str) -> int:
    """由场景键稳定派生 seed（sha256 前 8 字节，落在 [0, 2^63)）。"""
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") >> 1


def _w_scen(split: str, klass: str, f: float, bo: float, rel: float) -> Scenario:
    key = scenario_key(klass, f, bo, rel, AWGN_SNR_DB)
    name = f"{klass}_f{round(f*1000)}" + ("" if klass == "clean" else
                                          f"_b{round(bo*1000)}_r{rel:+.0f}")
    return Scenario(name=name, klass=klass, f_off_mhz=f, blocker_off_mhz=bo,
                    blocker_rel_db=rel, snr_db=AWGN_SNR_DB,
                    seed=seed_from_key(key), split=split)


def _w_template(split: str, f: float) -> list:
    """四场景模板：clean + OBB 0.30 + OBB 0.42 + alias-edge 0.555（均 −3 dB）。"""
    out = [_w_scen(split, "clean", f, 0.0, -999.0)]
    out += [_w_scen(split, "obb", f, bo, W_REL_DB) for bo in W_OBB_MHZ]
    out.append(_w_scen(split, "alias", f, W_ALIAS_MHZ, W_REL_DB))
    return out


def build_witness_scenarios(split: str | None = None) -> list:
    """C_main 36 / C_heldout 32 / C_stress 9；split=None 返回三者按序拼接。"""
    sets = {
        "main": [s for f in W_F_MAIN_MHZ for s in _w_template("main", f)],
        "heldout": [s for f in W_F_HELDOUT_MHZ for s in _w_template("heldout", f)],
        "stress": [_w_scen("stress", "alias", f, W_ALIAS_MHZ, W_STRESS_REL_DB)
                   for f in W_F_MAIN_MHZ],
    }
    if split is None:
        return sets["main"] + sets["heldout"] + sets["stress"]
    return sets[split]


def fcw_of(f_off_mhz: float) -> int:
    """整数 FCW = round(f/Fs·2^32)（与 fixed_chain / rtl_gen 同式）。"""
    return int(round(f_off_mhz * 1e6 / FS_IN * (1 << W_P_ACC)))


def fcw_info(f_off_mhz: float) -> dict:
    fcw = fcw_of(f_off_mhz)
    g = math.gcd(fcw, 1 << W_P_ACC)
    return {"fcw": fcw, "gcd": g, "period": (1 << W_P_ACC) // g,
            "f_exact_hz": fcw * FS_IN / (1 << W_P_ACC)}


def export_witness_manifest(path: str | None = None, levels: dict | None = None) -> dict:
    """witness 场景 manifest。levels 可选：{name: 实测功率/缩放}，由 scenarios 生成后填入。"""
    scen = build_witness_scenarios()
    m = {
        "scenario_version": SCENARIO_VERSION,
        "chain_version": CHAIN_VERSION,
        "params": asdict(ChainParams()),
        "n_sym": N_SYM,
        "n_warmup_sym": N_WARMUP_SYM,
        "seed_base": SEED_BASE,
        "seed_rule": "sha256(scenario_key)[:8] >> 1",
        "snr_definition": ("output measurement-domain P_des_out/P_noise_out = snr_db, "
                           "via ideal integer-FCW mix + prototype FIR + R, same segment as q; "
                           "before blocker; input full-band SNR reported per scenario"),
        "qpsk_symbol_power": 0.5,
        "front_end_scale_rule": "s = 0.95/peak if peak(|d+b+n|) >= 1 else 1; applied to all components",
        "decim_phase": DECIM_PHASE,
        "nco_init_phase": NCO_INIT_PHASE,
        "fcw": {f"{f:.3f}": fcw_info(f) for f in W_F_MAIN_MHZ + W_F_HELDOUT_MHZ},
        "scenarios": [dict(asdict(s), key=scenario_key(s.klass, s.f_off_mhz,
                                                         s.blocker_off_mhz,
                                                         s.blocker_rel_db, s.snr_db),
                           **({"levels": levels[s.name + "@" + s.split]}
                              if levels and (s.name + "@" + s.split) in levels else {}))
                      for s in scen],
    }
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
    return m


def export_manifest(path: str | None = None) -> dict:
    """冻结 manifest：参数 + 场景清单（写入 experiments_system/）。"""
    m = {
        "chain_version": CHAIN_VERSION,
        "params": asdict(ChainParams()),
        "n_sym": N_SYM,
        "n_warmup_sym": N_WARMUP_SYM,
        "seed_base": SEED_BASE,
        "f_off_grid_mhz": list(F_OFF_GRID_MHZ),
        "blocker_offset_mhz": {k: list(v) for k, v in BLOCKER_OFFSET_MHZ.items()},
        "blocker_rel_db": list(BLOCKER_REL_DB),
        "awgn_snr_db": AWGN_SNR_DB,
        "scenarios": [asdict(s) for s in build_scenarios()],
    }
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
    return m
