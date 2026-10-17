"""图：R32 窄带规格上 5 个设计的 PPA（论文 fig:ppa）。

OpenSTA 静态时序与功耗，Nangate45 typical，快速 ABC 映射，2 ns 时钟约束，全局翻转率 0.1。
"""
import matplotlib
import matplotlib.ticker
import numpy as np
import matplotlib.pyplot as plt
from style import C_BASE, C_NAIVE, C_OURS, C_REF, C_EXTRA, INK, SURFACE, save, use_data_style

# ===== 数据（可直接修改） =====
# 名称: (面积 μm², 最小周期 ns, fmax MHz, 总功耗 mW)
DESIGNS = {
    "直写起点": (715916, 3.29, 304, 182.0),
    "进化搜索": (93689, 9.66, 104, 32.0),
    "模板参数搜索": (27345, 4.00, 250, 9.66),
    "DeepSeek 智能体": (110467, 4.09, 244, 30.7),
    "本框架智能体": (14639, 2.36, 423, 4.78),
}
COLORS = {"直写起点": C_NAIVE, "进化搜索": C_BASE, "模板参数搜索": C_REF, "DeepSeek 智能体": C_EXTRA[0],
          "本框架智能体": C_OURS}
HIGHLIGHT = "本框架智能体"
# ==============================

use_data_style()
names = list(DESIGNS)
y = np.arange(len(names))
vals = np.array([DESIGNS[n] for n in names], dtype=float)
panels = [
    (r"面积（千 $\mu\mathrm{m}^2$，越小越好）", vals[:, 0] / 1e3, True, "{:.1f}"),
    ("最高频率（MHz，越大越好）", vals[:, 2], False, "{:.0f}"),
    ("功耗（mW，越小越好）", vals[:, 3], True, "{:.1f}"),
]
fig, axes = plt.subplots(1, 3, figsize=(10.0, 2.9), sharey=True)
for ax, (title, v, logx, fmt) in zip(axes, panels):
    cols = [COLORS[n] for n in names]
    ax.barh(y, v, height=0.62, color=cols, edgecolor=SURFACE, linewidth=1.2)
    for yi, vi, n in zip(y, v, names):
        x_txt = vi * 1.08 if logx else vi + v.max() * 0.02
        ax.text(x_txt, yi, fmt.format(vi), va="center", fontsize=8.5, color=INK,
                fontweight="bold" if n == HIGHLIGHT else None)
    if logx:
        ax.set_xscale("log")
        ax.set_xlim(v.min() * 0.5, v.max() * 4)
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda t, _: f"{t:g}"))
        ax.minorticks_off()
    else:
        ax.set_xlim(0, v.max() * 1.22)
    ax.set_title(title, fontsize=9.5, color=INK)
    ax.grid(axis="y", visible=False)
axes[0].set_yticks(y, names)
axes[0].invert_yaxis()
for lab in axes[0].get_yticklabels():
    if lab.get_text() == HIGHLIGHT:
        lab.set_fontweight("bold")
        lab.set_color(C_OURS)
fig.subplots_adjust(wspace=0.12)
save(fig, "fig_ppa_r32n")
