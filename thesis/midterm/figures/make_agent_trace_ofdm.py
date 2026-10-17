"""Claude agent 在 OFDM 接收内环（ofdm_rx64）上的设计轨迹（读取工作区 candidates.jsonl）。

用法：python make_agent_trace_ofdm.py <candidates.jsonl> <输出目录>
面积为 Nangate45 真实综合面积；只跑功能仿真（area 为 null）的候选不画。
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, NullFormatter
from src.style import use_data_style

# 与 make_agent_trace.py 相同的角色配色
C_OURS, C_BASE, C_REF, C_NAIVE = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
use_data_style()

rows = [json.loads(l) for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]
start = next(r for r in rows if r["file"] == "direct_start.v")
rows = [r for r in rows if r.get("area") is not None and r["file"] != "direct_start.v"]
xs = list(range(1, len(rows) + 1))
fig, ax = plt.subplots(figsize=(9.2, 3.6))
best = start["area"]
bx, by = [0], [best / 1e3]
ax.scatter([0], [best / 1e3], s=60, color=C_BASE, edgecolor=SURFACE, linewidth=1.5, zorder=3)
for x, r in zip(xs, rows):
    ok = r["passed"]
    ax.scatter([x], [r["area"] / 1e3], s=60, color=C_OURS if ok else C_NAIVE, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    if ok and (best is None or r["area"] < best):
        best = r["area"]
    if best is not None:
        bx.append(x); by.append(best / 1e3)
ax.step(bx, by, where="post", color=C_OURS, linewidth=2, zorder=2, label="当前最优达标面积")
ax.annotate(f"直写起点 {start['area'] / 1e3:.1f}k", (0, start["area"] / 1e3), xytext=(8, -4),
            textcoords="offset points", fontsize=8.5, color=INK2, va="top")
ax.annotate(f"最终 {best / 1e3:.1f}k（约 1/{start['area'] / best:.0f}）", (bx[-1], by[-1]), xytext=(0, 10),
            textcoords="offset points", fontsize=8.5, color=INK2, ha="right")
ax.set_yscale("log")
ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
ax.yaxis.set_minor_formatter(NullFormatter())
ax.set_xlabel("候选编号（按时间顺序）")
ax.set_ylabel(r"面积（千 $\mu\mathrm{m}^2$，Nangate45 综合）")
ax.set_xticks([0] + xs, ["起点"] + [str(x) for x in xs])
ax.scatter([], [], s=60, color=C_OURS, label="达标")
ax.scatter([], [], s=60, color=C_NAIVE, label="未达标")
ax.legend(loc="center right", fontsize=8.5)
save_dir = Path(sys.argv[2])
fig.savefig(save_dir / "fig_agent_trace_ofdm.png", dpi=220, bbox_inches="tight")
fig.savefig(save_dir / "fig_agent_trace_ofdm.pdf", bbox_inches="tight")
print("wrote fig_agent_trace_ofdm")
