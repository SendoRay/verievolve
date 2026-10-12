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

    box(ax, 1.1, yt, 1.6, 1.25, "", GRAY, "#ffffff")
    ax.text(1.1, yt + 0.42, "规格（人写）", ha="center", fontsize=9.5, color=INK, fontweight="bold")
    ax.text(1.1, yt - 0.08, "公式 F\n指标 M\n允许空间 T", ha="center", va="center", fontsize=9, color=INK2, linespacing=1.4)

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
    """图 3：LLM 如何参与变换。"""
    fig, ax = canvas(11.6, 5.0)

    # (a) 一次变换
    ax.text(0.15, 4.78, "(a) 一次变换：LLM 改写原语程序，两种解释分别用于判定和计价", fontsize=10, color=INK, fontweight="bold", va="center")
    code_box(
        ax, 0.2, 2.75, 2.75, 1.72, "父代程序",
        ["d = g.delay_line(x, 96)", "y = g.mac(zip(d, h))", "y = g.decimate(y, 16)", "g.output(g.q(y, 16, 15))"],
        GRAY, hi=(1, 2),
    )
    code_box(
        ax, 4.35, 2.75, 3.05, 1.72, "子代程序",
        ["x4 = g.decimate(fir(x, h1), 4)", "x4 = g.decimate(fir(x4, h2), 4)", "y  = g.mac(zip(taps(x4), h3))", "g.output(g.q(y, 16, 15))"],
        BLUE, hi=(0, 1),
    )
    arrow(ax, (2.95, 3.6), (4.35, 3.6), color=VIOLET, lw=1.8)
    ax.text(3.65, 3.98, "LLM", ha="center", fontsize=10, color=VIOLET, fontweight="bold")
    ax.text(3.65, 3.74, "单级 → 两级抽取", ha="center", fontsize=8, color=INK2)
    ax.text(3.65, 3.38, "近似变换", ha="center", fontsize=8, color=INK2)
    ax.text(4.42, 2.6, "示意：fir、taps 是 delay_line + mac 的简写", fontsize=7.5, color=INK2, va="center")

    box(ax, 8.55, 4.12, 1.75, 0.6, "浮点解释", AQUA, AQUA_T, sub="数学行为", fs=9.5)
    box(ax, 8.55, 3.1, 1.75, 0.6, "定点解释", ORANGE, ORANGE_T, sub="Verilog（逐位一致）", fs=9.5)
    arrow(ax, (7.4, 3.75), (7.67, 4.12), rad=-0.2)
    arrow(ax, (7.4, 3.45), (7.67, 3.1), rad=0.2)
    box(ax, 10.6, 4.12, 1.7, 0.6, "落在允许空间 T 内？", AQUA, "#ffffff", fs=8.5)
    box(ax, 10.6, 3.1, 1.7, 0.6, "面积 / 时序 / 功耗", ORANGE, "#ffffff", fs=8.5)
    arrow(ax, (9.43, 4.12), (9.75, 4.12))
    arrow(ax, (9.43, 3.1), (9.75, 3.1))

    ax.plot([0.15, 11.45], [2.5, 2.5], color="#d9d8d3", lw=1)

    # (b) 进化树
    ax.text(0.15, 2.27, "(b) 多次变换的积累：一条真实的演化路径（R32 宽带，数字为面积 / 直写起点）", fontsize=10, color=INK, fontweight="bold", va="center")
    ys = 1.15
    nodes = [
        (0.9, "1.000", "直写起点", GRAY, 1.0, False),
        (3.2, "4.056", "多相分解\n（未达标）", GRAY, 1.0, True),
        (5.5, "0.243", "两级抽取 + 多相", BLUE, 0.4, False),
        (7.8, "0.138", "1/4 波查表\n+ 三级抽取 8×2×2", BLUE, 0.7, False),
        (10.1, "0.129", "缩短字长", BLUE, 1.0, False),
    ]
    for i, (x, v, t, c, a, hollow) in enumerate(nodes):
        ax.scatter([x], [ys], s=1500, color="#ffffff" if hollow else c, alpha=1.0 if hollow else a, edgecolor=c, linewidth=1.6, linestyle="--" if hollow else "-", zorder=3)
        ax.text(x, ys, v, ha="center", va="center", fontsize=9.5, color=INK if (hollow or a < 0.6 or c == GRAY and False) else "#ffffff", zorder=4, fontweight="bold")
        ax.text(x, ys - 0.62, t, ha="center", va="center", fontsize=8.5, color=INK, linespacing=1.3)
        if i:
            arrow(ax, (nodes[i - 1][0] + 0.36, ys), (x - 0.36, ys), color=VIOLET, lw=1.6)
            ax.text((nodes[i - 1][0] + x) / 2, ys + 0.17, f"变换 {i}", ha="center", fontsize=8, color=VIOLET)
    # 被淘汰的旁支
    for x0, dx in [(3.2, 0.9), (5.5, 0.9), (7.8, 0.9)]:
        ax.scatter([x0 + dx], [ys + 0.72], s=260, color=GRAY_T, edgecolor=GRAY, linewidth=1, zorder=3)
        arrow(ax, (x0 + 0.22, ys + 0.3), (x0 + dx - 0.14, ys + 0.62), color=GRAY, lw=1, dashed=True)
    ax.text(9.85, ys + 0.72, "灰色小圆：被淘汰的其他候选", fontsize=8, color=INK2, va="center")
    ax.text(0.15, 0.08, "面积的大幅下降来自结构变换（第 2、3 步）；进化可以穿过未达标的中间设计（第 1 步）。", fontsize=8.5, color=INK2)
    save(fig, "fig3_method")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_chain()
    fig_system()
    fig_method()
