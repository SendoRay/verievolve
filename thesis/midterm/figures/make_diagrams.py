"""中期报告的三张示意图：通信链路、系统架构、方法细节。

用法：python make_diagrams.py <输出目录>
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

OUT = Path(sys.argv[1])

INK, INK2, SURFACE = "#0b0b0b", "#52514e", "#ffffff"
# 每种角色：描边色与浅底色
BLUE, BLUE_T = "#2a78d6", "#dbe8f8"
ORANGE, ORANGE_T = "#eb6834", "#fbe1d6"
AQUA, AQUA_T = "#1baf7a", "#d5f0e5"
YELLOW, YELLOW_T = "#c98500", "#fbeccb"
VIOLET, VIOLET_T = "#4a3aa7", "#e3e0f4"
GRAY, GRAY_T = "#8a8984", "#efeeeb"

plt.rcParams.update(
    {
        "font.sans-serif": ["PingFang SC", "Heiti SC", "Arial Unicode MS"],
        "axes.unicode_minus": False,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    }
)


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    fig.subplots_adjust(0, 0, 1, 1)
    return fig, ax


def box(ax, x, y, w, h, text, ec=GRAY, fc=GRAY_T, fs=9.5, sub=None, dashed=False, lw=1.4, bold=False):
    """以 (x, y) 为中心的圆角方框。"""
    ax.add_patch(
        FancyBboxPatch(
            (x - w / 2, y - h / 2),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=0.08",
            ec=ec,
            fc=fc,
            lw=lw,
            ls="--" if dashed else "-",
            zorder=2,
        )
    )
    if sub:
        ax.text(x, y + 0.11, text, ha="center", va="center", fontsize=fs, color=INK, zorder=3, fontweight="bold" if bold else None)
        ax.text(x, y - 0.14, sub, ha="center", va="center", fontsize=fs - 2, color=INK2, zorder=3)
    else:
        ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK, zorder=3, fontweight="bold" if bold else None, linespacing=1.3)


def arrow(ax, p, q, color=INK2, lw=1.3, dashed=False, rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            p,
            q,
            arrowstyle="-|>",
            mutation_scale=11,
            color=color,
            lw=lw,
            ls="--" if dashed else "-",
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=0,
            shrinkB=0,
            zorder=1,
        )
    )


def bracket(ax, x0, x1, y, text, color, dashed=False):
    ls = "--" if dashed else "-"
    ax.plot([x0, x0, x1, x1], [y + 0.1, y, y, y + 0.1], color=color, lw=1.4, ls=ls)
    ax.text((x0 + x1) / 2, y - 0.16, text, ha="center", va="center", fontsize=8.5, color=INK)


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", dpi=220, bbox_inches="tight", pad_inches=0.08)
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    print("wrote", name)


def fig_chain():
    """图 1：通信收发链路与数据集链路的覆盖范围。"""
    fig, ax = canvas(12.0, 4.5)
    W, H = 0.98, 0.52

    # 发射链
    yt = 3.75
    ax.text(0.15, yt, "发射", fontsize=10, color=INK2, va="center")
    tx = [
        ("比特", GRAY, GRAY_T),
        ("调制映射", VIOLET, VIOLET_T),
        ("IFFT", YELLOW, YELLOW_T),
        ("成形滤波", ORANGE, ORANGE_T),
        ("多级内插", ORANGE, ORANGE_T),
        ("NCO\n上变频", BLUE, BLUE_T),
        ("DAC", GRAY, GRAY_T),
    ]
    xs = [1.2 + i * 1.32 for i in range(len(tx))]
    for i, (x, (t, ec, fc)) in enumerate(zip(xs, tx)):
        box(ax, x, yt, W, H, t, ec, fc)
        if i:
            arrow(ax, (xs[i - 1] + W / 2, yt), (x - W / 2, yt))
    bracket(ax, xs[1] - W / 2, xs[2] + W / 2, yt - 0.48, "链 C：OFDM 发射", GRAY, dashed=True)
    bracket(ax, xs[3] - W / 2, xs[5] + W / 2, yt - 0.48, "链 B：发射 DUC（接入中）", ORANGE)

    # 接收链
    yr = 1.75
    ax.text(0.15, yr, "接收", fontsize=10, color=INK2, va="center")
    x_adc, x_nco, x_mix, x_fir = 1.2, 2.45, 3.75, 5.05
    box(ax, x_adc, yr, 0.8, H, "ADC", GRAY, GRAY_T)
    box(ax, x_nco, yr, W, H, "NCO\nsin / cos", BLUE, BLUE_T)
    arrow(ax, (x_adc + 0.4, yr), (x_nco - W / 2, yr))
    for dy, lab in [(0.36, "I"), (-0.36, "Q")]:
        box(ax, x_mix, yr + dy, W, 0.46, f"混频 {lab}", AQUA, AQUA_T, fs=9)
        box(ax, x_fir, yr + dy, W, 0.46, f"抽取滤波 {lab}", ORANGE, ORANGE_T, fs=9)
        arrow(ax, (x_nco + W / 2, yr), (x_mix - W / 2, yr + dy))
        arrow(ax, (x_mix + W / 2, yr + dy), (x_fir - W / 2, yr + dy))
    rest = [
        ("同步\n频偏校正", VIOLET, VIOLET_T),
        ("FFT", YELLOW, YELLOW_T),
        ("信道估计\n与均衡", BLUE, BLUE_T),
        ("软解调", AQUA, AQUA_T),
        ("LLR", GRAY, GRAY_T),
    ]
    xr = [6.45 + i * 1.22 for i in range(len(rest))]
    for i, (x, (t, ec, fc)) in enumerate(zip(xr, rest)):
        box(ax, x, yr, 0.96, H, t, ec, fc, fs=9)
        if i:
            arrow(ax, (xr[i - 1] + 0.48, yr), (x - 0.48, yr))
    for dy in (0.36, -0.36):
        arrow(ax, (x_fir + W / 2, yr + dy), (xr[0] - 0.48, yr))
    bracket(ax, x_nco - W / 2, x_fir + W / 2, yr - 0.78, "链 A：接收 DDC（已完成）", BLUE)
    bracket(ax, xr[0] - 0.48, xr[0] + 0.48, yr - 0.78, "链 E：同步前端", GRAY, dashed=True)
    bracket(ax, xr[1] - 0.48, xr[3] + 0.48, yr - 0.78, "链 D：OFDM 接收内环", GRAY, dashed=True)

    yc = 2.72
    ax.plot([xs[-1], xs[-1], x_adc, x_adc], [yt - H / 2, yc, yc, yr + H / 2 + 0.12], color=GRAY, lw=1.2, ls=":")
    arrow(ax, (x_adc, yr + H / 2 + 0.13), (x_adc, yr + H / 2), color=GRAY, lw=1.2)
    ax.text((xs[-1] + x_adc) / 2, yc + 0.1, "信道", fontsize=9, color=INK2, ha="center")
    ax.text(0.15, 0.3, "另有三条链未在图中画出：F 多相信道化器、G WCDMA Rake 支路、H 分数倍重采样。", fontsize=8.5, color=INK2)
    save(fig, "fig1_comm_chain")


def fig_system():
    """图 2：系统架构（两层搜索闭环）。"""
    fig, ax = canvas(13.2, 5.6)
    yt, yb = 3.95, 1.15

    # 两层的底色带
    ax.add_patch(FancyBboxPatch((2.25, yt - 0.72), 4.7, 1.62, boxstyle="round,pad=0,rounding_size=0.12", ec=VIOLET, fc="#f6f4fc", lw=1.2, ls="--", zorder=0))
    ax.text(4.6, yt + 0.68, "外层：结构搜索（LLM，持续探索，不冻结）", ha="center", fontsize=9.5, color=VIOLET, fontweight="bold")
    ax.add_patch(FancyBboxPatch((7.15, yt - 1.05), 4.05, 1.95, boxstyle="round,pad=0,rounding_size=0.12", ec=ORANGE, fc="#fff6f1", lw=1.2, ls="--", zorder=0))
    ax.text(9.17, yt + 0.68, "内层：实现调优与评价（确定性）", ha="center", fontsize=9.5, color=ORANGE, fontweight="bold")

    box(ax, 1.1, yt, 1.72, 1.34, "", GRAY, "#ffffff")
    ax.text(1.1, yt + 0.42, "规格（人写）", ha="center", fontsize=9.5, color=INK, fontweight="bold")
    ax.text(1.1, yt - 0.10, "计算图 G\n设计边界 B\n指标 M + 允许空间 T", ha="center", va="center", fontsize=8.2, color=INK2, linespacing=1.35)

    box(ax, 3.05, yt, 1.2, 0.7, "提示词生成", BLUE, BLUE_T, fs=9)
    box(ax, 4.55, yt, 0.95, 0.7, "LLM", VIOLET, VIOLET_T, bold=True, fs=11)
    box(ax, 6.0, yt, 1.3, 0.7, "结构变换\n（程序 diff）", AQUA, AQUA_T, fs=9)
    ax.text(4.55, yt - 0.56, "多级抽取、查表结构、多相……", ha="center", fontsize=7.5, color=INK2)

    box(ax, 7.95, yt + 0.12, 1.25, 0.66, "位宽 / 复用\n小预算调优", ORANGE, ORANGE_T, fs=8.5)
    box(ax, 9.3, yt + 0.12, 0.95, 0.66, "编译器", ORANGE, ORANGE_T, fs=9)
    box(ax, 10.55, yt + 0.12, 0.95, 0.66, "裁判", ORANGE, ORANGE_T, fs=9)
    ax.text(9.3, yt - 0.48, "Verilog\n整数模型", ha="center", va="center", fontsize=7.5, color=INK2, linespacing=1.3)
    ax.text(10.55, yt - 0.48, "搜索 + 留出场景\n安全裕量 0.3 dB", ha="center", va="center", fontsize=7.5, color=INK2, linespacing=1.3)
    arrow(ax, (8.58, yt + 0.12), (8.82, yt + 0.12))
    arrow(ax, (9.78, yt + 0.12), (10.07, yt + 0.12))
    arrow(ax, (10.55, yt - 0.21), (7.95, yt - 0.21), rad=0.35, color=ORANGE)
    ax.text(9.25, yt - 0.86, "每次调优都重新过裁判", ha="center", fontsize=7.5, color=ORANGE)

    arrow(ax, (1.9, yt), (2.45, yt))
    arrow(ax, (3.65, yt), (4.07, yt))
    arrow(ax, (5.03, yt), (5.35, yt))
    arrow(ax, (6.65, yt), (7.32, yt + 0.05))

    box(ax, 12.35, yt + 0.12, 1.25, 0.72, "最优设计\nVerilog + PPA", AQUA, AQUA_T, fs=8.5)
    arrow(ax, (11.2, yt + 0.12), (11.72, yt + 0.12))

    # 下方回路
    box(ax, 9.3, yb, 2.3, 0.95, "", VIOLET, VIOLET_T)
    ax.text(9.3, yb + 0.26, "种群档案（Pareto）", ha="center", fontsize=9.5, color=INK, fontweight="bold")
    for i, (c, a) in enumerate([(BLUE, 0.25), (BLUE, 0.45), (BLUE, 0.7), (BLUE, 1.0), (GRAY, 0.5), (BLUE, 0.55)]):
        ax.scatter([8.48 + i * 0.33], [yb - 0.16], s=110, color=c, alpha=a, edgecolor="white", linewidth=1, zorder=4)
    box(ax, 5.9, yb, 2.0, 0.95, "", BLUE, BLUE_T, dashed=True)
    ax.text(5.9, yb + 0.26, "选择父代", ha="center", fontsize=9.5, color=INK, fontweight="bold")
    ax.text(5.9, yb - 0.14, "多岛 + MAP-Elites\n精英与多样性", ha="center", va="center", fontsize=8, color=INK2, linespacing=1.3)
    box(ax, 2.85, yb, 1.95, 0.95, "父代程序\n+ 指标数值反馈", AQUA, AQUA_T)
    box(ax, 12.35, yb, 1.15, 0.7, "直写起点\n（自动生成）", GRAY, GRAY_T, fs=8)

    arrow(ax, (9.3, yt - 1.05), (9.3, yb + 0.475))
    ax.text(9.45, 2.4, "调优后的面积、裕量、逐段指标", fontsize=8.5, color=INK2, va="center")
    arrow(ax, (8.15, yb), (6.9, yb))
    arrow(ax, (4.9, yb), (3.83, yb))
    arrow(ax, (2.85, yb + 0.475), (3.0, yt - 0.35), rad=-0.15)
    arrow(ax, (11.77, yb), (10.45, yb), dashed=True)
    save(fig, "fig2_system")


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
    ax.text(0.50, 1.02, "3  整条子链联合设计", fontsize=8.0, color=INK2)
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
    box(ax, 11.02, 1.55, 2.58, 0.66, "RTL ↔ 整数模型逐位对拍", BLUE, BLUE_T,
        sub="候选不能自己宣布正确", fs=9)
    arrow(ax, (10.10, 2.34), (10.62, 1.88), color=BLUE)
    arrow(ax, (11.96, 2.34), (11.42, 1.88), color=BLUE)
    ax.text(9.30, 0.92, "当前持久化：构造程序源码", fontsize=8.0, color=INK2)
    ax.text(9.30, 0.62, "当前运行态：内存图（尚未单独序列化）", fontsize=8.0, color=INK2)
    save(fig, "fig3_method")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_chain()
    fig_system()
    fig_method()
