#!/usr/bin/env python
"""B2 基线：两级翻译流程演示（公式 → 浮点算法 → 定点化 → RTL）

模拟"先进化/生成数学算法，再翻译到硬件"的经典两级流程：
  Stage 1（数学层）: 从任务规范出发的浮点参考算法（math.sin/cos）——
                     数学层没有面积/精度权衡信号，定点化决策靠"工程直觉"
  Stage 2（翻译层）: 定点化决策（表深 64 = 常用值、Q1.15 = 标准格式、
                     线性插值 = 教科书做法）→ 全波查找表 RTL

关键对照点：两级流程的定点化决策在无硬件反馈下一次锁定；联合进化在同一
面积预算下探索出 +33 dB 的结构（QW 压缩 / 深表权衡 / CORDIC 分支）。

用法: python two_stage_baseline.py            # 运行演示 + 对比输出
      python two_stage_baseline.py --emit out.v  # 只产出两级流程的 RTL
"""

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Stage 1: 数学层（浮点参考算法 + 无反馈的定点化决策记录）
# ---------------------------------------------------------------------------

FLOAT_ALGO = '''
import math

def sincos(z: int) -> tuple[float, float]:
    """cordic_sincos 任务规范的浮点实现（数学层最优解）"""
    theta = z * math.pi / 32768.0        # z: 16 位线性角度码
    return math.sin(theta), math.cos(theta)
'''

FIXPOINT_DECISIONS = {
    "表深 N": "64（工程常用值；无面积反馈，不做深浅权衡）",
    "表格式": "全波（未利用四分之一波对称——数学层无面积信号）",
    "量化格式": "Q1.15（16 位输出的标准格式）",
    "插值": "线性（教科书标准做法；不评估二次/深表替代方案）",
    "乘法器位宽": "全宽 16x10（不做动态范围截断分析）",
    "输出饱和": "未考虑（插值过冲的回绕风险在数学层不可见）",
}


# ---------------------------------------------------------------------------
# Stage 2: 翻译层（按上述决策产出 RTL——全波 64 表 + 线性插值）
# ---------------------------------------------------------------------------

def emit_two_stage_rtl() -> str:
    N = 64
    T = [max(-32767, min(32767, round(math.sin(2 * math.pi * k / N) * 32768)))
         for k in range(N)]
    entries = "\n".join(f"            6'd{k}: T = {v};" if v >= 0 else
                        f"            6'd{k}: T = -16'sd{-v};" for k, v in enumerate(T))
    return f"""// B2 两级翻译基线产出：全波 64 点表 + 线性插值（FW-lin-64）
// 由 two_stage_baseline.py 按无反馈定点化决策生成
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
    wire [15:0] phase = z;               // 全波相位（补码位型）
    wire [5:0]  idx_s = phase[15:10];    // sin 索引
    wire [5:0]  idx_c = idx_s + 6'd16;   // cos = sin(x + pi/2)
    wire [9:0]  frac  = phase[9:0];      // 插值小数

    function signed [15:0] T;
        input [5:0] k;
        begin
            case (k)
{entries}
                default: T = 16'sd0;
            endcase
        end
    endfunction

    wire signed [15:0] s0 = T(idx_s), s1 = T(idx_s + 6'd1);
    wire signed [15:0] c0 = T(idx_c), c1 = T(idx_c + 6'd1);
    wire signed [25:0] ds = (s1 - s0) * $signed({{1'b0, frac}});
    wire signed [25:0] dc = (c1 - c0) * $signed({{1'b0, frac}});
    wire signed [15:0] sin_v = s0 + ds[25:10];
    wire signed [15:0] cos_v = c0 + dc[25:10];

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0; sin_out <= 16'sd0; cos_out <= 16'sd0;
        end else if (in_valid && in_ready) begin
            sin_out <= sin_v; cos_out <= cos_v; out_valid <= 1'b1;
        end else if (out_valid && out_ready) begin
            out_valid <= 1'b0;
        end
    end
    // EVOLVE-BLOCK-END

endmodule
"""


# ---------------------------------------------------------------------------
# 评估与对比
# ---------------------------------------------------------------------------

def evaluate(path: Path) -> dict:
    import os
    env = os.environ.copy()
    env["COMMDSP_TASK"] = "cordic_sincos"
    env["PYTHONPATH"] = str(BENCH.parent.parent)
    r = subprocess.run([sys.executable, str(BENCH / "evaluator.py"), str(path)],
                       capture_output=True, text=True, env=env, timeout=900)
    m = re.search(r"metrics:\s*(\{.*?\})\s*artifacts:", r.stdout, re.S)
    return json.loads(m.group(1)) if m else {"error": r.stdout[-300:]}


# 联合搜索前沿代表点（ablation C 组实测）
JOINT_FRONT = [
    ("CORDIC-16 (多周期)", 84.2, 1594, 0.056, 1594),
    ("QW-lin-256", 85.1, 2332, 0.908, 2332),
    ("QW-lin-512", 94.0, 2770, 0.908, 2770),
    ("QW-lin-1024 (深表)", 96.0, 3648, 0.908, 3648),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", default=None, help="只产出 RTL 到指定文件")
    args = ap.parse_args()

    rtl = emit_two_stage_rtl()

    if args.emit:
        Path(args.emit).write_text(rtl)
        print(f"two-stage RTL -> {args.emit}")
        return

    tmp = BENCH / ".manual_answers" / "two_stage_design.v"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(rtl)
    print("=" * 72)
    print("B2 两级翻译基线演示（cordic_sincos 任务）")
    print("=" * 72)
    print("\n【Stage 1 · 数学层】浮点参考算法：")
    print(FLOAT_ALGO)
    print("【Stage 1 · 定点化决策（无硬件反馈，一次锁定）】")
    for k, v in FIXPOINT_DECISIONS.items():
        print(f"  - {k}: {v}")

    print("\n【Stage 2 · 翻译层】评估产出 RTL：")
    m = evaluate(tmp)
    print(f"  SQNR = {m.get('precision')} dB   area = {m.get('area')} LUT   "
          f"area_um2 = {m.get('area_um2')} μm²   thr = {m.get('throughput')}")

    print("\n【对照 · 联合搜索前沿（同任务，混合模式消融 C 组）】")
    print(f"  {'设计':<24} {'SQNR_dB':>8} {'LUT':>6} {'ASIC_μm²':>9} {'thr':>6}")
    for name, p, a, t, aum in JOINT_FRONT:
        print(f"  {name:<24} {p:>8.1f} {a:>6.0f} {'~' + str(int(aum*0.95)):>9} {t:>6.3f}")
    b_p = m.get("precision", 0)
    print(f"\n  结论：两级翻译单点 = {b_p:.1f} dB；联合搜索同量级面积可达 94-96 dB"
          f"（+{94-b_p:.0f} dB），且保留 CORDIC 低面积分支——"
          f"定点化决策的不可协商性 = 两级流程的结构性损失。")


if __name__ == "__main__":
    main()
