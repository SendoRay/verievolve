"""图：编码智能体在本框架工具上设计 R32 窄带 DDC 的轨迹（论文 fig:agenttrace）。

智能体只看任务契约，通过本框架的裁判 / 编译器 / 探针工具逐步改写原语程序。
"""
import matplotlib.pyplot as plt
from style import C_NAIVE, C_OURS, C_REF, INK2, SURFACE, save, use_data_style

# ===== 数据（可直接修改） =====
# 候选按提交顺序：(候选名, 面积 μm²（代理模型）, 是否达标（含 0.3 dB 安全裕量判断）, 搜索裕量 dB)
# 来源 /Users/chengzhy/verievolve_agent_ws/dev_r32_narrow/candidates.jsonl（去掉直写起点、标定程序与 final.py）
CANDIDATES = [
    ('c02', 25757.3, False, -8.9),
    ('c03', 25757.3, False, -8.9),
    ('c04', 18838.8, False, -24.8),
    ('c05', 18838.8, False, -24.7),
    ('c06', 22580.3, False, -24.6),
    ('c07', 19341.3, False, -9.7),
    ('c08', 23853.4, False, -1.57),
    ('c09', 27327.7, True, 0.8),
    ('c10', 24198.0, True, 0.76),
    ('c11', 18895.9, True, 0.5),
    ('c12', 17519.1, True, 0.68),
    ('c13', 16609.2, True, 1.55),
    ('c14', 14779.7, False, -1.34),
    ('c15', 15879.7, True, 1.09),
    ('c17', 15547.0, True, 1.46),
    ('c18', 15270.4, True, 1.855),
    ('c19', 14641.4, True, 1.578),
    ('c20', 14225.8, True, 1.192),
    ('c21', 13766.6, True, 1.407),
    ('c22', 13466.2, False, -54.8),
    ('c23', 13490.2, True, 0.107),
    ('c24', 13160.4, True, 1.15),
    ('c25', 12996.0, True, 1.134),
    ('c26', 12773.4, True, 0.529),
    ('c27', 12896.4, True, 0.756),
    ('c28', 12725.1, True, 0.583),
    ('c29', 12760.6, True, 0.549),
    ('c30', 12720.0, True, 0.611),
    ('c31', 12633.0, False, 0.261),
    ('c32', 12644.5, True, 0.385),
]
# 参考线：(数值 千 μm², 标签, 颜色)
REFS = [
    (29.2, "固定结构参数调优（真实面积，仅参考）", C_REF),
]
# ==============================

use_data_style()
xs = list(range(1, len(CANDIDATES) + 1))
fig, ax = plt.subplots(figsize=(9.2, 3.6))
best, bx, by = None, [], []
for x, (_, area, ok, _m) in zip(xs, CANDIDATES):
    ax.scatter([x], [area / 1e3], s=46, color=C_OURS if ok else C_NAIVE, edgecolor=SURFACE, linewidth=1.3, zorder=3)
    if ok and (best is None or area < best):
        best = area
    if best is not None:
        bx.append(x)
        by.append(best / 1e3)
ax.step(bx, by, where="post", color=C_OURS, linewidth=2, zorder=2, label="当前最优达标面积")
for y, lab, col in REFS:
    ax.axhline(y, color=col, linestyle="--", linewidth=1.3, zorder=1)
    ax.text(len(CANDIDATES) + 0.5, y * 1.06, lab, ha="right", va="bottom", fontsize=8.5, color=col)
ax.set_yscale("log")
ax.set_ylim(10, 130)
ax.set_yticks([10, 20, 30, 50, 100], ["10", "20", "30", "50", "100"])
ax.minorticks_off()
ax.set_xlim(0.3, len(CANDIDATES) + 0.7)
ax.set_xlabel("候选编号（按提交顺序）")
ax.set_ylabel(r"面积（千 $\mu\mathrm{m}^2$，代理模型）")
ax.set_xticks(xs[::2] if len(xs) > 20 else xs)
ax.grid(axis="x", visible=False)
ax.scatter([], [], s=46, color=C_OURS, label="达标候选")
ax.scatter([], [], s=46, color=C_NAIVE, label="未达标候选")
ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.86), fontsize=8.5, ncol=3)
save(fig, "fig_agent_trace")
