"""预注册的正式必要条件与条件性cost-first；旧pilot源码保持不变。"""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np

from chains.ddc import fixed_chain, scenarios, spec
from . import synthesize as synth
from .dev_fixtures import development_candidates
from .dev_run import THRESHOLD_SOURCE, build_context, _strict_json
from .evaluate import EvaluationError, aggregate_rows, evaluate_candidate, prepare_case
from .formal_state import FormalState
from .frontier import hypervolume, grid_values, engineering_hits, paired_bootstrap
from .pilot import AreaCache, area_key, _artifact_check, _event, _plain, watch
from .validate import IRValidationError, validate_candidate
from .validate_main import DEFAULT_AREA_RUN


BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parent.parent
OUTPUT = BENCH / "experiments_search/formal_s"
PILOT = BENCH / "experiments_search/pilot/paired-pilot-v2-20261002"
PILOT_AUDIT = ROOT / "refine-logs/PILOT_ANALYSIS.json"
CALIBRATION = BENCH / "experiments_search/pilot_calibration/fixed-repeat-v2-20261002/results.json"
VERIFICATION = BENCH / "experiments_search/verification/pilot-v2-rtl-deadline-v3-20261002"
VERIFIER = ROOT / "scripts/verify_ddc_pilot.py"
PROTOCOL = ROOT / "refine-logs/FORMAL_S_PROTOCOL_v1.json"
SEEDS = (101, 211, 307, 401, 503)
BUDGET = 32
Q_BUDGET = 2.32929922807541e-5
EPS_Q = 2.32929922807541e-6
A_REF = 38346.294
EPS_A = 383.46294


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return synth._sha(Path(path).read_bytes())


def write(path, value):
    synth._write_new(path, value)


def _split_definition(split):
    original = read(THRESHOLD_SOURCE)["scenario_manifest"]
    current = spec.export_witness_manifest()
    def view(doc):
        rows = [r for r in doc["scenarios"] if r["split"] == split]
        frequencies = {f"{r['f_off_mhz']:.3f}" for r in rows}
        return {**{k: v for k, v in doc.items() if k not in ("scenarios", "fcw")},
                "scenarios": rows, "fcw": {k: v for k, v in doc["fcw"].items() if k in frequencies}}
    expected = view(original)
    if view(current) != expected or len(expected["scenarios"]) != {"main": 36, "heldout": 32}[split]:
        raise EvaluationError("冻结场景定义漂移")
    return expected


def _cases(split, definition):
    values = []
    for scene, item in zip(spec.build_witness_scenarios(split), definition["scenarios"]):
        if any(item[key] != value for key, value in asdict(scene).items()):
            raise EvaluationError("实际场景与冻结清单不一致")
        data = scenarios.generate_scenario(scene)
        i, q = fixed_chain.adc_quantize(data.x_adc)
        values.append(prepare_case(item["key"], i, q, spec.fcw_of(scene.f_off_mhz), data.desired,
                                   scenarios.measure_start_out(data.n_pre)))
    if len(values) != len(definition["scenarios"]):
        raise EvaluationError("场景覆盖不完整")
    return values


class NumericContext:
    """复用原评分实现，但正式层使用准确的scope和独立的单一提案账本。"""

    def __init__(self, directory, split, definition):
        self.path, self.split = directory, split
        self.cases = _cases(split, definition)
        if [c.case_id for c in self.cases] != [r["key"] for r in definition["scenarios"]]:
            raise EvaluationError("正式数值上下文的场景覆盖不一致")
        self.context = self._context()
        self.digest = synth._digest(self.context)
        directory.mkdir()
        (directory / "evaluations").mkdir()
        inputs = []
        for index, case in enumerate(self.cases):
            path = directory / f"input-{index:03d}.npz"
            with path.open("xb") as handle:
                np.savez(handle, **{field: getattr(case, field) for field in (
                    "i12", "q12", "desired_input", "y_ref", "y_des_ref", "output_indices"
                )})
            inputs.append({"path": path.name, "sha256": sha(path)})
        self.inputs = inputs
        write(directory / "manifest.json", {"context": self.context, "context_sha256": self.digest,
                                             "inputs": inputs, "split": split})
        self.manifest_sha = sha(directory / "manifest.json")

    def _context(self):
        context = build_context(self.cases)
        context.update(schema_version="formal-numeric-context-v1", scope=f"formal {self.split} numeric substage",
                       formal_truth_allowed=True, proposer_enabled=False)
        context["quality"]["thresholds"]["use"] = "frozen quality thresholds; formal decision belongs to outer gate"
        return context

    def score(self, candidate, label):
        if synth._digest(self._context()) != self.digest or sha(self.path / "manifest.json") != self.manifest_sha:
            raise EvaluationError("正式数值上下文漂移")
        if any(sha(self.path / item["path"]) != item["sha256"] for item in self.inputs):
            raise EvaluationError("正式数值输入快照漂移")
        raw = evaluate_candidate(candidate, self.cases)
        if raw["candidate_hash"] != synth.candidate_hash(candidate) or raw["status"] not in ("ok", "mask_failed"):
            raise EvaluationError("正式评分回显身份或状态不一致")
        if raw["status"] == "ok":
            q = aggregate_rows(raw["rows"], [case.case_id for case in self.cases])
            if q != raw["Q_dev"] or [r["case_identity"] for r in raw["rows"]] != self.context["cases"]:
                raise EvaluationError("正式评分回显/覆盖不一致")
        if (synth._digest(self._context()) != self.digest
                or sha(self.path / "manifest.json") != self.manifest_sha
                or any(sha(self.path / item["path"]) != item["sha256"] for item in self.inputs)):
            raise EvaluationError("评分期间输入/快照/依赖发生漂移")
        result = {"schema_version": "formal-numeric-result-v1", "split": self.split,
                  "context_sha256": self.digest, "measurement": raw,
                  "note": "base adapter supplies numbers; this wrapper binds them to the frozen complete split"}
        path = self.path / "evaluations" / f"{label}.json"
        write(path, result)
        return raw, {"path": str(path), "sha256": sha(path)}


class WarmAreaCache(AreaCache):
    def __init__(self, root, contract):
        super().__init__(root, contract)
        previous = read(PILOT / "results.json")
        previous_manifest = read(PILOT / "manifest.json")
        audited = read(PILOT_AUDIT)
        if (audited["result_sha256"] != sha(PILOT / "results.json")
                or audited["manifest_sha256"] != sha(PILOT / "manifest.json")):
            raise EvaluationError("pilot来源不同于已审计版本")
        if previous["status"] != "pilot_completed" or previous["manifest_sha256"] != sha(PILOT / "manifest.json"):
            raise EvaluationError("pilot缓存来源不完整")
        configs = {r["candidate_hash"]: r["candidate"] for state in previous["arms"].values() for r in state["history"]}
        self.warm_index = []
        for path in sorted((PILOT / "cache").glob("*.json")):
            entry = read(path)
            row = entry["row"]
            identity = row["binding"]["candidate_hash"]
            config = configs[identity]
            rtl = synth.lower_ddc_rtl(config)
            key = area_key(config, rtl, previous_manifest["contract"])
            if key != path.stem or key != area_key(config, rtl, contract):
                raise EvaluationError("pilot缓存不能重标为新的工具/RTL身份")
            if row["status"] != "ok" or row["binding"]["rtl_sha256"] != synth._sha(rtl.encode()):
                raise EvaluationError("pilot缓存未对应当前候选")
            source_result = Path(entry["source_result"])
            if read(source_result) != row:
                raise EvaluationError("缓存条目不同于原始结果")
            if source_result.is_relative_to(DEFAULT_AREA_RUN):
                source_contract = read(DEFAULT_AREA_RUN / "manifest.json")["contract"]
            elif source_result.is_relative_to(PILOT / "synthesis"):
                source_contract = read(PILOT / "contracts" / f"{row['binding']['proposal_id']:04d}.json")
            else:
                raise EvaluationError("缓存来源不在已核验的C/pilot目录")
            if (synth._digest(source_contract) != row["binding"]["contract_sha256"]
                    or area_key(config, rtl, source_contract) != key):
                raise EvaluationError("缓存来源实际契约与key不一致")
            _artifact_check(row, source_result, entry["source_sha256"])
            if key not in self.entries:
                self._store(key, row, Path(entry["source_result"]))
            self.warm_index.append({"key": key, "source_entry": str(path), "sha256": sha(path)})
        if len(configs) != len(self.entries):
            raise EvaluationError("没有完整导入全部pilot成功面积缓存")


def _calibration_record(contract):
    result = read(CALIBRATION)
    manifest_path = CALIBRATION.parent / "manifest.json"
    previous = read(manifest_path)
    if (result["status"] != "ok" or result["epsilon_A_um2"] != EPS_A or len(result["rows"]) != 2
            or result["manifest_sha256"] != sha(manifest_path)):
        raise EvaluationError("缺少已通过的固定重复校准")
    old = previous["contract"]
    # 历史来源逐个核对；新增正式模块不回写旧清单，也不使旧证据自动失效。
    for item in [*old["sources"], old["yosys"], old["abc"], old["liberty"]]:
        if sha(item["path"]) != item["sha256"]:
            raise EvaluationError("校准来源被修改")
    if any(old[k]["sha256"] != contract[k]["sha256"] for k in ("yosys", "abc", "liberty")) or old["script_sha256"] != contract["script_sha256"]:
        raise EvaluationError("当前综合契约不同于校准")
    baseline = read(DEFAULT_AREA_RUN / "results.json")
    if (previous["candidate_indices"] != [1, 2]
            or previous["reference_results_sha256"] != sha(DEFAULT_AREA_RUN / "results.json")):
        raise EvaluationError("校准参考集合发生漂移")
    configs = development_candidates()
    for index, row in enumerate(result["rows"], 1):
        path = CALIBRATION.parent / f"job-{index:02d}/result.json"
        original = read(path)
        expected = {"attempt_id": index, "candidate_hash": synth.candidate_hash(configs[index]),
                    "rtl_sha256": synth._sha(synth.lower_ddc_rtl(configs[index]).encode()),
                    "contract_sha256": synth._digest(old), "manifest_sha256": result["manifest_sha256"]}
        if (row["binding"] != expected or row["status"] != "ok"
                or row["process"]["returncode"] != 0 or row["process"]["timed_out"] is not False):
            raise EvaluationError("校准任务绑定或进程状态不一致")
        if {k: v for k, v in row.items() if k != "repeat_matches"} != original:
            raise EvaluationError("校准汇总不匹配")
        for field in ("area_um2", "cells_by_type", "stat_top_sha256", "netlist_semantic_sha256"):
            if row[field] != baseline["rows"][index][field] or row["repeat_matches"][field] is not True:
                raise EvaluationError("补重复不一致")
        _artifact_check(original, path, sha(path))
    return {"path": str(CALIBRATION), "sha256": sha(CALIBRATION), "epsilon_A_um2": EPS_A}


class RTLChecks:
    def __init__(self, directory):
        self.path = directory
        directory.mkdir()
        description = importlib.util.spec_from_file_location("formal_rtl_support", VERIFIER)
        self.module = importlib.util.module_from_spec(description)
        description.loader.exec_module(self.module)
        self.script_sha = sha(VERIFIER)
        reference = read(VERIFICATION / "manifest.json")
        passed = read(VERIFICATION / "report.json")
        if (passed["status"] != "pass" or passed["candidate_count"] != 37
                or passed["manifest_sha256"] != sha(VERIFICATION / "manifest.json")
                or reference["script_sha256"] != self.script_sha
                or reference["source_result_sha256"] != sha(PILOT / "results.json")
                or {p["candidate_hash"] for p in passed["ddc_proofs"]} != set(reference["candidates"])):
            raise EvaluationError("pilot候选的RTL验证未完成或来源不匹配")
        self.inputs = reference
        self.tools = reference["tools"]
        for item in self.tools.values():
            if sha(item["path"]) != item["sha256"]:
                raise EvaluationError("RTL仿真工具发生漂移")
        rng = np.random.Generator(np.random.PCG64(20261002))
        self.acc = (np.arange(65536, dtype=np.int64) << 16) | rng.integers(0, 65536, size=65536)
        if synth._sha(self.acc.astype("<u4").tobytes()) != reference["phase_input_sha256"]:
            raise EvaluationError("相位验证向量漂移")
        self.proofs = {}

    def verify(self, candidate, proposal_id, deadline):
        identity = synth.candidate_hash(candidate)
        if sha(VERIFIER) != self.script_sha:
            raise EvaluationError("RTL验证脚本发生漂移")
        for item in self.tools.values():
            if sha(item["path"]) != item["sha256"]:
                raise EvaluationError("RTL验证工具发生漂移")
        if identity in self.proofs:
            stored = self.proofs[identity]
            if sha(stored["path"]) != stored["sha256"]:
                raise EvaluationError("缓存的RTL证明发生漂移")
            for path, digest in read(stored["path"])["artifacts"].items():
                if sha(path) != digest:
                    raise EvaluationError("RTL验证产物发生漂移")
            return stored
        if time.monotonic() >= deadline:
            raise TimeoutError("全局deadline在RTL验证前触发")
        tools = {**self.tools, "deadline": deadline}
        nco = self.module.check_nco(self.path / f"nco-{proposal_id:04d}", candidate["nco"], tools, self.acc)
        ddc = self.module.check_ddc(self.path / f"ddc-{proposal_id:04d}", candidate, tools,
                                    np.array(self.inputs["i12"], dtype=np.int64),
                                    np.array(self.inputs["q12"], dtype=np.int64), self.inputs["fcw"])
        artifacts = {str(path): sha(path) for name in (f"nco-{proposal_id:04d}", f"ddc-{proposal_id:04d}")
                     for path in (self.path / name).iterdir() if path.is_file()}
        proof = {"candidate_hash": identity, "nco": nco, "ddc": ddc,
                 "verifier_sha256": self.script_sha, "artifacts": artifacts}
        path = self.path / f"proof-{proposal_id:04d}.json"
        write(path, proof)
        self.proofs[identity] = {"path": str(path), "sha256": sha(path)}
        return self.proofs[identity]


def protocol_spec():
    return {
        "schema_version": "formal-S-protocol-v1", "seeds": list(SEEDS), "budget_per_arm": BUDGET,
        "initial_candidates": [{"candidate_hash": synth.candidate_hash(c), "candidate": c} for c in development_candidates()],
        "population": 8, "tournament": 2, "staged_lock_after": 16,
        "actions": "unchanged reviewed pilot actions; sequential one/two-step patches",
        "rng": "independent PCG64(seed) for each arm; no shared RNG",
        "q_budget": Q_BUDGET, "epsilon_Q": EPS_Q, "A_ref_um2": A_REF, "epsilon_A_um2": EPS_A,
        "quality_budget_multipliers": [0.25, 0.5, 1.0],
        "area_budget_multipliers": [0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
        "hv_reference": [1, 2], "bootstrap_seed": 271828, "bootstrap_samples": 10000,
        "bootstrap_quantile_method": "linear", "confidence_percentiles": [0.025, 0.975],
        "engineering_seed_requirement": 3, "both_baselines_same_grid_required": True,
        "empty_hv": 0, "empty_grid": None,
        "stage1_arms": ["joint", "staged"], "stage1_attempts": 320,
        "stage2_arms": ["cost-first"], "stage2_attempts": 160,
        "cost_first": {"target_cycle": [0.25, 0.5, 1.0],
                       "parents": "area-smallest 8 from own valid history satisfying current target; area/hash tournament",
                       "phase": "mixed throughout", "quality_used_for_parent_ranking": False},
        "stop_rule": "complete all five paired seeds and locked heldout evaluation; fail any stage1 necessary condition -> S0; otherwise execute frozen cost-first",
        "budget_unit": "all proposal attempts, including invalid/duplicate/timeout; one started event charges one",
        "saturation_gate": "zero events over accepted mixer inputs and retained valid FIR outputs, including preamble",
        "quality_cache": False, "area_cache": "all audited pilot successes, shared lookup only, never shared archive",
        "output_selection": "all-history main Q<=q_budget nondominated archive, frozen before heldout",
        "heldout_role": "historical holdout, final evaluation only; never proposal feedback",
        "candidate_timeout_seconds": 600, "stage_wall_limit_seconds": 43200,
        "failed_run": "inconclusive, never S0; no automatic retry or seed deletion",
        "LLM_allowed": False, "second_chain_allowed": False,
    }


def _ready(contract):
    if read(PROTOCOL) != protocol_spec():
        raise EvaluationError("正式协议不同于已实现的固定规格")
    path = ROOT / "refine-logs/FORMAL_S_READY.json"
    gate = read(path)
    if (gate["status"] != "reviewed" or gate["protocol_sha256"] != sha(PROTOCOL)
            or gate["sources_sha256"] != synth._digest(contract["sources"])
            or gate["verifier_sha256"] != sha(VERIFIER)
            or gate["verification_report_sha256"] != sha(VERIFICATION / "report.json")):
        raise EvaluationError("正式实现尚未通过匹配当前源码的独立复核")
    return {"path": str(path), "sha256": sha(path), "record": gate}


def _guard(manifest, manifest_path):
    synth._check_contract(manifest["contract"])
    for key in ("protocol", "readiness", "verifier", "calibration", "pilot_result", "pilot_audit", "verification_manifest", "verification_report"):
        item = manifest[key]
        if sha(item["path"]) != item["sha256"]:
            raise EvaluationError(f"正式运行输入漂移: {key}")
    if synth._digest(read(manifest_path)) != synth._digest(manifest):
        raise EvaluationError("正式manifest被修改")


def schedule(arms):
    result = []
    for index, seed in enumerate(SEEDS):
        ordered = list(arms) if index % 2 == 0 else list(reversed(arms))
        for attempt in range(1, BUDGET + 1):
            for arm in ordered:
                result.append({"seed": seed, "arm": arm, "attempt": attempt})
    return result


def search_phase(root, name, arms, first_id, context, cache, checks, manifest, deadline):
    directory = root / name
    directory.mkdir()
    for child in ("proposals", "trials", "states"):
        (directory / child).mkdir()
    states = {(seed, arm): FormalState(seed, arm, BUDGET, Q_BUDGET) for seed in SEEDS for arm in arms}
    trials = []
    active = None
    error = None
    charged = 0
    try:
        for offset, item in enumerate(schedule(arms)):
            if time.monotonic() >= deadline:
                raise TimeoutError("正式阶段全局deadline")
            _guard(manifest, root / "manifest.json")
            state = states[(item["seed"], item["arm"])]
            identifier = first_id + offset
            active = {"proposal_id": identifier, **item, "phase": state.phase(item["attempt"]),
                      "rng_before": copy.deepcopy(state.rng.bit_generator.state)}
            _event(directory / "ledger.jsonl", {**active, "event": "attempt_started", "budget_units": 1})
            charged += 1
            proposal = state.candidate(item["attempt"])
            write(directory / "proposals" / f"{identifier:04d}.json", {**active, **proposal})
            active.update(actions=proposal["actions"], action_error=proposal["error"],
                          parent_hash=proposal.get("parent_hash"), candidate_hash=None,
                          rng_after=copy.deepcopy(state.rng.bit_generator.state))
            record = None
            if proposal["error"] is not None:
                active["status"] = "invalid_proposal"
            else:
                candidate = _strict_json(json.dumps(proposal["candidate"]))
                validate_candidate(candidate)
                active["candidate_hash"] = synth.candidate_hash(candidate)
                measurement, source = context.score(candidate, f"{identifier:04d}")
                active["numeric_source"] = source
                active["status"] = measurement["status"]
                if measurement["status"] == "ok":
                    active["Q"] = measurement["Q_dev"]
                    saturated = any(r["n_sat_mix"] or r["n_sat_fir"] for r in measurement["rows"])
                    if saturated:
                        active["status"] = "saturation_failed"
                    else:
                        area = cache.get(candidate, identifier, deadline)
                        active["area"] = area
                        active["status"] = area["status"]
                        if area["status"] not in ("ok", "candidate_timeout", "global_deadline"):
                            raise EvaluationError("面积返回未知状态")
                        if area["status"] == "global_deadline" or time.monotonic() >= deadline:
                            raise TimeoutError("全局deadline，不计作候选600秒失败")
                        if area["status"] == "ok":
                            active["rtl_proof"] = checks.verify(candidate, identifier, deadline)
                            record = {"candidate": candidate, "candidate_hash": active["candidate_hash"],
                                      "Q": measurement["Q_dev"], "area_um2": area["area_um2"]}
            if time.monotonic() >= deadline:
                raise TimeoutError("全局deadline在提案完成前触发")
            _guard(manifest, root / "manifest.json")
            state.update(record, item["attempt"])
            write(directory / "trials" / f"{identifier:04d}.json", active)
            write(directory / "states" / f"{identifier:04d}.json", state.snapshot())
            trials.append(active)
            _event(directory / "ledger.jsonl", {"event": "attempt_finished", "proposal_id": identifier,
                                                 "budget_units": 0, "status": active["status"]})
            print(f"[{name} {offset+1}/{len(schedule(arms))}] {item['seed']} {item['arm']} {active['status']}", flush=True)
            active = None
        if charged != len(SEEDS) * len(arms) * BUDGET or any(s.last_attempt != BUDGET for s in states.values()):
            raise EvaluationError("正式预算未完整执行")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        if active is not None and not any(t["proposal_id"] == active["proposal_id"] for t in trials):
            active.update(status="interrupted", error=error)
            path = directory / "trials" / f"{active['proposal_id']:04d}.json"
            if not path.exists():
                write(path, active)
            trials.append(active)
    result = {"status": "main_completed" if error is None else "inconclusive", "error": error,
              "charged": charged, "trials": trials,
              "states": {f"{seed}-{arm}": state.snapshot() for (seed, arm), state in states.items()}}
    write(directory / "main_results.json", result)
    if error is not None:
        return result, None
    # 全部seed完成后一次固化，而非逐seed提前读取留出结果。
    lock = {"main_results_sha256": sha(directory / "main_results.json"),
            "collections": {key: state["main_archive"] for key, state in result["states"].items()},
            "selection_rule": protocol_spec()["output_selection"]}
    write(directory / "archive_lock.json", lock)
    return result, lock


def terminal_evaluation(root, phase, lock, definition, deadline):
    directory = root / phase
    lock_path = directory / "archive_lock.json"
    lock_sha = sha(lock_path)
    if read(lock_path) != lock:
        raise EvaluationError("留出前的固定候选集合不一致")
    context = NumericContext(directory / "heldout", "heldout", definition)
    candidates = {r["candidate_hash"]: r for records in lock["collections"].values() for r in records}
    evaluated = {}
    for index, (identity, record) in enumerate(sorted(candidates.items())):
        if time.monotonic() >= deadline:
            raise TimeoutError("留出终考全局deadline")
        raw, source = context.score(record["candidate"], identity)
        if raw["status"] != "ok":
            raise EvaluationError("main入选候选在终考中发生非预期mask/评分错误")
        saturated = any(r["n_sat_mix"] or r["n_sat_fir"] for r in raw["rows"])
        evaluated[identity] = {"candidate_hash": identity, "Q": raw["Q_dev"], "area_um2": record["area_um2"],
                               "eligible": not saturated and raw["Q_dev"] <= Q_BUDGET,
                               "observed_saturation": saturated, "numeric_source": source}
    if sha(lock_path) != lock_sha or time.monotonic() >= deadline:
        raise EvaluationError("候选锁定记录漂移或终考未在时限内完成")
    collections = {key: [evaluated[r["candidate_hash"]] for r in records if evaluated[r["candidate_hash"]]["eligible"]]
                   for key, records in lock["collections"].items()}
    report = {"status": "heldout_completed", "archive_lock_sha256": lock_sha,
              "candidates": evaluated, "collections": collections,
              "heldout_manifest_sha256": sha(directory / "heldout/manifest.json")}
    write(directory / "heldout_results.json", report)
    return report


def comparison(collections, baseline):
    deltas, rows = [], []
    for seed in SEEDS:
        joint = collections[f"{seed}-joint"]
        other = collections[f"{seed}-{baseline}"]
        jhv = hypervolume(joint, Q_BUDGET, A_REF)
        bhv = hypervolume(other, Q_BUDGET, A_REF)
        hits = engineering_hits(joint, [other], Q_BUDGET, A_REF, EPS_Q, EPS_A)
        deltas.append(jhv - bhv)
        rows.append({"seed": seed, "joint_hv": jhv, "baseline_hv": bhv, "difference": jhv-bhv,
                     "engineering_hits": hits, "joint_grid": grid_values(joint, Q_BUDGET, A_REF),
                     "baseline_grid": grid_values(other, Q_BUDGET, A_REF)})
    interval = paired_bootstrap(deltas)
    hit_seeds = sum(bool(row["engineering_hits"]) for row in rows)
    return {"baseline": baseline, "rows": rows, "bootstrap": interval, "engineering_hit_seeds": hit_seeds,
            "necessary_pass": interval["lower"] > 0 and hit_seeds >= 3}


def execute(run_id):
    root = synth._run_root(run_id, OUTPUT)
    contract = synth.build_contract()
    readiness = _ready(contract)
    calibration = _calibration_record(contract)
    started = time.monotonic()
    deadline = started + protocol_spec()["stage_wall_limit_seconds"]
    manifest = {"schema_version": "formal-S-execution-v1", "run_id": run_id, "contract": contract,
                "settings": protocol_spec(), "protocol": {"path": str(PROTOCOL), "sha256": sha(PROTOCOL)},
                "readiness": readiness, "calibration": calibration,
                "verifier": {"path": str(VERIFIER), "sha256": sha(VERIFIER)},
                "verification_manifest": {"path": str(VERIFICATION / "manifest.json"), "sha256": sha(VERIFICATION / "manifest.json")},
                "verification_report": {"path": str(VERIFICATION / "report.json"), "sha256": sha(VERIFICATION / "report.json")},
                "pilot_result": {"path": str(PILOT / "results.json"), "sha256": sha(PILOT / "results.json")},
                "pilot_audit": {"path": str(PILOT_AUDIT), "sha256": sha(PILOT_AUDIT)},
                "main_definition": _split_definition("main"), "heldout_definition": _split_definition("heldout"),
                "quality_adapter": "new formal context, same numeric scorer; one outer proposal ledger",
                "started_unix": time.time()}
    root.mkdir(parents=True, exist_ok=False)
    cache = WarmAreaCache(root, contract)
    manifest["warm_cache_index"] = cache.warm_index
    checks = RTLChecks(root / "rtl_checks")
    manifest["verification_tools"] = checks.tools
    write(root / "manifest.json", manifest)
    result = {"status": "inconclusive", "S": "N/A", "L": "N/A", "error": None,
              "cost_first": "not-run", "manifest_sha256": sha(root / "manifest.json")}
    try:
        context = NumericContext(root / "main_numeric", "main", manifest["main_definition"])
        first, lock = search_phase(root, "joint-staged", ("joint", "staged"), 1,
                                   context, cache, checks, manifest, deadline)
        if lock is None:
            raise EvaluationError(f"第一阶段未完成: {first['error']}")
        _guard(manifest, root / "manifest.json")
        heldout = terminal_evaluation(root, "joint-staged", lock, manifest["heldout_definition"], deadline)
        _guard(manifest, root / "manifest.json")
        first_comparison = comparison(heldout["collections"], "staged")
        write(root / "stage1_decision.json", first_comparison)
        result["joint_staged"] = first_comparison
        if not first_comparison["necessary_pass"]:
            result.update(status="formal_completed", S="S0", cost_first="not-run-preregistered-necessary-condition-failed")
        else:
            # 分支算法/代码已在首次提案前冻结；后续提案不接受heldout数值作为输入。
            deadline = time.monotonic() + protocol_spec()["stage_wall_limit_seconds"]
            result["cost_first"] = "running"
            second, lock2 = search_phase(root, "cost-first", ("cost-first",), 321,
                                         context, cache, checks, manifest, deadline)
            if lock2 is None:
                raise EvaluationError(f"成本优先阶段未完成: {second['error']}")
            heldout2 = terminal_evaluation(root, "cost-first", lock2, manifest["heldout_definition"], deadline)
            _guard(manifest, root / "manifest.json")
            combined = {**heldout["collections"], **heldout2["collections"]}
            second_comparison = comparison(combined, "cost-first")
            common = {str(seed): engineering_hits(combined[f"{seed}-joint"],
                      [combined[f"{seed}-staged"], combined[f"{seed}-cost-first"]],
                      Q_BUDGET, A_REF, EPS_Q, EPS_A) for seed in SEEDS}
            passed = (first_comparison["bootstrap"]["lower"] > 0
                      and second_comparison["bootstrap"]["lower"] > 0
                      and sum(bool(v) for v in common.values()) >= 3)
            result.update(status="formal_completed", S="S1" if passed else "S0", cost_first="completed",
                          joint_cost_first=second_comparison, common_engineering_hits=common)
        _guard(manifest, root / "manifest.json")
    except BaseException as exc:
        result.update(status="inconclusive", S="N/A", L="N/A",
                      error={"type": type(exc).__name__, "message": str(exc)})
        if result["cost_first"] == "running":
            result["cost_first"] = "incomplete"
    result["wall_seconds"] = time.monotonic() - started
    write(root / "results.json", result)
    return root / "results.json"


def launch(run_id):
    target = synth._run_root(run_id, OUTPUT)
    if target.exists():
        raise FileExistsError(target)
    directory = OUTPUT / f"{run_id}.launch"
    directory.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "search_ir.formal_run", "--worker", "--run-id", run_id,
               "--launch-dir", str(directory)]
    with (directory / "stdout.log").open("x") as out, (directory / "stderr.log").open("x") as err:
        proc = subprocess.Popen(command, cwd=BENCH, stdout=out, stderr=err, start_new_session=True)
    write(directory / "launch.json", {"pid": proc.pid, "command": command, "target": str(target), "started_unix": time.time()})
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--launch", action="store_true")
    modes.add_argument("--worker", action="store_true")
    modes.add_argument("--watch", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--launch-dir", type=Path)
    args = parser.parse_args(argv)
    if args.watch:
        print(synth._json(watch(args.watch, 240)))
        return 0
    if args.run_id is None:
        parser.error("--run-id is required")
    if args.launch:
        print(launch(args.run_id))
        return 0
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"formal worker interrupted: {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    done = {"exit_code": 1}
    try:
        path = execute(args.run_id)
        status = read(path)["status"]
        done.update(result_path=str(path), result_status=status, exit_code=0 if status == "formal_completed" else 1)
        print(path, flush=True)
    except BaseException as exc:
        import traceback
        traceback.print_exc()
        done["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        done["finished_unix"] = time.time()
        if args.launch_dir:
            write(args.launch_dir / "exit.json", done)
    return done["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
