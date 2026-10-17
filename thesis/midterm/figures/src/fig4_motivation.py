"""图：同一个 DDC 公式两种实现的真实综合面积（论文 fig:motivation）。"""
import numpy as np
import matplotlib.pyplot as plt
from style import C_NAIVE, C_REF, INK, SURFACE, SPECS, save, use_data_style

# ===== 数据（可直接修改） =====
# 真实综合面积 μm²（Yosys + ABC，Nangate45），来源 main_table_v2_20261010.json
NAIVE = [425644, 946859, 709042, 1889223, 1622343, 2559706]  # 照公式直写
TEXTBOOK = [32210, 112852, 29155, 109802, 35428, 56303]  # 教科书多速率结构（模板参数搜索最优）
# ==============================

use_data_style()
x = np.arange(len(SPECS))
naive = np.array(NAIVE) / 1e3
ref = np.array(TEXTBOOK) / 1e3
fig, ax = plt.subplots(figsize=(6.4, 3.2))
w = 0.36
ax.bar(x - w / 2, naive, w, color=C_NAIVE, edgecolor=SURFACE, linewidth=1.5, label="照公式直写")
ax.bar(x + w / 2, ref, w, color=C_REF, edgecolor=SURFACE, linewidth=1.5, label="教科书多速率结构")
for i, (a, b) in enumerate(zip(naive, ref)):
    ax.text(i + w / 2, b * 1.15, f"小 {a / b:.0f} 倍", ha="center", va="bottom", fontsize=9, color=INK)
ax.set_yscale("log")
ax.set_ylabel(r"真实综合面积（千 $\mu\mathrm{m}^2$）")
ax.set_xticks(x, SPECS)
ax.grid(axis="x", visible=False)
ax.legend(loc="upper left", ncol=2)
ax.set_ylim(10, 9000)
save(fig, "fig4_motivation")
