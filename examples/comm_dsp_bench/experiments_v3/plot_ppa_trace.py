"""搜索中每次真实综合的面积与目标时钟下 wns（数据来自各 agent 工作区的 tool_log.jsonl）。

用法：python plot_ppa_trace.py
输出：thesis/midterm/figures/v4/ppa_trace.{png,pdf}
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/chengzhy/verievolve/thesis/midterm/figures/src")
from style import C_BASE, C_OURS, C_REF, GRID, INK2, use_data_style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

WS = Path("/Users/chengzhy/verievolve_agent_ws")
OUT = Path("/Users/chengzhy/verievolve/thesis/midterm/figures/v4")
RUNS = [
    ("r1_real_r32_narrow_full_1", "链路 A 运行 1（2 ns）", C_OURS),
    ("r1_real_r32_narrow_full_2", "链路 A 运行 2（2 ns）", "#4a3aa7"),
    ("r1_ofdm_tx64_gen_full_1", "链路 C 任意输入（2.5 ns）", C_REF),
]


def calls(ws):
    rows = [json.loads(l) for l in (WS / ws / "tool_log.jsonl").read_text().splitlines() if l.strip()]
    # 运行 1 的 work/t_nomix.py 是去掉混频的分析用片段，不是完整候选，不画
    return [r for r in rows if r["cmd"] in ("ppa", "ppa_vcd") and "t_nomix" not in r.get("file", "")]


def main():
    use_data_style()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.2, 5.2), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    for ws, name, c in RUNS:
        cs = calls(ws)
        x = list(range(1, len(cs) + 1))
        area = [r["area_um2"] / 1e3 for r in cs]
        wns = [r["wns_ns"] for r in cs]
        ax1.plot(x, area, "-", color=c, lw=1.6, label=name, zorder=2)
        ax2.plot(x, wns, "-", color=c, lw=1.6, zorder=2)
        for xi, a, w in zip(x, area, wns):
            bad = w < 0
            kw = dict(s=34, zorder=3, edgecolor=C_BASE if bad else c, linewidth=1.4)
            ax1.scatter([xi], [a], facecolor="white" if bad else c, **kw)
            ax2.scatter([xi], [w], facecolor="white" if bad else c, **kw)
    ax2.axhline(0, color=C_BASE, lw=1.0, ls="--", zorder=1)
    ax2.text(1.1, 0.12, "wns = 0（目标时钟）", color=C_BASE, fontsize=8.5)
    ax1.set_ylabel(r"综合面积 ($10^3\ \mu\mathrm{m}^2$)")
    ax2.set_ylabel("目标时钟下 wns (ns)")
    ax2.set_xlabel("搜索中第几次真实综合")
    ax2.set_ylim(-3.4, 1.4)
    ax1.legend(frameon=False, fontsize=8.5, loc="upper right")
    ax1.text(0.01, 0.04, "空心点：时序不收敛（wns < 0）", transform=ax1.transAxes, fontsize=8.5, color=INK2)
    for ax in (ax1, ax2):
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    ax2.set_xticks(range(1, 11))
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"ppa_trace.{ext}", dpi=220, bbox_inches="tight")
    print("wrote", OUT / "ppa_trace.png")


if __name__ == "__main__":
    main()
