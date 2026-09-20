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
    """图 5.1：两臂 Pareto 前沿对比（2×2；999 哨兵封顶显示并标注）"""
    tasks = [("cmul_w16_free", "cmul（复数乘法）"),
             ("cordic_sincos", "cordic_sincos（正余弦）"),
             ("atan2_w16", "atan2（复数辐角）"),
             ("llr_64qam_snr20", "llr（64QAM 软解调）")]
    CAP = 120.0  # 哨兵显示封顶
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, (task, label) in zip(axes.flat, tasks):
        for arm, color, lbl in [("S", C_S, "Arm S（采样适应度）"),
                                ("C", C_C, "Arm C（证书适应度）")]:
            rd = E1 / f"e1_{task}_arm{arm}_seed0"
            if not rd.exists():
                continue
            front = front_of(rd)
            if not front:
                continue
            real = [(p, a, t) for p, a, t in front if p < 900]
            sent = [(p, a, t) for p, a, t in front if p >= 900]
            if real:
                rr = sorted(real, key=lambda x: x[1])
                ax.plot([x[1] for x in rr], [min(x[0], CAP) for x in rr],
                        "--" if arm == "S" else "-", color=color, lw=1.6, alpha=0.75,
                        label=lbl)
                ax.scatter([x[1] for x in rr], [x[0] for x in rr], c=color, s=46,
                           zorder=3, edgecolors="white", linewidths=0.6)
            if sent:
                ax.scatter([x[1] for x in sent], [CAP] * len(sent), marker="*",
                           s=170, c=color, zorder=4, edgecolors="k", linewidths=0.5,
                           label=("★ 精确参考（哨兵 999）" if arm == "S" else None))

        ax.axhline(CAP, color="gray", ls=":", lw=1)
        ax.set_title(label)
        ax.set_xlabel("面积（ice40 LUT）")
        ax.set_ylabel("SQNR（dB）")
        ax.set_ylim(0, 140)
        ax.legend(fontsize=9, loc="lower right")
    fig.suptitle("同一 LLM、同一预算（40 迭代）下两臂的精度-面积前沿", y=1.02)
    fig.text(0.5, 0.985, "★ = 精确参考（SQNR 哨兵 999，封顶 120 dB 显示）；"
                         "虚线 = Arm S，实线 = Arm C",
             ha="center", fontsize=9, color="#333")
    fig.tight_layout()
    fig.savefig(FIG / "fig5_1_fronts.png")
    plt.close(fig)


def fig_rejudge():
    """图 5.2：重判一致性散点（哨兵点剔除并注明）"""
    d = load("rejudge.json")
    if not d:
        return
    fig, ax = plt.subplots(figsize=(6.6, 5.6))
    n_sent = 0
    for task, marker in [("cmul_w16_free", "o"), ("cordic_sincos", "s"),
                         ("atan2_w16", "^"), ("llr_64qam_snr20", "D")]:
        pts = [r for r in d["tasks"].get(task, {}).get("rejudge", [])
               if "sampled_sqnr" in r and r.get("params")]
        pts_real = [p for p in pts if p["prec_in_loop"] < 900]
        n_sent += len(pts) - len(pts_real)
        if pts_real:
            ax.scatter([p["prec_in_loop"] for p in pts_real],
                       [p["sampled_sqnr"] for p in pts_real],
                       marker=marker, s=46, label=task, alpha=0.9,
                       edgecolors="white", linewidths=0.6)
    lim = [20, 100]
    ax.plot(lim, lim, "k--", lw=1, label="y = x")
    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("环内适应度（Arm C：证书 SQNR；Arm S：采样 SQNR，dB）")
    ax.set_ylabel("重判采样 SQNR（dB）")
    if n_sent:
        ax.text(0.02, 0.97, f"（另 {n_sent} 个精确哨兵点（999 dB）未绘入）",
                transform=ax.transAxes, fontsize=8.5, color="#444", va="top")
    ax.legend(fontsize=8.5, loc="lower right")
    ax.set_title("证书预测 vs 重判实测（平滑族主簇贴合 y=x）")
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
        sb = d["select_by_ber_cert"]
        ax1.axvline(sb["b"], color=C_C, ls=":", lw=1.4)
        ax1.annotate(f"BER 证书选型 b={sb['b']}\n（{sb['area']} LUT，含最坏裕度）",
                     xy=(sb["b"], 29.6), xytext=(sb["b"] + 0.5, 29.6),
                     fontsize=8.5, color=C_C, va="center",
                     arrowprops=dict(arrowstyle="->", color=C_C, lw=0.9))
    if d.get("select_by_sqnr60"):
        ss = d["select_by_sqnr60"]
        ax1.axvline(ss["b"], color=C_S, ls=":", lw=1.4)
        ax1.annotate(f"SQNR 门槛选型\nb={ss['b']}（{ss['area']} LUT）",
                     (ss["b"] - 0.15, 45), fontsize=8.5, color=C_S, ha="right")
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="center right")
    fig.tight_layout()
    fig.savefig(FIG / "fig5_4_e4_ber.png")
    plt.close(fig)


def fig_scatter():
    """图 4.3：证书-采样散点（平滑族 vs 重尾族）"""
    d = load("e2b_scatter.json")
    if not d:
        return
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))

    rows = [r for r in d.get("cordic_sincos", []) if r["sampled"] is not None]
    xs = [r["cert"] for r in rows]
    ys = [r["sampled"] for r in rows]
    devs = [abs(y - x) for x, y in zip(xs, ys)]
    axes[0].scatter(xs, ys, s=42, c=C_C, alpha=0.9, edgecolors="white", linewidths=0.6)
    lim = [20.0, 102.0]
    axes[0].plot(lim, lim, "k--", lw=1, label="y = x")
    axes[0].set_xlim(lim); axes[0].set_ylim(lim)
    axes[0].set_title(f"cordic（平滑族，全枚举证书）\n19 个配置，max |Δ| = {max(devs):.2f} dB")
    axes[0].set_xlabel("证书 SQNR（L2 确定性，dB）")
    axes[0].set_ylabel("采样 SQNR（L1，dB）")
    axes[0].legend(fontsize=9, loc="upper left")

    l2 = [r for r in d.get("llr_64qam_snr20", []) if r["sampled"] is not None
          and r["params"]["metric"] == "l2"]
    l1 = [r for r in d.get("llr_64qam_snr20", []) if r["sampled"] is not None
          and r["params"]["metric"] == "l1"]
    if l2:
        axes[1].scatter([r["cert"] for r in l2], [r["sampled"] for r in l2], s=42,
                        c="#c44e52", alpha=0.9, edgecolors="white", linewidths=0.6,
                        label="l2 度量（Δ ≈ −11 dB）")
    if l1:
        axes[1].scatter([r["cert"] for r in l1], [r["sampled"] for r in l1], s=42,
                        c="#55a868", alpha=0.9, edgecolors="white", linewidths=0.6,
                        label="l1 度量（一致但精度仅 1.3 dB）")
    lim2 = [0, 88]
    axes[1].plot(lim2, lim2, "k--", lw=1, label="y = x")
    axes[1].set_xlim(lim2); axes[1].set_ylim(lim2)
    devs2 = [abs(r["sampled"] - r["cert"]) for r in l2] if l2 else [0]
    axes[1].set_title(f"llr（重尾族，Sobol 证书）\n"
                      f"l2 配置系统性偏高 {min(devs2):.1f}~{max(devs2):.1f} dB")
    axes[1].set_xlabel("证书 SQNR（L2 确定性，dB）")
    axes[1].set_ylabel("采样 SQNR（L1，dB）")
    axes[1].legend(fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "fig4_3_scatter.png")
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


def fig_handshake():
    """图 3.1：stream_v1 流式握手时序（含气泡拍、反压与输出对齐）"""
    fig, ax = plt.subplots(figsize=(10, 4.6))
    cycles = 12
    in_valid = [1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    in_ready = [1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1]   # 第 7 拍反压
    out_valid = [0, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1]  # 3 拍延迟
    out_ready = [1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1]  # 第 6 拍下游反压

    def step(sig, y, color):
        xs, ys = [], []
        for i, v in enumerate(sig):
            xs += [i, i + 1]; ys += [v + y, v + y]
            if i < len(sig) - 1 and sig[i + 1] != v:
                xs += [i + 1, i + 1]; ys += [v + y, sig[i + 1] + y]
        ax.plot(xs, ys, color=color, lw=2.0)

    clk_x, clk_y = [], []
    for i in range(cycles):
        clk_x += [i, i + 0.5, i + 0.5, i + 1]
        clk_y += [0.2, 0.2, 0.9, 0.9]
    ax.plot(clk_x, clk_y, color="#555555", lw=1.4)
    ax.text(-0.5, 0.55, "clk", ha="right", va="center", fontsize=10)

    # 各信号独立高度（2.0 间隔，避免共线）
    step(in_valid, 1.8, "#4c72b0"); ax.text(-0.5, 2.3, "in_valid", ha="right", fontsize=10)
    step(in_ready, 3.4, "#55a868"); ax.text(-0.5, 3.9, "in_ready", ha="right", fontsize=10)
    step(out_valid, 5.0, "#c44e52"); ax.text(-0.5, 5.5, "out_valid", ha="right", fontsize=10)
    step(out_ready, 6.6, "#8172b2"); ax.text(-0.5, 7.1, "out_ready", ha="right", fontsize=10)

    ax.annotate("气泡拍（输入侧不握手，不采样）", (2.5, 2.9), fontsize=8.5, ha="center",
                color="#222", arrowprops=dict(arrowstyle="->", color="#555", lw=0.8),
                xytext=(3.0, 2.32))
    ax.annotate("DUT 反压（输出未取走，不丢数据）", (6.5, 4.6), fontsize=8.5, ha="center",
                color="#222", arrowprops=dict(arrowstyle="->", color="#555", lw=0.8),
                xytext=(6.5, 4.0))
    ax.annotate("输出有效延迟（拍数任意）\n握手协议自动对齐", (1.5, 6.1), fontsize=8.5, ha="center",
                color="#222", arrowprops=dict(arrowstyle="->", color="#555", lw=0.8),
                xytext=(2.2, 6.2))
    for i in range(cycles):
        ax.axvline(i, color="k", lw=0.2, alpha=0.22)
    ax.set_xlim(-1.8, 12); ax.set_ylim(-0.1, 7.8)
    ax.axis("off")
    ax.set_title("stream_v1 协议：valid/ready 握手（吞吐在接口层实测，含气泡与反压）")
    fig.tight_layout()
    fig.savefig(FIG / "fig3_1_handshake.png")
    plt.close(fig)


def fig_regression():
    """图 3.2：基线回归三轮修复对比（按族堆叠柱）"""
    data = {
        "初版":   {"crc": (20, 20), "llr": (20, 20), "fir": (0, 30), "atan2": (7, 7),
                   "nco": (0, 12), "mfilt": (0, 5), "cmul": (3, 12)},
        "修复后": {"crc": (20, 20), "llr": (20, 20), "fir": (18, 30), "atan2": (7, 7),
                   "nco": (12, 12), "mfilt": (3, 5), "cmul": (2, 12)},
    }
    fams = list(data["初版"].keys())
    x = np.arange(len(fams)); w = 0.38
    fig, ax = plt.subplots(figsize=(8.6, 4.3))
    for k, (key, label, color) in enumerate([("初版", "初版", C_S),
                                             ("修复后", "修复后（run5）", C_C)]):
        oks = [data[key][f][0] for f in fams]
        tots = [data[key][f][1] for f in fams]
        ax.bar(x + (k - 0.5) * w, oks, w, color=color, label=label)
        for xi, (o, t) in enumerate(zip(oks, tots)):
            ax.text(xi + (k - 0.5) * w, o + 0.4, f"{o}/{t}", ha="center", fontsize=7.5)
    ax.set_xticks(x); ax.set_xticklabels(fams)
    ax.set_ylabel("回归通过实例数")
    ax.set_title("基线回归：修复前 50/106 → 修复后 82/106（残余 24 例已定性）")
    ax.legend(fontsize=9)
    ax.set_ylim(0, 33)
    fig.tight_layout()
    fig.savefig(FIG / "fig3_2_regression.png")
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
            "e4": fig_e4, "lemma": fig_lemma, "noise": fig_noise,
            "scatter": fig_scatter, "handshake": fig_handshake,
            "regression": fig_regression}
    for name, fn in todo.items():
        if which in ("all", name):
            try:
                fn()
                print(f"{name}: ok")
            except Exception as ex:
                print(f"{name}: FAIL {ex}")
