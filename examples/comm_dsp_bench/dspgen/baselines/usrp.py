"""开源基线：Ettus USRP2 的 DDC 数据通路（CORDIC → 4 阶 CIC → 两级半带 → 缩放 → round_sd），接入链路 A。

外部 RTL（EttusResearch/fpga@287ad57，usrp2/sdr_lib）只作为 Verilog 文本读入，不执行其中任何脚本。
与 ddc_chain.v 的差别：去掉 setting_reg / dsp_rx_glue（主机寄存器），设置值改为常数（综合时可做常数传播）；
MULT18X18S、SRL16E 用行为模型代替。实数输入：I = 输入码左对齐到 24 位，Q = 0（ddc_chain 的 realmode）。
"""
from __future__ import annotations

from pathlib import Path

SRC = Path("/Users/chengzhy/verievolve_untrusted/usrp_ddc_src")
COMMIT = "287ad57430b1dacdce6d793536ff96dc8f630419"
FILES = ["cordic_z24.v", "cordic_stage.v", "clip_reg.v", "clip.v", "sign_extend.v", "cic_strober.v", "cic_decim.v",
         "cic_dec_shifter.v", "small_hb_dec.v", "hb_dec.v", "srl.v", "round.v", "round_sd.v",
         "add2_and_clip_reg.v", "add2_and_clip.v", "acc.v"]
LEAD = 8            # USRP 的 out_valid 要等流水线灌满；补前导零只平移时间原点（见 Iknow 2026-10-12 H1 R=16 说明）
RESET_CYCLES = 32   # 部分流水寄存器只在 enable 低时清零
SCALES = (1 << 14, 1 << 15, 1 << 16, (1 << 17) - 1)

# Xilinx 原语的可综合行为模型（仿真与综合用同一份，语义与原语一致）
SRL = """module SRL16E #(parameter [15:0] INIT = 16'h0000) (output Q, input A0, input A1, input A2, input A3,
                input CE, input CLK, input D);
  reg [15:0] data = INIT;
  assign Q = data[{A3, A2, A1, A0}];
  always @(posedge CLK) if (CE) data <= {data[14:0], D};
endmodule
"""

MULT = """module MULT18X18S (output reg signed [35:0] P, input signed [17:0] A, input signed [17:0] B,
                   input C, input CE, input R);
  always @(posedge C) if (R) P <= 0; else if (CE) P <= A * B;
endmodule
"""


def config(R: int):
    """总抽取 R = cic × (hb1?2:1) × (hb2?2:1)，CIC 倍率 4–128（8 位）。优先两级半带都打开（与 UHD 一致）。"""
    for e1, e2 in ((1, 1), (1, 0), (0, 0)):
        d = (2 if e1 else 1) * (2 if e2 else 1)
        if R % d == 0 and 4 <= R // d <= 128:
            return {"cic": R // d, "hb1": e1, "hb2": e2}
    return None


def wrapper(spec, cfg, phase_inc: int, scale: int, headroom: int = 0) -> str:
    b = spec.input_bits
    W = 24
    return f"""
module top (input wire clk, input wire rst, input wire in_valid, input wire signed [{b - 1}:0] in_i,
            output wire out_valid, output wire signed [15:0] out_i, output wire signed [15:0] out_q);
  localparam WIDTH = {W};
  wire en = ~rst;      // 等价于 ddc_chain 的 ddc_enb：复位期间关闭，各模块据此清零
  // ADC 码放入 24 位前端字：左对齐，可留 headroom 位余量（CORDIC 增益约 1.647，满幅实数输入会在 clip_reg 处削顶）
  wire [WIDTH-1:0] fe_i = {{{{{headroom + 1}{{in_i[{b - 1}]}}}}, in_i[{b - 2}:0], {W - b - headroom}'b0}};
  wire [WIDTH-1:0] fe_q = 0;
  reg [31:0] phase;
  always @(posedge clk) if (rst) phase <= 0; else phase <= phase + 32'd{phase_inc & 0xFFFFFFFF};
  wire [24:0] ci, cq, xi, yi;
  sign_extend #(.bits_in(WIDTH), .bits_out(25)) se_i (.in(fe_i), .out(xi));
  sign_extend #(.bits_in(WIDTH), .bits_out(25)) se_q (.in(fe_q), .out(yi));
  cordic_z24 #(.bitwidth(25)) cordic (.clock(clk), .reset(rst), .enable(en), .xi(xi), .yi(yi),
                                      .zi(phase[31:8]), .xo(ci), .yo(cq), .zo());
  wire [WIDTH-1:0] i_cc, q_cc, i_cic, q_cic, i_hb1, q_hb1, i_hb2, q_hb2;
  clip_reg #(.bits_in(25), .bits_out(WIDTH)) clip_i (.clk(clk), .in(ci), .strobe_in(1'b1), .out(i_cc));
  clip_reg #(.bits_in(25), .bits_out(WIDTH)) clip_q (.clk(clk), .in(cq), .strobe_in(1'b1), .out(q_cc));
  wire strobe_cic, strobe_hb1, strobe_hb2;
  wire [7:0] rate = 8'd{cfg['cic']};
  cic_strober cs (.clock(clk), .reset(rst), .enable(en), .rate(rate), .strobe_fast(1'b1), .strobe_slow(strobe_cic));
  cic_decim #(.bw(WIDTH)) di (.clock(clk), .reset(rst), .enable(en), .rate(rate), .strobe_in(1'b1),
                             .strobe_out(strobe_cic), .signal_in(i_cc), .signal_out(i_cic));
  cic_decim #(.bw(WIDTH)) dq (.clock(clk), .reset(rst), .enable(en), .rate(rate), .strobe_in(1'b1),
                             .strobe_out(strobe_cic), .signal_in(q_cc), .signal_out(q_cic));
  small_hb_dec #(.WIDTH(WIDTH)) h1i (.clk(clk), .rst(rst), .bypass(1'b{1 - cfg['hb1']}), .run(en),
      .stb_in(strobe_cic), .data_in(i_cic), .stb_out(strobe_hb1), .data_out(i_hb1));
  small_hb_dec #(.WIDTH(WIDTH)) h1q (.clk(clk), .rst(rst), .bypass(1'b{1 - cfg['hb1']}), .run(en),
      .stb_in(strobe_cic), .data_in(q_cic), .stb_out(), .data_out(q_hb1));
  wire [8:0] cpi_hb = {cfg['hb1']} ? {{rate, 1'b0}} : {{1'b0, rate}};
  hb_dec #(.WIDTH(WIDTH)) h2i (.clk(clk), .rst(rst), .bypass(1'b{1 - cfg['hb2']}), .run(en), .cpi(cpi_hb),
      .stb_in(strobe_hb1), .data_in(i_hb1), .stb_out(strobe_hb2), .data_out(i_hb2));
  hb_dec #(.WIDTH(WIDTH)) h2q (.clk(clk), .rst(rst), .bypass(1'b{1 - cfg['hb2']}), .run(en), .cpi(cpi_hb),
      .stb_in(strobe_hb1), .data_in(q_hb1), .stb_out(), .data_out(q_hb2));
  wire [17:0] ir, qr;
  round #(.bits_in(WIDTH), .bits_out(18)) ri (.in(i_hb2), .out(ir));
  round #(.bits_in(WIDTH), .bits_out(18)) rq (.in(q_hb2), .out(qr));
  wire [35:0] pi_, pq_;
  wire [17:0] scale = 18'd{scale & 0x3FFFF};
  MULT18X18S mi (.P(pi_), .A(ir), .B(scale), .C(clk), .CE(strobe_hb2), .R(rst));
  MULT18X18S mq (.P(pq_), .A(qr), .B(scale), .C(clk), .CE(strobe_hb2), .R(rst));
  wire [33:0] pri, prq; wire strobe_mult;
  clip_reg #(.bits_in(36), .bits_out(34)) cpi (.clk(clk), .in(pi_), .out(pri), .strobe_in(strobe_hb2), .strobe_out(strobe_mult));
  clip_reg #(.bits_in(36), .bits_out(34)) cpq (.clk(clk), .in(pq_), .out(prq), .strobe_in(strobe_hb2), .strobe_out());
  round_sd #(.WIDTH_IN(34), .WIDTH_OUT(16)) rsi (.clk(clk), .reset(rst), .in(pri), .strobe_in(strobe_mult), .out(out_i), .strobe_out(out_valid));
  round_sd #(.WIDTH_IN(34), .WIDTH_OUT(16)) rsq (.clk(clk), .reset(rst), .in(prq), .strobe_in(strobe_mult), .out(out_q), .strobe_out());
endmodule
"""


def design(spec, cfg, phase_inc, scale, headroom=0):
    src = "\n".join((SRC / f).read_text(errors="replace") for f in FILES)
    return src + "\n" + SRL + MULT + wrapper(spec, cfg, phase_inc, scale, headroom)




def configs(R):
    out = []
    for e1, e2 in ((1, 1), (1, 0), (0, 0)):
        d = (2 if e1 else 1) * (2 if e2 else 1)
        if R % d == 0 and 4 <= R // d <= 128:
            out.append({"cic": R // d, "hb1": e1, "hb2": e2})
    return out


def evaluate_spec(task_name: str, period_ns: float = 2.0, n_stat: int = 30, ppa: bool = True) -> dict:
    """在一个链路 A 规格上评价 USRP：按搜索场景选最好的合法配置与缩放，再做留出、统计复核与 PPA（同一流程）。"""
    from types import SimpleNamespace
    from .. import vlog, ppa_sta
    from ..task import get
    t = get(task_name)
    sp = SimpleNamespace(input_bits=t.interface["in_bits"], r_total=int(t.params["r_total"]), fcw=int(t.params["fcw"]))
    kw = dict(lead=LEAD, reset_cycles=RESET_CYCLES)
    tried = []
    for cfg in configs(sp.r_total):
        for sc in SCALES:
            v = design(sp, cfg, -sp.fcw, sc)
            q = vlog.evaluate(v, task_name, **kw)["quality"]
            tried.append({"cfg": cfg, "scale": sc, "margin": q["snr_margin_db"], "ripple": q["ripple_db"],
                          "snr": [s["snr_db"] for s in q["scenarios"]]})
    best = max(tried, key=lambda r: r["margin"])
    v = design(sp, best["cfg"], -sp.fcw, best["scale"])
    hold = vlog.evaluate(v, task_name, idxs=t.holdout_scenarios, **kw)["quality"]
    stat = vlog.evaluate(v, task_name, idxs=range(100, 100 + n_stat), **kw)["quality"] if n_stat else None
    out = {"task": task_name, "source_commit": COMMIT, "best": best, "tried": tried,
           "holdout": {"passed": hold["passed"], "margin_db": hold["snr_margin_db"],
                       "snr": [s["snr_db"] for s in hold["scenarios"]]},
           "stat": None if stat is None else {"failures": sum(not s["passed"] for s in stat["scenarios"]),
                                              "scenarios": len(stat["scenarios"]),
                                              "snr_min": min(s["snr_db"] for s in stat["scenarios"])}}
    if ppa:
        p = ppa_sta.evaluate_verilog_vcd(v, task_name, scenario=t.search_scenarios[0], period_ns=period_ns, fast=True)
        out["ppa"] = {k: p.get(k) for k in ("status", "area_um2", "cells", "wns_ns", "fmax_mhz", "power_vcd",
                                            "fanout_buffers", "stderr")}
    return out
