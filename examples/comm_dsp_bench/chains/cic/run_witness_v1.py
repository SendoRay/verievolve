#!/usr/bin/env python3
"""CIC witness 的冻结输入准备与正式执行入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


BENCH = Path(__file__).resolve().parent.parent.parent
ROOT = BENCH.parent.parent
sys.path.insert(0, str(BENCH))

from chains.cic import metrics_v1, prepare_witness_v1, reference, scenarios_v1
from chains.cic.bittrue import run_iq
from chains.ddc.metrics import aligned_impl_error


OUT = BENCH / "experiments_system/cic_witness_v1"
PREFLIGHT = OUT / "preflight_manifest.json"
SECOND_FREEZE = OUT / "SECOND_FREEZE_v1.json"
METRICS_FREEZE = OUT / "METRICS_FREEZE_v1.json"
PRUNING_FREEZE = OUT / "PRUNING_TOLERANCE_FREEZE_v1.json"
BACKEND_FREEZE = OUT / "BACKEND_ERRATUM_FREEZE_v1.json"
METRICS_DOC = ROOT / "thesis/CONTRACT_CIC_METRICS_ADDENDUM_v1.md"
BACKEND_ERRATUM = ROOT / "thesis/CIC_BACKEND_ERRATUM_v1.md"
LOCAL = OUT / "local_metrics_v3.json"
EXECUTION = OUT / "execution_manifest_v3.json"
RUNS = OUT / "runs"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refuse to overwrite artifact: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _finite_db_or_none(value: float) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def validate_freezes() -> tuple[dict, dict, dict]:
    preflight = _load(PREFLIGHT)
    second = _load(SECOND_FREEZE)
    metric_freeze = _load(METRICS_FREEZE)
    if _sha256(PREFLIGHT) != second["preflight_manifest"]["sha256"]:
        raise RuntimeError("preflight manifest drifted after second freeze")
    if _sha256(ROOT / second["protocol"]["path"]) != second["protocol"]["sha256"]:
        raise RuntimeError("first-freeze protocol drifted")
    if _sha256(METRICS_DOC) != metric_freeze["document"]["sha256"]:
        raise RuntimeError("metrics addendum drifted")
    if not second["next_stage"]["allowed"] or not metric_freeze["formal_metrics_allowed"]:
        raise RuntimeError("formal metrics are not approved")
    return preflight, second, metric_freeze


def validate_pruning_freeze() -> dict:
    freeze = _load(PRUNING_FREEZE)
    if freeze["status"] != "approved":
        raise RuntimeError("cumulative-pruning tolerance is not approved")
    if freeze["cumulative_pruning_tolerance_bits"] != 0:
        raise RuntimeError("unexpected cumulative-pruning tolerance")
    if _sha256(METRICS_FREEZE) != freeze["metrics_freeze"]["sha256"]:
        raise RuntimeError("metrics freeze drifted after pruning tolerance approval")
    return freeze


def validate_backend_erratum() -> dict:
    freeze = _load(BACKEND_FREEZE)
    if freeze["status"] != "approved-for-complete-replay":
        raise RuntimeError("CIC backend erratum is not approved for replay")
    if _sha256(BACKEND_ERRATUM) != freeze["document"]["sha256"]:
        raise RuntimeError("CIC backend erratum document drifted")
    return freeze


def _code_files() -> list[Path]:
    return [
        BENCH / "chains/cic/bittrue.py",
        BENCH / "chains/cic/gen_candidates_v1.py",
        BENCH / "chains/cic/metrics_v1.py",
        BENCH / "chains/cic/reference.py",
        BENCH / "chains/cic/run_witness_v1.py",
        BENCH / "chains/cic/scenarios_v1.py",
        BENCH / "chains/ddc/metrics.py",
        ROOT / "tests/test_cic_metrics.py",
        ROOT / "tests/test_cic_reference.py",
        ROOT / "tests/test_cic_runner.py",
    ]


def _candidate_rows(preflight: dict) -> list[dict]:
    by_name = {row["name"]: row for row in preflight["candidate_set"]["rows"]}
    return [by_name[name] for name in preflight["deduplicated_pool"]]


def prepare() -> dict:
    preflight, _, _ = validate_freezes()
    pruning_freeze = validate_pruning_freeze()
    backend_freeze = validate_backend_erratum()
    missing = [str(path) for path in _code_files() if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing code files: {missing}")
    candidates = _candidate_rows(preflight)
    local_rows = [metrics_v1.local_metrics(row) for row in candidates]
    local = {
        "schema_version": "cic-local-metrics-v3",
        "status": "frozen before chain q",
        "supersedes": [
            "local_metrics_v1.json (diagnostic only)",
            "local_metrics_v2.json (paired with invalidated backend)",
        ],
        "rows": local_rows,
    }
    execution = {
        "schema_version": "cic-witness-execution-v3",
        "status": "approved-for-formal-execution",
        "supersedes": [
            "execution_manifest_v1.json (diagnostic only)",
            "execution_manifest_v2.json (backend erratum requires complete replay)",
        ],
        "preflight": {"path": str(PREFLIGHT.relative_to(BENCH)), "sha256": _sha256(PREFLIGHT)},
        "second_freeze": {"path": str(SECOND_FREEZE.relative_to(BENCH)),
                          "sha256": _sha256(SECOND_FREEZE)},
        "metrics_freeze": {"path": str(METRICS_FREEZE.relative_to(BENCH)),
                           "sha256": _sha256(METRICS_FREEZE)},
        "pruning_tolerance_freeze": {
            "path": str(PRUNING_FREEZE.relative_to(BENCH)),
            "sha256": _sha256(PRUNING_FREEZE),
        },
        "backend_erratum_freeze": {
            "path": str(BACKEND_FREEZE.relative_to(BENCH)),
            "sha256": _sha256(BACKEND_FREEZE),
        },
        "backend_erratum_document": {
            "path": str(BACKEND_ERRATUM.relative_to(ROOT)),
            "sha256": _sha256(BACKEND_ERRATUM),
        },
        "metrics_document": {"path": str(METRICS_DOC.relative_to(ROOT)),
                             "sha256": _sha256(METRICS_DOC)},
        "local_metrics": {"path": str(LOCAL.relative_to(BENCH)), "sha256": None},
        "candidate_count": len(candidates),
        "candidate_names": [row["name"] for row in candidates],
        "scenario_counts": preflight["scenario_manifest"]["counts"],
        "quality_contract": {
            **metrics_v1.exact_zero_q_calibration(),
            "sqnr_tolerance_db": 0.10,
            "cumulative_pruning_tolerance_bits": pruning_freeze[
                "cumulative_pruning_tolerance_bits"
            ],
            "pruning_tolerance_status": "approved before formal chain q",
        },
        "code_sha256": {str(path.relative_to(ROOT)): _sha256(path) for path in _code_files()},
        "code_checkpoint": _git_head(),
        "formal_execution_allowed": True,
        "remaining_gate": None,
    }
    _write_new(LOCAL, local)
    execution["local_metrics"]["sha256"] = _sha256(LOCAL)
    _write_new(EXECUTION, execution)
    return execution


def _validate_execution() -> tuple[dict, dict]:
    preflight, _, _ = validate_freezes()
    execution = _load(EXECUTION)
    if execution["formal_execution_allowed"] is not True:
        raise RuntimeError("execution manifest has not been launched")
    for key in ("preflight", "second_freeze", "metrics_freeze",
                "pruning_tolerance_freeze", "backend_erratum_freeze"):
        item = execution[key]
        if _sha256(BENCH / item["path"]) != item["sha256"]:
            raise RuntimeError(f"frozen input drifted: {key}")
    if _sha256(ROOT / execution["metrics_document"]["path"]) != execution["metrics_document"]["sha256"]:
        raise RuntimeError("metrics document drifted")
    if (_sha256(ROOT / execution["backend_erratum_document"]["path"])
            != execution["backend_erratum_document"]["sha256"]):
        raise RuntimeError("backend erratum document drifted")
    if _sha256(BENCH / execution["local_metrics"]["path"]) != execution["local_metrics"]["sha256"]:
        raise RuntimeError("local metrics drifted")
    for rel, digest in execution["code_sha256"].items():
        if _sha256(ROOT / rel) != digest:
            raise RuntimeError(f"code drifted: {rel}")
    return preflight, execution


def _sum_events(events: dict) -> dict:
    out = {}
    for component in ("i", "q"):
        e = events[component]
        out[component] = {
            "internal_wrap_event": e["internal_wrap_event"],
            "internal_sat_event": e["internal_sat_event"],
            "first_internal_event": e["first_internal_event"],
            "output_sat": e["output_sat"],
        }
    return out


def _evaluate_one(candidate: dict, spec: dict, sd=None) -> dict:
    sd = scenarios_v1.generate(spec) if sd is None else sd
    R, N = int(candidate["R"]), int(candidate["N"])
    y_ref, ref_audit = reference.normalized_iq(sd.i_codes, sd.q_codes, R, N)
    y_des, _ = reference.normalized_iq(
        sd.desired_i_codes, sd.desired_q_codes, R, N
    )
    got = run_iq(candidate, sd.i_codes.tolist(), sd.q_codes.tolist())
    y_fix = (np.asarray(got["i"], dtype=np.float64)
             + 1j * np.asarray(got["q"], dtype=np.float64)) / float(1 << 15)
    n_pre_out = sd.n_pre_in // R
    q = aligned_impl_error(y_ref, y_fix, n_pre_out, y_des_ref=y_des)
    if not math.isfinite(q["err_aligned"]):
        raise RuntimeError(f"non-finite q for {candidate['name']} {spec['scenario_key']}")
    return {
        "candidate": candidate["name"],
        "R": R,
        "N": N,
        "split": spec["split"],
        "scenario_key": spec["scenario_key"],
        "scenario_kind": spec["kind"],
        "anchor_g_khz": spec["anchor_g_khz"],
        "blocker_g_khz": spec["blocker_g_khz"],
        "q_raw": q["err_raw"],
        "q_aligned": q["err_aligned"],
        "q_raw_db": _finite_db_or_none(q["err_raw_db"]),
        "q_aligned_db": _finite_db_or_none(q["err_aligned_db"]),
        "gain_re": q["gain_re"],
        "gain_im": q["gain_im"],
        "gain_off_db": q["gain_off_db"],
        "phase_off_deg": q["phase_off_deg"],
        "p_ref": q["p_ref"],
        "n_measure_samples": len(y_ref) - n_pre_out,
        "events": _sum_events(got["events"]),
        "front_end_scale": sd.scale,
        "scenario_levels": sd.levels,
        "reference_audit": ref_audit,
    }


def _evaluate_split(preflight: dict, split: str) -> list[dict]:
    candidates = _candidate_rows(preflight)
    specs = [row for row in preflight["scenario_manifest"]["rows"] if row["split"] == split]
    rows = []
    started = time.monotonic()
    for index, spec in enumerate(specs, 1):
        sd = scenarios_v1.generate(spec)
        for candidate in candidates:
            if candidate["R"] == spec["R"]:
                rows.append(_evaluate_one(candidate, spec, sd))
        print(f"[{split}] scenario {index}/{len(specs)} rows={len(rows)} "
              f"elapsed={time.monotonic()-started:.1f}s", flush=True)
    return rows


def _aggregate(rows: list[dict], split: str) -> list[dict]:
    out = []
    for name in sorted({row["candidate"] for row in rows if row["split"] == split}):
        rs = [row for row in rows if row["split"] == split and row["candidate"] == name]
        worst = max(rs, key=lambda row: row["q_aligned"])
        out.append({
            "candidate": name,
            "R": worst["R"],
            "N": worst["N"],
            "Q": worst["q_aligned"],
            "Q_db": worst["q_aligned_db"],
            "argmax_scenario_key": worst["scenario_key"],
            "n_scenarios": len(rs),
        })
    return out


def truth(run_id: str) -> dict:
    if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
        raise ValueError("invalid run-id")
    preflight, execution = _validate_execution()
    run_dir = RUNS / run_id
    if run_dir.exists():
        raise RuntimeError(f"refuse to reuse run-id: {run_id}")
    run_dir.mkdir(parents=True)
    _write_new(run_dir / "run_manifest.json", {
        "schema_version": "cic-witness-run-v2",
        "run_id": run_id,
        "execution_manifest_sha256": _sha256(EXECUTION),
        "started_unix": time.time(),
    })

    main_rows = _evaluate_split(preflight, "main")
    main_agg = _aggregate(main_rows, "main")
    _write_new(run_dir / "main_checkpoint.json", {
        "rows": main_rows, "aggregate": main_agg
    })
    local = _load(LOCAL)["rows"]
    decision = metrics_v1.analyze_order(
        local, main_agg,
        float(execution["quality_contract"]["epsilon_q"]),
        int(execution["quality_contract"]["cumulative_pruning_tolerance_bits"]),
    )
    _write_new(run_dir / "main_decision.json", decision)

    heldout_rows = _evaluate_split(preflight, "heldout")
    heldout_agg = _aggregate(heldout_rows, "heldout")
    _write_new(run_dir / "heldout_checkpoint.json", {
        "rows": heldout_rows, "aggregate": heldout_agg
    })
    stress_rows = _evaluate_split(preflight, "stress")
    stress_agg = _aggregate(stress_rows, "stress")
    _write_new(run_dir / "stress_checkpoint.json", {
        "rows": stress_rows, "aggregate": stress_agg
    })
    result = {
        "schema_version": "cic-witness-results-v2",
        "run_id": run_id,
        "status": "formal_completed",
        "main_decision": decision,
        "main_aggregate": main_agg,
        "heldout_aggregate": heldout_agg,
        "stress_aggregate": stress_agg,
        "row_counts": {
            "main": len(main_rows), "heldout": len(heldout_rows), "stress": len(stress_rows)
        },
        "finished_unix": time.time(),
    }
    _write_new(run_dir / "results.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    run = sub.add_parser("truth")
    run.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepared = prepare()
        print(json.dumps(prepared, ensure_ascii=False, indent=2))
    else:
        result = truth(args.run_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
