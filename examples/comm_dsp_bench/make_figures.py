#!/usr/bin/env python
"""生成论文全部 PNG 图表（matplotlib，数据来自 experiments_e1/*.json 与回归报告）。

产物写入 thesis/figures/。运行前提：E1 两臂、E3、E4、rejudge 数据就绪。
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BENCH = Path(__file__).resolve().parent
E1 = BENCH / "experiments_e1"
FIG = BENCH.parent.parent / "thesis" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
    "figure.dpi": 150, "savefig.bbox": "tight",
    "font.family": ["Arial Unicode MS", "Heiti SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
})
C_S, C_C = "#c44e52", "#4c72b0"


def load(p, default=None):
    f = E1 / p
    return json.loads(f.read_text()) if f.exists() else default


def dedup_front(pts):
    seen, out = set(), []
    for p in sorted(pts, key=lambda x: x[1]):
        key = (round(p[0], 1), round(p[1]))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def front_of(run_dir, min_score=0.5):
    from run_experiments import pareto_filter
    ckpts = sorted((run_dir / "checkpoints").glob("checkpoint_*"),
                   key=lambda p: int(p.name.split("_")[1]))
    if not ckpts:
        return []
    pts = []
    for pf in (ckpts[-1] / "programs").glob("*.json"):
        d = json.loads(pf.read_text())
        m = d.get("metrics", {})
        if m.get("combined_score", 0) > min_score and "precision" in m:
            pts.append((float(m["precision"]), float(m["area"]),
                        float(m.get("throughput", 0))))
    uniq = dedup_front(pts)
    return pareto_filter([(p, a, t) for p, a, t in uniq])


def fig_fronts():
    """图 5.1：两臂 Pareto 前沿对比（2×2）"""
    tasks = [("cmul_w16_free", "cmul（复数乘法）", 8000),
             ("cordic_sincos", "cordic_sincos（正余弦）", 3000),
             ("atan2_w16", "atan2（复数辐角）", 6000),
             ("llr_64qam_snr20", "llr（64QAM 软解调）", 8000)]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, (task, label, _) in zip(axes.flat, tasks):
        for arm, color, label2 in [("S", C_S, "Arm S（采样适应度）"),
                                   ("C", C_C, "Arm C（证书适应度）")]:
            rd = E1 / f"e1_{task}_arm{arm}_seed0"
            if not rd.exists():
                continue
            front = front_of(rd)
            if not front:
                continue
            ps = [p[0] for p in front]
            ar = [p[1] for p in front]
            ax.scatter(ar, ps, c=color, s=42, label=label2, zorder=3)
            ax.plot(sorted(ar), [p for _, a, p in sorted((p, a, p) for p, a, _ in front)],
                    c=color, alpha=0.25, lw=1)
        ax.set_title(label)
        ax.set_xlabel("面积（ice40 LUT）")
        ax.set_ylabel("SQNR（dB）")
        ax.legend(fontsize=9)
    fig.suptitle("同一 LLM、同一预算（40 迭代）下两臂的精度-面积前沿", y=1.0)
    fig.tight_layout()
    fig.savefig(FIG / "fig5_1_fronts.png")
    plt.close(fig)


def fig_rejudge():
    """图 5.2：证书-实测一致性散点（重判数据）"""
    d = load("rejudge.json")
    if not d:
        return
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    for task, marker in [("cmul_w16_free", "o"), ("cordic_sincos", "s"),
                         ("atan2_w16", "^"), ("llr_64qam_snr20", "D")]:
        pts = [r for r in d["tasks"].get(task, {}).get("rejudge", [])
               if "sampled_sqnr" in r and r.get("params")]
        xs = [p["prec_in_loop"] for p in pts]
        ys = [p["sampled_sqnr"] for p in pts]
        if pts:
            ax.scatter(xs, ys, marker=marker, s=40, label=task, alpha=0.85)
    lim = [0, 130]
    ax.plot(lim, lim, "k--", lw=1, label="y = x")
    ax.set_xlabel("环内适应度（Arm C：证书 SQNR；Arm S：采样 SQNR）")
    ax.set_ylabel("重判采样 SQNR（dB）")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "fig5_2_rejudge.png")
    plt.close(fig)


def fig_e3():
    """图 5.3：证书导航的综合预算曲线"""
    d = load("e3_nav.json")
    if not d:
        return
    fig, axes = plt.subplots(1, len(d), figsize=(5.2 * len(d), 4.2))
    if len(d) == 1:
        axes = [axes]
    for ax, (task, e) in zip(np.atleast_1d(axes), d.items()):
        g = e["curve_guided"]
        r = e["curve_random"]
        ax.plot(range(1, len(g) + 1), g, c=C_C, label="证书引导")
        ax.plot(range(1, len(r) + 1), r, c="#55a868", label="随机（均值）")
        ax.axhline(e["hv_true"], color="k", ls="--", lw=1, label="全量前沿 HV")
        ax.axvline(e["budget_guided_99"], color=C_C, ls=":", lw=1)
        ax.set_title(f"{task}\n99% 预算：证书 {e['budget_guided_99']} vs 随机 {e['budget_random_99']}")
        ax.set_xlabel("综合调用数")
        ax.set_ylabel("HV")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "fig5_3_e3_nav.png")
    plt.close(fig)


def fig_e4():
    """图 5.4：E4 位宽决策——BER 证书 vs SQNR 门槛"""
    d = load("e4_ber.json")
    if not d:
        return
    rows = d["rows"]
    bs = [r["b"] for r in rows]
    fig, ax1 = plt.subplots(figsize=(7.4, 4.6))
    ax1.plot(bs, [r["sqnr_model"] for r in rows], "o-", c="#8172b2", label="模型 SQNR（均值层）")
    ax1.plot(bs, [r["snr_min_db"] for r in rows], "s--", c="#cc8963", label="证书 SNR 下界（最坏层）")
    ax1.axhline(60, color=C_S, ls=":", lw=1.2)
    ax1.annotate("B3 竞品 60 dB 门槛", (bs[0], 61), fontsize=9, color=C_S)
    ax1.set_xlabel("系数量化小数位 b（bits）")
    ax1.set_ylabel("dB")
    ax2 = ax1.twinx()
    areas = [r["area"] for r in rows]
    ax2.plot(bs, areas, "^-", c="gray", alpha=0.6, label="综合面积 LUT")
    ax2.set_ylabel("面积（LUT）")
    if d.get("select_by_ber_cert"):
        ax1.axvline(d["select_by_ber_cert"]["b"], color=C_C, ls=":", lw=1.4)
        ax1.annotate(f"BER 证书选型 b={d['select_by_ber_cert']['b']}",
                     (d["select_by_ber_cert"]["b"], 20), fontsize=9, color=C_C)
    if d.get("select_by_sqnr60"):
        ax1.axvline(d["select_by_sqnr60"]["b"], color=C_S, ls=":", lw=1.4)
        ax1.annotate(f"SQNR 门槛选型 b={d['select_by_sqnr60']['b']}",
                     (d["select_by_sqnr60"]["b"], 32), fontsize=9, color=C_S)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="center right")
    fig.tight_layout()
    fig.savefig(FIG / "fig5_4_e4_ber.png")
    plt.close(fig)


def fig_lemma():
    """图 4.1：模分解引理（精确） vs Sobol 收敛"""
    sys.path.insert(0, str(BENCH))
    os_environ = None
    from certfit import common
    sig = common.cmul_exact_signal_power()
    xs, lem, sob = [], [], []
    for sd in range(2, 16):
        m = common.cmul_exact_err_moments(sd, mode="rne")
        exact = max(m["re_mom2"], m["im_mom2"])
        # Sobol（N=2^16）
        pts = common.lattice_points(65536, [1 << 16] * 4)
        a = pts[:, 0] - (1 << 15)
        b = pts[:, 1] - (1 << 15)
        c = pts[:, 2] - (1 << 15)
        d = pts[:, 3] - (1 << 15)
        re = a * c - b * d
        im = a * d + b * c
        import numpy as np
        drop = sd
        rq = ((re + (1 << (drop - 1))) >> drop) << drop
        iq = ((im + (1 << (drop - 1))) >> drop) << drop
        err2 = max(float(np.mean((rq - re) ** 2)), float(np.mean((iq - im) ** 2)))
        xs.append(sd)
        lem.append(common.sqnr_db(sig, exact))
        sob.append(common.sqnr_db(sig, err2))
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.plot(xs, lem, "o-", label="引理 4.1/4.2（精确）")
    ax.plot(xs, sob, "s--", label="Sobol $2^{16}$（L2 确定性）")
    ax.set_xlabel("输出丢位 s（drop bits）")
    ax.set_ylabel("总体均值 SQNR（dB）")
    ax.set_title("模分解引理与确定性积分的一致性（Δ ≤ 0.02 dB）")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "fig4_1_lemma.png")
    plt.close(fig)


def fig_noise():
    """图 4.2：适应度重评噪声（平滑族）"""
    d = load("fitness_noise.json")
    if not d:
        return
    names = [k for k in d if isinstance(d[k], dict) and "mean" in d[k]]
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.bar(names, [d[k]["stdev"] for k in names], color=C_C, alpha=0.8)
    ax.set_ylabel("10 次重评的 SQNR 标准差（dB）")
    ax.set_title("平滑族的新鲜种子重评噪声（L1 层）")
    fig.tight_layout()
    fig.savefig(FIG / "fig4_2_noise.png")
    plt.close(fig)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    todo = {"fronts": fig_fronts, "rejudge": fig_rejudge, "e3": fig_e3,
            "e4": fig_e4, "lemma": fig_lemma, "noise": fig_noise}
    for name, fn in todo.items():
        if which in ("all", name):
            try:
                fn()
                print(f"{name}: ok")
            except Exception as ex:
                print(f"{name}: FAIL {ex}")
