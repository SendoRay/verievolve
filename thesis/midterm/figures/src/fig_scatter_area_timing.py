"""图：面积与关键路径延迟（论文 fig:timing）。"""
import matplotlib.pyplot as plt
from style import C_NAIVE, C_OURS, C_REF, INK2, SURFACE, SPECS, save, use_data_style

# ===== 数据（可直接修改） =====
# 每个设计 (关键路径 ps, 面积 μm²)，ABC 尺寸调整后口径。来源 timing_summary_v1_20261011.json
# 顺序与 SPECS 一致：R16 窄、R16 宽、R32 窄、R32 宽、R64 窄、R64 宽
DATA = {
    "直写起点": [(2828, 431960), (3099, 955140), (3091, 715916), (3442, 1898520), (3292, 1631667), (3516, 2570838)],
    "本方法": [(2257, 122617), (2615, 137553), (1972, 93689), (2221, 279569), (2446, 180631), (2317, 300514)],
    "专家模板": [(2426, 32831), (2787, 114793), (2470, 29934), (2787, 113669), (2486, 36123), (2770, 57785)],
}
STYLE = {"直写起点": (C_NAIVE, "o"), "本方法": (C_OURS, "s"), "专家模板": (C_REF, "^")}
# ==============================

use_data_style()
fig, ax = plt.subplots(figsize=(5.4, 3.6))
for name, pts in DATA.items():
    col, mk = STYLE[name]
    ax.scatter([p[0] / 1e3 for p in pts], [p[1] / 1e3 for p in pts], s=64, color=col, marker=mk,
               edgecolor=SURFACE, linewidth=1.5, label=name, zorder=3)
ax.set_yscale("log")
ax.set_xlabel("关键路径延迟（ns）")
ax.set_ylabel(r"面积（千 $\mu\mathrm{m}^2$）")
ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=9)
ax.text(0.03, 0.04, "← 左下更优", transform=ax.transAxes, fontsize=9, color=INK2)
save(fig, "fig_scatter_area_timing")
