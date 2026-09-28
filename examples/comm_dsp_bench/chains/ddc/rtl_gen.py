"""DDC 候选链参数化 Verilog 生成器（S2 综合面积口径）。

位语义与 fixed_chain.py 整数模型逐位对应：
  NCO   : 32 位相位累加器 → 高 B 位 MSB 对齐 16 位相位码 → tpl_cordic 同款
          四分之一波 LUT（_table）或展开 CORDIC（19/18 位自然回绕）
  混频   : 4 个 12×16 乘积 →（可选 pd 丢位，rne=half-up/trunc）→ 求和
          → >>11（同模式舍入）→ 饱和 16 位
  FIR   : pd=0 对称预加（17 乘/通道，整数域与逐抽头位恒等）；pd>0 逐抽头
          乘积丢位求和（33 乘/通道）→ 精确累加 →（可选 wacc 饱和）
          → >>(wc−2)（同模式舍入）→ 饱和 16 位
  抽取   : 输出使能计数器（R 分频，无额外数值操作）
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parent.parent.parent
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

from certfit import tpl_cordic


# ---------------------------------------------------------------------------
# NCO
# ---------------------------------------------------------------------------

def _lut_rom(depth: int, tag: str) -> list:
    """四分之一波 ROM case 语句（内容 = tpl_cordic._table）。"""
    S = depth // 4
    T = tpl_cordic._table(depth)
    aw = max(1, (S + 1).bit_length())
    lines = [f"reg signed [15:0] rom_{tag};", "always @(*) begin",
             f"    case (mi_{tag})"]
    for k in range(S + 2):
        lines.append(f"        {aw}'d{k}: rom_{tag} = 16'sd{int(T[k])};")
    lines += ["        default: rom_%s = 16'sd0;" % tag, "    endcase", "end"]
    return lines, aw


def _lut_interp(depth: int, order: str, tag: str) -> list:
    """插值路径（linear/quad），与 _emul_lut 逐位对应。"""
    S = depth // 4
    fb = 14 - int(math.log2(S))
    aw = max(1, (S + 1).bit_length())
    lines = [
        f"reg signed [15:0] rom1_{tag};",
        "always @(*) begin",
        f"    case (mi_{tag} + 1)",
    ]
    T = tpl_cordic._table(depth)
    for k in range(S + 2):
        lines.append(f"        {aw}'d{k}: rom1_{tag} = 16'sd{int(T[k])};")
    lines += ["        default: rom1_%s = 16'sd0;" % tag, "    endcase", "end"]
    lines += [
        f"wire signed [15:0] a1_{tag} = rom1_{tag} - rom_{tag};",
        f"wire signed [{16 + fb}:0] lt_{tag} = a1_{tag} * {{1'b0, d_{tag}}};",
        f"wire signed [17:0] lr_{tag} = {{2'b0, rom_{tag}}} + (lt_{tag} >>> {fb})"
        f" + {{17'd0, (lt_{tag} >>> {fb - 1}) & 1'b1}};",
    ]
    if order == "quad":
        lines += [
            f"reg signed [15:0] rom2_{tag};",
            "always @(*) begin",
            f"    case (mi_{tag} + 2)",
        ]
        for k in range(S + 2):
            lines.append(f"        {aw}'d{k}: rom2_{tag} = 16'sd{int(T[k])};")
        lines += ["        default: rom2_%s = 16'sd0;" % tag, "    endcase", "end"]
        lines += [
            f"wire signed [16:0] a2f_{tag} = rom2_{tag} - 2 * rom1_{tag} + rom_{tag};",
            f"wire signed [7:0] a2_{tag} = a2f_{tag}[7:0];   // 模型复刻的 a2[7:0] 截断",
            f"wire signed [{2 * fb + 1}:0] qw_{tag} = {{1'b0, d_{tag}}} * ({{1'b0, d_{tag}}} - {1 << fb});",
            f"wire signed [{8 + 2 * fb + 1}:0] t2_{tag} = a2_{tag} * qw_{tag};",
            f"wire signed [17:0] qr_{tag} = (t2_{tag} >>> {2 * fb + 1})"
            f" + {{17'd0, (t2_{tag} >>> {2 * fb}) & 1'b1}};",
            f"wire signed [17:0] yw_{tag} = lr_{tag} + qr_{tag};",
        ]
    else:
        lines += [f"wire signed [17:0] yw_{tag} = lr_{tag};"]
    return lines


def _lut_wave(tag: str, depth: int, order: str, zsrc: str) -> list:
    """一条正交支路：16 位相位码 → 表查 + 插值 + 象限折叠裁剪。"""
    S = depth // 4
    fb = 14 - int(math.log2(S))
    aw = max(1, (S + 1).bit_length())
    lines = [
        f"wire        ngs_{tag};",
        f"wire [14:0] prs_{tag};",
        f"wire [14:0] ms_{tag};",
        f"wire [{aw-1}:0] mi_{tag};",
        f"wire [{fb-1}:0] d_{tag};",
        f"assign ngs_{tag} = {zsrc}[15];",
        f"assign prs_{tag} = {zsrc}[14:0];",
        f"wire [15:0] msf_{tag} = 16'd32768 - {{1'b0, prs_{tag}}};",
        f"assign ms_{tag} = prs_{tag}[14] ? msf_{tag}[14:0] : {{1'b0, prs_{tag}[13:0]}};",
        f"assign mi_{tag} = ms_{tag} >> {fb};",
        f"assign d_{tag} = ms_{tag}[{fb-1}:0];",
    ]
    rom_lines, _ = _lut_rom(depth, tag)
    lines += rom_lines
    if order == "nearest":
        lines += [f"wire signed [17:0] yw_{tag} = {{2'b0, rom_{tag}}};"]
    else:
        lines += _lut_interp(depth, order, tag)
    lines += [
        f"wire signed [17:0] yn_{tag} = ngs_{tag} ? -yw_{tag} : yw_{tag};",
        f"wire signed [15:0] out_{tag} = (yn_{tag} > 32767) ? 16'sd32767 :"
        f" ((yn_{tag} < -32768) ? -16'sd32768 : yn_{tag}[15:0]);",
    ]
    return lines


def _gen_nco_lut(nco_cfg: dict, fcw: int) -> list:
    b = int(nco_cfg["phase_bits"])
    depth, order = int(nco_cfg["depth"]), nco_cfg["order"]
    lines = [
        "    // ---- NCO：32 位相位累加器 + 相位截断 ----",
        "    reg [31:0] phase_acc;",
        f"    localparam [31:0] PHASE_FCW = 32'h{fcw & 0xFFFFFFFF:08x};",
        f"    localparam [31:0] PHASE_INIT = 32'h{(0x100000000 - fcw) & 0xFFFFFFFF:08x};  // -FCW：首个递增后为 0",
        "    always @(posedge clk) begin",
        "        if (!rst_n) phase_acc <= PHASE_INIT;",
        "        else phase_acc <= phase_acc + PHASE_FCW;",
        "    end",
        f"    wire [{b-1}:0] phase_w = phase_acc[31:{32-b}];",
        f"    wire [15:0] z_sin = {{phase_w, {{{16-b}{{1'b0}}}}}};",
        "    wire [15:0] z_cos = z_sin + 16'd16384;",
        "    // ---- 四分之一波 LUT + 插值 ----",
    ]
    lines += ["    " + ln for ln in _lut_wave("s", depth, order, "z_sin")]
    lines += ["    " + ln for ln in _lut_wave("c", depth, order, "z_cos")]
    lines += [
        "    wire signed [15:0] nco_sin = out_s;",
        "    wire signed [15:0] nco_cos = out_c;",
    ]
    return lines


def _gen_nco_cordic(nco_cfg: dict, fcw: int) -> list:
    b = int(nco_cfg["phase_bits"])
    stages = int(nco_cfg["stages"])
    alpha = [round(math.atan(2.0 ** -i) * 65536 / math.pi) for i in range(stages)]
    lines = [
        "    // ---- NCO：32 位相位累加器 + 相位截断 ----",
        "    reg [31:0] phase_acc;",
        f"    localparam [31:0] PHASE_FCW = 32'h{fcw & 0xFFFFFFFF:08x};",
        f"    localparam [31:0] PHASE_INIT = 32'h{(0x100000000 - fcw) & 0xFFFFFFFF:08x};  // -FCW：首个递增后为 0",
        "    always @(posedge clk) begin",
        "        if (!rst_n) phase_acc <= PHASE_INIT;",
        "        else phase_acc <= phase_acc + PHASE_FCW;",
        "    end",
        f"    wire [{b-1}:0] phase_w = phase_acc[31:{32-b}];",
        f"    wire [15:0] z16 = {{phase_w, {{{16-b}{{1'b0}}}}}};",
        "    // ---- 展开 CORDIC（za0 = 8·z mod 2^18；x/y 19 位自然回绕）----",
        "    // 相位码转有符号域（s = z16 的 16 位补码值），与 Python 侧一致",
        "    wire signed [16:0] s_w = $signed(z16);",
        "    wire signed [17:0] z2 = $signed({z16, 1'b0});    // 2s（17 位符号保持）",
        "    wire        hi_c = (s_w > 17'sd16384);            // 严格大于（16384 不折叠，对拍校准）",
        "    wire        lo_c = (s_w < -17'sd16384);",
        "    wire signed [17:0] z_0 = hi_c ? (z2 - 18'sd65536) : (lo_c ? (z2 + 18'sd65536) : z2);",
        "    wire        neg_c = hi_c | lo_c;",
        "    wire signed [18:0] x_0 = 19'sd79594;",
        "    wire signed [18:0] y_0 = 19'sd0;",
    ]
    for i in range(stages):
        lines += [
            # Python: zpos = (za >= 0)；RTL 用符号位 zp = (za < 0)，臂与 Python 相反
            f"    wire        zp{i} = z_{i}[17];",
            f"    wire signed [18:0] x_{i+1} = zp{i} ? (x_{i} + (y_{i} >>> {i})) : (x_{i} - (y_{i} >>> {i}));",
            f"    wire signed [18:0] y_{i+1} = zp{i} ? (y_{i} - (x_{i} >>> {i})) : (y_{i} + (x_{i} >>> {i}));",
            f"    wire signed [17:0] z_{i+1} = zp{i} ? (z_{i} + 18'sd{alpha[i]}) : (z_{i} - 18'sd{alpha[i]});",
        ]
    n = stages
    lines += [
        f"    wire signed [18:0] sin_r = (y_{n} + 19'sd2) >>> 2;",
        f"    wire signed [18:0] cos_r = (x_{n} + 19'sd2) >>> 2;",
        "    wire signed [17:0] sin_n = neg_c ? -sin_r : sin_r;",
        "    wire signed [17:0] cos_n = neg_c ? -cos_r : cos_r;",
        "    wire signed [15:0] nco_sin = (sin_n > 32767) ? 16'sd32767 :"
        " ((sin_n < -32768) ? -16'sd32768 : sin_n[15:0]);",
        "    wire signed [15:0] nco_cos = (cos_n > 32767) ? 16'sd32767 :"
        " ((cos_n < -32768) ? -16'sd32768 : cos_n[15:0]);",
    ]
    return lines


# ---------------------------------------------------------------------------
# 混频
# ---------------------------------------------------------------------------

def _gen_mixer(cmul_cfg: dict) -> list:
    pd, mode = int(cmul_cfg["prod_drop"]), cmul_cfg["mode"]
    lines = ["    // ---- 输入寄存 ----",
             "    reg signed [11:0] i_r, q_r;",
             "    always @(posedge clk) begin",
             "        if (!rst_n) begin i_r <= 12'sd0; q_r <= 12'sd0; end",
             "        else begin i_r <= i_in; q_r <= q_in; end",
             "    end",
             "    // ---- 复数混频：12×16 乘积 → 丢位 → 求和 → >>11 → 饱和 ----"]
    for tag, (a, b) in {"pic": ("i_r", "nco_cos"), "qsc": ("q_r", "nco_sin"),
                        "isc": ("i_r", "nco_sin"), "qcc": ("q_r", "nco_cos")}.items():
        lines.append(f"    wire signed [27:0] {tag} = $signed({a}) * $signed({b});")
    if pd > 0:
        half = 1 << (pd - 1) if mode == "rne" else 0
        for tag in ("pic", "qsc", "isc", "qcc"):
            if mode == "rne":
                lines.append(f"    wire signed [27:0] {tag}_d = (({tag} + 28'sd{half}) >>> {pd}) <<< {pd};")
            else:
                lines.append(f"    wire signed [27:0] {tag}_d = ({tag} >>> {pd}) <<< {pd};")
        src = {t: f"{t}_d" for t in ("pic", "qsc", "isc", "qcc")}
    else:
        src = {t: t for t in ("pic", "qsc", "isc", "qcc")}
    lines += [
        f"    wire signed [28:0] re_pre = {src['pic']} + {src['qsc']};",
        f"    wire signed [28:0] im_pre = {src['qcc']} - {src['isc']};",
    ]
    for tag, pre in (("mix_re", "re_pre"), ("mix_im", "im_pre")):
        if mode == "rne":
            lines.append(f"    wire signed [28:0] {pre}_r = {pre} + 29'sd1024;")
        else:
            lines.append(f"    wire signed [28:0] {pre}_r = {pre};")
        lines += [
            f"    wire signed [17:0] {tag}_sh = {pre}_r >>> 11;",
            f"    wire signed [15:0] {tag}_sat = ({tag}_sh > 32767) ? 16'sd32767 :"
            f" (({tag}_sh < -32768) ? -16'sd32768 : {tag}_sh[15:0]);",
        ]
    lines += [
        "    // 混频输出寄存",
        "    reg signed [15:0] mre_r, mim_r;",
        "    always @(posedge clk) begin",
        "        if (!rst_n) begin mre_r <= 0; mim_r <= 0; end",
        "        else begin mre_r <= mix_re_sat; mim_r <= mix_im_sat; end",
        "    end",
    ]
    return lines


# ---------------------------------------------------------------------------
# FIR
# ---------------------------------------------------------------------------

def _gen_fir(fir_cfg: dict) -> list:
    wc, wacc, pd, mode = (int(fir_cfg["wc"]), int(fir_cfg.get("wacc", 0)),
                          int(fir_cfg["prod_drop"]), fir_cfg["mode"])
    hq = fir_cfg["hq"]
    taps = len(hq)
    half_out = 1 << (wc - 3)  # >>（wc−2）的 rne 半值
    lines = [
        f"    // ---- FIR：{taps} 抽头对称，wc={wc} wacc={wacc} pd={pd} mode={mode} ----",
        f"    localparam signed [{wc-1}:0] H0 = -{abs(int(hq[0])) if hq[0] < 0 else 0};" ,
    ]
    # 系数常量（逐 tap）
    lines = [f"    // ---- FIR：{taps} 抽头对称，wc={wc} wacc={wacc} pd={pd} mode={mode} ----"]
    for k, h in enumerate(hq):
        v = int(h) & ((1 << wc) - 1)
        lines.append(f"    localparam [{wc-1}:0] HK{k} = {wc}'h{v:x};")
    # 延迟线（mixer 输出 16 位，延迟 1..taps−1）
    lines += [
        f"    reg signed [15:0] line_re [0:{taps-2}];",
        "    integer li;",
        "    always @(posedge clk) begin",
        "        if (!rst_n) begin",
        f"            for (li = 0; li < {taps-1}; li = li + 1) line_re[li] <= 16'sd0;",
        "        end else begin",
        "            line_re[0] <= mre_r;",
        f"            for (li = 1; li < {taps-1}; li = li + 1) line_re[li] <= line_re[li-1];",
        "        end",
        "    end",
        f"    reg signed [15:0] line_im [0:{taps-2}];",
        "    always @(posedge clk) begin",
        "        if (!rst_n) begin",
        f"            for (li = 0; li < {taps-1}; li = li + 1) line_im[li] <= 16'sd0;",
        "        end else begin",
        "            line_im[0] <= mim_r;",
        f"            for (li = 1; li < {taps-1}; li = li + 1) line_im[li] <= line_im[li-1];",
        "        end",
        "    end",
    ]
    for ch, mreg in (("re", "mre_r"), ("im", "mim_r")):
        aw = 16 + wc + (6 if pd == 0 else 6)
        if pd == 0:
            # 对称预加：pre[k] = x[n−k] + x[n−(taps−1−k)]，k=0..taps/2−1；中心单独
            half_taps = taps // 2
            for k in range(half_taps):
                if k == 0:
                    lines.append(f"    wire signed [16:0] pre_{ch}{k} = {mreg} + line_{ch}[{taps-2}];")
                else:
                    lines.append(
                        f"    wire signed [16:0] pre_{ch}{k} = line_{ch}[{k-1}] + line_{ch}[{taps-2-k}];")
            lines.append(
                f"    wire signed [{16 + wc - 1}:0] pr_{ch}c = $signed(line_{ch}[{taps // 2 - 1}]) * $signed(HK{taps // 2});")
            terms = [f"$signed(HK{k}) * pre_{ch}{k}" for k in range(half_taps)]
            lines.append(
                f"    wire signed [{17 + wc + 4}:0] acc_{ch} = pr_{ch}c + "
                + " + ".join(terms) + ";")
        else:
            terms = []
            for k in range(taps):
                if k == 0:
                    xw = mreg
                else:
                    xw = f"line_{ch}[{k-1}]"
                lines.append(
                    f"    wire signed [{16 + wc - 1}:0] prod_{ch}{k} = $signed({xw}) * $signed(HK{k});")
                if mode == "rne":
                    lines.append(
                        f"    wire signed [{16 + wc - 1}:0] prod_{ch}{k}_d = ((prod_{ch}{k} + {16 + wc}'sd{1 << (pd - 1)}) >>> {pd}) <<< {pd};")
                else:
                    lines.append(
                        f"    wire signed [{16 + wc - 1}:0] prod_{ch}{k}_d = (prod_{ch}{k} >>> {pd}) <<< {pd};")
                terms.append(f"prod_{ch}{k}_d")
            lines.append(
                f"    wire signed [{16 + wc + 5}:0] acc_{ch} = " + " + ".join(terms) + ";")
        # wacc 饱和
        if wacc:
            hi = (1 << (wacc - 1)) - 1
            lo = 1 << (wacc - 1)
            wa = 16 + wc + 6
            lines += [
                f"    wire signed [{16 + wc + 5}:0] accs_{ch} = (acc_{ch} > {wa}'sd{hi}) ? {wa}'sd{hi} :"
                f" ((acc_{ch} < -{wa}'sd{lo}) ? -{wa}'sd{lo} : acc_{ch});",
            ]
        else:
            lines.append(f"    wire signed [{16 + wc + 5}:0] accs_{ch} = acc_{ch};")
        # 输出舍入 + 饱和 16 位
        if mode == "rne":
            lines.append(
                f"    wire signed [{16 + wc + 5}:0] accq_{ch} = accs_{ch} + {16 + wc + 6}'sd{half_out};")
        else:
            lines.append(
                f"    wire signed [{16 + wc + 5}:0] accq_{ch} = accs_{ch};")
        lines += [
            f"    wire signed [17:0] ysh_{ch} = accq_{ch} >>> {wc - 2};",
            f"    wire signed [15:0] y_{ch}_sat = (ysh_{ch} > 32767) ? 16'sd32767 :"
            f" ((ysh_{ch} < -32768) ? -16'sd32768 : ysh_{ch}[15:0]);",
        ]
    lines += ["    // ---- 抽取：R 分频输出使能 ----"]
    return lines


PHASE_FCW_PLACEHOLDER = "__PHASE_FCW__"


def gen_ddc_verilog(nco_cfg: dict, fir_cfg: dict, cmul_cfg: dict,
                    fcw: int = 0x30000000) -> str:
    """生成一个候选组合的完整 DDC 顶层（module top，II=1，R:1 抽取）。"""
    if nco_cfg["algo"] == "lut":
        nco_lines = _gen_nco_lut(nco_cfg, fcw)
    else:
        nco_lines = _gen_nco_cordic(nco_cfg, fcw)
    mixer_lines = _gen_mixer(cmul_cfg)
    fir_lines = _gen_fir(fir_cfg)
    body = "\n".join(nco_lines + mixer_lines + fir_lines)
    return f"""// DDC 候选链 nco={nco_cfg['name']} fir={fir_cfg['name']} cmul={cmul_cfg['name']}
// 由 chains/ddc/rtl_gen.py 生成；位语义对应 fixed_chain.run_candidate
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,   // 面积口径忽略握手
    input  wire signed [11:0] i_in,
    input  wire signed [11:0] q_in,
    output reg  signed [15:0] y_re,
    output reg  signed [15:0] y_im,
    output reg                out_valid
);
{body}
    // ---- 抽取使能：在接受沿按样本序号（n_cnt 自增前的值）计算 flag，
    //      经 f0/f1/f2 延迟两级与输出寄存对齐；条件 = 序号为偶（抽取相位）
    //      且 >= 32（N_TAPS-1 裁剪）----
    reg [31:0] n_cnt;
    reg f0, f1;
    always @(posedge clk) begin
        if (!rst_n) begin
            n_cnt <= 32'd0;
            f0 <= 1'b0; f1 <= 1'b0;
            y_re <= 16'sd0; y_im <= 16'sd0; out_valid <= 1'b0;
        end else begin
            n_cnt <= n_cnt + 32'd1;            // 连续样本流契约
            // f0/c−2 与输出寄存 y_re/c−4 的两级差经位精确对拍校准：
            // out_valid(c) 标记 fir(c−4)，fir(c−4) 合法当且仅当序号偶且 ≥32
            f0 <= (n_cnt >= 32) && (n_cnt[0] == 1'b0);
            f1 <= f0;
            y_re <= y_re_sat;
            y_im <= y_im_sat;
            out_valid <= f1;
        end
    end
endmodule
"""
