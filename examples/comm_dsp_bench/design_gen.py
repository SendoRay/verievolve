#!/usr/bin/env python
"""CommDSP-Bench 参数化设计生成器（cordic_sincos 任务）

生成 Verilog 设计族并本地评估，产出设计库 design_library.json：
  - LUT 族：表深 N × 插值阶 {nearest, linear, quad} × 四分之一波折叠
  - CORDIC 族：迭代级数 {12, 14, 16}

用途：消融实验的设计弹药库 / 论文案例分析素材 / golden 对拍基准。
用法：
  python design_gen.py                # 生成 + 评估全部设计
  python design_gen.py --list-only    # 只列设计清单
  python design_gen.py --skip-eval    # 只生成 .v 文件不评估
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
DESIGNS = BENCH / ".designs"


# ---------------------------------------------------------------------------
# LUT + 插值族生成（四分之一波折叠）
# ---------------------------------------------------------------------------

def gen_lut_quarter(N: int, order: str) -> str:
    """四分之一波表 + 指定插值阶。N 为全波表深（QW 表项数 = N/4 + 2）。"""
    S = N // 4                            # QW 段数
    fb = 14 - int(math.log2(S))           # 段内小数位宽（S*2^fb = 2^14 半波相位）
    ib = 16 - fb                          # 段索引位宽
    fdiv = 1 << fb                        # 线性项除数
    tbl = [max(-32767, min(32767, round(math.sin(2 * math.pi * k / N) * 32768)))
           for k in range(S + 2)]
    entries = "\n".join(f"            {ib}'d{k}: Tq = 16'sd{v};" for k, v in enumerate(tbl))

    # 预计算位宽（避免 f-string 内写表达式）
    lt_w = 17 + fb + 2                    # a1(17b) × d 的宽松积宽
    d9w = fb + 1                          # d 零扩展位宽
    qw_w = 2 * fb + 2                     # d*(d-fdiv) 积宽
    t2_w = 8 + qw_w                       # a2[7:0] × qw 积宽
    q_shift = 2 * fb + 1                  # 二次项除数 = 2^q_shift

    # 折叠/索引公共段
    head = f"""    wire [15:0] ps = z;
    wire [15:0] pc = z + 16'd16384;
    wire        ngs = ps[15];
    wire        ngc = pc[15];
    wire [14:0] prs = ps[14:0];
    wire [14:0] prc = pc[14:0];
    wire [15:0] ms = prs[14] ? (16'h8000 - {{1'b0, prs}}) : {{1'b0, prs}};
    wire [15:0] mc = prc[14] ? (16'h8000 - {{1'b0, prc}}) : {{1'b0, prc}};
    wire [{ib - 1}:0] mis = ms[15:{fb}];
    wire [{fb - 1}:0] ds  = ms[{fb - 1}:0];
    wire [{ib - 1}:0] mic = mc[15:{fb}];
    wire [{fb - 1}:0] dc  = mc[{fb - 1}:0];

    function signed [15:0] Tq;
        input [{ib - 1}:0] k;
        begin
            case (k)
{entries}
                default: Tq = 16'sd0;
            endcase
        end
    endfunction
"""

    if order == "nearest":
        core = """    wire signed [15:0] ys = Tq(mis);
    wire signed [15:0] yc = Tq(mic);
    wire signed [16:0] yss = ngs ? -{1'b0, ys} : {1'b0, ys};
    wire signed [16:0] ycs = ngc ? -{1'b0, yc} : {1'b0, yc};
    wire signed [15:0] sin_v = (yss > 17'sd32767) ? 16'sd32767 : yss[15:0];
    wire signed [15:0] cos_v = (ycs > 17'sd32767) ? 16'sd32767 : ycs[15:0];"""
    elif order == "linear":
        core = f"""    function signed [17:0] interpl;
        input [{ib - 1}:0] mi;
        input [{fb - 1}:0] d;
        reg signed [15:0] s0, s1;
        reg signed [16:0] a1;
        reg signed [{lt_w - 1}:0] lt;
        begin
            s0 = Tq(mi); s1 = Tq(mi + {ib}'d1);
            a1 = s1 - s0;
            lt = a1 * $signed({{1'b0, d}});
            interpl = s0 + $signed(lt[{lt_w - 1}:{fb}]) + $signed({{1'b0, lt[{fb - 1}]}});
        end
    endfunction

    wire signed [17:0] ys = interpl(mis, ds);
    wire signed [17:0] yc = interpl(mic, dc);
    wire signed [18:0] yss = ngs ? -ys : ys;
    wire signed [18:0] ycs = ngc ? -yc : yc;
    wire signed [15:0] sin_v = (yss > 19'sd32767) ? 16'sd32767 :
                               (yss < -19'sd32768) ? -16'sd32768 : yss[15:0];
    wire signed [15:0] cos_v = (ycs > 19'sd32767) ? 16'sd32767 :
                               (ycs < -19'sd32768) ? -16'sd32768 : ycs[15:0];"""
    else:  # quad
        core = f"""    function signed [18:0] interpq;
        input [{ib - 1}:0] mi;
        input [{fb - 1}:0] d;
        reg signed [15:0] s0, s1, s2;
        reg signed [16:0] a1;
        reg signed [17:0] a2;
        reg signed [{lt_w - 1}:0] lt;
        reg signed [16:0] lr;
        reg signed [{d9w - 1}:0] d9, dm;
        reg signed [{qw_w - 1}:0] qw;
        reg signed [{t2_w - 1}:0] t2;
        reg signed [18:0] qr;
        begin
            s0 = Tq(mi); s1 = Tq(mi + {ib}'d1); s2 = Tq(mi + {ib}'d2);
            a1 = s1 - s0;
            a2 = s2 - 2*s1 + s0;
            d9 = $signed({{1'b0, d}});
            dm = d9 - {d9w}'sd{fdiv};
            lt = a1 * d9;
            lr = $signed(lt[{lt_w - 1}:{fb}]) + $signed({{1'b0, lt[{fb - 1}]}});
            qw = d9 * dm;
            t2 = $signed(a2[7:0]) * qw;
            qr = $signed(t2[{t2_w - 1}:{q_shift}]) + $signed({{1'b0, t2[{2 * fb}]}});
            interpq = s0 + lr + qr;
        end
    endfunction

    wire signed [18:0] ys = interpq(mis, ds);
    wire signed [18:0] yc = interpq(mic, dc);
    wire signed [19:0] yss = ngs ? -ys : ys;
    wire signed [19:0] ycs = ngc ? -yc : yc;
    wire signed [15:0] sin_v = (yss > 20'sd32767) ? 16'sd32767 :
                               (yss < -20'sd32768) ? -16'sd32768 : yss[15:0];
    wire signed [15:0] cos_v = (ycs > 20'sd32767) ? 16'sd32767 :
                               (ycs < -20'sd32768) ? -16'sd32768 : ycs[15:0];"""

    return f"""// 参数化设计：QW-LUT N={N} order={order}
// 四分之一波折叠（{S}+2 项表），段内小数 {fb} 位，线性除数 {fdiv}
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] z,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [15:0] sin_out,
    output reg  signed [15:0] cos_out
);

    // EVOLVE-BLOCK-START
{head}
{core}

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            sin_out   <= 16'sd0;
            cos_out   <= 16'sd0;
        end else begin
            if (in_valid && in_ready) begin
                sin_out   <= sin_v;
                cos_out   <= cos_v;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
"""


# ---------------------------------------------------------------------------
# CORDIC 族生成
# ---------------------------------------------------------------------------

def gen_cordic(stages: int) -> str:
    alpha = [round(math.atan(2.0 ** -i) * 65536 / math.pi) for i in range(stages)]
    entries = "\n".join(
        f"                {stages - 1}'d{i}: alpha_rom = 18'sd{v};" for i, v in enumerate(alpha)
    )
    cw = len(bin(stages)[2:])            # 计数器位宽（stages=16 → 5 位）
    return f"""// 参数化设计：CORDIC-{stages}（旋转模式，多周期，零乘法器）
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] z,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [15:0] sin_out,
    output reg  signed [15:0] cos_out
);

    // EVOLVE-BLOCK-START
    reg signed [18:0] x, y;
    reg signed [17:0] za;
    reg [{cw - 1}:0] iter;
    reg        busy, negf;

    wire signed [17:0] z2 = {{z[15], z, 1'b0}};
    wire fold_hi = (z > 16'sd16384);
    wire fold_lo = (z < -16'sd16384);
    wire signed [17:0] z_fold = fold_hi ? (z2 - 18'sd65536) :
                                 fold_lo ? (z2 + 18'sd65536) : z2;
    wire neg = fold_hi | fold_lo;

    function signed [17:0] alpha_rom;
        input [{cw - 1}:0] i;
        begin
            case (i)
{entries}
                default: alpha_rom = 18'sd0;
            endcase
        end
    endfunction

    wire signed [18:0] xs = x, ys = y;
    wire signed [18:0] xsh = xs >>> iter;
    wire signed [18:0] ysh = ys >>> iter;
    wire zpos = (za >= 0);
    wire signed [17:0] alpha = alpha_rom(iter);

    wire signed [19:0] sin_r = (ys + 20'sd2) >>> 2;
    wire signed [19:0] cos_r = (xs + 20'sd2) >>> 2;
    wire signed [19:0] sin_a = negf ? -sin_r : sin_r;
    wire signed [19:0] cos_a = negf ? -cos_r : cos_r;
    wire signed [15:0] sin_p = (sin_a > 20'sd32767) ? 16'sd32767 :
                               (sin_a < -20'sd32768) ? -16'sd32768 : sin_a[15:0];
    wire signed [15:0] cos_p = (cos_a > 20'sd32767) ? 16'sd32767 :
                               (cos_a < -20'sd32768) ? -16'sd32768 : cos_a[15:0];

    assign in_ready = !busy && (!out_valid || out_ready);

    always @(posedge clk) begin
        if (!rst_n) begin
            x <= 19'sd0; y <= 19'sd0; za <= 18'sd0;
            iter <= {cw}'d0; busy <= 1'b0; negf <= 1'b0;
            out_valid <= 1'b0; sin_out <= 16'sd0; cos_out <= 16'sd0;
        end else begin
            if (out_valid && out_ready)
                out_valid <= 1'b0;
            if (busy) begin
                if (iter < {cw}'d{stages}) begin
                    if (zpos) begin
                        x <= xs - ysh;
                        y <= ys + xsh;
                        za <= za - alpha;
                    end else begin
                        x <= xs + ysh;
                        y <= ys - xsh;
                        za <= za + alpha;
                    end
                    iter <= iter + {cw}'d1;
                end else begin
                    sin_out   <= sin_p;
                    cos_out   <= cos_p;
                    out_valid <= 1'b1;
                    busy      <= 1'b0;
                end
            end else if (in_valid && in_ready) begin
                x    <= 19'sd79594;
                y    <= 19'sd0;
                za   <= z_fold;
                negf <= neg;
                iter <= {cw}'d0;
                busy <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END

endmodule
"""


# ---------------------------------------------------------------------------
# 设计库构建
# ---------------------------------------------------------------------------

def build_designs() -> dict:
    designs = {}
    for N in [64, 128, 256, 512, 1024]:
        for order in ["nearest", "linear", "quad"]:
            if order == "nearest" and N != 64:
                continue  # nearest 与表深的关系已有 64 点基线覆盖
            if N == 64 and order == "quad":
                continue  # 表太浅，quad 收益为负
            designs[f"qw_lut_{order}_N{N}"] = gen_lut_quarter(N, order)
    for stages in [12, 14, 16]:
        designs[f"cordic_{stages}"] = gen_cordic(stages)
    return designs


def evaluate_design(path: Path) -> dict:
    env = os.environ.copy()
    env["COMMDSP_TASK"] = "cordic_sincos"
    env["PYTHONPATH"] = str(BENCH.parent.parent)
    r = subprocess.run(
        [sys.executable, str(BENCH / "evaluator.py"), str(path)],
        capture_output=True, text=True, env=env, timeout=600,
    )
    m = re.search(r"metrics:\s*(\{.*?\})\s*artifacts:", r.stdout, re.S)
    if not m:
        return {"error": (r.stdout + r.stderr)[-400:]}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {"raw": m.group(1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--skip-eval", action="store_true")
    args = ap.parse_args()

    designs = build_designs()
    DESIGNS.mkdir(exist_ok=True)

    if args.list_only:
        for name in designs:
            print(name)
        return

    library = []
    for name, code in designs.items():
        p = DESIGNS / f"{name}.v"
        p.write_text(code)
        entry = {"name": name, "file": str(p), "chars": len(code)}
        if not args.skip_eval:
            print(f"evaluating {name} ...", flush=True)
            m = evaluate_design(p)
            entry["metrics"] = m
            print(f"  -> precision={m.get('precision')} area={m.get('area')} "
                  f"thr={m.get('throughput')}", flush=True)
        library.append(entry)

    out = BENCH / "design_library.json"
    out.write_text(json.dumps(library, indent=2))
    print(f"\n{len(library)} designs -> {out}")


if __name__ == "__main__":
    main()
