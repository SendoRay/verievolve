#!/usr/bin/env python
"""任务族朴素基线生成器（与 tasks_gen/ 实例一一对应）

各族基线 = 参数化的直接型实现（故意朴素，给进化留空间）：
  crc   : 组合逐位展开（16 步/字，单拍，面积大）
  atan2 : 八分象限折叠 + 粗查表
  mfilt : 直接型移位相关（乘法器版——进化应发现 ±1 序列的加减退化）
  fir   : 直接型全抽头（复用 tasks/fir 基线生成逻辑）
  nco   : 相位累加 + 最近邻表（复用 tasks/nco 逻辑，参数化位宽）
  cmul  : 4 乘法器（参数化位宽）
  llr   : max-log 逐比特（参数化阶数）

用法: python family_baselines_gen.py [--sample]   # --sample 每族 1 个
"""

import argparse
import math
from pathlib import Path

import numpy as np
import yaml

BENCH = Path(__file__).resolve().parent
TASKS = BENCH / "tasks_gen"
OUT = BENCH / ".family_baselines"


# ---------------------------------------------------------------------------
# CRC：组合逐位展开
# ---------------------------------------------------------------------------

def crc_baseline(width: int, poly_hex: str) -> str:
    poly = int(poly_hex, 16)
    return f"""// 参数化基线：CRC-{width} 组合逐位展开（16 步，单拍，朴素）
module top (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [15:0] data,
    output reg         out_valid,
    input  wire        out_ready,
    output reg  [{width - 1}:0] crc
);
    // EVOLVE-BLOCK-START
    reg [{width - 1}:0] acc;
    reg [{width - 1}:0] c;
    integer k;
    always @(*) begin
        c = acc;
        for (k = 15; k >= 0; k = k - 1) begin
            if ((c[{width - 1}] ^ data[k]))
                c = (c << 1) ^ {width}'h{poly:x};
            else
                c = c << 1;
        end
    end
    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            acc <= {width}'d0; out_valid <= 1'b0; crc <= {width}'d0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                acc <= c;
                crc <= c;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""


# ---------------------------------------------------------------------------
# atan2：八分象限折叠 + 粗查表
# ---------------------------------------------------------------------------

def atan2_baseline(w: int) -> str:
    half = 1 << (w - 1)
    # 512 点 atan(r) 表（r ∈ [0,1)，输出 0..half/4）
    q = half // 4
    tbl = [int(round(math.atan((k + 0.5) / 512.0) * half / math.pi)) for k in range(512)]
    tbl = [min(q - 1, max(0, v)) for v in tbl]
    entries = []
    for k, v in enumerate(tbl):
        entries.append(f"                9'd{k}: atab = {q and ''}{v};")
    # 分行打包（512 行太长，压缩为每行 8 项）
    rows = []
    for k in range(0, 512, 8):
        cells = "; ".join(f"9'd{k+j}: atab = {tbl[k+j]}" for j in range(8))
        rows.append(f"                {cells};")
    case_body = "\n".join(rows)
    return f"""// 参数化基线：atan2 八分象限折叠 + 512 点查表（{w} 位，朴素）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [{w - 1}:0] i_in,
    input  wire signed [{w - 1}:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [{w - 1}:0] theta
);
    // EVOLVE-BLOCK-START
    wire [{w - 1}:0] ai = i_in < 0 ? -i_in : i_in;
    wire [{w - 1}:0] aq = q_in < 0 ? -q_in : q_in;
    wire sgn_i = i_in[{w - 1}];
    wire sgn_q = q_in[{w - 1}];
    wire swap = aq > ai;                       // 八分象限：比值 <= 1
    wire [{w - 1}:0] x = swap ? aq : ai;
    wire [{w - 1}:0] y = swap ? ai : aq;
    // 比值查表索引（朴素除法，16 位截断）
    wire [15:0] r16 = (x == {w}'d0) ? 16'd0 : ((y * 16'd512) / (x | {w}'d1));
    wire [8:0] ridx = r16[8:0];

    function signed [{w - 1}:0] atab;
        input [8:0] r;
        begin
            case (r)
{case_body}
                default: atab = {q};
            endcase
        end
    endfunction

    wire signed [{w - 1}:0] a0 = atab(ridx);
    wire signed [{w}:0] base = swap ? ({half // 2} - a0) : a0;
    wire signed [{w}:0] t0 = sgn_i ? -base : base;
    wire signed [{w}:0] tf = (sgn_q ^ sgn_i) ? (t0 + {half}) : t0;
    wire signed [{w}:0] norm = tf >= {half} ? (tf - {2 * half}) :
                                (tf < -{half} ? (tf + {2 * half}) : tf);
    wire signed [{w - 1}:0] result = norm[{w - 1}:0];

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; theta <= 0;
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


# ---------------------------------------------------------------------------
# mfilt：直接型移位相关
# ---------------------------------------------------------------------------

def mfilt_baseline(L: int, S: list) -> str:
    sdecl = "\n".join(f"    localparam signed [15:0] S{k} = 16'sd{v};" for k, v in enumerate(S))
    return f"""// 参数化基线：匹配滤波直接型（{L} tap，乘法器版，朴素）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [23:0] c_re,
    output reg  signed [23:0] c_im
);
    // EVOLVE-BLOCK-START
{sdecl}
    reg signed [15:0] di [0:{L - 1}];
    reg signed [15:0] dq [0:{L - 1}];
    integer k;
    reg signed [23:0] acci, accq;
    always @(*) begin
        acci = 0; accq = 0;
        for (k = 0; k < {L}; k = k + 1) begin
            acci = acci + (di[k] * S{{0}});  // 占位，下面替换
            accq = accq + (dq[k] * S{{0}});
        end
    end
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (k = 0; k < {L}; k = k + 1) begin di[k] <= 0; dq[k] <= 0; end
            out_valid <= 1'b0; c_re <= 0; c_im <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                for (k = {L} - 1; k > 0; k = k - 1) begin
                    di[k] <= di[k-1]; dq[k] <= dq[k-1];
                end
                di[0] <= i_in; dq[0] <= q_in;
                c_re <= acci; c_im <= accq;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
""".replace("di[k] * S{0}", "di[k] * Sk").replace("dq[k] * S{0}", "dq[k] * Kk")


# 更简单的实现：用 generate 展开系数
def mfilt_baseline2(L: int, S: list) -> str:
    sarr = "\n".join(
        f"                9'd{k}: seqf = " + (f"-16'sd{abs(v)}" if v < 0 else f"16'sd{v}") + ";"
        for k, v in enumerate(S))
    return f"""// 参数化基线：匹配滤波直接型（{L} tap，乘法器版，朴素）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [23:0] c_re,
    output reg  signed [23:0] c_im
);
    // EVOLVE-BLOCK-START
    function signed [15:0] seqf;
        input [8:0] k;
        begin
            case (k)
{sarr}
                default: seqf = 16'sd0;
            endcase
        end
    endfunction
    reg signed [15:0] di [0:{L - 1}];
    reg signed [15:0] dq [0:{L - 1}];
    integer k;
    reg signed [23:0] acci, accq;

    // c[n] = Σ_k S[k]·r(n−k)：当前输入为 r(n)，di[k−1] 为 r(n−k)
    always @(*) begin
        acci = i_in * seqf(9'd0);
        accq = q_in * seqf(9'd0);
        for (k = 1; k < {L}; k = k + 1) begin
            acci = acci + (di[k-1] * seqf(k[8:0]));
            accq = accq + (dq[k-1] * seqf(k[8:0]));
        end
    end

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (k = 0; k < {L}; k = k + 1) begin di[k] <= 0; dq[k] <= 0; end
            out_valid <= 1'b0; c_re <= 0; c_im <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                for (k = {L} - 1; k > 0; k = k - 1) begin
                    di[k] <= di[k-1]; dq[k] <= dq[k-1];
                end
                di[0] <= i_in; dq[0] <= q_in;
                c_re <= acci; c_im <= accq;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""


# ---------------------------------------------------------------------------
# FIR：直接型（参数化抽头）
# ---------------------------------------------------------------------------

def fir_baseline(taps: int, h: list) -> str:
    hq = [int(round(x * 32768)) for x in h]
    harr = "\n".join(
        f"                8'd{k}: hf = " + (f"16'sd{v}" if v >= 0 else f"-16'sd{abs(v)}") + ";"
        for k, v in enumerate(hq))
    return f"""// 参数化基线：直接型 FIR（{taps} 抽头，朴素）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] x,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [39:0] y
);
    // EVOLVE-BLOCK-START
    function signed [15:0] hf;
        input [7:0] k;
        begin
            case (k)
{harr}
                default: hf = 16'sd0;
            endcase
        end
    endfunction
    reg signed [15:0] d [0:{taps - 1}];
    integer k;
    reg signed [39:0] acc;
    // y[n] = Σ_k h[k]·x(n−k)：当前输入为 x(n)，d[k−1] 为 x(n−k)
    always @(*) begin
        acc = x * hf(8'd0);
        for (k = 1; k < {taps}; k = k + 1)
            acc = acc + (d[k-1] * hf(k[7:0]));
    end
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (k = 0; k < {taps}; k = k + 1) d[k] <= 0;
            out_valid <= 1'b0; y <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                for (k = {taps} - 1; k > 0; k = k - 1)
                    d[k] <= d[k-1];
                d[0] <= x;
                y <= acc;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""


# ---------------------------------------------------------------------------
# NCO：相位累加 + 最近邻表
# ---------------------------------------------------------------------------

def nco_baseline(pw: int, tbl: int) -> str:
    N = tbl
    tbl_bits = int(math.log2(N))
    entries = []
    for k in range(N):
        v = math.sin(2 * math.pi * k / N) * 32768
        v = max(-32767, min(32767, round(v)))
        entries.append(f"{tbl_bits}'d{k}: T = " + (f"-16'sd{abs(v)}" if v < 0 else f"16'sd{v}"))
    # 打包每行 4 项
    case_body = "\n".join(f"                {e};" for e in entries)
    return f"""// 参数化基线：NCO 相位累加 + {N} 点最近邻表（朴素）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire [{pw - 1}:0]  fcw,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [15:0] sin_out
);
    // EVOLVE-BLOCK-START
    reg [{pw - 1}:0] phase;
    wire [{pw - 1}:0] pnext = phase + fcw;
    wire [{tbl_bits - 1}:0] idx = pnext[{pw - 1}:{pw - tbl_bits}];

    function signed [15:0] T;
        input [{tbl_bits - 1}:0] k;
        begin
            case (k)
{case_body}
                default: T = 16'sd0;
            endcase
        end
    endfunction

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            phase <= 0; out_valid <= 1'b0; sin_out <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                phase <= pnext;
                sin_out <= T(idx);
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""


# ---------------------------------------------------------------------------
# cmul：4 乘法器（参数化位宽）
# ---------------------------------------------------------------------------

def cmul_baseline(w: int, rnd: str) -> str:
    ow = (2 * w + 1) if rnd == "free" else w
    if rnd == "free":
        satf = ""
    else:
        satf = f"""
    function signed [{ow - 1}:0] satw;
        input signed [{2 * w + 1}:0] v;
        begin
            if (v > {2 * w + 1}'sd{(1 << (ow - 1)) - 1}) satw = -{ow}'sd{(1 << (ow - 1)) - 1};
            else if (v < -{2 * w + 1}'sd{(1 << (ow - 1))}) satw = {ow}'sd{(1 << (ow - 1))};
            else satw = v[{ow - 1}:0];
        end
    endfunction"""
    return f"""// 参数化基线：复数乘法 4 乘法器（{w} 位，{rnd}）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [{w - 1}:0] a,
    input  wire signed [{w - 1}:0] b,
    input  wire signed [{w - 1}:0] c,
    input  wire signed [{w - 1}:0] d,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [{ow - 1}:0] y_re,
    output reg  signed [{ow - 1}:0] y_im
);
    // EVOLVE-BLOCK-START
{satf}
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; y_re <= 0; y_im <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                {"y_re <= a * c - b * d; y_im <= a * d + b * c;" if rnd == "free" else
                 (f"y_re <= satw((a * c - b * d) >>> {w - 1}); y_im <= satw((a * d + b * c) >>> {w - 1});" if rnd == "trunc" else
                  f"y_re <= satw((a * c - b * d + {2 ** (w - 2)}) >>> {w - 1}); y_im <= satw((a * d + b * c + {2 ** (w - 2)}) >>> {w - 1});")}
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""


# ---------------------------------------------------------------------------
# LLR：max-log 逐比特（参数化阶数，v4 结构）
#
# 与 golden（精确 LSE）同口径的 max-log 基线，数值等价轻量结构：
#   min_s (y-s)² = (min_s |y-s|)²（非负整数上平方单调）
#   m1 - m0 = d1² - d0² = (d1-d0)(d1+d0)   → 每轴 M 个 abs 距离 + 每 bit 1 个乘法
# （v3 直控平方版在 64QAM 以上 yosys ice40 综合超时，勿回退）
# 位宽（bits≤4 全适用）：|y-A| ≤ 32768+61440 < 2^17 → ad 18 位无符号；
# d1+d0 < 2^18 → 19 位有符号非负；pd = 19×19 → 38 位；Q8.24 >> 16 → Q8.8 饱和。
# ---------------------------------------------------------------------------

def _gray_amp(val_b: int, nb: int) -> int:
    """binary→Gray→奇数格点（与 evaluator._axis_gray_map 一致，返回整数格点值）"""
    g = val_b ^ (val_b >> 1)
    amp, sign = 0, 1
    for k in range(nb):
        bit = (g >> (nb - 1 - k)) & 1
        if k == 0:
            sign = -1 if bit else 1
        else:
            amp |= bit << (nb - 1 - k)
    return sign * (2 * amp + 1)


def _min_tree(names: list) -> str:
    """平衡 minu18 嵌套表达式（单元素直通）"""
    if len(names) == 1:
        return names[0]
    mid = len(names) // 2
    a = _min_tree(names[:mid])
    b = _min_tree(names[mid:])
    return f"minu18({a}, {b})"


def llr_baseline(bits: int) -> str:
    nbits = 2 * bits
    M = 1 << bits
    mod_name = {1: "QPSK", 2: "16QAM", 3: "64QAM", 4: "256QAM"}[bits]
    # 格点常量（Gray level 0..M-1 → ±1/±3/... Q4.12）
    a_lines = []
    for lv in range(M):
        v = _gray_amp(lv, bits) * 4096
        lit = f"-20'sd{abs(v)}" if v < 0 else f"20'sd{v}"
        a_lines.append(f"    wire signed [19:0] A{lv} = {lit};")
    adecl = "\n".join(a_lines)
    # 每轴 M 个绝对距离
    ad_lines = []
    for ax in ("i", "q"):
        for lv in range(M):
            ad_lines.append(
                f"    wire signed [19:0] dy{ax}{lv} = y{ax} - A{lv};"
                f"  wire signed [19:0] ndy{ax}{lv} = -dy{ax}{lv};"
            )
        for lv in range(M):
            ad_lines.append(
                f"    wire [17:0] ad{ax}{lv} = "
                f"dy{ax}{lv}[19] ? ndy{ax}{lv}[17:0] : dy{ax}{lv}[17:0];"
            )
    addecl = "\n".join(ad_lines)
    # 每 bit 距离差块（I 轴 bit 在前，与 golden 分桶约定一致）
    blk = []
    for b in range(bits):
        s0 = [lv for lv in range(M) if ((lv >> (bits - 1 - b)) & 1) == 0]
        s1 = [lv for lv in range(M) if ((lv >> (bits - 1 - b)) & 1) == 1]
        for ai, ax in ((0, "i"), (1, "q")):
            t = b + ai * bits  # llr 输出索引
            d0 = _min_tree([f"ad{ax}{lv}" for lv in s0])
            d1 = _min_tree([f"ad{ax}{lv}" for lv in s1])
            tag = f"{ax}{b}"
            blk.append(f"    // {'IQ'[ai]} 轴 bit{b}（S0={s0} S1={s1}）")
            blk.append(f"    wire [17:0] d0_{tag} = {d0};")
            blk.append(f"    wire [17:0] d1_{tag} = {d1};")
            blk.append(
                f"    wire signed [18:0] dd_{tag} = $signed({{1'b0, d1_{tag}}})"
                f" - $signed({{1'b0, d0_{tag}}});"
            )
            blk.append(
                f"    wire signed [18:0] ds_{tag} = $signed({{1'b0, d1_{tag}}})"
                f" + $signed({{1'b0, d0_{tag}}});"
            )
            blk.append(f"    wire signed [37:0] pd_{tag} = dd_{tag} * ds_{tag};")
            blk.append(f"    wire signed [37:0] lq_{tag} = pd_{tag} >>> 16;  // Q8.24 → Q8.8")
            blk.append(
                f"    wire signed [15:0] llrv_{tag} = (lq_{tag} > 38'sd32767) ? 16'sd32767 :"
                f" (lq_{tag} < -38'sd32768) ? -16'sd32768 : lq_{tag}[15:0];"
            )
    bitdecl = "\n".join(blk)
    outs = ", ".join(f"output reg signed [15:0] llr{i}" for i in range(nbits))
    rst_zeros = "\n".join(f"            llr{i} <= 16'sd0;" for i in range(nbits))
    regs = "\n".join(f"                llr{i} <= llrv_{'iq'[i // bits]}{i % bits};" for i in range(nbits))
    return f"""// 参数化基线：{mod_name} max-log LLR（v4：abs 距离 + (d1-d0)(d1+d0)，朴素）
// 2σ²归一 Q8.8 与 golden 同口径；距离差 = m1 - m0（bit=0 证据强 → 正 LLR）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    {outs}
);
    // EVOLVE-BLOCK-START
    function [17:0] minu18;
        input [17:0] a;
        input [17:0] b;
        begin
            minu18 = (a < b) ? a : b;
        end
    endfunction
    // 拼接是无符号上下文：符号扩展必须显式补满位（16→20）
    wire signed [19:0] yi = {{{{4{{i_in[15]}}}}, i_in}};
    wire signed [19:0] yq = {{{{4{{q_in[15]}}}}, q_in}};
{adecl}
{addecl}
{bitdecl}

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
{rst_zeros}
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
{regs}
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""


# ---------------------------------------------------------------------------
# 主：遍历实例生成基线
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="每族只生成 1 个代表实例")
    args = ap.parse_args()

    count = 0
    for fam_dir in sorted(TASKS.iterdir()):
        insts = sorted(d for d in fam_dir.iterdir() if (d / "task.yaml").exists())
        if args.sample:
            insts = insts[:1]
        for inst_dir in insts:
            ty = yaml.safe_load((inst_dir / "task.yaml").read_text())
            name = ty["task"]
            params = ty["metric"]["params"]
            if name.startswith("crc"):
                text = crc_baseline(int(params["width"]), params["poly"])
            elif name.startswith("atan2"):
                text = atan2_baseline(int(params["width"]))
            elif name.startswith("mfilt"):
                text = mfilt_baseline2(int(params["length"]), params["sequence"])
            elif name.startswith("fir_"):
                text = fir_baseline(int(params["taps"]), params["coefficients"])
            elif name.startswith("nco_"):
                text = nco_baseline(int(params["phase_bits"]), int(params["baseline_table"]))
            elif name.startswith("cmul_"):
                text = cmul_baseline(int(params["width"]), params["rounding"])
            elif name.startswith("llr_"):
                text = llr_baseline(int(params["bits"]))
            else:
                continue
            out = OUT / fam_dir.name / name
            out.mkdir(parents=True, exist_ok=True)
            (out / "initial_program.v").write_text(text)
            count += 1
    print(f"baselines: {count} -> {OUT}/<family>/<instance>/initial_program.v")


if __name__ == "__main__":
    main()
