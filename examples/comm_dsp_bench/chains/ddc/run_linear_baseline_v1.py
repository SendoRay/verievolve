#!/usr/bin/env python3
"""运行 DDC witness 的 candidate-exact linear-reference baseline ③。

协议冻结于 ``thesis/BASELINE3_PROTOCOL_DDC_v1.md``。本脚本只读取已经
完成的 formal truth，不重新运行 bit-true 候选链，也不改动任何冻结产物。
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau


BENCH = Path(__file__).resolve().parent.parent.parent
ROOT = BENCH.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import (candidates, fixed_chain, metrics, ref_chain,
                        run_witness_v1, scenarios, spec)


WITNESS = BENCH / "experiments_system" / "ddc_witness_v1"
EXECUTION = WITNESS / "frozen_inputs_v1" / "execution_manifest.json"
TRUTH = WITNESS / "runs" / "formal-v1-20260930" / "results.json"
PROTOCOL = ROOT / "thesis" / "BASELINE3_PROTOCOL_DDC_v1.md"
OUT = WITNESS / "baseline3_v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _architecture_class(cfg: dict) -> str:
    if cfg["algo"] == "cordic":
        return "cordic"
    return f"lut-{cfg['order']}"


def _linear_prediction(cfg: dict, scen: spec.Scenario, h_ref: np.ndarray,
                       h_linear: np.ndarray) -> dict:
    sd = scenarios.generate_scenario(scen)
    ref = ref_chain.run_reference(sd, h_ref)
    sin16, cos16 = fixed_chain.nco_sincos(
        cfg, len(sd.x_adc), scen.f_off_mhz)
    lo = (cos16 - 1j * sin16) / float(1 << 15)
    mix = sd.x_adc * lo
    y3 = ref_chain.fir_float(mix, h_linear)[spec.DECIM_PHASE::spec.R]
    y_des = scenarios.ideal_output(sd.desired, scen.f_off_mhz)
    n_pre_out = scenarios.measure_start_out(sd.n_pre)
    q3 = metrics.aligned_impl_error(
        ref["y_out"], y3, n_pre_out, y_des_ref=y_des)
    return {
        "candidate": cfg["name"], "architecture_class": _architecture_class(cfg),
        "scenario": scen.name, "split": scen.split,
        "scenario_key": spec.scenario_key(
            scen.klass, scen.f_off_mhz, scen.blocker_off_mhz,
            scen.blocker_rel_db, scen.snr_db),
        "fcw": spec.fcw_of(scen.f_off_mhz),
        "q3": q3["err_aligned"], "q3_db": q3["err_aligned_db"],
        "q3_raw": q3["err_raw"], "g_re": q3["gain_re"],
        "g_im": q3["gain_im"], "p_ref": q3["p_ref"],
    }


def _aggregate(rows: list[dict], split: str) -> list[dict]:
    out = []
    for name in sorted({r["candidate"] for r in rows if r["split"] == split}):
        rs = [r for r in rows if r["candidate"] == name and r["split"] == split]
        worst = max(rs, key=lambda r: r["q3"])
        out.append({"candidate": name, "Q3": worst["q3"],
                    "Q3_db": worst["q3_db"],
                    "argmax_scenario": worst["scenario"],
                    "argmax_fcw": worst["fcw"], "n_scenarios": len(rs)})
    return out


def _topk_with_ties(values: dict[str, float], k: int) -> set[str]:
    order = sorted(values, key=lambda name: (values[name], name))
    boundary = values[order[min(k, len(order)) - 1]]
    return {name for name in order if values[name] <= boundary}


def _percentiles(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    return {"median": float(np.median(a)), "p95": float(np.percentile(a, 95)),
            "max": float(np.max(a)), "n": len(a)}


def analyze(rows: list[dict], truth: dict, preflight: dict) -> dict:
    truth_rows = {(r["candidate"], r["scenario_key"]): r for r in truth["rows"]}
    epsilon = float(preflight["quality_contract"]["calibration"]["epsilon_q"])
    q_budget = float(preflight["quality_contract"]["calibration"]["q_budget"])
    for row in rows:
        tr = truth_rows[(row["candidate"], row["scenario_key"])]
        row["q_true"] = tr["q_aligned"]
        row["abs_error"] = abs(row["q3"] - tr["q_aligned"])
        row["relative_error"] = row["abs_error"] / max(tr["q_aligned"], epsilon)

    gate_rows = [r for r in rows if r["split"] in ("main", "heldout")]
    by_class = {}
    for klass in ("lut-nearest", "lut-linear", "cordic"):
        rs = [r for r in gate_rows if r["architecture_class"] == klass]
        by_class[klass] = {
            "absolute": _percentiles([r["abs_error"] for r in rs]),
            "relative": _percentiles([r["relative_error"] for r in rs]),
            "pass": max(r["abs_error"] for r in rs) <= epsilon,
        }
    gate_a = {
        "epsilon_Q": epsilon,
        "overall_absolute": _percentiles([r["abs_error"] for r in gate_rows]),
        "by_architecture_class": by_class,
        "pass": all(x["pass"] for x in by_class.values()),
    }

    aggregate = {split: _aggregate(rows, split)
                 for split in ("main", "heldout", "stress")}
    q3 = {r["candidate"]: r["Q3"] for r in aggregate["main"]}
    qtrue = {r["candidate"]: r["Q"] for r in truth["aggregate"]["main"]}
    true_best = min(qtrue.values())
    topk = {}
    for k in (1, 3, 5):
        selected = _topk_with_ties(q3, k)
        regret = min(qtrue[n] for n in selected) - true_best
        topk[str(k)] = {"selected": sorted(selected), "regret": regret,
                        "true_best_hit": any(qtrue[n] == true_best for n in selected)}

    false_feasible = []
    for name in sorted(q3):
        if q3[name] <= q_budget and qtrue[name] > q_budget:
            false_feasible.append({"candidate": name, "Q3": q3[name],
                                   "Q_true": qtrue[name],
                                   "violation": qtrue[name] - q_budget})

    witness_checks = []
    decisions = truth["main_decision"]["metrics"]
    seen = set()
    for metric, value in decisions.items():
        pool = value["pools"]["union26"]
        for kind, records in (("strict", pool["strict_reversals"]),
                              ("collapse", pool["collapses"])):
            for record in records:
                if kind == "strict":
                    a, b = record["locally_better"], record["system_better"]
                else:
                    a, b = record["a"], record["b"]
                    if qtrue[a] < qtrue[b]:
                        a, b = b, a
                key = (metric, kind, a, b)
                if key in seen:
                    continue
                seen.add(key)
                delta = q3[a] - q3[b]
                explained = delta > 0.0 or abs(delta) <= epsilon
                witness_checks.append({"metric": metric, "kind": kind,
                                       "truth_worse": a, "truth_better": b,
                                       "Q3_delta": delta, "explained": explained})

    tau = kendalltau([q3[n] for n in sorted(q3)],
                     [qtrue[n] for n in sorted(qtrue)], variant="b")
    max_regret = max(x["regret"] for x in topk.values())
    max_violation = max((x["violation"] for x in false_feasible), default=0.0)
    gate_b = {
        "topk": topk, "max_topk_regret": max_regret,
        "false_feasible": false_feasible,
        "max_budget_violation": max_violation,
        "witness_checks": witness_checks,
        "all_registered_failures_explained": all(x["explained"] for x in witness_checks),
        "kendall_tau_b": float(tau.statistic), "kendall_pvalue": float(tau.pvalue),
    }
    gate_b["pass"] = (max_regret <= epsilon and max_violation <= epsilon
                       and gate_b["all_registered_failures_explained"])
    return {"gate_a": gate_a, "gate_b": gate_b, "aggregate": aggregate}


def main() -> int:
    if OUT.exists():
        raise RuntimeError(f"拒绝覆盖已有 baseline 产物: {OUT}")
    if not PROTOCOL.is_file() or not TRUTH.is_file():
        raise RuntimeError("缺少冻结 baseline 协议或 formal truth")
    preflight, _ = run_witness_v1.load_execution_manifest(EXECUTION)
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    ncos = candidates.witness_nco_candidates(include_legacy=True)
    if [x["name"] for x in ncos] != [x["name"] for x in preflight["candidate_set"]["candidates"]]:
        raise RuntimeError("candidate pool 漂移")

    started = time.time()
    h_ref = ref_chain.prototype_taps()
    frozen_fir = preflight["fixed_downstream"]["fir"]
    h_linear = (np.asarray(frozen_fir["hq"], dtype=np.float64)
                / float(1 << (int(frozen_fir["wc"]) - 2)))
    rows = []
    for split in ("main", "heldout", "stress"):
        for scen in spec.build_witness_scenarios(split):
            for cfg in ncos:
                rows.append(_linear_prediction(cfg, scen, h_ref, h_linear))
    analysis = analyze(rows, truth, preflight)
    result = {
        "schema_version": "ddc-linear-baseline-v1",
        "protocol": {"path": str(PROTOCOL.relative_to(ROOT)),
                     "sha256": _sha256(PROTOCOL)},
        "execution_manifest": {"path": str(EXECUTION.relative_to(BENCH)),
                               "sha256": _sha256(EXECUTION)},
        "truth": {"path": str(TRUTH.relative_to(BENCH)), "sha256": _sha256(TRUTH)},
        "code_sha256": _sha256(Path(__file__)),
        "identity": "candidate-exact linear-reference baseline; excludes downstream round/sat",
        "started_unix": started, "finished_unix": time.time(),
        "rows": rows, **analysis,
    }
    OUT.mkdir(parents=True)
    (OUT / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT / "results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
