"""cmul_w16_free 证书模板：参数化复数乘法器 + 精确误差模型。

参数空间（LLM 在此空间内进化，每一点都有证书）：
  operand_trunc: 每操作数 RNE 丢弃的低位数 so ∈ [0, 10]（缩小乘法器）
  prod_drop:     乘积累加后丢弃的低位数 sd ∈ [0, 8]（输出量化）
  rounding:      "rne" | "trunc"
  structure:     "direct"（4 乘法器）| "karatsuba"（3 乘法器，精确重组）

关键代数事实（论文 §4.2）：operand 截断后 karatsuba 重组
  im = (a_h+b_h)(c_h+d_h) − a_h·c_h − b_h·d_h
在整数域**精确**成立——结构选择只影响面积，不影响精度（ε-等价类的
具体体现）。精度完全由 (so, sd, rounding) 决定。

位宽设计：乘法器位宽 (17-so)，累加器恒宽 35 位（移位恢复满幅值）——
面积收益全部来自乘法器，数值范围与全精度设计相同。

误差模型层级：
  precision     : 确定性 Sobol 格点（固定种子）上的整数域精确仿真 → 零随机性
  precision_wc  : 区间算术闭式最坏界（对全体输入 sound）
  exact_lemma   : so=0 且 sd ≤ 15 时模分解引理给出精确总体矩（验证用）
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

from . import common

THROUGHPUT_STRUCT = 0.908  # 单拍输出设计在 10% 气泡协议下的期望吞吐（实测校准）

DEFAULTS = {
    "operand_trunc": 0,
    "prod_drop": 0,
    "rounding": "rne",
    "structure": "direct",
}


def validate(p: Dict) -> Tuple[bool, str]:
    so = p.get("operand_trunc", 0)
    sd = p.get("prod_drop", 0)
    if not isinstance(so, int) or not (0 <= so <= 10):
        return False, f"operand_trunc={so} 越界 [0,10]"
    if not isinstance(sd, int) or not (0 <= sd <= 8):
        return False, f"prod_drop={sd} 越界 [0,8]"
    if 2 * so + sd > 24:
        return False, f"总丢位 2*{so}+{sd}={2*so+sd} > 24（小数位不足 8 位，无意义）"
    if p.get("rounding", "rne") not in ("rne", "trunc"):
        return False, f"rounding={p.get('rounding')} 非法"
    if p.get("structure", "direct") not in ("direct", "karatsuba"):
        return False, f"structure={p.get('structure')} 非法"
    return True, "ok"


# ---------------------------------------------------------------------------
# 精确整数域模型（与生成的 Verilog 逐位对应）
# ---------------------------------------------------------------------------

def _rne_shift(v, s: int):
    """算术 RNE 右移（Verilog: 先 +2^(s-1) 再算术右移）。"""
    if s <= 0:
        return v
    return (v + (1 << (s - 1))) >> s


def _drop(v, s: int, mode: str):
    """丢弃低 s 位（rne half-up / trunc floor），保持 2^s 倍数。"""
    if s <= 0:
        return v
    if mode == "trunc":
        return (v >> s) << s
    return ((v + (1 << (s - 1))) >> s) << s


def emulate(p: Dict, a, b, c, d) -> Tuple[np.ndarray, np.ndarray]:
    """整数域逐位仿真 DUT。输入 16 位补码值，输出量化后的整数（Q2.30 域）。"""
    so, sd = p["operand_trunc"], p["prod_drop"]
    mode = p["rounding"]
    kar = p["structure"] == "karatsuba"
    ah = _rne_shift(a, so)
    bh = _rne_shift(b, so)
    ch = _rne_shift(c, so)
    dh = _rne_shift(d, so)
    pac, pbd = ah * ch, bh * dh
    re_pre = (pac - pbd) << (2 * so)
    if kar:
        im_pre = ((ah + bh) * (ch + dh) - pac - pbd) << (2 * so)
    else:
        im_pre = (ah * dh + bh * ch) << (2 * so)
    return _drop(re_pre, sd, mode), _drop(im_pre, sd, mode)


def ideal(a, b, c, d) -> Tuple[np.ndarray, np.ndarray]:
    """全精度理想值（golden 口径，整数域）。"""
    return a * c - b * d, a * d + b * c


# ---------------------------------------------------------------------------
# 证书指标
# ---------------------------------------------------------------------------

def cert_metrics(p: Dict) -> Dict:
    """确定性证书评估（全程无随机数）。"""
    so, sd = p["operand_trunc"], p["prod_drop"]
    mode = p["rounding"]
    kar = p["structure"] == "karatsuba"

    N = 65536
    pts = common.lattice_points(N, [1 << 16] * 4)
    a = pts[:, 0] - (1 << 15)
    b = pts[:, 1] - (1 << 15)
    c = pts[:, 2] - (1 << 15)
    d = pts[:, 3] - (1 << 15)

    re_d, im_d = emulate(p, a, b, c, d)
    re_i, im_i = ideal(a, b, c, d)
    err2 = float(max(
        np.mean((re_d - re_i) ** 2),
        np.mean((im_d - im_i) ** 2),
    ))
    sig = common.cmul_exact_signal_power()
    prec_mean = common.sqnr_db(sig, err2)

    # L3 最坏界（区间算术，sound，对全体输入成立）
    eo = 0
    if so > 0:
        eo = (1 << (so - 1)) if mode == "rne" else (1 << so)  # |a − a_h·2^so| ≤
    amax = 1 << 15
    e_prod = eo * amax + (amax + eo) * eo + eo * eo  # |ac − a_h c_h 2^(2so)|
    e_acc = e_prod * (3 if kar else 2)
    e_drop = 0
    if sd > 0:
        per = (1 << (sd - 1)) if mode == "rne" else ((1 << sd) - 1)
        e_drop = per * (3 if kar else 2)  # 每输出涉及的独立丢位项上界
    e_wc = float(e_acc + e_drop)
    prec_wc = common.sqnr_db(sig, e_wc * e_wc)

    out = {
        "precision": round(prec_mean, 4),
        "precision_wc": round(prec_wc, 4),
        "throughput": THROUGHPUT_STRUCT,
        "err_power_mean": err2,
        "sig_power": sig,
    }

    # 模分解引理（so=0 且 sd≤15：精确总体矩，用于验证 Sobol 积分）
    if so == 0 and sd <= 15:
        try:
            m = common.cmul_exact_err_moments(sd, mode=mode, karatsuba=kar)
            exact_err2 = float(max(m["re_mom2"], m["im_mom2"]))
            out["exact_lemma_sqnr"] = round(common.sqnr_db(sig, exact_err2), 4)
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------------------
# Verilog 生成（与 emulate() 逐位对应）
# ---------------------------------------------------------------------------

def generate_verilog(p: Dict) -> str:
    so, sd = p["operand_trunc"], p["prod_drop"]
    mode = p["rounding"]
    kar = p["structure"] == "karatsuba"

    acc_w = 35  # 恒宽累加器（|re| ≤ 2^31 + 舍入余量）
    qw = 17 - so  # 截断后 |a_h| ≤ 2^(16-so)-1
    half = (1 << (so - 1)) if so > 0 else 0

    if so > 0:
        qline = f"""
    wire signed [16:0] a_e = a + 17'sd{half};
    wire signed [16:0] b_e = b + 17'sd{half};
    wire signed [16:0] c_e = c + 17'sd{half};
    wire signed [16:0] d_e = d + 17'sd{half};
    wire signed [{qw - 1}:0] a_h = a_e >>> {so};
    wire signed [{qw - 1}:0] b_h = b_e >>> {so};
    wire signed [{qw - 1}:0] c_h = c_e >>> {so};
    wire signed [{qw - 1}:0] d_h = d_e >>> {so};"""
        aq, bq, cq, dq = "a_h", "b_h", "c_h", "d_h"
        shift = 2 * so
    else:
        qline = ""
        aq, bq, cq, dq = "a", "b", "c", "d"
        shift = 0

    mw = 2 * (17 - so)  # 乘积位宽
    if kar:
        sw = 18 - so
        mult = f"""
    wire signed [{mw - 1}:0] pac = $signed({aq}) * $signed({cq});
    wire signed [{mw - 1}:0] pbd = $signed({bq}) * $signed({dq});
    wire signed [{sw - 1}:0] sab = $signed({aq}) + $signed({bq});
    wire signed [{sw - 1}:0] scd = $signed({cq}) + $signed({dq});
    wire signed [{2 * sw - 1}:0] p1 = sab * scd;"""
        sums = f"""
    wire signed [{acc_w - 1}:0] pac_x = pac;
    wire signed [{acc_w - 1}:0] pbd_x = pbd;
    wire signed [{acc_w - 1}:0] p1_x = p1;
    wire signed [{acc_w - 1}:0] re_pre = (pac_x - pbd_x) <<< {shift};
    wire signed [{acc_w - 1}:0] im_pre = (p1_x - pac_x - pbd_x) <<< {shift};"""
    else:
        mult = f"""
    wire signed [{mw - 1}:0] pac = $signed({aq}) * $signed({cq});
    wire signed [{mw - 1}:0] pbd = $signed({bq}) * $signed({dq});
    wire signed [{mw - 1}:0] pad = $signed({aq}) * $signed({dq});
    wire signed [{mw - 1}:0] pbc = $signed({bq}) * $signed({cq});"""
        sums = f"""
    wire signed [{acc_w - 1}:0] pac_x = pac;
    wire signed [{acc_w - 1}:0] pbd_x = pbd;
    wire signed [{acc_w - 1}:0] pad_x = pad;
    wire signed [{acc_w - 1}:0] pbc_x = pbc;
    wire signed [{acc_w - 1}:0] re_pre = (pac_x - pbd_x) <<< {shift};
    wire signed [{acc_w - 1}:0] im_pre = (pad_x + pbc_x) <<< {shift};"""

    if sd > 0:
        h2 = 1 << (sd - 1)
        if mode == "trunc":
            dq_l = f"""
    wire signed [{acc_w - 1}:0] re_q = (re_pre >>> {sd}) <<< {sd};
    wire signed [{acc_w - 1}:0] im_q = (im_pre >>> {sd}) <<< {sd};"""
        else:
            dq_l = f"""
    wire signed [{acc_w}:0] re_e = re_pre + {acc_w + 1}'sd{h2};
    wire signed [{acc_w}:0] im_e = im_pre + {acc_w + 1}'sd{h2};
    wire signed [{acc_w - 1}:0] re_q = (re_e >>> {sd}) <<< {sd};
    wire signed [{acc_w - 1}:0] im_q = (im_e >>> {sd}) <<< {sd};"""
        yline = "                y_re <= re_q[32:0]; y_im <= im_q[32:0];"
    else:
        dq_l = ""
        yline = "                y_re <= re_pre[32:0]; y_im <= im_pre[32:0];"

    return f"""// certfit 参数化复数乘法器 so={so} sd={sd} mode={mode} structure={p['structure']}
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] a,
    input  wire signed [15:0] b,
    input  wire signed [15:0] c,
    input  wire signed [15:0] d,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [32:0] y_re,
    output reg  signed [32:0] y_im
);
    // EVOLVE-BLOCK-START
{qline}
{mult}
{sums}
{dq_l}
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; y_re <= 0; y_im <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
{yline}
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""
