"""中期报告的数据图。只读已有实验结果，不跑实验。

用法：python make_data_figures.py <experiments_dspgraph 目录> <输出目录>
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.font_config import SIMPLIFIED_CHINESE_FONTS, register_simplified_chinese_fonts

B = Path(sys.argv[1])
OUT = Path(sys.argv[2])

# 角色配色（已用 dataviz 校验脚本验证）：本方法 / 对照基线 / 专家参考 / 直写起点
C_OURS, C_BASE, C_REF, C_NAIVE = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
C_EXTRA = ["#eda100", "#e87ba4"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

register_simplified_chinese_fonts()

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": SIMPLIFIED_CHINESE_FONTS,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.size": 10,
        "axes.edgecolor": INK2,
        "axes.labelcolor": INK,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "legend.frameon": False,
    }
)

SPECS = [
    "dev_r16_narrow",
    "dev_r16_wide",
    "dev_r32_narrow",
    "dev_r32_wide",
    "dev_r64_narrow",
    "dev_r64_wide",
]
LABEL = {
    "dev_r16_narrow": "R16 窄带",
    "dev_r16_wide": "R16 宽带",
    "dev_r32_narrow": "R32 窄带",
    "dev_r32_wide": "R32 宽带",
    "dev_r64_narrow": "R64 窄带",
    "dev_r64_wide": "R64 宽带",
}


def load(name):
    return json.loads((B / name).read_text(encoding="utf-8"))


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", dpi=220, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


main = {r["spec"]: r for r in load("main_table_v2_20261010.json")["rows"]}
x = np.arange(len(SPECS))
xt = [LABEL[s] for s in SPECS]


def fig_motivation():
    """同一公式两种实现的真实面积。"""
    naive = [main[s]["naive_real"] / 1e3 for s in SPECS]
    ref = [main[s]["R_real"] / 1e3 for s in SPECS]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    w = 0.36
    ax.bar(x - w / 2, naive, w, color=C_NAIVE, edgecolor=SURFACE, linewidth=1.5, label="照公式直写")
    ax.bar(x + w / 2, ref, w, color=C_REF, edgecolor=SURFACE, linewidth=1.5, label="教科书多速率结构")
    for i, (a, b) in enumerate(zip(naive, ref)):
        ax.text(i + w / 2, b * 1.15, f"小 {a / b:.0f} 倍", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_yscale("log")
    ax.set_ylabel("真实综合面积（千 μm²）")
    ax.set_xticks(x, xt)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", ncol=2)
    ax.set_ylim(10, 9000)
    save(fig, "fig4_motivation")


def fig_main():
    """主结果：直写起点、本方法、专家模板的真实面积。"""
    naive = [main[s]["naive_real"] / 1e3 for s in SPECS]
    ours = [main[s]["M_real"] / 1e3 for s in SPECS]
    ref = [main[s]["R_real"] / 1e3 for s in SPECS]
    fig, ax = plt.subplots(figsize=(6.8, 3.3))
    w = 0.26
    ax.bar(x - w, naive, w, color=C_NAIVE, edgecolor=SURFACE, linewidth=1.5, label="直写起点")
    ax.bar(x, ours, w, color=C_OURS, edgecolor=SURFACE, linewidth=1.5, label="本方法")
    ax.bar(x + w, ref, w, color=C_REF, edgecolor=SURFACE, linewidth=1.5, label="专家模板（参考上限）")
    for i, (a, b) in enumerate(zip(naive, ours)):
        ax.text(i, b * 1.15, f"−{(1 - b / a) * 100:.0f}%", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_yscale("log")
    ax.set_ylabel("真实综合面积（千 μm²）")
    ax.set_xticks(x, xt)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", ncol=3, fontsize=9)
    ax.set_ylim(10, 12000)
    save(fig, "fig_main_area")


def fig_lineage():
    """挑战一：演化路径。"""
    anc = load("ancestry_M_r32w_r64n_v2_20261010.json")
    paths = {
        "R32 宽带": (
            [1.000, 4.056, 0.243, 0.138, 0.129],
            ["直写起点", "多相分解\n（未达标）", "两级抽取\n+ 多相", "1/4 波查表\n+ 三级抽取", "缩短字长"],
            [True, False, True, True, True],
            [(0, -14), (0, 12), (44, 4), (0, 12), (0, 12)],
        ),
        "R64 窄带": (
            [1.000, 0.184, 0.114, 0.107],
            ["直写起点", "相位截短到 14 位\n+ 两级抽取", "相位截短\n到 12 位", "缩短字长"],
            [True, True, True, True],
            [(0, 12), (52, 6), (0, 12), (0, 12)],
        ),
    }
    del anc  # 数值与人工归纳的变换名取自该文件的 note 与实验方汇报
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.5), sharey=True, gridspec_kw={"width_ratios": [5, 4]})
    for ax, (title, (ys, names, ok, _offs)) in zip(axes, paths.items()):
        xs = np.arange(len(ys))
        ax.plot(xs, ys, color=C_OURS, linewidth=2, zorder=2)
        for xi, yi, good in zip(xs, ys, ok):
            ax.scatter([xi], [yi], s=70, zorder=3, color=C_OURS if good else C_NAIVE, edgecolor=SURFACE, linewidth=2)
            ax.annotate(f"{yi:.3f}", (xi, yi), textcoords="offset points", xytext=(9, 7), fontsize=9.5, color=INK)
        ax.set_yscale("log")
        ax.set_title(title, fontsize=10.5, color=INK)
        ax.set_xticks(xs, names, fontsize=8.5)
        ax.set_xlim(-0.5, len(ys) - 0.4)
        ax.set_ylim(0.07, 9)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("面积 / 直写起点")
    axes[0].scatter([], [], s=70, color=C_OURS, label="达标")
    axes[0].scatter([], [], s=70, color=C_NAIVE, label="未达标的中间设计")
    axes[0].legend(loc="upper right", fontsize=9)
    fig.subplots_adjust(wspace=0.08)
    save(fig, "fig_c1_lineage")


def fig_stagewise():
    """挑战二：逐级最优再拼接 vs 整链优化；误差份额。"""
    e21 = {r["spec"]: r for r in load("e21_stagewise_v1_20261011/E21_summary.json")["rows"]}
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.2, 3.5), gridspec_kw={"width_ratios": [1.05, 1]})
    w = 0.36
    chain, stage, note = [], [], []
    for s in SPECS:
        r = e21[s]
        chain.append(r["chain_opt"]["best_real"] / 1e3)
        if "A_asdesigned" in r and r["A_asdesigned"]["search_passed"]:
            stage.append(r["A_asdesigned"]["real_area"] / 1e3)
            note.append(None)
        elif "A_justpassing" in r:
            stage.append(r["A_justpassing"]["real_area"] / 1e3)
            note.append(None)
        else:
            stage.append(0)
            note.append(r["A_firstfeasible"]["search_margin"])
    ax.bar(x - w / 2, stage, w, color=C_BASE, edgecolor=SURFACE, linewidth=1.5, label="逐级最优再拼接")
    ax.bar(x + w / 2, chain, w, color=C_OURS, edgecolor=SURFACE, linewidth=1.5, label="整链优化")
    for i, (a, b, n) in enumerate(zip(stage, chain, note)):
        if n is None:
            ax.text(i, max(a, b) + 4, f"整链省 {(1 - b / a) * 100:.0f}%", ha="center", fontsize=9, color=INK)
        else:
            ax.text(i - w / 2, 4, "无达标解", ha="center", fontsize=8.5, color=INK2, rotation=90, va="bottom")
    ax.set_ylabel("真实综合面积（千 μm²）")
    ax.set_xticks(x, xt, fontsize=9)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", fontsize=9)
    ax.set_ylim(0, 150)
    ax.set_title("(a) 同一模板空间内的面积", fontsize=10.5, color=INK)

    shares = {r["spec"]: r["share_of_total_error"] for r in load("e21_stagewise_v1_20261011/error_shares_E22_normalized.json")["rows"]}
    parts = [
        ("ADC 量化 + 滤波结构", ["all_wide_baseline(ADC+structure)"], C_NAIVE),
        ("NCO", ["nco(P,A)"], C_OURS),
        ("混频字长", ["mixer_word(Wm)"], C_BASE),
        ("滤波系数", ["fir_coef(Cf)", "halfband(Ch,Wh)"], C_REF),
        ("CIC 字长", ["cic_word(Wc)"], C_EXTRA[0]),
    ]
    left = np.zeros(len(SPECS))
    for name, keys, col in parts:
        v = np.array([max(0.0, sum(shares[s].get(k, 0.0) for k in keys)) * 100 for s in SPECS])
        ax2.barh(x, v, left=left, height=0.62, color=col, edgecolor=SURFACE, linewidth=1.5, label=name)
        if name == "NCO":
            for i, (l, vi) in enumerate(zip(left, v)):
                ax2.text(l + vi / 2, i, f"{vi:.0f}%", ha="center", va="center", fontsize=8.5, color="white")
        left += v
    ax2.set_yticks(x, xt, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlabel("占整链最优解总误差功率的比例（%）")
    ax2.set_xlim(0, 104)
    ax2.grid(axis="y", visible=False)
    ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=8.5)
    ax2.set_title("(b) 整链最优解的误差份额", fontsize=10.5, color=INK)
    fig.subplots_adjust(wspace=0.32)
    save(fig, "fig_c2_stagewise")


def fig_curves():
    """挑战三：进化曲线，本方法 vs 非 LLM 搜索。"""
    data = defaultdict(list)
    with open(B / "curves_M_B3_v2_20261010.csv", newline="") as f:
        for r in csv.DictReader(f):
            data[(r["method"], r["spec"], r["seed"])].append((int(r["eval"]), float(r["best_rel"])))
    style = {"B3_numeric": (C_BASE, "随机数值变异"), "B3_struct": (C_REF, "随机结构变异"), "M": (C_OURS, "本方法")}
    fig, axes = plt.subplots(2, 3, figsize=(9.6, 4.6), sharex=True, sharey=True)
    for ax, s in zip(axes.flat, SPECS):
        for m in ["B3_numeric", "B3_struct", "M"]:
            col, _ = style[m]
            for (mm, ss, _seed), pts in data.items():
                if mm == m and ss == s:
                    pts = sorted(pts)
                    ax.step([p[0] for p in pts], [p[1] for p in pts], where="post", color=col, linewidth=2 if m == "M" else 1.3)
        ax.set_yscale("log")
        ax.set_title(LABEL[s], fontsize=10, color=INK)
        ax.set_ylim(0.08, 1.3)
        ax.set_xlim(0, 120)
    for ax in axes[1]:
        ax.set_xlabel("评价次数")
    for ax in axes[:, 0]:
        ax.set_ylabel("最优面积 / 直写起点")
    handles = [plt.Line2D([], [], color=style[m][0], linewidth=2, label=style[m][1]) for m in ["M", "B3_numeric", "B3_struct"]]
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02), fontsize=9.5)
    fig.subplots_adjust(hspace=0.28, wspace=0.1)
    save(fig, "fig_c3_curves")


def fig_feedback():
    """挑战三：反馈档位。"""
    rows = load("groupA_v1_20261011/A3_feedback_4seeds_analysis.json")["rows"]
    modes = ["scalar", "metrics", "verified"]
    names = ["只给分数", "给全部指标", "再加诊断归因"]
    by = defaultdict(dict)
    for r in rows:
        by[(r["spec"], r["seed"])][r["mode"]] = r["rel"]
    fig, ax = plt.subplots(figsize=(4.6, 3.3))
    for vals in by.values():
        ax.plot(range(3), [vals[m] for m in modes], color=C_NAIVE, linewidth=1, marker="o", markersize=4, alpha=0.75)
    gm = [float(np.exp(np.mean([np.log(v[m]) for v in by.values()]))) for m in modes]
    ax.plot(range(3), gm, color=C_OURS, linewidth=2.4, marker="o", markersize=8, markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
    for i, g in enumerate(gm):
        ax.annotate(f"{g:.3f}", (i, g), textcoords="offset points", xytext=(10, 6), fontsize=9.5, color=INK)
    ax.set_yscale("log")
    ax.set_yticks([0.1, 0.2, 0.3, 0.4], ["0.1", "0.2", "0.3", "0.4"])
    ax.minorticks_off()
    ax.set_xticks(range(3), names)
    ax.set_xlim(-0.3, 2.45)
    ax.set_ylabel("最优面积 / 直写起点")
    ax.grid(axis="x", visible=False)
    ax.plot([], [], color=C_OURS, linewidth=2.4, marker="o", label="几何均值")
    ax.plot([], [], color=C_NAIVE, linewidth=1, marker="o", markersize=4, label="单次运行（规格 × 种子）")
    ax.legend(loc="upper right", fontsize=8.5)
    save(fig, "fig_c3_feedback")


def fig_ppa_scatter():
    """散点图一：面积–关键路径。"""
    rows = load("timing_summary_v1_20261011.json")["rows"]
    style = {"naive": (C_NAIVE, "o", "直写起点"), "M": (C_OURS, "s", "本方法"), "R": (C_REF, "^", "专家模板")}
    fig, ax = plt.subplots(figsize=(5.4, 3.6))
    seen = set()
    for r in rows:
        key = "naive" if r["name"].lower().startswith("naive") else r["name"]
        if key not in style:
            continue
        col, mk, lab = style[key]
        ax.scatter(
            r["critical_path_ps_sized"] / 1e3,
            r["area_um2_sized"] / 1e3,
            s=64,
            color=col,
            marker=mk,
            edgecolor=SURFACE,
            linewidth=1.5,
            label=None if key in seen else lab,
            zorder=3,
        )
        seen.add(key)
    ax.set_yscale("log")
    ax.set_xlabel("关键路径延迟（ns）")
    ax.set_ylabel("面积（千 μm²）")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=9)
    ax.text(0.03, 0.04, "← 左下更优", transform=ax.transAxes, fontsize=9, color=INK2)
    save(fig, "fig_scatter_area_timing")


def fig_margin_scatter():
    """散点图二：搜索裕量 vs 留出裕量，裁判 v1 与 v2。"""
    rows = load("margin_pairs_v1_v2_20261010.json")
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.4), sharex=True)
    for ax, judge, col, title in [(axes[0], "v1", C_BASE, "裁判 v1：3 个阻塞音"), (axes[1], "v2", C_OURS, "裁判 v2：覆盖全部混叠带")]:
        pts = [(r["search_margin_db"], r["holdout_margin_db"]) for r in rows if r["judge"] == judge]
        ax.axhline(0, color=INK2, linewidth=0.8)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=34, color=col, edgecolor=SURFACE, linewidth=1, alpha=0.9, zorder=3)
        n_ok = sum(p[1] >= 0 for p in pts)
        ax.set_title(f"{title}\n留出达标 {n_ok}/{len(pts)}", fontsize=10, color=INK)
        ax.set_xlabel("搜索场景裕量（dB）")
    axes[0].set_ylabel("留出场景裕量（dB）")
    axes[0].text(0.97, 0.42, "达标线以下：\n对搜索场景过拟合", transform=axes[0].transAxes, ha="right", fontsize=9, color=INK2)
    fig.subplots_adjust(wspace=0.22)
    save(fig, "fig_scatter_margin")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_motivation()
    fig_main()
    fig_lineage()
    fig_stagewise()
    fig_curves()
    fig_feedback()
    fig_ppa_scatter()
    fig_margin_scatter()
