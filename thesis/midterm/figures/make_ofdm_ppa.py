"""OFDM 接收内环：三组全部候选的 PPA 散点（面积 × 最小时钟周期 × 功耗）与非支配前沿。

用法：python make_ofdm_ppa.py <ppa_all.json> <输出目录>
功耗为 OpenSTA 在 12.5 ns、全局翻转率 0.1 下的估计（不是真实激励下的功耗），只作相对参考。
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from src.style import use_data_style

INK2, GRID, SURFACE, C_NAIVE = "#52514e", "#e4e3df", "#fcfcfb", "#8a8984"
COL = {"verilog": "#2a78d6", "dsp_me": "#1baf7a", "dsp_agent": "#7a5bd6"}
LAB = {"verilog": "原语+搜索 ", "dsp_me": "原语", "dsp_agent": "直接写verilog，Claude agent"}
use_data_style()
rows = [r for r in json.loads(Path(sys.argv[1]).read_text()) if r["passed"]]


def front(pts, keys):
    out = []
    for p in pts:
        if not any(all(q[k] <= p[k] for k in keys) and any(q[k] < p[k] for k in keys) for q in pts):
            out.append(p)
    return out


fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
for ax, (yk, ylab) in zip(axes, [("min_period_ns", "最小时钟周期（ns，越小越快）"), ("power_mw", "功耗（mW，翻转率 0.1 估计）")]):
    for g in COL:
        pts = [r for r in rows if r["group"] == g]
        ax.scatter([p["area"] / 1e3 for p in pts], [p[yk] for p in pts], s=34, color=COL[g], alpha=0.85,
                   edgecolor=SURFACE, linewidth=0.8, label=LAB[g], zorder=3)
    fr = sorted(front(rows, ["area", yk]), key=lambda p: p["area"])
    ax.step([p["area"] / 1e3 for p in fr], [p[yk] for p in fr], where="post", color=INK2, linestyle="--",
            linewidth=1.1, zorder=2, label="非支配前沿（全部候选）")
    ax.set_xscale("log")
    ax.set_xlabel(r"面积（千 $\mu\mathrm{m}^2$，Nangate45）")
    ax.set_ylabel(ylab)
axes[0].axhline(12.5, color=C_NAIVE, linewidth=0.8)
axes[0].text(12, 12.0, "约束 12.5 ns", fontsize=8, color=INK2, va="top")
axes[1].legend(fontsize=8, loc="upper left")
fig.tight_layout()
out = Path(sys.argv[2])
fig.savefig(out / "fig_ofdm_ppa.png", dpi=220, bbox_inches="tight")
fig.savefig(out / "fig_ofdm_ppa.pdf", bbox_inches="tight")
for yk in ("min_period_ns", "power_mw"):
    print(yk, [(p["group"], p["file"], round(p["area"]), round(p[yk], 2)) for p in sorted(front(rows, ["area", yk]), key=lambda p: p["area"])])
