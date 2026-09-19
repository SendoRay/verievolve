"""atan2_w16 证书模板：八分象限折叠 + 参数化除法精度/表深/插值阶。

参数空间：
  depth: atan 表深 D ∈ {64,128,256,512,1024}（r ∈ [0,1] 均匀分格）
  interp: "nearest"（bin-center 表）| "linear"（边沿表 + 线性插值）
  div_frac: 除法商的小数位 p ∈ {8..16}（r = min·2^p / max，截断）

模型层级：
  precision    : 确定性 Sobol 2D 格点（复平面幅角×幅值分布，固定种子）上的
                 整数域逐位仿真——零随机性
  precision_wc : 除法截断 + 表系数舍入 + 插值误差的解析最坏界（sound）
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np

from certfit import common

THROUGHPUT_PARALLEL = 0.908
C_CODE = 32768.0 / math.pi  # 弧度 → 角度码

DEFAULTS = {
    "depth": 512,
    "interp": "nearest",
    "div_frac": 9,
}


def validate(p: Dict) -> Tuple[bool, str]:
    if int(p.get("depth", 0)) not in (64, 128, 256, 512, 1024):
        return False, f"depth={p.get('depth')} 非法"
    if p.get("interp") not in ("nearest", "linear"):
        return False, f"interp={p.get('interp')} 非法"
    if not isinstance(p.get("div_frac"), int) or not (8 <= p["div_frac"] <= 16):
        return False, f"div_frac={p.get('div_frac')} 越界 [8,16]"
    return True, "ok"


# ---------------------------------------------------------------------------
# 整数域逐位仿真
# ---------------------------------------------------------------------------

def _tables(D: int, interp: str) -> np.ndarray:
    if interp == "nearest":
        return np.array([round(math.atan((k + 0.5) / D) * C_CODE)
                         for k in range(D)], dtype=np.int64)
    return np.array([round(math.atan(k / D) * C_CODE)
                     for k in range(D + 1)], dtype=np.int64)


def emulate(p: Dict, i_in: np.ndarray, q_in: np.ndarray):
    """返回 16 位角度码（与 RTL 逐位对应）。"""
    D = int(p["depth"])
    interp = p["interp"]
    pf = int(p["div_frac"])
    fb = int(math.log2(D))
    A = _tables(D, interp)

    ai = np.abs(i_in.astype(np.int64))
    aq = np.abs(q_in.astype(np.int64))
    swap = aq > ai
    x = np.where(swap, aq, ai)
    y = np.where(swap, ai, aq)
    xr = np.where(x == 0, 1, x)
    rq = np.minimum((y << pf) // xr, (1 << pf) - 1)

    if interp == "nearest":
        a0 = A[rq >> (pf - fb)]
    else:
        idx = rq >> (pf - fb)
        frac = rq & ((1 << (pf - fb)) - 1)
        a0w = A[idx]
        a1w = A[np.minimum(idx + 1, D)]
        dd = (a1w - a0w) * frac
        a0 = a0w + (dd >> (pf - fb)) + ((dd >> (pf - fb - 1)) & 1)

    base = np.where(swap, (1 << 14) - a0, a0)
    t1 = np.where(i_in < 0, (1 << 15) - base, base)
    t2 = np.where(q_in < 0, -t1, t1)
    tw = np.where(t2 >= (1 << 15), t2 - (1 << 16),
                  np.where(t2 < -(1 << 15), t2 + (1 << 16), t2))
    return tw.astype(np.int64)


# ---------------------------------------------------------------------------
# 证书指标
# ---------------------------------------------------------------------------

def cert_metrics(p: Dict) -> Dict:
    D = int(p["depth"])
    interp = p["interp"]
    pf = int(p["div_frac"])
    fb = int(math.log2(D))

    N = 1 << 20  # 尖刺型被积函数：加大格点；确定性保证可复现（收敛性见论文 §5.4）
    u = common.sobol_unit(N, 2)
    ang = u[:, 0] * 2 * math.pi - math.pi
    mag = (0.2 + 0.8 * u[:, 1]) * 32767.0
    i_in = np.clip(np.round(mag * np.cos(ang)), -32768, 32767).astype(np.int64)
    q_in = np.clip(np.round(mag * np.sin(ang)), -32768, 32767).astype(np.int64)

    dut = emulate(p, i_in, q_in)
    ref = np.clip(np.round(np.arctan2(q_in.astype(np.float64), i_in.astype(np.float64))
                           * (1 << 15) / math.pi), -(1 << 15), (1 << 15) - 1)
    err2 = float(np.mean((dut.astype(np.float64) - ref) ** 2))
    sig = float(np.mean(ref.astype(np.float64) ** 2))
    prec = common.sqnr_db(sig, err2)

    # L3 最坏界（角度码单位）
    hb = 1.0 / D
    e_div = C_CODE * (2.0 ** -pf)
    if interp == "nearest":
        e_tbl = 0.5 + hb / 2 * C_CODE
    else:
        e_tbl = 1.0 + hb * hb * 0.6495 / 8 * C_CODE
    e_wc = e_div + e_tbl
    prec_wc = common.sqnr_db(math.pi ** 2 / 3 * C_CODE ** 2, e_wc * e_wc)

    return {
        "precision": round(prec, 4),
        "precision_wc": round(prec_wc, 4),
        "throughput": THROUGHPUT_PARALLEL,
        "err_power_mean": err2,
        "sig_power": sig,
        "grid_points": N,
    }


# ---------------------------------------------------------------------------
# Verilog 生成
# ---------------------------------------------------------------------------

def generate_verilog(p: Dict) -> str:
    D = int(p["depth"])
    interp = p["interp"]
    pf = int(p["div_frac"])
    fb = int(math.log2(D))
    A = _tables(D, interp)
    iw = fb + 1
    entries = "\n".join(
        f"                {iw}'d{k}: T = 16'sd{v};" for k, v in enumerate(A)
    )

    core = f"""
    wire [{15 + pf}:0] yext = y;
    wire [{15 + pf}:0] num = yext << {pf};
    wire [{15 + pf}:0] rq = num / xr;
    wire [{15 + pf}:0] rq_c = (rq > {15 + pf}'d{(1 << pf) - 1}) ? {15 + pf}'d{(1 << pf) - 1} : rq;
    function signed [15:0] T;
        input [{iw - 1}:0] k;
        begin
            case (k)
{entries}
                default: T = 16'sd0;
            endcase
        end
    endfunction"""
    if interp == "nearest":
        core += f"""
    wire signed [16:0] a0 = T(rq_c[{pf - 1}:{pf - fb}]);"""
    else:
        core += f"""
    wire [{fb - 1}:0] idx = rq_c[{pf - 1}:{pf - fb}];
    wire [{pf - fb - 1}:0] frac = rq_c[{pf - fb - 1}:0];
    wire signed [15:0] a0w = T(idx);
    wire signed [15:0] a1w = T(idx + 1'b1);
    wire signed [16 + {pf - fb}:0] dd = (a1w - a0w) * $signed({{1'b0, frac}});
    wire signed [16 + {pf - fb}:0] dqs = dd >>> {pf - fb};
    wire signed [16:0] a0w_x = a0w;
    wire signed [16:0] dqs_x = dqs;
    wire signed [16:0] a0 = a0w_x + dqs_x + $signed({{16'd0, dd[{pf - fb - 1}]}});"""

    return f"""// certfit 参数化 atan2：D={D} interp={interp} div_frac={pf}
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [15:0] theta
);
    // EVOLVE-BLOCK-START
    wire [15:0] ai = i_in < 0 ? -i_in : i_in;
    wire [15:0] aq = q_in < 0 ? -q_in : q_in;
    wire swap = aq > ai;
    wire [15:0] x = swap ? aq : ai;
    wire [15:0] y = swap ? ai : aq;
    wire [15:0] xr = (x == 16'd0) ? 16'd1 : x;
{core}
    wire signed [16:0] base = swap ? (17'sd16384 - a0) : a0;
    wire signed [17:0] t1 = i_in[15] ? (18'sd32768 - base) : base;
    wire signed [17:0] t2 = q_in[15] ? -t1 : t1;
    wire signed [17:0] tw = (t2 >= 18'sd32768) ? (t2 - 18'sd65536) :
                            (t2 < -18'sd32768) ? (t2 + 18'sd65536) : t2;
    wire signed [15:0] result = tw[15:0];

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; theta <= 16'sd0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                theta <= result;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""
