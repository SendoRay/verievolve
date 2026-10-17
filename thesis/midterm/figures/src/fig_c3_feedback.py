"""图：反馈档位消融（论文 表 tab:feedback 的配图）。"""
import numpy as np
import matplotlib.pyplot as plt
from style import C_NAIVE, C_OURS, INK, SURFACE, save, use_data_style

# ===== 数据（可直接修改） =====
# 每个运行（规格, 种子）在三种反馈下的 最优面积 / 直写起点。来源 groupA_v1_20261011/A3_feedback_4seeds_analysis.json
MODES = ["只给分数", "给全部指标", "再加诊断归因"]
RUNS = {
    ("R16 窄带", 0): [0.2108, 0.2127, 0.2264],
    ("R16 窄带", 1): [0.3859, 0.2152, 0.0906],
    ("R16 窄带", 2): [0.2969, 0.2246, 0.2303],
    ("R16 窄带", 3): [0.2111, 0.1827, 0.2101],
    ("R32 宽带", 0): [0.3655, 0.1678, 0.1294],
    ("R32 宽带", 1): [0.3897, 0.1246, 0.1258],
    ("R32 宽带", 2): [0.1885, 0.1163, 0.1298],
    ("R32 宽带", 3): [0.2021, 0.0842, 0.1667],
    ("R64 窄带", 0): [0.1474, 0.1081, 0.1074],
    ("R64 窄带", 1): [0.1478, 0.1176, 0.1419],
    ("R64 窄带", 2): [0.1971, 0.1301, 0.1036],
    ("R64 窄带", 3): [0.1366, 0.0539, 0.0816],
}
# ==============================

use_data_style()
fig, ax = plt.subplots(figsize=(4.6, 3.3))
for vals in RUNS.values():
    ax.plot(range(3), vals, color=C_NAIVE, linewidth=1, marker="o", markersize=4, alpha=0.75)
gm = np.exp(np.mean(np.log(np.array(list(RUNS.values()))), axis=0))
ax.plot(range(3), gm, color=C_OURS, linewidth=2.4, marker="o", markersize=8, markeredgecolor=SURFACE,
        markeredgewidth=2, zorder=3)
for i, g in enumerate(gm):
    ax.annotate(f"{g:.3f}", (i, g), textcoords="offset points", xytext=(10, 6), fontsize=9.5, color=INK)
ax.set_yscale("log")
ax.set_yticks([0.1, 0.2, 0.3, 0.4], ["0.1", "0.2", "0.3", "0.4"])
ax.minorticks_off()
ax.set_xticks(range(3), MODES)
ax.set_xlim(-0.3, 2.45)
ax.set_ylabel("最优面积 / 直写起点")
ax.grid(axis="x", visible=False)
ax.plot([], [], color=C_OURS, linewidth=2.4, marker="o", label="几何均值")
ax.plot([], [], color=C_NAIVE, linewidth=1, marker="o", markersize=4, label="单次运行（规格 × 种子）")
ax.legend(loc="upper right", fontsize=8.5)
save(fig, "fig_c3_feedback")
