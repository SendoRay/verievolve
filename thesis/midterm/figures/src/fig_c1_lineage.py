"""图：沿最优设计祖先链的演化路径（论文 fig:lineage）。"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, NullFormatter
from style import C_NAIVE, C_OURS, INK, SURFACE, save, use_data_style

# ===== 数据（可直接修改） =====
# 每步：(面积 / 直写起点, 横轴标签, 是否达标)。来源 ancestry_M_r32w_r64n_v2_20261010.json 与实验汇报
PATHS = {
    "R32 宽带": [
        (1.000, "直写起点", True),
        (4.056, "多相分解\n（未达标）", False),
        (0.243, "两级抽取\n+ 多相", True),
        (0.138, "1/4 波查表\n+ 三级抽取", True),
        (0.129, "缩短字长", True),
    ],
    "R64 窄带": [
        (1.000, "直写起点", True),
        (0.184, "相位截短到 14 位\n+ 两级抽取", True),
        (0.114, "相位截短\n到 12 位", True),
        (0.107, "缩短字长", True),
    ],
}
# ==============================

use_data_style()
fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.5), sharey=True,
                         gridspec_kw={"width_ratios": [len(p) for p in PATHS.values()]})
for ax, (title, steps) in zip(axes, PATHS.items()):
    ys = [s[0] for s in steps]
    xs = np.arange(len(ys))
    ax.plot(xs, ys, color=C_OURS, linewidth=2, zorder=2)
    for xi, (yi, _, good) in zip(xs, steps):
        ax.scatter([xi], [yi], s=70, zorder=3, color=C_OURS if good else C_NAIVE, edgecolor=SURFACE, linewidth=2)
        ax.annotate(f"{yi:.3f}", (xi, yi), textcoords="offset points", xytext=(9, 7), fontsize=9.5, color=INK)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_title(title, fontsize=10.5, color=INK)
    ax.set_xticks(xs, [s[1] for s in steps], fontsize=8.5)
    ax.set_xlim(-0.5, len(ys) - 0.4)
    ax.set_ylim(0.07, 9)
    ax.grid(axis="x", visible=False)
axes[0].set_ylabel("面积 / 直写起点")
axes[0].scatter([], [], s=70, color=C_OURS, label="达标")
axes[0].scatter([], [], s=70, color=C_NAIVE, label="未达标的中间设计")
axes[0].legend(loc="upper right", fontsize=9)
fig.subplots_adjust(wspace=0.08)
save(fig, "fig_c1_lineage")
