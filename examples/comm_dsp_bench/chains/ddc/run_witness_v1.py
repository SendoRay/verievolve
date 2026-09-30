#!/usr/bin/env python3
"""DDC witness v1 的专用冻结输入准备器与 formal truth runner。

默认只做协议校验；不会隐式运行 chain truth。执行顺序严格分两阶段：

1. ``prepare`` 计算局部指标、主 pair 审计和 NCO-only Nangate45 面积，
   写入不可覆盖的 frozen-input manifest；此阶段不计算任何链级 Q。
2. ``truth --run-id ID`` 只接受上述 manifest，先重验全部哈希，再按
   main → heldout → stress 顺序计算冻结的 26-NCO/固定下游真值。

历史 ``run_s1.py`` 不是本协议入口。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np


BENCH = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import (candidates, fixed_chain, metrics, prepare_witness_v1,
                        ref_chain, rtl_gen, scenarios, spec)


OUT = BENCH / "experiments_system" / "ddc_witness_v1"
PREFLIGHT = OUT / "preflight_manifest.json"
FROZEN_INPUTS = OUT / "frozen_inputs_v1"
RUNS = OUT / "runs"
N_SFDR = 1 << 16
SFDR_ZERO_PAD = 8


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"拒绝覆盖已有产物: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _assert_equal(label: str, actual, expected) -> None:
    if _canonical(actual) != _canonical(expected):
        raise RuntimeError(f"preflight 字段漂移: {label}")


def load_and_validate_preflight(path: Path = PREFLIGHT) -> dict:
    """逐字段重建并校验预检对象；任何代码/协议/工具漂移均拒绝。"""
    if not path.is_file():
        raise RuntimeError(f"缺少 preflight manifest: {path}")
    stored = json.loads(path.read_text(encoding="utf-8"))
    fresh = prepare_witness_v1.build_preflight_manifest()
    _assert_equal("entire manifest", stored, fresh)
    if stored["truth_runner"]["forbidden_entrypoint"] != "chains/ddc/run_s1.py":
        raise RuntimeError("历史 run_s1.py 禁用标记丢失")
    if stored["candidate_set"]["count"] != 26:
        raise RuntimeError("正式候选池必须恰为 26 点")
    return stored


def _architecture_class(cfg: dict) -> str:
    if cfg["algo"] == "cordic":
        return "cordic"
    return f"lut-{cfg['order']}"


def _representatives(preflight: dict) -> dict[str, str]:
    rep = {}
    for members in preflight["rtl_equivalence"]["classes"]:
        leader = min(members)
        for name in members:
            rep[name] = leader
    return rep


def select_v2_pair(local_rows: list[dict], preflight: dict) -> dict:
    """冻结稿 §2.3 的完整、Q-blind 主 pair 选择审计。"""
    q_budget = preflight["quality_contract"]["calibration"]["q_budget"]
    target = -10.0 * math.log10(q_budget)
    reps = _representatives(preflight)
    v2 = [r for r in local_rows if r["name"].startswith("v2_")]
    table = []
    eligible = []
    for i, a in enumerate(v2):
        for b in v2[i + 1:]:
            row = {
                "a": a["name"], "b": b["name"],
                "class_a": _architecture_class(a),
                "class_b": _architecture_class(b),
                "representative_a": reps[a["name"]],
                "representative_b": reps[b["name"]],
                "delta_sqnr_db": abs(a["mcore_sqnr_db"] - b["mcore_sqnr_db"]),
            }
            if row["class_a"] == row["class_b"]:
                row["status"] = "discard:same-architecture-class"
            elif row["representative_a"] == row["representative_b"]:
                row["status"] = "discard:numerically-equivalent"
            elif row["delta_sqnr_db"] > 3.0:
                row["status"] = "discard:delta-sqnr-over-3db"
            else:
                row["status"] = "eligible"
                row["target_max_distance_db"] = max(
                    abs(a["mcore_sqnr_db"] - target),
                    abs(b["mcore_sqnr_db"] - target),
                )
                eligible.append(row)
            table.append(row)
    eligible.sort(key=lambda r: (r["target_max_distance_db"],
                                 r["delta_sqnr_db"], r["a"], r["b"]))
    selected = None if not eligible else {k: eligible[0][k] for k in (
        "a", "b", "target_max_distance_db", "delta_sqnr_db")}
    return {
        "rule": "WITNESS_FROZEN_DDC_v1 §2.3",
        "q_blind": True,
        "sqnr_target_db": target,
        "max_delta_sqnr_db": 3.0,
        "selected": selected,
        "outcome": "v2-no-eligible-pair" if selected is None else "selected",
        "complete_pair_table": table,
    }


def compute_local_metrics(preflight: dict) -> dict:
    """计算 M_core 与冻结有限记录 SFDR；不读取任何链级 Q。"""
    rows = candidates.build_witness_nco_pool(include_legacy=True)
    expected = preflight["candidate_set"]["candidates"]
    configs = [{key: row[key] for key in expected[i]}
               for i, row in enumerate(rows)]
    if configs != expected:
        raise RuntimeError("局部指标候选顺序/参数与 preflight 不一致")

    main_fcws = [spec.fcw_of(f) for f in spec.W_F_MAIN_MHZ]
    held_fcws = [spec.fcw_of(f) for f in spec.W_F_HELDOUT_MHZ]
    from certfit import tpl_cordic
    for row in rows:
        by_fcw = {}
        for split, fcws in (("main", main_fcws), ("heldout", held_fcws)):
            values = []
            for fcw in fcws:
                n = np.arange(N_SFDR, dtype=np.int64)
                acc = (n * fcw) & 0xFFFFFFFF
                phase_bits = int(row["phase_bits"])
                z16 = (acc >> (32 - phase_bits)) << (16 - phase_bits)
                z_signed = np.where(z16 >= (1 << 15), z16 - (1 << 16), z16)
                params = ({"algo": "lut", "order": row["order"], "depth": row["depth"]}
                          if row["algo"] == "lut" else
                          {"algo": "cordic", "stages": row["stages"]})
                sin16, cos16 = tpl_cordic.emulate(params, z_signed.astype(np.int64))
                tone = (cos16 + 1j * sin16) / float(1 << 15)
                ideal = np.exp(1j * 2.0 * math.pi * fcw * n / (1 << 32))
                values.append({"fcw": fcw,
                               "sfdr_db": metrics.sfdr_db(tone, ideal, SFDR_ZERO_PAD)})
            by_fcw[split] = values
        row["sfdr_main_worst_db"] = min(x["sfdr_db"] for x in by_fcw["main"])
        row["sfdr_main_argmin_fcw"] = min(
            by_fcw["main"], key=lambda x: x["sfdr_db"])["fcw"]
        row["sfdr_by_fcw"] = by_fcw
    return {
        "schema_version": "ddc-witness-local-v1",
        "preflight_sha256": _sha256(PREFLIGHT),
        "sfdr": {
            "n_samples": N_SFDR,
            "zero_pad_factor": SFDR_ZERO_PAD,
            "window": "scipy.signal.windows.blackmanharris(sym=True)",
            "main_aggregation": "minimum dBc over 9 main FCWs",
        },
        "rows": rows,
    }


def _synth_nco_area(cfg: dict, contract: dict, timeout: int = 600) -> dict:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        verilog = td_path / "nco.v"
        log = td_path / "stat.txt"
        verilog.write_text(rtl_gen.gen_nco_verilog(cfg), encoding="utf-8")
        liberty = BENCH / contract["liberty"]["path"]
        script = contract["script_template"].format(
            verilog=verilog, liberty=liberty, log=log)
        try:
            p = subprocess.run([contract["tool"]["executable"], "-q", "-p", script],
                               cwd=td, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"name": cfg["name"], "error": "synthesis timeout"}
        if not log.is_file():
            return {"name": cfg["name"], "error": (p.stderr or p.stdout)[-1000:]}
        text = log.read_text(encoding="utf-8")
        m = re.search(r"Chip area for module '\\nco_map':\s*([0-9.]+)", text)
        if not m:
            return {"name": cfg["name"], "error": f"area not found: {text[-500:]}"}
        cells = {name: int(count) for name, count in
                 re.findall(r"^\s+(\S+)\s+(\d+)\s*$", text, flags=re.MULTILINE)}
        return {"name": cfg["name"], "area_um2": float(m.group(1)), "cells": cells}


def compute_area(preflight: dict) -> dict:
    contract = preflight["synthesis_contract"]
    rows = [_synth_nco_area(cfg, contract)
            for cfg in preflight["candidate_set"]["candidates"]]
    errors = [r for r in rows if "error" in r]
    if errors:
        raise RuntimeError(f"NCO-only 综合失败: {errors}")
    return {"schema_version": "ddc-witness-area-v1",
            "preflight_sha256": _sha256(PREFLIGHT),
            "contract": contract, "rows": rows}


def prepare_frozen_inputs() -> Path:
    """不跑 Q；冻结 local/area/pair 后才签发 truth-allowed manifest。"""
    preflight = load_and_validate_preflight()
    if FROZEN_INPUTS.exists():
        raise RuntimeError(f"拒绝覆盖已有冻结输入目录: {FROZEN_INPUTS}")
    # 先全部算完再创建正式目录；任一 gate 失败都不留下貌似已冻结的半成品。
    local_value = compute_local_metrics(preflight)
    pair_value = select_v2_pair(local_value["rows"], preflight)
    area_value = compute_area(preflight)
    FROZEN_INPUTS.mkdir(parents=True)
    local_path = FROZEN_INPUTS / "local_metrics.json"
    area_path = FROZEN_INPUTS / "area_results.json"
    pair_path = FROZEN_INPUTS / "pair_selection.json"
    _write_new_json(local_path, local_value)
    _write_new_json(pair_path, pair_value)
    _write_new_json(area_path, area_value)
    manifest = {
        "schema_version": "ddc-witness-execution-v1",
        "protocol": preflight["protocol"],
        "preflight": {"path": str(PREFLIGHT.relative_to(BENCH)),
                      "sha256": _sha256(PREFLIGHT)},
        "inputs": {
            "local_metrics": {"path": str(local_path.relative_to(BENCH)),
                              "sha256": _sha256(local_path)},
            "pair_selection": {"path": str(pair_path.relative_to(BENCH)),
                               "sha256": _sha256(pair_path)},
            "area_results": {"path": str(area_path.relative_to(BENCH)),
                             "sha256": _sha256(area_path)},
        },
        "truth_runner": {"allowed": True,
                         "entrypoint": "chains/ddc/run_witness_v1.py truth"},
    }
    execution = FROZEN_INPUTS / "execution_manifest.json"
    _write_new_json(execution, manifest)
    return execution


def load_execution_manifest(path: Path) -> tuple[dict, dict]:
    preflight = load_and_validate_preflight()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "ddc-witness-execution-v1":
        raise RuntimeError("execution manifest schema 不匹配")
    if manifest.get("truth_runner", {}).get("allowed") is not True:
        raise RuntimeError("execution manifest 未放行 truth")
    if manifest["preflight"]["sha256"] != _sha256(PREFLIGHT):
        raise RuntimeError("execution manifest 引用的 preflight 已漂移")
    for label, item in manifest["inputs"].items():
        path_i = BENCH / item["path"]
        if not path_i.is_file() or _sha256(path_i) != item["sha256"]:
            raise RuntimeError(f"冻结输入缺失或漂移: {label}")
    return preflight, manifest


def _load_frozen_input(manifest: dict, label: str) -> dict:
    item = manifest["inputs"][label]
    return json.loads((BENCH / item["path"]).read_text(encoding="utf-8"))


def _evaluate_one(nco: dict, fir: dict, cmul: dict,
                  scen: spec.Scenario) -> dict:
    sd = scenarios.generate_scenario(scen)
    h = ref_chain.prototype_taps()
    ref = ref_chain.run_reference(sd, h)
    cand = fixed_chain.run_candidate(nco, fir, cmul, sd, fir["hq"])
    y_fix = (cand["y_re"] + 1j * cand["y_im"]) / float(1 << 15)
    y_des = scenarios.ideal_output(sd.desired, scen.f_off_mhz)
    n_pre_out = scenarios.measure_start_out(sd.n_pre)
    aerr = metrics.aligned_impl_error(ref["y_out"], y_fix, n_pre_out,
                                      y_des_ref=y_des)
    denom = float((1 << 15) * (1 << spec.MIX_FRAC_SHIFT))
    pre_peak_ratio = float(max(np.max(np.abs(cand["mix_re_pre"])),
                               np.max(np.abs(cand["mix_im_pre"]))) / denom)
    return {
        "candidate": nco["name"], "scenario": scen.name, "split": scen.split,
        "scenario_key": spec.scenario_key(scen.klass, scen.f_off_mhz,
                                           scen.blocker_off_mhz,
                                           scen.blocker_rel_db, scen.snr_db),
        "fcw": spec.fcw_of(scen.f_off_mhz),
        "q_raw": aerr["err_raw"], "q_aligned": aerr["err_aligned"],
        "q_raw_db": aerr["err_raw_db"], "q_aligned_db": aerr["err_aligned_db"],
        "g_re": aerr["gain_re"], "g_im": aerr["gain_im"],
        "gain_off_db": aerr["gain_off_db"],
        "phase_off_deg": aerr["phase_off_deg"], "p_ref": aerr["p_ref"],
        "n_sat_mix": cand["n_sat_mix"], "n_sat_fir": cand["n_sat_fir"],
        "mix_preclip_peak_ratio": pre_peak_ratio,
        "front_end_scale": sd.scale,
        "input_peak_raw": sd.levels["peak_raw"],
        "scenario_snr_out_db": sd.levels["snr_out_db"],
        "n_samples": len(ref["y_out"]) - n_pre_out,
    }


def _aggregate(rows: list[dict], split: str) -> list[dict]:
    out = []
    names = sorted({r["candidate"] for r in rows if r["split"] == split})
    for name in names:
        rs = [r for r in rows if r["split"] == split and r["candidate"] == name]
        worst = max(rs, key=lambda r: r["q_aligned"])
        out.append({"candidate": name, "Q": worst["q_aligned"],
                    "Q_db": worst["q_aligned_db"],
                    "argmax_scenario": worst["scenario"],
                    "argmax_fcw": worst["fcw"], "n_scenarios": len(rs)})
    return out


def _pareto_front(names: list[str], x: dict[str, float],
                  y: dict[str, float]) -> list[str]:
    """两个均为越小越好的确定性标准 Pareto 前沿。"""
    front = []
    for name in names:
        dominated = any(
            other != name
            and x[other] <= x[name] and y[other] <= y[name]
            and (x[other] < x[name] or y[other] < y[name])
            for other in names
        )
        if not dominated:
            front.append(name)
    return sorted(front)


def analyze_main_decisions(main_aggregate: list[dict], local: dict,
                           area: dict, preflight: dict) -> dict:
    """冻结稿 §5/§6：局部前沿、保序失败、decision witness 与 regret。"""
    q = {r["candidate"]: float(r["Q"]) for r in main_aggregate}
    area_um2 = {r["name"]: float(r["area_um2"]) for r in area["rows"]}
    local_by_name = {r["name"]: r for r in local["rows"]}
    expected = [r["name"] for r in preflight["candidate_set"]["candidates"]]
    if sorted(q) != sorted(expected) or sorted(area_um2) != sorted(expected):
        raise RuntimeError("Q/area 候选集不是冻结的 26 点并集")

    tolerances = preflight["quality_contract"]["local_tolerances"]
    metric_specs = {
        "sqnr": (lambda r: -float(r["mcore_sqnr_db"]),
                 float(tolerances["sqnr_db"])),
        "wce": (lambda r: float(r["mcore_wce_lsb"]),
                float(tolerances["wce_lsb"])),
        "last_bit": (lambda r: 1.0 - float(r["mcore_last_bit_accuracy"]),
                     float(tolerances["last_bit_probability_mass"])),
        "sfdr": (lambda r: -float(r["sfdr_main_worst_db"]),
                 float(tolerances["sfdr_db"])),
    }
    epsilon_q = float(preflight["quality_contract"]["calibration"]["epsilon_q"])
    pools = {
        "legacy6": [n for n in expected if not n.startswith("v2_")],
        "v2_20": [n for n in expected if n.startswith("v2_")],
        "union26": expected,
    }
    report = {"epsilon_Q": epsilon_q, "metrics": {}, "auxiliary_sqnr_selection": {}}
    for metric, (extract, epsilon_m) in metric_specs.items():
        loss = {name: extract(local_by_name[name]) for name in expected}
        per_pool = {}
        for pool_name, names in pools.items():
            front = _pareto_front(names, loss, area_um2)
            witnesses = []
            for selected in front:
                for better in names:
                    if better == selected:
                        continue
                    if (area_um2[better] <= area_um2[selected]
                            and q[better] < q[selected]
                            and q[selected] - q[better] >= epsilon_q):
                        witnesses.append({
                            "local_front_candidate": selected,
                            "system_dominator": better,
                            "Q_regret": q[selected] - q[better],
                            "area_delta_um2": area_um2[selected] - area_um2[better],
                        })
            strict = []
            collapse = []
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    for first, second in ((a, b), (b, a)):
                        if (loss[first] + epsilon_m < loss[second]
                                and q[first] > q[second] + epsilon_q):
                            strict.append({"locally_better": first,
                                           "system_better": second,
                                           "delta_m": loss[second] - loss[first],
                                           "delta_Q": q[first] - q[second]})
                    if (abs(loss[a] - loss[b]) <= epsilon_m
                            and abs(q[a] - q[b]) > epsilon_q):
                        collapse.append({"a": a, "b": b,
                                         "delta_m": abs(loss[a] - loss[b]),
                                         "delta_Q": abs(q[a] - q[b])})
            per_pool[pool_name] = {
                "local_area_front": front,
                "decision_witnesses": witnesses,
                "decision_witness": bool(witnesses),
                "strict_reversals": strict,
                "collapses": collapse,
            }
        report["metrics"][metric] = {"epsilon_m": epsilon_m,
                                      "loss_convention": "smaller-is-better",
                                      "pools": per_pool}

    target = -10.0 * math.log10(
        preflight["quality_contract"]["calibration"]["q_budget"])
    eligible = [n for n in expected
                if float(local_by_name[n]["mcore_sqnr_db"]) >= target]
    if eligible:
        selected = min(eligible, key=lambda n: (area_um2[n], n))
        same_area = [n for n in expected if area_um2[n] <= area_um2[selected]]
        q_best_name = min(same_area, key=lambda n: (q[n], area_um2[n], n))
        same_quality = [n for n in expected if q[n] <= q[selected]]
        area_best_name = min(same_quality, key=lambda n: (area_um2[n], q[n], n))
        report["auxiliary_sqnr_selection"] = {
            "target_sqnr_db": target, "selected": selected,
            "Q": q[selected], "area_um2": area_um2[selected],
            "quality_reference_same_or_lower_area": q_best_name,
            "quality_regret": q[selected] - q[q_best_name],
            "area_reference_same_or_better_Q": area_best_name,
            "area_regret_um2": area_um2[selected] - area_um2[area_best_name],
        }
    else:
        report["auxiliary_sqnr_selection"] = {
            "target_sqnr_db": target, "outcome": "no-candidate-meets-target"}
    return report


def run_truth(execution_path: Path, run_id: str) -> Path:
    """显式 formal truth 入口；调用者必须提供新 run_id。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError("run_id 只能含字母数字、点、下划线、连字符，长度 1..64")
    preflight, execution = load_execution_manifest(execution_path)
    local = _load_frozen_input(execution, "local_metrics")
    area = _load_frozen_input(execution, "area_results")

    h = ref_chain.prototype_taps()
    full = candidates.build_all(h)
    fir = next(x for x in full["fir"]
               if x["name"] == prepare_witness_v1.FIXED_FIR_NAME)
    cmul = next(x for x in full["cmul"]
                if x["name"] == prepare_witness_v1.FIXED_CMUL_NAME)
    frozen_fir = preflight["fixed_downstream"]["fir"]
    actual_fir = {key: value for key, value in fir.items() if key != "hq"}
    actual_fir["hq"] = np.asarray(fir["hq"], dtype=np.int64).tolist()
    actual_fir["hq_sha256"] = hashlib.sha256(
        np.asarray(fir["hq"], dtype="<i8").tobytes()).hexdigest()
    _assert_equal("fixed FIR", actual_fir, frozen_fir)
    _assert_equal("fixed CMUL", cmul, preflight["fixed_downstream"]["cmul"])
    ncos = candidates.witness_nco_candidates(include_legacy=True)
    _assert_equal("candidate pool", ncos,
                  preflight["candidate_set"]["candidates"])

    run_meta = {
        "schema_version": "ddc-witness-results-v1",
        "protocol": preflight["protocol"], "run_id": run_id,
        "execution_manifest": {"path": str(execution_path.relative_to(BENCH)),
                               "sha256": _sha256(execution_path)},
        "candidate_set_sha256": hashlib.sha256(_canonical(ncos).encode("utf-8")).hexdigest(),
        "reproducibility": preflight["reproducibility"],
        "synthesis_contract": preflight["synthesis_contract"],
        "q_cal": preflight["quality_contract"]["calibration"]["q_cal"],
        "epsilon_Q": preflight["quality_contract"]["calibration"]["epsilon_q"],
        "started_unix": time.time(),
    }
    if prepare_witness_v1.exact_zero_q_calibration() != (
            preflight["quality_contract"]["calibration"]):
        raise RuntimeError("q_cal/epsilon_Q 校准漂移")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_new_json(run_dir / "run_manifest.json", run_meta)

    all_rows = []
    aggregates = {}
    for split in ("main", "heldout", "stress"):
        split_rows = []
        for scen in spec.build_witness_scenarios(split):
            for nco in ncos:
                row = _evaluate_one(nco, fir, cmul, scen)
                if split in ("main", "heldout") and (
                        row["n_sat_mix"] or row["n_sat_fir"]):
                    raise RuntimeError(f"非 stress 场景发生饱和: {row}")
                split_rows.append(row)
        all_rows.extend(split_rows)
        aggregates[split] = _aggregate(split_rows, split)
        _write_new_json(run_dir / f"{split}_checkpoint.json",
                        {"split": split, "rows": split_rows,
                         "aggregate": aggregates[split]})
        if split == "main":
            # 先固化 C_main 判定，再允许读取 heldout/stress。
            main_decisions = analyze_main_decisions(
                aggregates["main"], local, area, preflight)
            _write_new_json(run_dir / "main_decision.json", main_decisions)

    result = {**run_meta, "finished_unix": time.time(), "rows": all_rows,
              "aggregate": aggregates,
              "main_decision": main_decisions,
              "note": "Q uses max of linear q_aligned; dB fields are display only"}
    _write_new_json(run_dir / "results.json", result)
    return run_dir / "results.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="只校验 preflight，不计算 local/area/Q")
    sub.add_parser("prepare", help="冻结 local/area/pair；不运行 chain truth")
    truth = sub.add_parser("truth", help="显式运行 formal chain truth")
    truth.add_argument("--execution-manifest", type=Path,
                       default=FROZEN_INPUTS / "execution_manifest.json")
    truth.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "validate":
        load_and_validate_preflight()
        print("[ok] preflight manifest 与当前实现逐字段一致；未运行 truth")
    elif args.command == "prepare":
        print(prepare_frozen_inputs())
    else:
        print(run_truth(args.execution_manifest, args.run_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
