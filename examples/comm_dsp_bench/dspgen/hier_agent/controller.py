"""Deterministic controller around LLM-proposed primitive-program macro actions."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dspgen.task import BENCH, get, run_program

from .model import (
    ActionKind,
    Attribution,
    Candidate,
    MacroAction,
    RegionContract,
    RootEvaluation,
    SignalContract,
    dominates,
)
from .source import tune_parameters


def inspect_program(code: str, task_name: str, timeout: int = 300) -> dict[str, Any]:
    request = json.dumps({"code": code, "task": task_name})
    try:
        process = subprocess.run(
            [sys.executable, "-W", "ignore", "-m", "dspgen.hier_agent.inspect_worker"],
            input=request,
            capture_output=True,
            text=True,
            cwd=BENCH,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "timeout", "message": f"inspection exceeded {timeout}s"}}
    try:
        return json.loads(process.stdout)
    except Exception:
        return {"ok": False, "error": {"code": "worker_crash", "message": process.stderr[-800:]}}


class HierExperiment:
    """Append-only experiment state; the full-program root alternative is never discarded."""

    def __init__(self, task_name: str, out_dir: Path, min_margin_db: float = 0.3):
        get(task_name)
        self.task_name = task_name
        self.out_dir = Path(out_dir)
        self.candidate_dir = self.out_dir / "candidates"
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        self.min_margin_db = float(min_margin_db)
        self.candidates: list[Candidate] = []
        self.attributions: dict[str, list[Attribution]] = {}
        state_path = self.out_dir / "state.json"
        if state_path.exists():
            self._load(state_path)

    def add_root(self, source: str, rationale: str = "preserve the complete primitive program") -> Candidate:
        return self.add_source(
            source,
            MacroAction(ActionKind.ROOT, ["root"], rationale),
            parent_id=None,
        )

    def add_source(self, source: str, action: MacroAction, parent_id: str | None) -> Candidate:
        digest = hashlib.sha256(source.encode()).hexdigest()
        existing = next((row for row in self.candidates if row.source_sha256 == digest), None)
        if existing:
            return existing
        candidate_id = f"c{len(self.candidates):03d}-{digest[:10]}"
        path = (self.candidate_dir / f"{candidate_id}.py").resolve()
        path.write_text(source)
        inspected = inspect_program(source, self.task_name)
        evaluation, regions = self._decode(inspected)
        candidate = Candidate(candidate_id, str(path), digest, parent_id, action, evaluation, regions)
        self.candidates.append(candidate)
        self.save()
        return candidate

    def tune(self, parent_id: str, edits: dict[str, Any], rationale: str) -> Candidate:
        parent = self.by_id(parent_id)
        source = Path(parent.source_path).read_text()
        tuned = tune_parameters(source, edits)
        return self.add_source(
            tuned,
            MacroAction(ActionKind.TUNE, parent.action.target_regions, rationale, edits),
            parent_id,
        )

    def by_id(self, candidate_id: str) -> Candidate:
        return next(row for row in self.candidates if row.candidate_id == candidate_id)

    def frontier(self) -> list[Candidate]:
        return [
            row
            for row in self.candidates
            if not any(
                other.candidate_id != row.candidate_id and dominates(other, row, self.min_margin_db)
                for other in self.candidates
            )
        ]

    def attribute(self, candidate_id: str, extra_bits: int = 4) -> list[Attribution]:
        candidate = self.by_id(candidate_id)
        evaluation = candidate.evaluation
        if not evaluation.valid or evaluation.margin_db is None:
            raise ValueError("cannot attribute an invalid candidate")
        code = Path(candidate.source_path).read_text()
        task = get(self.task_name)
        rows: list[Attribution] = []
        for scope, area in sorted(evaluation.per_scope_area.items()):
            result = run_program(
                code,
                self.task_name,
                task.search_scenarios,
                extra_bits=extra_bits,
                extra_scopes=[scope],
            )
            if result.get("ok"):
                quality = task.combine(result["scores"])
                widened = float(quality["snr_margin_db"])
                rows.append(
                    Attribution(
                        scope,
                        float(area),
                        evaluation.margin_db,
                        widened,
                        widened - evaluation.margin_db,
                        float(quality["ripple_db"]),
                        "ok",
                    )
                )
            else:
                rows.append(
                    Attribution(scope, float(area), evaluation.margin_db, None, None, None, "invalid")
                )
        self.attributions[candidate_id] = rows
        self.save()
        return rows

    def save(self) -> None:
        state = {
            "schema_version": "hier-agent-prototype-v1",
            "task": self.task_name,
            "min_margin_db": self.min_margin_db,
            "candidates": [row.to_dict() for row in self.candidates],
            "frontier_ids": [row.candidate_id for row in self.frontier()],
            "attributions": {
                key: [asdict(row) for row in value] for key, value in self.attributions.items()
            },
        }
        (self.out_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str))

    def _load(self, state_path: Path) -> None:
        state = json.loads(state_path.read_text())
        if state.get("schema_version") != "hier-agent-prototype-v1":
            raise ValueError(f"unsupported state schema: {state.get('schema_version')}")
        if state.get("task") != self.task_name:
            raise ValueError(f"state task {state.get('task')} != requested task {self.task_name}")
        self.min_margin_db = float(state["min_margin_db"])
        self.candidates = [_candidate_from_dict(row, state_path.parent) for row in state.get("candidates", [])]
        self.attributions = {
            key: [Attribution(**row) for row in rows] for key, rows in state.get("attributions", {}).items()
        }

    @staticmethod
    def _decode(result: dict[str, Any]) -> tuple[RootEvaluation, list[RegionContract]]:
        if not result.get("ok"):
            return RootEvaluation(False, error=result.get("error")), []
        quality, area = result["quality"], result["area"]
        evaluation = RootEvaluation(
            valid=True,
            passed=bool(quality["passed"]),
            margin_db=float(quality["snr_margin_db"]),
            ripple_db=float(quality["ripple_db"]),
            area_um2_est=float(area["total"]),
            per_scope_area={key: float(value) for key, value in area["per_scope"].items()},
        )
        syntax = {row["region_id"]: row for row in result["syntax"]}
        captures: dict[str, list[dict[str, Any]]] = {}
        for row in result["captures"]:
            captures.setdefault(row["region_id"], []).append(row)
        regions = []
        for region_id, row in syntax.items():
            dynamic = captures.get(region_id, [])
            ins = _unique_signals(dynamic, "inputs")
            outs = _unique_signals(dynamic, "outputs")
            regions.append(
                RegionContract(
                    region_id=region_id,
                    name=row["name"],
                    line=int(row["line"]),
                    inputs=list(row["inputs"]),
                    outputs=list(row["outputs"]),
                    input_signals=ins,
                    output_signals=outs,
                    area_um2_est=float(area["per_scope"].get(row["name"], 0.0)),
                    occurrences=len(dynamic),
                )
            )
        return evaluation, regions


def _unique_signals(rows: list[dict[str, Any]], side: str) -> list[SignalContract]:
    unique: dict[tuple, SignalContract] = {}
    for row in rows:
        for signal in row[side]:
            contract = SignalContract(**signal)
            key = tuple(asdict(contract).values())
            unique[key] = contract
    return list(unique.values())


def _candidate_from_dict(row: dict[str, Any], state_dir: Path) -> Candidate:
    action = dict(row["action"])
    action["kind"] = ActionKind(action["kind"])
    source_path = Path(row["source_path"])
    if not source_path.is_absolute():
        direct = source_path.resolve()
        source_path = direct if direct.exists() else (state_dir / source_path.name).resolve()
    regions = []
    for raw in row.get("regions", []):
        raw = dict(raw)
        raw["input_signals"] = [SignalContract(**signal) for signal in raw.get("input_signals", [])]
        raw["output_signals"] = [SignalContract(**signal) for signal in raw.get("output_signals", [])]
        regions.append(RegionContract(**raw))
    return Candidate(
        candidate_id=row["candidate_id"],
        source_path=str(source_path),
        source_sha256=row["source_sha256"],
        parent_id=row.get("parent_id"),
        action=MacroAction(**action),
        evaluation=RootEvaluation(**row["evaluation"]),
        regions=regions,
    )
