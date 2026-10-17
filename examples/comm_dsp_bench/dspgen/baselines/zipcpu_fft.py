"""开源基线：ZipCPU dblclockfft（LGPL，github.com/ZipCPU/dblclockfft）的 64 点 IFFT 级模块，接入链路 C（OFDM 发射）。

只把其 rtl/ 目录下预生成的 Verilog 模块作为设计数据读入，不运行其生成器；各级位宽与旋转因子表按 fftgen.cpp 的规则
由本模块计算并内联（12 位输入：stage_64 12→13、stage_32 13→14、stage_16 14→14、stage_8 14→15、qtrstage 15→15、
laststage 15→16，SHIFT=1；系数 = llround(2^(CWIDTH−2)·cos/sin(+2πk/S))）。

外壳尽量省存储：输入只缓存槽 0..25（bin 38..63），bin 0 在槽 25 补 0，槽 26..51 到达即送入，槽 51 之后补
bin 27..37 的 0 与缓存的 bin 38..63；去掉 ZipCPU 的 bitreverse，末级输出按倒位序地址写入两组 64 项缓冲，与循环前缀
共用存储；ZipCPU 输出为 Σ/4（输入码单位），任务要求 Σ/32，右移 3 位四舍五入并饱和到 12 位。
"""
from __future__ import annotations

import math
import re
from pathlib import Path

SRC = Path("/Users/chengzhy/verievolve_untrusted/zipcpu_fft")
CONFIGS = ((1, 1), (1, 3))       # (OPT_HWMPY, CKPCE)；软件乘法器配置流水过深，2 个填充符号内排不空，不采用


def coeffs(S, cbits):
    out = []
    for k in range(S // 2):
        W = 2 * math.pi * k / S          # inverse: +
        ic = round((1 << (cbits - 2)) * math.cos(W))
        is_ = round((1 << (cbits - 2)) * math.sin(W))
        m = (1 << cbits) - 1
        v = ((ic & m) << cbits) | (is_ & m)
        out.append(f"{v:0{(2 * cbits + 3) // 4}x}")
    return "\n".join(out) + "\n"


def stage_plan(nbitsin=12, N=64):
    import math
    lg = int(math.log2(N)); st = []; nb = nbitsin; ob = nb + 1
    st.append((N, nb, nb + 4, ob, lg - 1)); nb = ob; size = N // 2; lgt = lg - 1; drop = 0
    while size >= 8:
        ob = nb + (0 if drop else 1); st.append((size, nb, nb + 4, ob, lgt - 1)); drop ^= 1; nb = ob; size //= 2; lgt -= 1
    q = (nb, nb + (0 if drop else 1)); drop ^= 1; nb = q[1]
    nout = nbitsin + 1; t = N >> 1
    while t > 4:
        nout += 1; t >>= 2
    if t > 1:
        nout += 1
    last = (nb, min(nb + (0 if drop else 1), nout), 0 if drop else 1)
    return st, q, last


def specialized_stage(S, cbits):
    """fftstage 的一个专用副本：把 $readmemh(COEFFILE) 换成内联初值（便于综合与仿真，不依赖外部文件）。"""
    src = (SRC / "fftstage.v").read_text()
    words = coeffs(S, cbits).split()
    init = "begin\n" + "".join(f"\t\tcmem[{i}] = {2*cbits}'h{w};\n" for i, w in enumerate(words)) + "\tend"
    src = src.replace("module\tfftstage", f"module\tfftstage_{S}", 1).replace("module fftstage", f"module fftstage_{S}", 1)
    src, n = re.subn(r"initial\s+\$readmemh\(COEFFILE,\s*cmem\);", f"initial {init}", src)
    assert n == 1, "readmemh not found"
    return src


def verilog(hwmpy=0, ckpce=1):
    st, (qi, qo), (li, lo, lsh) = stage_plan()
    gap = max(1, ckpce)
    v = ["`default_nettype none",
         "module top(input wire clk, input wire rst, input wire in_valid, input wire signed [11:0] in_i,",
         "  input wire signed [11:0] in_q, output reg out_valid, output reg signed [11:0] out_i, output reg signed [11:0] out_q);",
         "  reg [6:0] s; reg [23:0] abuf [0:25]; reg ce; reg [23:0] smp; reg burst; reg [5:0] bcnt; reg [1:0] gc;",
         "  always @(posedge clk) begin",
         "    if (rst) begin s <= 0; ce <= 0; smp <= 0; burst <= 0; bcnt <= 0; gc <= 0; end",
         "    else begin",
         "      ce <= 0;",
         "      if (in_valid) begin",
         "        if (s < 26) abuf[s[4:0]] <= {in_i, in_q};",
         "        if (s == 25) begin ce <= 1; smp <= 24'd0; end",
         "        else if (s >= 26 && s <= 51) begin ce <= 1; smp <= {in_i, in_q}; end",
         f"        if (s == 51) begin burst <= 1; bcnt <= 0; gc <= {gap - 1}; end",
         "        s <= (s == 79) ? 7'd0 : s + 7'd1;",
         "      end else if (burst) begin",
         "        if (gc == 0) begin",
         "          ce <= 1; smp <= (bcnt < 11) ? 24'd0 : abuf[bcnt - 6'd11];",
         f"          gc <= {gap - 1}; bcnt <= bcnt + 6'd1; if (bcnt == 36) burst <= 0;",
         "        end else gc <= gc - 2'd1;",
         "      end",
         "    end",
         "  end"]
    prev_d, prev_s = "smp", "!rst"
    for (S, iw, cw, ow, ls) in st:
        v += [f"  wire w_s{S}; wire [{2*ow-1}:0] w_d{S};",
              f"  fftstage_{S} #(.IWIDTH({iw}), .CWIDTH({cw}), .OWIDTH({ow}), .LGSPAN({ls}), .BFLYSHIFT(0), "
              f".OPT_HWMPY({hwmpy}), .CKPCE({ckpce})) stage_{S} (.i_clk(clk), .i_reset(rst), .i_ce(ce), "
              f".i_sync({prev_s}), .i_data({prev_d}), .o_data(w_d{S}), .o_sync(w_s{S}));"]
        prev_d, prev_s = f"w_d{S}", f"w_s{S}"
    v += [f"  wire w_s4; wire [{2*qo-1}:0] w_d4;",
          f"  qtrstage #(.IWIDTH({qi}), .OWIDTH({qo}), .LGWIDTH(6), .INVERSE(1), .SHIFT(0)) stage_4 (.i_clk(clk), "
          f".i_reset(rst), .i_ce(ce), .i_sync({prev_s}), .i_data({prev_d}), .o_data(w_d4), .o_sync(w_s4));",
          f"  wire w_s2; wire [{2*lo-1}:0] w_d2;",
          f"  laststage #(.IWIDTH({qo}), .OWIDTH({lo}), .SHIFT({lsh})) stage_2 (.i_clk(clk), .i_reset(rst), .i_ce(ce), "
          ".i_sync(w_s4), .i_val(w_d4), .o_val(w_d2), .o_sync(w_s2));",
          # 末级输出：倒位序，第 j 个对应 bin bitrev6(j)；缩放 /8 四舍五入并饱和到 12 位
          "  reg ce_d; always @(posedge clk) ce_d <= rst ? 1'b0 : ce;",
          f"  wire signed [{lo-1}:0] zr = w_d2[{2*lo-1}:{lo}], zi = w_d2[{lo-1}:0];",
          f"  wire signed [{lo-3}:0] rr = (zr + {lo}'sd4) >>> 3, ri = (zi + {lo}'sd4) >>> 3;",
          "  function [11:0] sat12(input signed [" + str(lo - 3) + ":0] x);",
          "    sat12 = (x > 2047) ? 12'h7ff : (x < -2048) ? 12'h800 : x[11:0];",
          "  endfunction",
          "  reg [23:0] obuf [0:127]; reg [5:0] j; reg wb; reg started; reg rdy; reg rbank;",
          "  wire [5:0] jn = started ? j + 6'd1 : 6'd0;   // 只用第一次同步启动，之后按 64 计数（同 ZipCPU 原顶层）",
          "  wire [5:0] rev = {jn[0], jn[1], jn[2], jn[3], jn[4], jn[5]};",
          "  reg [6:0] r; reg rd;",
          "  always @(posedge clk) begin",
          "    if (rst) begin j <= 6'd63; wb <= 0; started <= 0; rdy <= 0; rd <= 0; r <= 0; out_valid <= 0; rbank <= 0; end",
          "    else begin",
          "      rdy <= 0;",
          "      if (ce_d && (started || w_s2)) begin",
          "        started <= 1; j <= jn; obuf[{wb, rev}] <= {sat12(rr), sat12(ri)};",
          "        if (jn == 6'd63) begin rdy <= 1; rbank <= wb; wb <= ~wb; end",
          "      end",
          "      out_valid <= 0;",
          "      if (rdy) begin rd <= 1; r <= 0; end",
          "      else if (rd) begin",
          "        out_valid <= 1;",
          "        {out_i, out_q} <= obuf[{rbank, (r < 16) ? (r[5:0] + 6'd48) : (r[5:0] - 6'd16)}];",
          "        r <= r + 7'd1; if (r == 79) rd <= 0;",
          "      end",
          "    end",
          "  end",
          "endmodule"]
    lib = "".join(specialized_stage(S, cw) + "\n" for (S, iw, cw, ow, ls) in st)
    lib += "".join((SRC / f).read_text() + "\n" for f in ("butterfly.v", "hwbfly.v", "longbimpy.v", "bimpy.v",
                                                           "convround.v", "qtrstage.v", "laststage.v"))
    return "\n".join(v) + "\n" + lib




def evaluate(task_name: str, period_ns: float = 2.5, n_stat: int = 30) -> dict:
    import os
    from .. import vlog, ppa_sta
    from ..task import get
    os.environ.setdefault("VERIEVOLVE_STA", "/Users/chengzhy/verievolve_thirdparty/OpenSTA/build/sta")
    t = get(task_name)
    out = {}
    for hw, ck in CONFIGS:
        v = verilog(hw, ck)
        q = vlog.evaluate(v, task_name)["quality"]
        h = vlog.evaluate(v, task_name, idxs=t.holdout_scenarios)["quality"]
        st = vlog.evaluate(v, task_name, idxs=range(100, 100 + n_stat))["quality"] if n_stat else None
        p = ppa_sta.evaluate_verilog_vcd(v, task_name, scenario=t.search_scenarios[0], period_ns=period_ns, fast=True)
        out[f"hwmpy{hw}_ckpce{ck}"] = {
            "search_margin_db": q["snr_margin_db"], "holdout_passed": h["passed"],
            "evm_db": [-s["snr_db"] for s in q["scenarios"] + h["scenarios"]],
            "stat_failures": None if st is None else sum(not s["passed"] for s in st["scenarios"]),
            "ppa": {k: p.get(k) for k in ("status", "area_um2", "cells", "wns_ns", "fmax_mhz", "power_vcd")}}
    return out
