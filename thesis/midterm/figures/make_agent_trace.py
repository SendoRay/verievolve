"""Claude agent 在 r32n 上的设计轨迹（读取工作区 candidates.jsonl）。

用法：python make_agent_trace.py <candidates.jsonl> <输出目录>
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 与 make_data_figures.py 相同的角色配色
C_OURS, C_BASE, C_REF, C_NAIVE = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({"font.sans-serif": ["PingFang SC", "Heiti SC", "Arial Unicode MS"], "axes.unicode_minus": False,
                     "font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": GRID, "axes.axisbelow": True, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                     "savefig.facecolor": SURFACE, "legend.frameon": False})

rows = [json.loads(l) for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]
rows = [r for r in rows if r["area"] is not None and r["file"] != "direct_start.py"]
xs = list(range(1, len(rows) + 1))
fig, ax = plt.subplots(figsize=(9.2, 3.6))
best = None
bx, by = [], []
for x, r in zip(xs, rows):
    ok = r["passed"]
    ax.scatter([x], [r["area"] / 1e3], s=60, color=C_OURS if ok else C_NAIVE, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    if ok and (best is None or r["area"] < best):
        best = r["area"]
    if best is not None:
        bx.append(x); by.append(best / 1e3)
ax.step(bx, by, where="post", color=C_OURS, linewidth=2, zorder=2, label="当前最优达标面积")
for y, lab, col in [(92.264, "原进化方法 M（真实面积）", C_BASE), (29.2, "原模板参数搜索 R", C_REF)]:
    ax.axhline(y, color=col, linestyle="--", linewidth=1.3)
    ax.text(len(rows) + 0.4, y, lab, va="center", fontsize=8.5, color=INK2)
ax.set_yscale("log")
ax.set_xlabel("候选编号（按时间顺序）")
ax.set_ylabel("面积（千 μm²，代理估计）")
ax.set_xticks(xs)
ax.scatter([], [], s=60, color=C_OURS, label="达标")
ax.scatter([], [], s=60, color=C_NAIVE, label="未达标")
ax.legend(loc="center right", fontsize=8.5)
save_dir = Path(sys.argv[2])
fig.savefig(save_dir / "fig_agent_trace.png", dpi=220, bbox_inches="tight")
fig.savefig(save_dir / "fig_agent_trace.pdf", bbox_inches="tight")
print("wrote fig_agent_trace")
