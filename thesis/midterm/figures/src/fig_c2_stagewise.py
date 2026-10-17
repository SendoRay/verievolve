"""图：逐级最优再拼接 vs 整链优化，及整链最优解的误差份额（论文 fig:stagewise）。"""
import numpy as np
import matplotlib.pyplot as plt
from style import C_BASE, C_EXTRA, C_NAIVE, C_OURS, C_REF, INK, INK2, SURFACE, SPECS, save, use_data_style

# ===== 数据（可直接修改） =====
# (a) 真实面积 μm²；逐级设计为 None 表示无达标解。来源 e21_stagewise_v1_20261011/E21_summary.json
STAGEWISE = [50542, None, 50439, None, 55938, None]
CHAIN = [32210, 112852, 29155, 109802, 35428, 56303]
# (b) 各误差源占整链最优解总误差功率的比例。来源 error_shares_E22_normalized.json（负值按 0 画）
SHARES = {
    "ADC 量化 + 滤波结构": [0.7283, 0.6615, 0.7154, 0.7506, 0.5565, 0.6379],
    "NCO": [0.1788, 0.1235, 0.2354, 0.0675, 0.3577, 0.2575],
    "混频字长": [0.0861, 0.0196, 0.0147, 0.0876, 0.0713, 0.0616],
    "滤波系数": [-0.0095, 0.1856, 0.0194, 0.0729, 0.0144, 0.0021],  # FIR 系数 + 半带
    "CIC 字长": [0.0324, 0.0001, 0.0147, 0.0011, 0.0079, 0.0560],
}
# ==============================

use_data_style()
x = np.arange(len(SPECS))
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.2, 3.5), gridspec_kw={"width_ratios": [1.05, 1]})
w = 0.36
stage = [0 if v is None else v / 1e3 for v in STAGEWISE]
chain = [v / 1e3 for v in CHAIN]
ax.bar(x - w / 2, stage, w, color=C_BASE, edgecolor=SURFACE, linewidth=1.5, label="逐级最优再拼接")
ax.bar(x + w / 2, chain, w, color=C_OURS, edgecolor=SURFACE, linewidth=1.5, label="整链优化")
for i, (a, b, raw) in enumerate(zip(stage, chain, STAGEWISE)):
    if raw is not None:
        ax.text(i, max(a, b) + 4, f"整链省 {(1 - b / a) * 100:.0f}%", ha="center", fontsize=9, color=INK)
    else:
        ax.text(i - w / 2, 4, "无达标解", ha="center", fontsize=8.5, color=INK2, rotation=90, va="bottom")
ax.set_ylabel(r"真实综合面积（千 $\mu\mathrm{m}^2$）")
ax.set_xticks(x, SPECS, fontsize=9)
ax.grid(axis="x", visible=False)
ax.legend(loc="upper left", fontsize=9)
ax.set_ylim(0, 150)
ax.set_title("(a) 同一模板空间内的面积", fontsize=10.5, color=INK)

cols = [C_NAIVE, C_OURS, C_BASE, C_REF, C_EXTRA[0]]
left = np.zeros(len(SPECS))
for (name, vals), col in zip(SHARES.items(), cols):
    v = np.maximum(np.array(vals), 0) * 100
    ax2.barh(x, v, left=left, height=0.62, color=col, edgecolor=SURFACE, linewidth=1.5, label=name)
    if name == "NCO":
        for i, (l, vi) in enumerate(zip(left, v)):
            ax2.text(l + vi / 2, i, f"{vi:.0f}%", ha="center", va="center", fontsize=8.5, color="white")
    left += v
ax2.set_yticks(x, SPECS, fontsize=9)
ax2.invert_yaxis()
ax2.set_xlabel("占整链最优解总误差功率的比例（%）")
ax2.set_xlim(0, 104)
ax2.grid(axis="y", visible=False)
ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=8.5)
ax2.set_title("(b) 整链最优解的误差份额", fontsize=10.5, color=INK)
fig.subplots_adjust(wspace=0.32)
save(fig, "fig_c2_stagewise")
