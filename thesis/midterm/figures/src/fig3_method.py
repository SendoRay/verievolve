"""图：数学计算图、原语级可执行 IR 与确定性后端（论文 fig:method）。"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from style import (AQUA, AQUA_T, BLUE, BLUE_T, GRAY, GRAY_T, INK, INK2, ORANGE, ORANGE_T, VIOLET, VIOLET_T,
                   YELLOW, YELLOW_T, arrow, box, canvas, save, use_diagram_style)

# ===== 数据（可直接修改） =====
# 示意图没有数值数据；所有文字都写在下面的绘图代码里，直接搜索要改的文字即可。
# ==============================

use_diagram_style()

def code_box(ax, x, y, w, h, title, lines, ec, hi=()):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.06", ec=ec, fc="#ffffff", lw=1.4, zorder=2))
    ax.text(x + 0.12, y + h - 0.2, title, fontsize=9, color=INK, fontweight="bold", va="center", zorder=3)
    for i, ln in enumerate(lines):
        yy = y + h - 0.5 - i * 0.25
        if i in hi:
            ax.add_patch(plt.Rectangle((x + 0.06, yy - 0.115), w - 0.12, 0.23, fc=BLUE_T, ec="none", zorder=2.5))
        ax.text(x + 0.14, yy, ln, fontsize=8, color=INK, family="Menlo", va="center", zorder=3)


def fig_method():
    """图 4：数学计算图、可执行 IR 与确定性后端。"""
    fig, ax = canvas(13.2, 6.2)

    # 三栏背景
    panels = [
        (0.18, 0.3, 3.78, 5.6, BLUE, "(a) 数学计算图与任务边界"),
        (4.12, 0.3, 4.72, 5.6, VIOLET, "(b) 原语级可执行 IR（真实字段）"),
        (9.02, 0.3, 4.0, 5.6, ORANGE, "(c) 同一 IR 的确定性后端"),
    ]
    for x, y, w, h, ec, title in panels:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.1",
                                    ec=ec, fc="#ffffff", lw=1.25, zorder=0))
        ax.text(x + 0.16, y + h - 0.25, title, fontsize=9.6, color=ec,
                fontweight="bold", va="center")

    # (a) 公式先成为有名字的计算图，边界来自任务契约而不是候选自己猜。
    ax.text(2.07, 5.14,
            r"$y[m]=\downarrow_R\{h*(x[n]e^{-j\phi[n]})\}$",
            ha="center", va="center", fontsize=10, color=INK)
    xs, yy = [0.58, 1.34, 2.14, 2.94, 3.60], 4.25
    labels = ["x", "NCO", "混频", "FIR", "↓R"]
    colors = [(GRAY, GRAY_T), (BLUE, BLUE_T), (AQUA, AQUA_T),
              (ORANGE, ORANGE_T), (ORANGE, ORANGE_T)]
    widths = [0.48, 0.62, 0.66, 0.58, 0.52]
    for i, (x, label, (ec, fc), w) in enumerate(zip(xs, labels, colors, widths)):
        box(ax, x, yy, w, 0.52, label, ec, fc, fs=8.2)
        if i:
            arrow(ax, (xs[i - 1] + widths[i - 1] / 2, yy), (x - w / 2, yy), lw=1.0)
    ax.add_patch(FancyBboxPatch((1.00, 3.76), 1.51, 0.98,
                                boxstyle="round,pad=0,rounding_size=0.06",
                                ec=VIOLET, fc="none", lw=1.4, ls="--", zorder=1))
    ax.text(1.76, 3.63, "可变子图 Bvar（示例）", ha="center", fontsize=7.5,
            color=VIOLET, fontweight="bold")
    ax.add_patch(FancyBboxPatch((2.58, 3.76), 1.28, 0.98,
                                boxstyle="round,pad=0,rounding_size=0.06",
                                ec=GRAY, fc="none", lw=1.2, ls=":", zorder=1))
    ax.text(3.22, 3.63, "冻结上下文 Bctx", ha="center", fontsize=7.2, color=INK2)
    arrow(ax, (3.60, 3.98), (3.60, 3.22), color=AQUA, lw=1.2)
    box(ax, 3.18, 2.92, 1.42, 0.48, "观测边界 Bobs", AQUA, AQUA_T, fs=8)
    ax.text(3.18, 2.55, "链末 SNR / EVM / BER", ha="center", fontsize=7.4, color=INK2)
    box(ax, 1.42, 2.92, 1.52, 0.48, "成本边界 Bcost", ORANGE, ORANGE_T, fs=8)
    ax.text(1.42, 2.55, "只综合被设计的模块", ha="center", fontsize=7.4, color=INK2)
    arrow(ax, (1.76, 3.76), (1.52, 3.17), color=ORANGE, lw=1.2)
    ax.text(0.42, 1.95, "同一张图可形成三类任务：", fontsize=8.3, color=INK, fontweight="bold")
    ax.text(0.50, 1.62, "1  单算子局部验收", fontsize=8.0, color=INK2)
    ax.text(0.50, 1.32, "2  冻结链路中的算子设计", fontsize=8.0, color=INK2)
    ax.text(0.50, 1.02, "3  整条链路联合设计", fontsize=8.0, color=INK2)
    ax.text(0.42, 0.62, "边界写在任务契约中，不能由 LLM\n从公式或 scope 名称中猜测。",
            fontsize=7.8, color=VIOLET, va="center", linespacing=1.35)

    # (b) 当前主线实际持久化的是构造程序，运行时产生带类型图。
    code_box(
        ax, 4.30, 1.88, 4.35, 3.58, "build(g, spec)：公式的直写起点",
        [
            "x    = g.input()",
            "ph   = g.counter(spec.fcw, 32)",
            "addr = g.bits(ph, 31, 16)",
            "c    = g.lut(addr, cos_table, 20, 18)",
            "s    = g.lut(addr, sin_table, 20, 18)",
            "i    = g.q(g.mul(x, c), 22, 20)",
            "q    = g.q(g.neg(g.mul(x, s)), 22, 20)",
            "i    = g.mac(zip(g.delay_line(i,N), h))",
            "q    = g.mac(zip(g.delay_line(q,N), h))",
            "i    = g.decimate(i, spec.r_total)",
            "q    = g.decimate(q, spec.r_total)",
            "g.output(g.q(i,b,b-1), g.q(q,b,b-1))",
        ],
        VIOLET, hi=(1, 2, 5, 7, 9, 11),
    )
    ax.text(4.36, 1.55, "运行时每根线都是 Sig：", fontsize=8.3, color=INK, fontweight="bold")
    ax.text(4.48, 1.22, "W/F  位宽与小数位    signed  符号", fontsize=7.7,
            color=INK2)
    ax.text(4.48, 0.92, "lin   采样率域         lat     延迟", fontsize=7.7,
            color=INK2)
    ax.text(4.48, 0.62, "v     当前激励下的逐位整数值", fontsize=7.7,
            color=INK2)

    # (c) 当前编译器在建图时同步维护整数语义和 RTL。
    box(ax, 11.02, 5.08, 1.70, 0.56, "带类型数据流图", VIOLET, VIOLET_T,
        sub="结构 + 定点 + 速率 + 状态", fs=9)
    box(ax, 10.10, 3.86, 1.58, 0.66, "逐位整数解释", AQUA, AQUA_T,
        sub="同一激励下精确执行", fs=8.7)
    box(ax, 11.96, 3.86, 1.46, 0.66, "Verilog 后端", ORANGE, ORANGE_T,
        sub="自动对齐 valid / 延迟", fs=8.7)
    arrow(ax, (10.72, 4.80), (10.24, 4.20), color=AQUA)
    arrow(ax, (11.32, 4.80), (11.83, 4.20), color=ORANGE)
    box(ax, 10.10, 2.66, 1.58, 0.62, "链级质量判定", AQUA, "#ffffff",
        sub="在 Bobs 计算 M ∈ T？", fs=8.5)
    box(ax, 11.96, 2.66, 1.46, 0.62, "综合与 PPA", ORANGE, "#ffffff",
        sub="只统计 Bcost", fs=8.5)
    arrow(ax, (10.10, 3.53), (10.10, 2.97))
    arrow(ax, (11.96, 3.53), (11.96, 2.97))
    box(ax, 11.02, 1.55, 2.58, 0.66, "RTL 与整数模型逐位对拍", BLUE, BLUE_T,
        sub="候选不能自己宣布正确", fs=9)
    arrow(ax, (10.10, 2.34), (10.62, 1.88), color=BLUE)
    arrow(ax, (11.96, 2.34), (11.42, 1.88), color=BLUE)
    ax.text(9.30, 0.92, "当前持久化：构造程序源码", fontsize=8.0, color=INK2)
    ax.text(9.30, 0.62, "当前运行态：内存图（尚未单独序列化）", fontsize=8.0, color=INK2)
    save(fig, "fig3_method")


fig_method()
