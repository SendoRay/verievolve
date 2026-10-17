"""图：同预算 120 次评价下的进化曲线（论文 fig:curves）。"""
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, NullFormatter
from style import C_BASE, C_OURS, C_REF, INK, save, use_data_style

# ===== 数据（可直接修改） =====
# (方法, 规格, 种子): [(评价次数, 当前最优面积 / 直写起点), ...]，只记录最优值发生变化的点（阶梯图）。
# 来源 curves_M_B3_v2_20261010.csv。方法：M = 本方法，B3_numeric = 随机数值变异，B3_struct = 随机结构变异
CURVES = {
    ('B3_numeric', 'dev_r16_narrow', 0): [(1, 1.0), (26, 0.9997), (89, 0.8012), (116, 0.7953), (120, 0.7953)],
    ('B3_numeric', 'dev_r16_narrow', 1): [(1, 1.0), (51, 0.8165), (120, 0.8165)],
    ('B3_numeric', 'dev_r16_wide', 0): [(1, 1.0), (72, 0.7816), (90, 0.7768), (118, 0.7739), (120, 0.7739)],
    ('B3_numeric', 'dev_r16_wide', 1): [(1, 1.0), (120, 1.0)],
    ('B3_numeric', 'dev_r32_narrow', 0): [(1, 1.0), (26, 0.9998), (88, 0.7992), (115, 0.7954), (120, 0.7954)],
    ('B3_numeric', 'dev_r32_narrow', 1): [(1, 1.0), (91, 0.9561), (120, 0.9561)],
    ('B3_numeric', 'dev_r32_wide', 0): [(1, 1.0), (26, 0.9999), (109, 0.9726), (117, 0.9711), (120, 0.9711)],
    ('B3_numeric', 'dev_r32_wide', 1): [(1, 1.0), (92, 0.9477), (120, 0.9477)],
    ('B3_numeric', 'dev_r64_narrow', 0): [(1, 1.0), (80, 0.9984), (91, 0.7459), (118, 0.7441), (120, 0.7441)],
    ('B3_numeric', 'dev_r64_narrow', 1): [(1, 1.0), (120, 1.0)],
    ('B3_numeric', 'dev_r64_wide', 0): [(1, 1.0), (27, 0.9999), (39, 0.9785), (72, 0.7741), (118, 0.773), (120, 0.773)],
    ('B3_numeric', 'dev_r64_wide', 1): [(1, 1.0), (92, 0.9475), (120, 0.9475)],
    ('B3_struct', 'dev_r16_narrow', 0): [(1, 1.0), (12, 0.859), (72, 0.859), (120, 0.859)],
    ('B3_struct', 'dev_r16_narrow', 1): [(1, 1.0), (120, 1.0)],
    ('B3_struct', 'dev_r16_wide', 0): [(1, 1.0), (60, 0.9997), (64, 0.7849), (115, 0.7816), (120, 0.7816)],
    ('B3_struct', 'dev_r16_wide', 1): [(1, 1.0), (82, 0.9998), (120, 0.9998)],
    ('B3_struct', 'dev_r32_narrow', 0): [(1, 1.0), (60, 0.9996), (64, 0.7992), (94, 0.7992), (120, 0.7992)],
    ('B3_struct', 'dev_r32_narrow', 1): [(1, 1.0), (81, 0.9998), (120, 0.9998)],
    ('B3_struct', 'dev_r32_wide', 0): [(1, 1.0), (60, 0.9999), (65, 0.9447), (77, 0.9328), (120, 0.9328)],
    ('B3_struct', 'dev_r32_wide', 1): [(1, 1.0), (120, 1.0)],
    ('B3_struct', 'dev_r64_narrow', 0): [(1, 1.0), (60, 0.9998), (64, 0.7459), (94, 0.7459), (120, 0.7459)],
    ('B3_struct', 'dev_r64_narrow', 1): [(1, 1.0), (43, 0.7459), (120, 0.7459)],
    ('B3_struct', 'dev_r64_wide', 0): [(1, 1.0), (60, 0.9999), (65, 0.9452), (77, 0.9333), (114, 0.8197), (120, 0.8197)],
    ('B3_struct', 'dev_r64_wide', 1): [(1, 1.0), (82, 0.9999), (120, 0.9999)],
    ('M', 'dev_r16_narrow', 0): [(1, 0.6497), (6, 0.301), (65, 0.292), (71, 0.2318), (117, 0.2264), (120, 0.2264)],
    ('M', 'dev_r16_wide', 0): [(1, 1.0), (2, 0.4872), (6, 0.4412), (7, 0.3269), (16, 0.3168), (22, 0.2703), (31, 0.2491), (37, 0.2369), (51, 0.2268), (56, 0.215), (61, 0.2141), (67, 0.1388), (120, 0.1388)],
    ('M', 'dev_r32_narrow', 0): [(1, 1.0), (3, 0.8187), (7, 0.4344), (14, 0.2087), (30, 0.1962), (44, 0.1745), (48, 0.1689), (51, 0.1369), (73, 0.1296), (86, 0.1185), (110, 0.1178), (118, 0.1135), (120, 0.1135)],
    ('M', 'dev_r32_wide', 0): [(1, 1.0), (14, 0.82), (32, 0.4521), (41, 0.2428), (55, 0.1987), (72, 0.1816), (85, 0.1424), (86, 0.1375), (112, 0.1294), (120, 0.1294)],
    ('M', 'dev_r64_narrow', 0): [(1, 1.0), (5, 0.7994), (9, 0.2838), (12, 0.184), (21, 0.1638), (28, 0.1288), (53, 0.1143), (73, 0.1142), (103, 0.1074), (120, 0.1074)],
    ('M', 'dev_r64_wide', 0): [(1, 1.0), (5, 0.2455), (9, 0.1974), (18, 0.162), (31, 0.1127), (35, 0.1065), (118, 0.1018), (120, 0.1018)],
}
SPEC_LABEL = {
    "dev_r16_narrow": "R16 窄带", "dev_r16_wide": "R16 宽带", "dev_r32_narrow": "R32 窄带",
    "dev_r32_wide": "R32 宽带", "dev_r64_narrow": "R64 窄带", "dev_r64_wide": "R64 宽带",
}
METHODS = {"M": (C_OURS, "进化搜索（LLM）"), "B3_numeric": (C_BASE, "随机数值变异"), "B3_struct": (C_REF, "随机结构变异")}
BUDGET = 120
# ==============================

use_data_style()
fig, axes = plt.subplots(2, 3, figsize=(9.6, 4.6), sharex=True, sharey=True)
for ax, (spec, label) in zip(axes.flat, SPEC_LABEL.items()):
    for m in ["B3_numeric", "B3_struct", "M"]:
        col, _ = METHODS[m]
        for (mm, ss, _seed), pts in CURVES.items():
            if mm == m and ss == spec:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                if xs[-1] < BUDGET:
                    xs.append(BUDGET)
                    ys.append(ys[-1])
                ax.step(xs, ys, where="post", color=col, linewidth=2 if m == "M" else 1.3)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_title(label, fontsize=10, color=INK)
    ax.set_ylim(0.08, 1.3)
    ax.set_xlim(0, BUDGET)
for ax in axes[1]:
    ax.set_xlabel("评价次数")
for ax in axes[:, 0]:
    ax.set_ylabel("最优面积 / 直写起点")
handles = [plt.Line2D([], [], color=METHODS[m][0], linewidth=2, label=METHODS[m][1]) for m in ["M", "B3_numeric", "B3_struct"]]
fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02), fontsize=9.5)
fig.subplots_adjust(hspace=0.28, wspace=0.1)
save(fig, "fig_c3_curves")
