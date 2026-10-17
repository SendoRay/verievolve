"""OFDM 接收内环（ofdm_rx64）：两种设计途径的面积轨迹对比（真实 Nangate45 综合面积）。

用法：python make_ofdm_traces.py <Verilog 组 jsonl> <原语组（手写）jsonl> <前馈原语最优面积> <输出目录> <手写组留出全过的最终面积> [原语组（agent）jsonl]
“达标”指搜索场景达标；留出场景复核结果用最后一个参数单独标注。
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, NullFormatter
from src.style import use_data_style

C_OURS, C_BASE, C_REF, C_NAIVE, C_AG = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984", "#7a5bd6"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
use_data_style()


def load(path):
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    return [r for r in rows if r.get("area") is not None and not r["file"].startswith("direct_start")]


def trace(ax, rows, color, label, start=None):
    xs = list(range(1, len(rows) + 1))
    best, bx, by = start, ([0] if start else []), ([start / 1e3] if start else [])
    for x, r in zip(xs, rows):
        ok = r["passed"]
        ax.scatter([x], [r["area"] / 1e3], s=46, color=color if ok else C_NAIVE, edgecolor=SURFACE, linewidth=1.2, zorder=3)
        if ok and (best is None or r["area"] < best):
            best = r["area"]
        if best is not None:
            bx.append(x); by.append(best / 1e3)
    ax.step(bx, by, where="post", color=color, linewidth=2, zorder=2, label=label)
    return best


ver, prim = load(sys.argv[1]), load(sys.argv[2])
ff = float(sys.argv[3])
fig, ax = plt.subplots(figsize=(9.2, 3.8))
ax.scatter([0], [114.6348], s=46, color=C_BASE, zorder=3)
ax.annotate("Verilog 直写起点 114.6k", (0, 114.6348), xytext=(8, -2), textcoords="offset points", fontsize=8.5, color=INK2, va="top")
bv = trace(ax, ver, C_OURS, "原语+树搜索", start=114634.8)
bp = trace(ax, prim, C_REF, "原语")
if len(sys.argv) > 6:
    ag = load(sys.argv[6])
    ba = trace(ax, ag, C_AG, "直接写verilog")
    ax.annotate(f"{ba / 1e3:.1f}k", (len(ag), ba / 1e3), xytext=(6, -12), textcoords="offset points", fontsize=8.5, color=C_AG)
ax.axhline(ff / 1e3, color=C_BASE, linestyle="--", linewidth=1.2)
ax.text(max(len(ver), len(prim)) + 0.3, ff / 1e3, f"只有前馈原语时最优 {ff / 1e3:.1f}k", va="center", fontsize=8.5, color=INK2)
ax.annotate(f"{bv / 1e3:.1f}k", (len(ver), bv / 1e3), xytext=(6, -10), textcoords="offset points", fontsize=8.5, color=C_OURS)
lab = f"{bp / 1e3:.1f}k"
if len(sys.argv) > 5:
    fin = float(sys.argv[5])
    lab += f"（留出未全过）；留出全过的最终设计 {fin / 1e3:.1f}k"
ax.annotate(lab, (len(prim), bp / 1e3), xytext=(6, 4), textcoords="offset points", fontsize=8.5, color=C_REF)
ax.scatter([], [], s=46, color=C_NAIVE, label="未达标")
ax.set_yscale("log")
ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
ax.yaxis.set_minor_formatter(NullFormatter())
ax.set_xlabel("候选编号（按时间顺序）")
ax.set_ylabel(r"面积（千 $\mu\mathrm{m}^2$，Nangate45 综合）")
ax.set_xticks(range(0, max(len(ver), len(prim)) + 1))
ax.set_title("“达标”指搜索场景；留出场景（未给出的调制 / 功率 / 多径）另行复核", fontsize=8.5, color=INK2, loc="left")
ax.legend(loc="upper right", fontsize=8.5)
out = Path(sys.argv[4])
fig.savefig(out / "fig_ofdm_traces.png", dpi=220, bbox_inches="tight")
fig.savefig(out / "fig_ofdm_traces.pdf", bbox_inches="tight")
print("wrote fig_ofdm_traces")
