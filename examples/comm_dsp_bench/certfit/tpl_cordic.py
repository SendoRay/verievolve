"""cordic_sincos 证书模板：LUT+插值 / CORDIC 迭代，全枚举精确误差模型。

参数空间：
  algo:   "lut" | "cordic"
  order:  "nearest" | "linear" | "quad"      （仅 lut）
  depth:  LUT 全波表深 ∈ {64,128,256,512,1024}
  stages: CORDIC 迭代级数 ∈ {8..20}           （仅 cordic）

模型层级：
  precision    : 65536 角度码**全枚举**上的整数域逐位仿真——L2 层的
                 完全精确形态（零积分误差，cordic 任务专属红利：
                 一维输入空间恰好可枚举）
  precision_wc : 解析最坏界（插值误差界 / CORDIC 残余角+舍入界），sound
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

_BENCH = Path(__file__).resolve().parent.parent
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

from design_gen import gen_lut_quarter, gen_cordic  # noqa: E402

THROUGHPUT_PARALLEL = 0.908

DEFAULTS = {
    "algo": "lut",
    "order": "linear",
    "depth": 64,
    "stages": 12,
}


def validate(p: Dict) -> Tuple[bool, str]:
    if p.get("algo") == "lut":
        if p.get("order") not in ("nearest", "linear", "quad"):
            return False, f"order={p.get('order')} 非法"
        if int(p.get("depth", 0)) not in (64, 128, 256, 512, 1024):
            return False, f"depth={p.get('depth')} 非法（须为 64..1024 的 2 幂）"
        if p["order"] == "nearest" and int(p["depth"]) > 1024:
            return False, "nearest 深表无意义"
        return True, "ok"
    if p.get("algo") == "cordic":
        st = int(p.get("stages", 0))
        if not (8 <= st <= 20):
            return False, f"stages={st} 越界 [8,20]"
        return True, "ok"
    return False, f"algo={p.get('algo')} 非法"


# ---------------------------------------------------------------------------
# 整数域逐位仿真（与 design_gen 生成的 RTL 位操作一一对应）
# ---------------------------------------------------------------------------

def _table(N: int) -> np.ndarray:
    S = N // 4
    return np.array(
        [max(-32767, min(32767, round(math.sin(2 * math.pi * k / N) * 32768)))
         for k in range(S + 2)], dtype=np.int64)


def _emul_lut(z: np.ndarray, N: int, order: str):
    """LUT 设计的整数域仿真，返回 (sin, cos) 各 16 位补码值。"""
    S = N // 4
    fb = 14 - int(math.log2(S))
    fdiv = 1 << fb
    T = _table(N)

    def wave(zx: np.ndarray) -> np.ndarray:
        ps = zx & 0xFFFF
        ngs = (ps >> 15) & 1
        prs = ps & 0x7FFF
        ms = np.where((prs >> 14) & 1, 0x8000 - prs, prs)  # 三角折叠 → [0, 2^14]
        mi = ms >> fb
        d = ms & (fdiv - 1)
        s0 = T[np.clip(mi, 0, S + 1)]
        if order == "nearest":
            y = s0
        elif order == "linear":
            s1 = T[np.clip(mi + 1, 0, S + 1)]
            a1 = s1 - s0
            lt = a1 * d                       # 有符号×无符号，整数精确
            y = s0 + (lt >> fb) + ((lt >> (fb - 1)) & 1)  # (lt>>fb) + 丢位 MSB
        else:  # quad
            s1 = T[np.clip(mi + 1, 0, S + 1)]
            s2 = T[np.clip(mi + 2, 0, S + 1)]
            a1 = s1 - s0
            a2 = s2 - 2 * s1 + s0
            lt = a1 * d
            lr = (lt >> fb) + ((lt >> (fb - 1)) & 1)
            qw = d * (d - fdiv)               # 可负
            t2 = a2 * qw                      # |a2| ≤ 8（正弦四分之一波），8 位截断无损
            qr = (t2 >> (2 * fb + 1)) + ((t2 >> (2 * fb)) & 1)
            y = s0 + lr + qr
        y = np.where(ngs == 1, -y, y)
        return np.clip(y, -32768, 32767)

    sin_v = wave(z)
    cos_v = wave(z + 16384)
    return sin_v, cos_v


def _emul_cordic(z: np.ndarray, stages: int):
    """CORDIC 设计的整数域仿真（19/18 位寄存器宽度逐位复刻）。"""
    alpha = [round(math.atan(2.0 ** -i) * 65536 / math.pi) for i in range(stages)]
    x = np.full(z.shape, 79594, dtype=np.int64)
    y = np.zeros(z.shape, dtype=np.int64)
    za = np.zeros(z.shape, dtype=np.int64)
    neg = np.zeros(z.shape, dtype=bool)

    z2 = ((z.astype(np.int64) << 1) & 0x3FFFF)
    z2 = np.where(z2 >= (1 << 17), z2 - (1 << 18), z2)  # 18 位补码
    fold_hi = z > 16384
    fold_lo = z < -16384
    zf = np.where(fold_hi, z2 - 65536, np.where(fold_lo, z2 + 65536, z2))
    neg = fold_hi | fold_lo
    za = np.where(zf >= 0, zf, zf + (1 << 18)) & 0x3FFFF
    za = np.where(zf < 0, zf + (1 << 18), zf).astype(np.int64)
    za = ((zf + (1 << 17)) % (1 << 18)) - (1 << 17)  # 18 位补码域
    for i in range(stages):
        xsh = x >> np.minimum(i, 63)
        ysh = y >> np.minimum(i, 63)
        zpos = za >= 0
        x_new = np.where(zpos, x - ysh, x + ysh)
        y_new = np.where(zpos, y + xsh, y - xsh)
        za = np.where(zpos, za - alpha[i], za + alpha[i])
        x = ((x_new + (1 << 18)) % (1 << 19)) - (1 << 18)  # 19 位寄存器回绕
        y = ((y_new + (1 << 18)) % (1 << 19)) - (1 << 18)
        za = ((za + (1 << 17)) % (1 << 18)) - (1 << 17)
    sin_r = (y + 2) >> 2
    cos_r = (x + 2) >> 2
    sin_a = np.where(neg, -sin_r, sin_r)
    cos_a = np.where(neg, -cos_r, cos_r)
    return (np.clip(sin_a, -32768, 32767), np.clip(cos_a, -32768, 32767))


def emulate(p: Dict, z: np.ndarray):
    if p["algo"] == "lut":
        return _emul_lut(z, int(p["depth"]), p["order"])
    return _emul_cordic(z, int(p["stages"]))


# ---------------------------------------------------------------------------
# 证书指标
# ---------------------------------------------------------------------------

def cert_metrics(p: Dict) -> Dict:
    from certfit import common as cm

    # 全枚举：65536 个角度码（L2 完全精确形态，零积分误差）
    z = np.arange(-(1 << 15), (1 << 15), dtype=np.int64)
    sin_d, cos_d = emulate(p, z)
    ang = z.astype(np.float64) * math.pi / float(1 << 15)
    sin_i = np.sin(ang) * 32768.0
    cos_i = np.cos(ang) * 32768.0
    err2 = max(float(np.mean((sin_d - sin_i) ** 2)),
               float(np.mean((cos_d - cos_i) ** 2)))
    sig = float(np.mean(sin_i ** 2))  # 离散均匀角的精确信号功率
    prec = cm.sqnr_db(sig, err2)

    # L3 最坏界（幅度误差单位 = 满幅 1.0）
    if p["algo"] == "lut":
        N = int(p["depth"])
        S = N // 4
        hb = (math.pi / 2) / S          # 段宽（弧度）
        if p["order"] == "nearest":
            e_ang = hb / 2
            e_tbl = 0.5 / 32768.0
        elif p["order"] == "linear":
            e_ang = hb * hb / 8         # |sin''| ≤ 1
            e_tbl = 1.5 / 32768.0       # 两表项 + 插值舍入
        else:
            e_ang = hb ** 3 / 24        # |sin'''| ≤ 1 保守界
            e_tbl = 2.5 / 32768.0
        e_wc = e_ang + e_tbl + 0.5 / 32768.0
    else:
        n = int(p["stages"])
        res_ang = math.atan(2.0 ** -(n - 1)) + n * 1.5 * (math.pi / (1 << 16))
        e_xy = n * 1.5 / ((1 << 17) * 0.6073) + 0.5 / 32768.0
        e_wc = res_ang + e_xy

    return {
        "precision": round(prec, 4),
        "precision_wc": round(cm.sqnr_db(sig, (e_wc * 32768.0) ** 2), 4),
        "throughput": (THROUGHPUT_PARALLEL if p["algo"] == "lut"
                       else THROUGHPUT_PARALLEL / (int(p["stages"]) + 1.5)),
        "err_power_mean": err2,
        "sig_power": sig,
        "enumeration": 65536,
    }


# ---------------------------------------------------------------------------
# Verilog 生成（复用 design_gen 参数化生成器）
# ---------------------------------------------------------------------------

def generate_verilog(p: Dict) -> str:
    if p["algo"] == "lut":
        return gen_lut_quarter(int(p["depth"]), p["order"])
    return gen_cordic(int(p["stages"]))
