"""图：链 A 主结果的真实面积（论文 fig:mainarea）。"""
import numpy as np
import matplotlib.pyplot as plt
from style import C_NAIVE, C_OURS, C_REF, INK, SURFACE, SPECS, save, use_data_style

# ===== 数据（可直接修改） =====
# 真实综合面积 μm²，来源 main_table_v2_20261010.json
NAIVE = [425644, 946859, 709042, 1889223, 1622343, 2559706]  # 直写起点
OURS = [121112, 134285, 92264, 276398, 178227, 296043]  # 本方法（种子 0）
TEMPLATE = [32210, 112852, 29155, 109802, 35428, 56303]  # 模板参数搜索
LABELS = ("直写起点", "进化搜索", "本方法搜索")
# ==============================

use_data_style()
x = np.arange(len(SPECS))
naive, ours, ref = (np.array(v) / 1e3 for v in (NAIVE, OURS, TEMPLATE))
fig, ax = plt.subplots(figsize=(6.8, 3.3))
w = 0.26
ax.bar(x - w, naive, w, color=C_NAIVE, edgecolor=SURFACE, linewidth=1.5, label=LABELS[0])
ax.bar(x, ours, w, color=C_OURS, edgecolor=SURFACE, linewidth=1.5, label=LABELS[1])
ax.bar(x + w, ref, w, color=C_REF, edgecolor=SURFACE, linewidth=1.5, label=LABELS[2])
for i, (a, b) in enumerate(zip(naive, ours)):
    ax.text(i, b * 1.15, f"−{(1 - b / a) * 100:.0f}%", ha="center", va="bottom", fontsize=9,
            color=INK, fontfamily="DejaVu Sans")
ax.set_yscale("log")
ax.set_ylabel(r"真实综合面积（千 $\mu\mathrm{m}^2$）")
ax.set_xticks(x, SPECS)
ax.grid(axis="x", visible=False)
ax.legend(loc="upper left", ncol=3, fontsize=9)
ax.set_ylim(10, 12000)
save(fig, "fig_main_area")
