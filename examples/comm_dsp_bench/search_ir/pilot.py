"""有界两臂 pilot：同一选择器、独立 RNG、失败计数及真实面积缓存。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import numpy as np

from .actions import propose
from .canonicalize import candidate_hash
from .dev_fixtures import development_candidates
from .dev_run import DevRun
from .evaluate import EvaluationError
from .selection import family_key, lock_families, main_archive, ranked, tournament, truncate
from . import synthesize as synth
from .validate_main import DEFAULT_AREA_RUN, frozen_main_definition, main_cases, verified_areas


BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parent.parent
DRAFT = ROOT / "refine-logs/PILOT_MANIFEST_v1.json"
PILOT_ROOT = BENCH / "experiments_search/pilot"
CAL_ROOT = BENCH / "experiments_search/pilot_calibration"
RECORD_FIELDS = ("candidate", "candidate_hash", "Q", "area_um2")


def _plain(record: dict) -> dict:
    return {key: copy.deepcopy(record[key]) for key in RECORD_FIELDS}


def _write(path: Path, value) -> None:
    synth._write_new(path, value)


def _hash(path: Path) -> str:
    return synth._sha(path.read_bytes())


def _event(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(synth._json(value) + "\n")
        handle.flush()


def _artifact_check(row: dict, result_path: Path, expected_sha: str) -> None:
    if _hash(result_path) != expected_sha:
        raise EvaluationError("缓存来源结果发生漂移")
    for name, digest in row["artifacts"].items():
        if Path(name).name != name or _hash(result_path.parent / name) != digest:
            raise EvaluationError("缓存来源综合产物发生漂移")


def area_key(config: dict, rtl: str, contract: dict) -> str:
    """实际 RTL 与工具/脚本决定面积；不把场景或临时路径放入面积缓存键。"""
    return synth._digest({
        "candidate_hash": candidate_hash(config), "rtl_sha256": synth._sha(rtl.encode()),
        "yosys": contract["yosys"]["sha256"], "abc": contract["abc"]["sha256"],
        "liberty": contract["liberty"]["sha256"], "script": contract["script_sha256"],
    })


class AreaCache:
    """只缓存成功面积；不向搜索器暴露其他臂的候选或缓存目录。"""

    def __init__(self, root: Path, contract: dict, initial_root: Path = DEFAULT_AREA_RUN):
        self.root = root
        self.contract = contract
        self.entries = {}
        (root / "cache").mkdir()
        (root / "synthesis").mkdir()
        (root / "contracts").mkdir()
        with (root / "synthesis/cells.lib").open("xb") as handle:
            handle.write(Path(contract["liberty"]["path"]).read_bytes())
        configs = development_candidates()
        verified = verified_areas(initial_root, configs)
        source = json.loads((initial_root / "results.json").read_text())
        source_contract = json.loads((initial_root / "manifest.json").read_text())["contract"]
        for index, config in enumerate(configs, 1):
            row = source["rows"][index - 1]
            if row["area_um2"] != verified["areas"][candidate_hash(config)]:
                raise EvaluationError("初始缓存面积不一致")
            rtl = synth.lower_ddc_rtl(config)
            source_key = area_key(config, rtl, source_contract)
            if source_key != area_key(config, rtl, contract):
                raise EvaluationError("旧面积与当前工具/库/脚本身份不同，不得重新标记缓存")
            self._store(source_key, row, initial_root / f"job-{index:02d}/result.json")

    def _store(self, key: str, row: dict, path: Path) -> None:
        if row["status"] != "ok":
            raise EvaluationError("不得缓存失败面积")
        entry = {"row": copy.deepcopy(row), "source_result": str(path.resolve()),
                 "source_sha256": _hash(path)}
        _write(self.root / "cache" / f"{key}.json", entry)
        self.entries[key] = entry

    def get(self, config: dict, proposal_id: int, deadline: float) -> dict:
        synth._check_contract(self.contract)
        if deadline <= time.monotonic():
            return {"status": "global_deadline", "cache_hit": False}
        rtl = synth.lower_ddc_rtl(config)
        key = area_key(config, rtl, self.contract)
        if key in self.entries:
            entry = self.entries[key]
            _artifact_check(entry["row"], Path(entry["source_result"]), entry["source_sha256"])
            return {"status": "ok", "cache_hit": True, "area_um2": entry["row"]["area_um2"],
                    "cache_key": key, "source_result": entry["source_result"],
                    "source_sha256": entry["source_sha256"]}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"status": "global_deadline", "cache_hit": False}
        # 个体600秒与全局deadline是两种不同的失败；后者不得进入候选p90样本。
        contract = copy.deepcopy(self.contract)
        contract["timeout_seconds"] = min(600.0, remaining)
        _write(self.root / "contracts" / f"{proposal_id:04d}.json", contract)
        binding = {"proposal_id": proposal_id, "candidate_hash": candidate_hash(config),
                   "rtl_sha256": synth._sha(rtl.encode()), "contract_sha256": synth._digest(contract)}
        directory = self.root / "synthesis" / f"job-{proposal_id:04d}"
        row = synth.run_job(directory, binding, contract, rtl,
                            synth.liberty_areas((self.root / "synthesis/cells.lib").read_text()))
        process = row.get("process", {})
        result = {"cache_hit": False, "source_result": str(directory / "result.json"),
                  "source_sha256": _hash(directory / "result.json"),
                  "cache_key": key, "wall_seconds": process.get("wall_seconds")}
        if process.get("timed_out") and remaining < 600:
            return {**result, "status": "global_deadline"}
        if row["status"] == "ok":
            self._store(key, row, directory / "result.json")
            return {**result, "status": "ok", "area_um2": row["area_um2"]}
        if process.get("timed_out"):
            return {**result, "status": "candidate_timeout", "cost_sample_seconds": 600.0}
        raise EvaluationError(f"非预期综合失败，停止pilot：{directory / 'result.json'}")


class ArmState:
    def __init__(self, seed: int, arm: str):
        self.seed = seed
        self.arm = arm
        # 两臂以同一seed分别初始化，绝不共用可变RNG实例。
        self.rng = np.random.Generator(np.random.PCG64(seed))
        self.population = []
        self.history = {}
        self.families = None

    def candidate(self, attempt: int, phase: str) -> dict:
        if attempt <= 3:
            return {"candidate": development_candidates()[attempt - 1], "actions": [], "error": None}
        family = None
        if self.arm == "staged" and self.families is not None:
            family = self.families[(attempt - 7) % len(self.families)]
        parent = tournament(self.population, self.rng, family=family)
        result = propose(parent["candidate"], self.rng, phase)
        if (family is not None and result["candidate"] is not None
                and family_key(result["candidate"]) != family):
            result = {**result, "candidate": None, "error": "locked structure family changed"}
        return {**result, "parent_hash": parent["candidate_hash"]}

    def update(self, record: dict | None, attempt: int) -> None:
        if record is not None:
            record = _plain(record)
            identity = record["candidate_hash"]
            if self.families is not None and family_key(record["candidate"]) not in self.families:
                raise EvaluationError("记录不属于锁定结构族")
            if identity in self.history and self.history[identity] != record:
                raise EvaluationError("相同候选的确定性质量/面积发生漂移")
            self.history[identity] = record
            # 每个有效提案插入后立即截断；重复按hash去重但提案预算不返还。
            self.population = [_plain(x) for x in truncate(
                [*self.population, record], capacity=8, families=self.families,
            )]
        if self.arm == "staged" and attempt == 6:
            history = list(self.history.values())
            self.families = lock_families(history, max_families=3)
            if not self.families:
                raise EvaluationError("结构阶段没有可锁定的有效族")
            selected = [x for x in self.population if family_key(x["candidate"]) in self.families]
            # 由全历史补缺失族；之后保留的是当前本族最佳，不永久钉死旧代表。
            for family in self.families:
                if not any(family_key(x["candidate"]) == family for x in selected):
                    selected.append(next(x for x in ranked(history)
                                         if family_key(x["candidate"]) == family))
            self.population = [_plain(x) for x in truncate(selected, capacity=8, families=self.families)]

    def snapshot(self, q_budget: float) -> dict:
        return {"rng_state": copy.deepcopy(self.rng.bit_generator.state),
                "population": self.population, "history": list(self.history.values()),
                "families": self.families,
                "main_archive": [_plain(x) for x in main_archive(list(self.history.values()), q_budget)]}


def calibration_run(run_id: str) -> Path:
    root = synth._run_root(run_id, CAL_ROOT)
    configs = development_candidates()
    verified_areas(DEFAULT_AREA_RUN, configs)
    original = json.loads((DEFAULT_AREA_RUN / "results.json").read_text())
    contract = synth.build_contract()
    frozen = [{"candidate": config, "candidate_hash": candidate_hash(config),
               "rtl_sha256": synth._sha(synth.lower_ddc_rtl(config).encode())} for config in configs]
    manifest = {"purpose": "remaining two fixed repeat checks, not search",
                "contract": contract, "candidates": frozen, "candidate_indices": [1, 2],
                "reference_results_sha256": _hash(DEFAULT_AREA_RUN / "results.json"),
                "epsilon_A_proposed_um2": 383.46294}
    root.mkdir(parents=True, exist_ok=False)
    with (root / "cells.lib").open("xb") as handle:
        handle.write(Path(contract["liberty"]["path"]).read_bytes())
    _write(root / "manifest.json", manifest)
    rows = []
    for attempt, index in enumerate((1, 2), 1):
        config = configs[index]
        binding = {"attempt_id": attempt, "candidate_hash": candidate_hash(config),
                   "rtl_sha256": frozen[index]["rtl_sha256"],
                   "contract_sha256": synth._digest(contract), "manifest_sha256": _hash(root / "manifest.json")}
        row = synth.run_job(root / f"job-{attempt:02d}", binding, contract,
                            synth.lower_ddc_rtl(config), synth.liberty_areas((root / "cells.lib").read_text()))
        if row["status"] == "ok":
            row["repeat_matches"] = {key: row[key] == original["rows"][index][key] for key in (
                "area_um2", "cells_by_type", "stat_top_sha256", "netlist_semantic_sha256",
            )}
        rows.append(row)
        print(f"[calibration] {attempt} {row['status']}", flush=True)
        if row["status"] != "ok" or not all(row["repeat_matches"].values()):
            break
    passed = len(rows) == 2 and all(r["status"] == "ok" and all(r["repeat_matches"].values()) for r in rows)
    _write(root / "results.json", {"status": "ok" if passed else "failed",
                                   "manifest_sha256": _hash(root / "manifest.json"), "rows": rows,
                                   "epsilon_A_um2": 383.46294 if passed else None,
                                   "interpretation": "engineering floor; observed repeat agreement, not a distribution bound"})
    return root / "results.json"


def _validated_draft() -> dict:
    draft = json.loads(DRAFT.read_text())
    reviewed = json.loads((ROOT / "refine-logs/PILOT_MANIFEST_20261001_220407.json").read_text())
    if draft != reviewed:
        raise EvaluationError("当前草案不同于已复核的版本快照")
    if draft["execution_allowed"] is not False:
        raise EvaluationError("必须从未执行草案生成新的执行manifest，不能原地修改草案授权")
    if _hash(ROOT / draft["rules"]["path"]) != draft["rules"]["sha256"]:
        raise EvaluationError("pilot规则摘要漂移")
    expected = []
    for index, seed in enumerate((11, 29, 47)):
        arms = ("joint", "staged") if index % 2 == 0 else ("staged", "joint")
        for attempt in range(1, 13):
            for arm in arms:
                phase = "initial" if attempt <= 3 else ("mixed" if arm == "joint" else ("structure" if attempt <= 6 else "numeric"))
                expected.append({"seed": seed, "arm": arm, "attempt": attempt, "phase": phase})
    if (draft["schedule"] != expected or draft["total_attempts"] != 72
            or draft["initial_candidates"] != [{"candidate_hash": candidate_hash(c), "candidate": c}
                                               for c in development_candidates()]):
        raise EvaluationError("pilot调度或初始候选与复核草案不一致")
    return draft


def _check_calibration(path: Path) -> dict:
    result = json.loads(path.read_text())
    manifest = json.loads((path.parent / "manifest.json").read_text())
    if (result["status"] != "ok" or result["epsilon_A_um2"] != 383.46294
            or len(result["rows"]) != 2 or manifest["candidate_indices"] != [1, 2]):
        raise EvaluationError("补重复校准尚未通过")
    baseline = json.loads((DEFAULT_AREA_RUN / "results.json").read_text())
    if _hash(DEFAULT_AREA_RUN / "results.json") != manifest["reference_results_sha256"]:
        raise EvaluationError("校准参照结果发生漂移")
    if result["manifest_sha256"] != _hash(path.parent / "manifest.json"):
        raise EvaluationError("校准manifest身份不一致")
    synth._check_contract(manifest["contract"])
    for index, row in enumerate(result["rows"], 1):
        fields = {"area_um2", "cells_by_type", "stat_top_sha256", "netlist_semantic_sha256"}
        if (row["status"] != "ok" or set(row["repeat_matches"]) != fields
                or any(row["repeat_matches"][field] is not True
                       or row[field] != baseline["rows"][index][field] for field in fields)):
            raise EvaluationError("校准重复结果不匹配")
        item = manifest["candidates"][index]
        expected_binding = {"attempt_id": index, "candidate_hash": item["candidate_hash"],
                            "rtl_sha256": item["rtl_sha256"],
                            "contract_sha256": synth._digest(manifest["contract"]),
                            "manifest_sha256": result["manifest_sha256"]}
        if (row["binding"] != expected_binding or row["process"]["returncode"] != 0
                or row["process"]["timed_out"] is not False):
            raise EvaluationError("补重复任务身份/进程状态不匹配")
        original = json.loads((path.parent / f"job-{index:02d}/result.json").read_text())
        if {key: value for key, value in row.items() if key != "repeat_matches"} != original:
            raise EvaluationError("校准任务与汇总不一致")
        _artifact_check(original, path.parent / f"job-{index:02d}/result.json",
                        _hash(path.parent / f"job-{index:02d}/result.json"))
    return {"path": str(path.resolve()), "sha256": _hash(path), "epsilon_A_um2": 383.46294}


def run_pilot(run_id: str, calibration: Path) -> Path:
    root = synth._run_root(run_id, PILOT_ROOT)
    draft = _validated_draft()
    cal = _check_calibration(calibration)
    definition = frozen_main_definition()
    contract = synth.build_contract()
    start = time.monotonic()
    deadline = start + draft["resources"]["pilot_wall_limit_seconds"]
    manifest = {"schema_version": "verievolve-pilot-execution-v1", "run_id": run_id,
                "draft": draft, "draft_sha256": _hash(DRAFT), "execution_allowed": True,
                "contract": contract, "main_definition": definition, "calibration": cal,
                "rng": "independent PCG64(seed) per seed/arm; same seed in paired arms",
                "update": "after each valid proposal; preserve current best member of each locked family",
                "quality_cache": False, "area_cache": True,
                "budget_accounting": "quality/*/attempts.jsonl attempt_started; outer events do not charge again",
                "formal_search": False, "S": "N/A", "L": "N/A", "started_unix": time.time()}
    root.mkdir(parents=True, exist_ok=False)
    _write(root / "manifest.json", manifest)
    (root / "trials").mkdir()
    (root / "states").mkdir()
    (root / "proposals").mkdir()
    rows = []
    states = {}
    quality = {}
    costs = []
    status, error = "incomplete", None
    active = None
    manifest_hash = _hash(root / "manifest.json")
    try:
        cases = main_cases(definition)
        cache = AreaCache(root, contract)
        for seed in draft["seeds"]:
            for arm in draft["arms"]:
                key = (seed, arm)
                states[key] = ArmState(seed, arm)
                quality[key] = DevRun(root / "quality", f"{seed}-{arm}", cases, max_attempts=12)
        for proposal_id, scheduled in enumerate(draft["schedule"], 1):
            if time.monotonic() >= deadline:
                raise TimeoutError("全局6小时预算已用完")
            if _hash(root / "manifest.json") != manifest_hash or _hash(DRAFT) != manifest["draft_sha256"]:
                raise EvaluationError("pilot manifest/规则发生漂移")
            key = (scheduled["seed"], scheduled["arm"])
            state, runner = states[key], quality[key]
            started = {"proposal_id": proposal_id, **scheduled,
                       "rng_before": copy.deepcopy(state.rng.bit_generator.state)}
            active = dict(started)
            _event(root / "events.jsonl", {**started, "event": "proposal_started"})
            proposer_error = None
            try:
                proposal = state.candidate(scheduled["attempt"], scheduled["phase"])
            except Exception as exc:
                proposer_error = str(exc)
                proposal = {"candidate": None, "actions": [], "error": f"proposer infrastructure: {exc}"}
            raw = proposal["candidate"] if proposal["error"] is None else {
                "invalid_action": proposal["error"], "actions": proposal["actions"],
            }
            _write(root / "proposals" / f"{proposal_id:04d}.json", {**started, **proposal})
            active.update(actions=proposal["actions"], action_error=proposal["error"],
                          parent_hash=proposal.get("parent_hash"))
            envelope = runner.submit(json.dumps(raw))
            trial = {**started, "actions": proposal["actions"], "action_error": proposal["error"],
                     "rng_after": copy.deepcopy(state.rng.bit_generator.state),
                     "quality_attempt_id": envelope["attempt_id"], "status": envelope["status"],
                     "candidate_hash": envelope["candidate_hash"],
                     "parent_hash": proposal.get("parent_hash")}
            active = trial
            if proposer_error is not None:
                trial["status"] = "proposer_failed"
                _write(root / "trials" / f"{proposal_id:04d}.json", trial)
                rows.append(trial)
                raise EvaluationError(proposer_error)
            record = None
            if envelope["status"] == "evaluation_failed":
                _write(root / "trials" / f"{proposal_id:04d}.json", trial)
                rows.append(trial)
                raise EvaluationError("质量评价发生系统性异常")
            if envelope["status"] == "ok":
                ev = envelope["evaluation"]
                saturated = any(row["n_sat_mix"] or row["n_sat_fir"] for row in ev["rows"])
                trial["Q"] = ev["Q_dev"]
                if saturated:
                    trial["status"] = "saturation_failed"
                else:
                    try:
                        area = cache.get(proposal["candidate"], proposal_id, deadline)
                    except Exception as exc:
                        trial["status"] = "area_infrastructure_failed"
                        trial["error"] = str(exc)
                        _write(root / "trials" / f"{proposal_id:04d}.json", trial)
                        rows.append(trial)
                        raise
                    trial["area"] = area
                    trial["status"] = area["status"]
                    if area["status"] == "global_deadline" or time.monotonic() >= deadline:
                        trial["status"] = "global_deadline"
                        _write(root / "trials" / f"{proposal_id:04d}.json", trial)
                        rows.append(trial)
                        raise TimeoutError("全局deadline触发，不计作候选600秒timeout")
                    if not area["cache_hit"]:
                        sample = area.get("cost_sample_seconds", area["wall_seconds"])
                        if sample is None or not np.isfinite(sample) or sample < 0:
                            raise EvaluationError("综合时延样本无效")
                        costs.append(sample)
                    if area["status"] == "ok":
                        record = {"candidate": proposal["candidate"],
                                  "candidate_hash": envelope["candidate_hash"], "Q": ev["Q_dev"],
                                  "area_um2": area["area_um2"]}
            state.update(record, scheduled["attempt"])
            _write(root / "trials" / f"{proposal_id:04d}.json", trial)
            rows.append(trial)
            _write(root / "states" / f"{proposal_id:04d}.json", state.snapshot(draft["evaluation"]["q_budget"]))
            _event(root / "events.jsonl", {"event": "proposal_finished", "proposal_id": proposal_id,
                                          "status": trial["status"]})
            print(f"[pilot {proposal_id}/72] {key} {trial['status']}", flush=True)
            active = None
        if time.monotonic() >= deadline or len(rows) != 72 or any(q._attempts != 12 for q in quality.values()):
            raise TimeoutError("全局时限或配对预算未完成")
        status = "pilot_completed"
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        if active is not None and not any(r["proposal_id"] == active["proposal_id"] for r in rows):
            aborted = {**active, "status": "interrupted", "error": error}
            runner = quality.get((active["seed"], active["arm"]))
            aborted["budget_charged"] = runner is not None and runner._attempts >= active["attempt"]
            target = root / "trials" / f"{active['proposal_id']:04d}.json"
            if not target.exists():
                _write(target, aborted)
            rows.append(aborted)
    p90 = float(np.quantile(costs, 0.9, method="higher")) if costs else None
    recommendation = (64 if status == "pilot_completed" and len(costs) >= 10 and p90 <= 90 else 32)
    result = {"status": status, "error": error, "manifest_sha256": manifest_hash,
              "trials": rows, "budget_charged": sum(q._attempts for q in quality.values()),
              "uncached_synthesis_costs": costs, "p90_seconds": p90,
              "formal_budget_recommendation": recommendation if status == "pilot_completed" else None,
              "arms": {f"{s}-{a}": state.snapshot(draft["evaluation"]["q_budget"])
                       for (s, a), state in states.items()},
              "wall_seconds": time.monotonic() - start, "S": "N/A", "L": "N/A"}
    _write(root / "results.json", result)
    return root / "results.json"


def launch(kind: str, run_id: str, calibration: Path | None = None) -> Path:
    """启动有界批处理而非项目服务；worker自行执行截止时间，日志与PID可查。"""
    base = CAL_ROOT if kind == "calibration" else PILOT_ROOT
    target = synth._run_root(run_id, base)
    if target.exists():
        raise FileExistsError(target)
    launch_dir = base / f"{run_id}.launch"
    launch_dir.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "search_ir.pilot", "--worker", kind, "--run-id", run_id,
               "--launch-dir", str(launch_dir.resolve())]
    if calibration is not None:
        command += ["--calibration", str(calibration.resolve())]
    with (launch_dir / "stdout.log").open("xb") as out, (launch_dir / "stderr.log").open("xb") as err:
        proc = subprocess.Popen(command, cwd=BENCH, stdout=out, stderr=err, start_new_session=True)
    _write(launch_dir / "launch.json", {"pid": proc.pid, "command": command,
                                       "target": str(target.resolve()), "started_unix": time.time()})
    return launch_dir


def watch(launch_dir: Path, seconds: int = 240) -> dict:
    """观察有界外部worker；超出观察窗口只返回running，不中止实际实验。"""
    if not 1 <= seconds <= 540:
        raise ValueError("观察窗口必须在1..540秒内")
    record = json.loads((launch_dir / "launch.json").read_text())
    end = time.monotonic() + seconds
    while True:
        if (launch_dir / "exit.json").is_file():
            return {"status": "exited", **json.loads((launch_dir / "exit.json").read_text())}
        try:
            os.kill(record["pid"], 0)
        except ProcessLookupError:
            return {"status": "worker_lost", "note": "没有完成记录；检查日志，不视为成功"}
        if time.monotonic() >= end:
            lines = (launch_dir / "stdout.log").read_text(errors="replace").splitlines()
            return {"status": "running", "recent_output": lines[-4:]}
        time.sleep(min(2.0, max(0.0, end - time.monotonic())))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--launch", choices=("calibration", "pilot"))
    group.add_argument("--worker", choices=("calibration", "pilot"))
    group.add_argument("--watch", type=Path)
    parser.add_argument("--watch-seconds", type=int, default=240)
    parser.add_argument("--run-id")
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--launch-dir", type=Path)
    args = parser.parse_args(argv)
    if args.watch:
        print(synth._json(watch(args.watch, args.watch_seconds)))
        return 0
    if args.run_id is None:
        parser.error("--run-id is required")
    kind = args.launch or args.worker
    if kind == "pilot" and args.calibration is None:
        parser.error("pilot requires --calibration")
    if args.launch:
        print(launch(kind, args.run_id, args.calibration))
        return 0
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"worker interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    completion = {"exit_code": 1}
    try:
        path = calibration_run(args.run_id) if kind == "calibration" else run_pilot(args.run_id, args.calibration)
        print(path, flush=True)
        status = json.loads(path.read_text())["status"]
        completion.update({"result_path": str(path.resolve()), "result_status": status,
                           "exit_code": 0 if status in ("ok", "pilot_completed") else 1})
    except BaseException as exc:
        import traceback
        traceback.print_exc()
        completion["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        completion["finished_unix"] = time.time()
        if args.launch_dir is not None:
            _write(args.launch_dir / "exit.json", completion)
    return completion["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
