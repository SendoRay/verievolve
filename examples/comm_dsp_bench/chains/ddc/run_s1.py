#!/usr/bin/env python3
"""实验 S1：局部误差指标 vs 系统级实现选择（RESEARCH_PLAN §6.1 第 4–10 天）。

问题（课题一/H1）：按局部指标筛选候选，是否会误删系统最优候选？
信息阶梯（每级 = 筛选时保留的信息量）：
  L0  最差级静态 SQNR（certfit 式证书口径，频率盲）
  L1  最差级 SQNR + NCO 纯音 SFDR（杂散幅度可知、位置未知用法）
  L2  最差级 SQNR + NCO 轨迹 SQNR（相位截断在真实轨迹上可见）
  L3  谱加权预测（逐级误差 + FIR 加权 + 抽取折叠，功率和假设）
  GT  完整链路真值（同输入 float 参考对齐误差，主系统指标）

输出：experiments_system/s1_local_vs_system_witness_v1/{manifest.json, results.json,
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

OUT = BENCH / "experiments_system" / "s1_local_vs_system_witness_v1"
MARGIN_DB = 1.0          # 显著性裕量：预测差 > margin 且真值反转才计为错筛
TOPK = (6, 12, 24)


def nco_tone_sfdr(nco_cfg: dict, f_off_mhz: float, n: int = 65536) -> float:
    """纯音记录上的复 NCO SFDR（已知载波消除，有限记录 dBc）。"""
    sin_v, cos_v = fixed_chain.nco_sincos(nco_cfg, n, f_off_mhz)
    fcw = int(round(f_off_mhz * 1e6 / spec.FS_IN * (1 << spec.W_P_ACC)))
    phase = 2.0 * math.pi * fcw * np.arange(n, dtype=np.float64) / (1 << spec.W_P_ACC)
    ideal = np.exp(1j * phase)
    actual = (cos_v + 1j * sin_v) / float(1 << 15)
    return metrics.sfdr_db(actual, ideal)


def fir_local_sqnr(fir_cfg: dict, hq: np.ndarray, h_ideal: np.ndarray,
                   x_in: np.ndarray) -> float:
    """FIR 自身误差的局部 SQNR：理想混频量化输出 → 候选 FIR vs 理想 FIR。"""
    x16 = np.floor(x_in.real * 32768 + 0.5).astype(np.int64)
    xq16 = np.floor(x_in.imag * 32768 + 0.5).astype(np.int64)
    yf = fixed_chain.fir_fixed(x16, xq16, hq, fir_cfg)
    y_fix = (yf["re"] + 1j * yf["im"]) / 32768.0
    y_ref = ref_chain.fir_float(x_in, h_ideal / float(np.sum(h_ideal)))
    return metrics.worst_field_sqnr_db(y_ref, y_fix[spec.N_TAPS - 1:])


def kendall_tau_a(a: np.ndarray, b: np.ndarray) -> float:
    """Kendall tau-a；保留作与历史产物的可追溯对照。"""
    n = len(a)
    c = d = 0
    for i, j in itertools.combinations(range(n), 2):
        s1 = a[i] - a[j]
        s2 = b[i] - b[j]
        v = s1 * s2
        c += v > 0
        d += v < 0
    denom = n * (n - 1) / 2
    return 0.0 if denom == 0 else (c - d) / denom


def kendall_tau_b(a: np.ndarray, b: np.ndarray) -> float:
    """Kendall tau-b；显式校正两个排序中的并列。"""
    if len(a) != len(b):
        raise ValueError("两个排序必须等长")
    concordant = discordant = tied_a = tied_b = 0
    for i, j in itertools.combinations(range(len(a)), 2):
        da = a[i] - a[j]
        db = b[i] - b[j]
        if da == 0 and db == 0:
            continue
        if da == 0:
            tied_a += 1
        elif db == 0:
            tied_b += 1
        elif da * db > 0:
            concordant += 1
        else:
            discordant += 1
    ranked = concordant + discordant
    denom = math.sqrt((ranked + tied_a) * (ranked + tied_b))
    return 0.0 if denom == 0.0 else (concordant - discordant) / denom


def topk_indices_with_ties(values: np.ndarray, k: int) -> set[int]:
    """返回越小越好排序的 top-k，并完整保留第 k 位边界并列。"""
    values = np.asarray(values)
    if values.ndim != 1 or len(values) == 0 or k < 1:
        raise ValueError("values 必须是非空一维数组，k 必须为正")
    cutoff = float(np.sort(values, kind="stable")[min(k, len(values)) - 1])
    return set(np.flatnonzero(values <= cutoff).tolist())


def minimum_tie_indices(values: np.ndarray) -> set[int]:
    """返回所有精确并列的最优项。"""
    values = np.asarray(values)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("values 必须是非空一维数组")
    return set(np.flatnonzero(values == np.min(values)).tolist())


def worst_inversion(predictor: np.ndarray, truth: np.ndarray,
                    labels: list[str], margin: float) -> tuple[int, dict | None]:
    """统计显著反转，并正确标注预测保留项与误删的真值更优项。"""
    count = 0
    worst = None
    for i, j in itertools.combinations(range(len(labels)), 2):
        if predictor[i] > predictor[j] + margin and truth[i] < truth[j] - margin:
            kept, dropped = j, i
        elif predictor[j] > predictor[i] + margin and truth[j] < truth[i] - margin:
            kept, dropped = i, j
        else:
            continue
        count += 1
        pred_gap = float(predictor[dropped] - predictor[kept])
        truth_gap = float(truth[kept] - truth[dropped])
        loss = pred_gap + truth_gap
        if worst is None or loss > worst["loss_db"]:
            worst = {
                "kept": labels[kept],
                "dropped": labels[dropped],
                "pred_gap_db": pred_gap,
                "truth_gap_db": truth_gap,
                "loss_db": loss,
            }
    return count, worst


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- 冻结 manifest ----
    spec.export_witness_manifest(str(OUT / "manifest.json"))
    scen_all = spec.build_witness_scenarios("main")
    scenario_levels = {}
    print(f"[manifest] {len(scen_all)} 主场景, scenario={spec.SCENARIO_VERSION}, "
          f"chain={spec.CHAIN_VERSION}")

    h_ideal = ref_chain.prototype_taps()
    pool = candidates.build_all(h_ideal)
    assert not pool["illegal"], f"存在非法候选: {pool['illegal']}"
    nco_list, fir_list, cmul_list = pool["nco"], pool["fir"], pool["cmul"]
    n_combos = len(nco_list) * len(fir_list) * len(cmul_list)
    print(f"[pool] {len(nco_list)}×{len(fir_list)}×{len(cmul_list)} = {n_combos} 组合")

    # NCO 静态精度 + 纯音 SFDR（每 f_off）
    nco_static = {n["name"]: n["sqnr_static_db"] for n in nco_list}
    f_grid = sorted({s.f_off_mhz for s in scen_all})
    nco_sfdr = {(n["name"], f): nco_tone_sfdr(n, f)
                for n in nco_list for f in f_grid}

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
        scenario_levels[f"{scen.name}@{scen.split}"] = sd.levels
        ref = ref_chain.run_reference(sd, h_ideal)
        n_pre_out = scenarios.measure_start_out(sd.n_pre)
        y_ref = ref["y_out"]
        y_des_ref = scenarios.ideal_output(sd.desired, sd.scen.f_off_mhz)
        p_ref = float(np.mean(np.abs(y_des_ref[n_pre_out:]) ** 2))

        # FIR 局部 SQNR（本场景输入口径，候选独立）
        fir_local_scen = fir_local_sqnr_pool(fir_list, h_ideal, ref["mix"])

        for nc in nco_list:
            i12, q12 = fixed_chain.adc_quantize(sd.x_adc)
            sin16, cos16 = fixed_chain.nco_sincos(nc, len(sd.x_adc), sd.scen.f_off_mhz)
            pre = {"i12": i12, "q12": q12, "sin": sin16, "cos": cos16}
            # NCO 轨迹 SQNR（本场景相位轨迹 vs 理想）
            nco_traj = metrics.worst_field_sqnr_db(
                ref["cos"] + 1j * ref["sin"],
                cos16 / 32768.0 + 1j * sin16 / 32768.0)
            for fc in fir_list:
                for cm in cmul_list:
                    cand = fixed_chain.run_candidate(nc, fc, cm, sd, fc["hq"], pre)
                    combo = f"{nc['name']}|{fc['name']}|{cm['name']}"
                    mix_fix = (cand["mix_re"] + 1j * cand["mix_im"]) / 32768.0
                    mixer_sqnr = metrics.worst_field_sqnr_db(ref["mix"], mix_fix)

                    y_fix = (cand["y_re"] + 1j * cand["y_im"]) / 32768.0
                    aerr = metrics.aligned_impl_error(
                        y_ref, y_fix, n_pre_out, y_des_ref=y_des_ref)
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
                        "pred_err": pred["pred_err"],
                        "pred_inband_err_db": pred["pred_inband_err_db"],
                        "truth_err_db": aerr["err_raw_db"],
                        "truth_err_aligned_db": aerr["err_aligned_db"],
                        "truth_err": aerr["err_raw"],
                        "truth_err_aligned": aerr["err_aligned"],
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
        truth = np.array([r["truth_err_aligned_db"] for r in rs])   # 越低越好
        order_t = np.argsort(truth)
        best_idx = minimum_tie_indices(truth)
        best_combos = sorted(rs[i]["combo"] for i in best_idx)
        best_combo = best_combos[0]
        truth_top3_idx = topk_indices_with_ties(truth, 3)
        sc = {"n": len(rs), "truth_best": best_combo,
              "truth_best_set": best_combos,
              "truth_best_err_db": float(truth[order_t[0]]),
              "truth_top3": sorted(rs[i]["combo"] for i in truth_top3_idx),
              "truth_err_range_db": [float(truth.min()), float(truth.max())]}
        for pname, key in predictors.items():
            # 预测值统一为"越低越好"：SQNR/SFDR 类取负
            if key.endswith("err_db"):
                pv = np.array([r[key] for r in rs])
            else:
                pv = np.array([-r[key] for r in rs])
            tau_a = kendall_tau_a(pv, truth)
            tau_b = kendall_tau_b(pv, truth)
            ret = {}
            for k in TOPK:
                selected_idx = topk_indices_with_ties(pv, k)
                selected = {rs[i]["combo"] for i in selected_idx}
                kept_best = selected_idx & best_idx
                ret[f"top{k}_selected_n"] = len(selected_idx)
                ret[f"top{k}_hit_any_best"] = bool(kept_best)
                ret[f"top{k}_keep_all_best"] = best_idx <= selected_idx
                ret[f"top{k}_best_retained_frac"] = len(kept_best) / len(best_idx)
                # 旧字段保留为兼容别名；语义明确为“任一并列最优”。
                ret[f"top{k}_hit_best"] = bool(kept_best)
                ret[f"top{k}_hit_top3"] = len(selected & set(sc["truth_top3"]))
            labels = [r["combo"] for r in rs]
            inv, worst = worst_inversion(pv, truth, labels, MARGIN_DB)
            sc[pname] = {"kendall_tau": round(tau_b, 4),
                         "kendall_tau_a": round(tau_a, 4),
                         "kendall_tau_b": round(tau_b, 4),
                         "significant_inversions": inv,
                         "worst_drop": worst, "retention": ret}
        analysis["per_scenario"][scen_name] = sc

    # 跨场景真值排序稳定性（场景间 Kendall τ）
    scen_names = list(df.keys())
    taus = []
    for s1, s2 in itertools.combinations(scen_names, 2):
        t1 = {r["combo"]: r["truth_err_aligned_db"] for r in df[s1]}
        t2 = {r["combo"]: r["truth_err_aligned_db"] for r in df[s2]}
        combos = sorted(t1)
        a1 = np.array([t1[c] for c in combos])
        a2 = np.array([t2[c] for c in combos])
        taus.append((kendall_tau_a(a1, a2), kendall_tau_b(a1, a2)))
    analysis["truth_rank_stability_across_scenarios"] = {
        "mean_kendall_tau": round(float(np.mean([t[1] for t in taus])), 4),
        "min_kendall_tau": round(float(np.min([t[1] for t in taus])), 4),
        "mean_kendall_tau_a": round(float(np.mean([t[0] for t in taus])), 4),
        "min_kendall_tau_a": round(float(np.min([t[0] for t in taus])), 4),
        "mean_kendall_tau_b": round(float(np.mean([t[1] for t in taus])), 4),
        "min_kendall_tau_b": round(float(np.min([t[1] for t in taus])), 4),
        "n_pairs": len(taus)}

    analysis["summary"] = {}
    for pname in predictors:
        per = [analysis["per_scenario"][s][pname] for s in scen_names]
        analysis["summary"][pname] = {
            "mean_kendall_tau": round(float(np.mean([p["kendall_tau_b"] for p in per])), 4),
            "mean_kendall_tau_a": round(float(np.mean([p["kendall_tau_a"] for p in per])), 4),
            "mean_kendall_tau_b": round(float(np.mean([p["kendall_tau_b"] for p in per])), 4),
            "scenarios_with_inversions": sum(1 for p in per if p["significant_inversions"] > 0),
            "total_significant_inversions": sum(p["significant_inversions"] for p in per),
            "best_retained_frac": round(float(np.mean(
                [p["retention"][f"top{TOPK[0]}_hit_any_best"] for p in per])), 4),
            "all_best_retained_frac": round(float(np.mean(
                [p["retention"][f"top{TOPK[0]}_keep_all_best"] for p in per])), 4),
            "mean_best_set_retained_frac": round(float(np.mean(
                [p["retention"][f"top{TOPK[0]}_best_retained_frac"] for p in per])), 4),
        }

    spec.export_witness_manifest(str(OUT / "manifest.json"), levels=scenario_levels)
    results = {
        "chain_version": spec.CHAIN_VERSION,
        "scenario_version": spec.SCENARIO_VERSION,
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
        ax.scatter([r["L0_sqnr_db"] for r in rs], [r["truth_err_aligned_db"] for r in rs],
                   s=16, alpha=0.65, c=c, label=klass, edgecolors="none")
    ax.set_xlabel("L0 最差级静态 SQNR（dB，越大越好）")
    ax.set_ylabel("系统实现误差（dB，越小越好）")
    ax.set_title("(a) 频率盲局部指标 vs 系统真值")
    ax.legend(fontsize=8)

    # (b) L3 谱加权预测 vs 真值
    ax = axes[1]
    for klass, c in klass_color.items():
        rs = [r for r in rows if r["klass"] == klass]
        ax.scatter([r["pred_err_db"] for r in rs], [r["truth_err_aligned_db"] for r in rs],
                   s=16, alpha=0.65, c=c, label=klass, edgecolors="none")
    lo = min(min(r["pred_err_db"] for r in rows),
             min(r["truth_err_aligned_db"] for r in rows)) - 3
    hi = max(max(r["pred_err_db"] for r in rows),
             max(r["truth_err_aligned_db"] for r in rows)) + 3
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
        f"- 真值跨场景排序稳定性：Kendall τ-b 均值 "
        f"{a['truth_rank_stability_across_scenarios']['mean_kendall_tau']}"
        f"（最小 {a['truth_rank_stability_across_scenarios']['min_kendall_tau']}）",
        "",
        "| 预测器 | 平均 τ-b（τ-a） | 出现错筛的场景数 | 显著错筛对总数 | top-6 任一最优命中 | top-6 全并列最优保留 |",
        "|---|---|---|---|---|---|",
    ]
    for p, s in a["summary"].items():
        lines.append(f"| {p} | {s['mean_kendall_tau_b']} ({s['mean_kendall_tau_a']}) | {s['scenarios_with_inversions']}"
                     f"/{results['n_scenarios']} | {s['total_significant_inversions']} "
                     f"| {s['best_retained_frac']} | {s['all_best_retained_frac']} |")
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
