#!/usr/bin/env python3
"""实验 S1：局部误差指标 vs 系统级实现选择（RESEARCH_PLAN §6.1 第 4–10 天）。

问题（课题一/H1）：按局部指标筛选候选，是否会误删系统最优候选？
信息阶梯（每级 = 筛选时保留的信息量）：
  L0  最差级静态 SQNR（certfit 式证书口径，频率盲）
  L1  最差级 SQNR + NCO 纯音 SFDR（杂散幅度可知、位置未知用法）
  L2  最差级 SQNR + NCO 轨迹 SQNR（相位截断在真实轨迹上可见）
  L3  谱加权预测（逐级误差 + FIR 加权 + 抽取折叠，功率和假设）
  GT  完整链路真值（同输入 float 参考对齐误差，主系统指标）

输出：experiments_system/s1_local_vs_system/{manifest.json, results.json,
summary.md, fig_s1_local_vs_system.png}
"""

from __future__ import annotations

import itertools
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import spec, scenarios, ref_chain, fixed_chain, candidates, metrics

OUT = BENCH / "experiments_system" / "s1_local_vs_system"
MARGIN_DB = 1.0          # 显著性裕量：预测差 > margin 且真值反转才计为错筛
TOPK = (6, 12, 24)


def nco_tone_sfdr(nco_cfg: dict, f_off_mhz: float, n: int = 65536) -> float:
    """纯音记录上的 NCO 输出 SFDR（dBc，两字段取最差）。"""
    sin_v, cos_v = fixed_chain.nco_sincos(nco_cfg, n, f_off_mhz)
    return min(metrics.sfdr_db(sin_v.astype(np.float64)),
               metrics.sfdr_db(cos_v.astype(np.float64)))


def fir_local_sqnr(fir_cfg: dict, hq: np.ndarray, h_ideal: np.ndarray,
                   x_in: np.ndarray) -> float:
    """FIR 自身误差的局部 SQNR：理想混频量化输出 → 候选 FIR vs 理想 FIR。"""
    x16 = np.floor(x_in.real * 32768 + 0.5).astype(np.int64)
    xq16 = np.floor(x_in.imag * 32768 + 0.5).astype(np.int64)
    yf = fixed_chain.fir_fixed(x16, xq16, hq, fir_cfg)
    y_fix = (yf["re"] + 1j * yf["im"]) / 32768.0
    y_ref = ref_chain.fir_float(x_in, h_ideal / float(np.sum(h_ideal)))
    return metrics.worst_field_sqnr_db(y_ref, y_fix[spec.N_TAPS - 1:])


def kendall_tau(a: np.ndarray, b: np.ndarray) -> float:
    """Kendall τ（并列按 0.5 记）。"""
    n = len(a)
    c = d = 0
    for i, j in itertools.combinations(range(n), 2):
        s1 = a[i] - a[j]
        s2 = b[i] - b[j]
        v = s1 * s2
        c += v > 0
        d += v < 0
        # 并列忽略（连续值几乎无并列）
    return (c - d) / (n * (n - 1) / 2)


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 冻结 manifest ----
    manifest = spec.export_manifest(str(OUT / "manifest.json"))
    scen_all = spec.build_scenarios()
    print(f"[manifest] {len(scen_all)} 场景, chain={spec.CHAIN_VERSION}")

    h_ideal = ref_chain.prototype_taps()
    pool = candidates.build_all(h_ideal)
    assert not pool["illegal"], f"存在非法候选: {pool['illegal']}"
    nco_list, fir_list, cmul_list = pool["nco"], pool["fir"], pool["cmul"]
    n_combos = len(nco_list) * len(fir_list) * len(cmul_list)
    print(f"[pool] {len(nco_list)}×{len(fir_list)}×{len(cmul_list)} = {n_combos} 组合")

    # NCO 静态精度 + 纯音 SFDR（每 f_off）
    nco_static = {n["name"]: n["sqnr_static_db"] for n in nco_list}
    nco_sfdr = {(n["name"], f): nco_tone_sfdr(n, f)
                for n in nco_list for f in spec.F_OFF_GRID_MHZ}

    # FIR 局部 SQNR（候选独立：理想混频量化输出为输入）
    fir_local = {}
    for f in fir_list:
        fir_local[f["name"]] = fir_local_sqnr(f, f["hq"], h_ideal, _probe_input(h_ideal))
    print("[local] FIR 局部 SQNR:",
          {k: round(v, 1) for k, v in fir_local.items()})

    results = {"chain_version": spec.CHAIN_VERSION}
    rows = []   # 每组合×场景一行
    t_run = time.time()
    for scen in scen_all:
        sd = scenarios.generate_scenario(scen)
        ref = ref_chain.run_reference(sd, h_ideal)
        n_pre_out = (sd.n_pre - (spec.N_TAPS - 1)) // spec.R
        y_ref = ref["y_out"]
        p_ref = float(np.mean(np.abs(y_ref) ** 2))

        # FIR 局部 SQNR（本场景输入口径，候选独立）
        fir_local_scen = fir_local_sqnr_pool(fir_list, h_ideal, ref["mix"])

        for nc in nco_list:
            i12, q12 = fixed_chain.adc_quantize(sd.x_adc)
            sin16, cos16 = fixed_chain.nco_sincos(nc, len(sd.x_adc), sd.scen.f_off_mhz)
            pre = {"i12": i12, "q12": q12, "sin": sin16, "cos": cos16}
            # NCO 轨迹 SQNR（本场景相位轨迹 vs 理想）
            nco_traj = metrics.worst_field_sqnr_db(
                np.stack([ref["cos"], ref["sin"]], axis=1),
                np.stack([cos16 / 32768.0, sin16 / 32768.0], axis=1))
            for fc in fir_list:
                for cm in cmul_list:
                    cand = fixed_chain.run_candidate(nc, fc, cm, sd, fc["hq"], pre)
                    combo = f"{nc['name']}|{fc['name']}|{cm['name']}"
                    mix_fix = (cand["mix_re"] + 1j * cand["mix_im"]) / 32768.0
                    mixer_sqnr = metrics.worst_field_sqnr_db(ref["mix"], mix_fix)

                    y_fix = (cand["y_re"] + 1j * cand["y_im"]) / 32768.0
                    aerr = metrics.aligned_impl_error(y_ref, y_fix, n_pre_out)
                    ieb = metrics.inband_error_db(y_ref, y_fix)
                    evm = metrics.symbol_evm(y_fix, sd.symbols, int(spec.FS_OUT / spec.SYM_RATE), 48, 12)

                    # 谱加权预测（有效段口径）
                    e_mix = (mix_fix - ref["mix"])[spec.N_TAPS - 1:]
                    y_ff = (cand["fir_re"][spec.N_TAPS - 1:]
                            + 1j * cand["fir_im"][spec.N_TAPS - 1:]) / 32768.0
                    y_ref_of_x = ref_chain.fir_float(
                        mix_fix, h_ideal / float(np.sum(h_ideal)))
                    fir_err = y_ff - y_ref_of_x
                    pred = metrics.spectral_prediction(e_mix, fir_err, h_ideal, p_ref)

                    # 局部聚合（各级取最差）
                    l0 = min(nco_static[nc["name"]], mixer_sqnr,
                             fir_local_scen[fc["name"]])
                    l1 = min(mixer_sqnr, fir_local_scen[fc["name"]],
                             nco_sfdr[(nc["name"], sd.scen.f_off_mhz)])
                    l2 = min(nco_traj, mixer_sqnr, fir_local_scen[fc["name"]])

                    rows.append({
                        "scenario": scen.name, "klass": scen.klass,
                        "combo": combo,
                        "nco": nc["name"], "fir": fc["name"], "cmul": cm["name"],
                        "nco_static_db": nco_static[nc["name"]],
                        "nco_sfdr_db": nco_sfdr[(nc["name"], sd.scen.f_off_mhz)],
                        "nco_traj_db": nco_traj,
                        "mixer_sqnr_db": mixer_sqnr,
                        "fir_local_db": fir_local_scen[fc["name"]],
                        "L0_sqnr_db": l0, "L1_sqnr_sfdr_db": l1, "L2_traj_db": l2,
                        "pred_err_db": pred["pred_err_db"],
                        "truth_err_db": aerr["err_raw_db"],
                        "truth_err_aligned_db": aerr["err_aligned_db"],
                        "gain_off_db": aerr["gain_off_db"],
                        "phase_off_deg": aerr["phase_off_deg"],
                        "inband_err_db": ieb,
                        "evm_total_db": evm["evm_total_db"],
                        "n_sat": cand["n_sat_mix"] + cand["n_sat_fir"],
                    })
        print(f"[run] {scen.name} 完成（累计 {time.time()-t_run:.0f}s）")

    # ---- 排序分析：信息阶梯 vs 真值 ----
    df = {}
    for r in rows:
        df.setdefault(r["scenario"], []).append(r)

    predictors = {"L0_sqnr": "L0_sqnr_db", "L1_sfdr": "L1_sqnr_sfdr_db",
                  "L2_traj": "L2_traj_db", "L3_spectral": "pred_err_db"}
    analysis = {"per_scenario": {}}
    for scen_name, rs in df.items():
        truth = np.array([r["truth_err_db"] for r in rs])   # 越低越好
        order_t = np.argsort(truth)
        best_combo = rs[int(order_t[0])]["combo"]
        sc = {"n": len(rs), "truth_best": best_combo,
              "truth_best_err_db": float(truth[order_t[0]]),
              "truth_top3": [rs[int(i)]["combo"] for i in order_t[:3]],
              "truth_err_range_db": [float(truth.min()), float(truth.max())]}
        for pname, key in predictors.items():
            # 预测值统一为"越低越好"：SQNR/SFDR 类取负
            if key.endswith("err_db"):
                pv = np.array([r[key] for r in rs])
            else:
                pv = np.array([-r[key] for r in rs])
            tau = kendall_tau(pv, truth)
            order_p = np.argsort(pv)
            ret = {}
            for k in TOPK:
                topk = set(rs[int(i)]["combo"] for i in order_p[:k])
                ret[f"top{k}_hit_best"] = best_combo in topk
                ret[f"top{k}_hit_top3"] = len(topk & set(sc["truth_top3"]))
            # 显著错筛：预测差 > margin 且真值反转
            inv = 0
            worst = None
            for i, j in itertools.combinations(range(len(rs)), 2):
                if pv[i] > pv[j] + MARGIN_DB and truth[i] < truth[j] - MARGIN_DB:
                    inv += 1
                    gap = (truth[j] - truth[i]) + (pv[i] - pv[j])
                    if worst is None or gap > worst["loss_db"]:
                        worst = {"kept": rs[i]["combo"], "dropped": rs[j]["combo"],
                                 "pred_gap_db": float(pv[i] - pv[j]),
                                 "truth_gap_db": float(truth[j] - truth[i]),
                                 "loss_db": float(gap)}
                elif pv[j] > pv[i] + MARGIN_DB and truth[j] < truth[i] - MARGIN_DB:
                    inv += 1
                    gap = (truth[i] - truth[j]) + (pv[j] - pv[i])
                    if worst is None or gap > worst["loss_db"]:
                        worst = {"kept": rs[j]["combo"], "dropped": rs[i]["combo"],
                                 "pred_gap_db": float(pv[j] - pv[i]),
                                 "truth_gap_db": float(truth[i] - truth[j]),
                                 "loss_db": float(gap)}
            sc[pname] = {"kendall_tau": round(tau, 4), "significant_inversions": inv,
                         "worst_drop": worst, "retention": ret}
        analysis["per_scenario"][scen_name] = sc

    # 跨场景真值排序稳定性（场景间 Kendall τ）
    scen_names = list(df.keys())
    taus = []
    for s1, s2 in itertools.combinations(scen_names, 2):
        t1 = {r["combo"]: r["truth_err_db"] for r in df[s1]}
        t2 = {r["combo"]: r["truth_err_db"] for r in df[s2]}
        combos = sorted(t1)
        taus.append(kendall_tau(np.array([t1[c] for c in combos]),
                                np.array([t2[c] for c in combos])))
    analysis["truth_rank_stability_across_scenarios"] = {
        "mean_kendall_tau": round(float(np.mean(taus)), 4),
        "min_kendall_tau": round(float(np.min(taus)), 4),
        "n_pairs": len(taus)}

    analysis["summary"] = {}
    for pname in predictors:
        per = [analysis["per_scenario"][s][pname] for s in scen_names]
        analysis["summary"][pname] = {
            "mean_kendall_tau": round(float(np.mean([p["kendall_tau"] for p in per])), 4),
            "scenarios_with_inversions": sum(1 for p in per if p["significant_inversions"] > 0),
            "total_significant_inversions": sum(p["significant_inversions"] for p in per),
            "best_retained_frac": round(float(np.mean(
                [p["retention"][f"top{TOPK[0]}_hit_best"] for p in per])), 4)}

    results = {
        "chain_version": spec.CHAIN_VERSION,
        "margin_db": MARGIN_DB,
        "n_combos": n_combos,
        "n_scenarios": len(scen_all),
        "runtime_s": round(time.time() - t0, 1),
        "analysis": analysis,
        "rows": rows,
    }
    with open(OUT / "results.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False)
    print(f"[out] results.json（{time.time()-t0:.0f}s）")

    _figure(rows, analysis, scen_all)
    print("[out] fig_s1_local_vs_system.png")

    _summary(results, scen_names, n_combos)
    print(f"[out] summary.md；总耗时 {time.time()-t0:.0f}s")
    return 0


def _probe_input(h_ideal: np.ndarray) -> np.ndarray:
    """FIR 局部指标用的确定性探测输入（宽带，覆盖全频段）。"""
    rng = np.random.default_rng(spec.SEED_BASE)
    n = 8192
    t = np.arange(n) / spec.FS_IN
    x = 0.3 * np.exp(2j * math.pi * 0.13e6 * t)      # 通带内音
    x += 0.3 * np.exp(2j * math.pi * 0.6e6 * t)      # 阻带音
    x += 0.1 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    return x / np.max(np.abs(x)) * 0.9


def fir_local_sqnr_pool(fir_list, h_ideal, mix_ideal: np.ndarray) -> dict:
    """各 FIR 候选在本场景理想混频输入下的自身误差 SQNR。"""
    out = {}
    for f in fir_list:
        x = mix_ideal
        x16 = np.floor(x.real * 32768 + 0.5).astype(np.int64)
        xq16 = np.floor(x.imag * 32768 + 0.5).astype(np.int64)
        yf = fixed_chain.fir_fixed(x16, xq16, f["hq"], f)
        y_fix = (yf["re"] + 1j * yf["im"]) / 32768.0
        y_ref = ref_chain.fir_float(x, h_ideal / float(np.sum(h_ideal)))
        out[f["name"]] = metrics.worst_field_sqnr_db(
            y_ref, y_fix[spec.N_TAPS - 1:])
    return out




predictors = {"L0_sqnr": "L0_sqnr_db", "L1_sfdr": "L1_sqnr_sfdr_db",
              "L2_traj": "L2_traj_db", "L3_spectral": "pred_err_db"}


def _figure(rows, analysis, scen_all) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Hiragino Sans GB", "Arial Unicode MS", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 3, figsize=(16.5, 4.8))
    klass_color = {"clean": "#4c72b0", "obb": "#dd8452", "alias": "#55a868"}

    # (a) L0 局部静态 SQNR vs 真值
    ax = axes[0]
    for klass, c in klass_color.items():
        rs = [r for r in rows if r["klass"] == klass]
        ax.scatter([r["L0_sqnr_db"] for r in rs], [r["truth_err_db"] for r in rs],
                   s=16, alpha=0.65, c=c, label=klass, edgecolors="none")
    ax.set_xlabel("L0 最差级静态 SQNR（dB，越大越好）")
    ax.set_ylabel("系统实现误差（dB，越小越好）")
    ax.set_title("(a) 频率盲局部指标 vs 系统真值")
    ax.legend(fontsize=8)

    # (b) L3 谱加权预测 vs 真值
    ax = axes[1]
    for klass, c in klass_color.items():
        rs = [r for r in rows if r["klass"] == klass]
        ax.scatter([r["pred_err_db"] for r in rs], [r["truth_err_db"] for r in rs],
                   s=16, alpha=0.65, c=c, label=klass, edgecolors="none")
    lo = min(min(r["pred_err_db"] for r in rows), min(r["truth_err_db"] for r in rows)) - 3
    hi = max(max(r["pred_err_db"] for r in rows), max(r["truth_err_db"] for r in rows)) + 3
    ax.plot([lo, hi], [lo, hi], "k--", lw=1, label="y = x")
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("L3 谱加权预测误差（dB）")
    ax.set_ylabel("系统实现误差（dB）")
    ax.set_title("(b) 谱加权模型（功率和假设）")
    ax.legend(fontsize=8)

    # (c) 信息阶梯：各场景显著错筛数
    ax = axes[2]
    names = list(predictors.keys())
    scen_names = list(analysis["per_scenario"].keys())
    width = 0.2
    for i, p in enumerate(names):
        vals = [analysis["per_scenario"][s][p]["significant_inversions"] for s in scen_names]
        ax.bar(np.arange(len(scen_names)) + (i - 1.5) * width, vals, width,
               label=p, alpha=0.85)
    ax.set_xticks(np.arange(len(scen_names)))
    ax.set_xticklabels(scen_names, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel(f"显著错筛对数（margin {MARGIN_DB} dB）")
    ax.set_title("(c) 信息阶梯：错筛随信息量下降")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fig_s1_local_vs_system.png", dpi=150)
    plt.close(fig)


def _summary(results, scen_names, n_combos) -> None:
    a = results["analysis"]
    lines = [
        "# S1 汇总：局部指标 vs 系统级实现选择",
        "",
        f"- chain `{results['chain_version']}`，{n_combos} 组合 × {results['n_scenarios']} 场景，"
        f"运行 {results['runtime_s']}s，margin {results['margin_db']} dB",
        f"- 真值跨场景排序稳定性：Kendall τ 均值 "
        f"{a['truth_rank_stability_across_scenarios']['mean_kendall_tau']}"
        f"（最小 {a['truth_rank_stability_across_scenarios']['min_kendall_tau']}）",
        "",
        "| 预测器 | 平均 Kendall τ | 出现错筛的场景数 | 显著错筛对总数 | top-6 命中真值最优比例 |",
        "|---|---|---|---|---|",
    ]
    for p, s in a["summary"].items():
        lines.append(f"| {p} | {s['mean_kendall_tau']} | {s['scenarios_with_inversions']}"
                     f"/{results['n_scenarios']} | {s['total_significant_inversions']} "
                     f"| {s['best_retained_frac']} |")
    lines.append("")
    worst_examples = []
    for s in scen_names:
        for p in predictors:
            w = a["per_scenario"][s][p]["worst_drop"]
            if w:
                worst_examples.append((p, s, w))
    lines += ["## 典型错筛实例（预测器判可丢弃、真值更优）", ""]
    seen = set()
    for p, s, w in worst_examples:
        key = (p, w["dropped"], w["kept"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- **{p}** @ {s}：丢弃 `{w['dropped']}`，保留 `{w['kept']}`；"
                     f"预测差 {w['pred_gap_db']:.2f} dB，真值反转 {w['truth_gap_db']:.2f} dB")
    lines.append("")
    with open(OUT / "summary.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
