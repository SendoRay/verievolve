"""Durable development planning records, evaluation cache, recovery, and export.

This module is intentionally development-only.  It preserves every charged
proposal and candidate identity, but it does not turn public-fixture evidence
into a formal result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .canonicalize import candidate_hash, canonical_json
from .formula_contract import formula_hash, validate_formula_request
from .lower_rtl import lower_ddc_rtl
from .planning_loop import normalize_candidate_evaluation
from .validate import validate_candidate


BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parent.parent
_SOURCE_PATHS = (
    BENCH / "numeric_semantics.py",
    BENCH / "search_ir/formula_contract.py",
    BENCH / "search_ir/architecture_plan.py",
    BENCH / "search_ir/planning_loop.py",
    BENCH / "search_ir/llm_planner.py",
    BENCH / "search_ir/dev_fixtures.py",
    BENCH / "search_ir/development_evaluator.py",
    BENCH / "search_ir/development_synthesis.py",
    BENCH / "search_ir/evaluate.py",
    BENCH / "search_ir/lower_bittrue.py",
    BENCH / "search_ir/lower_rtl.py",
    BENCH / "search_ir/run_archive.py",
    BENCH / "search_ir/synthesize.py",
    BENCH / "chains/ddc/fixed_chain.py",
    BENCH / "chains/ddc/ref_chain.py",
)


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(_json(value) + "\n")


def _sources() -> list[dict[str, str]]:
    return [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in _SOURCE_PATHS
    ]


class PlanningRunArchive:
    """Single-writer archive whose committed attempts can be resumed exactly."""

    def __init__(
        self,
        output_root: Path,
        run_id: str,
        formula: Any,
        *,
        max_attempts: int,
        evaluation_contract: Mapping[str, Any] | None = None,
        synthesis_contract: Mapping[str, Any] | None = None,
        max_synthesis_evaluations: int = 0,
        run_metadata: Mapping[str, Any] | None = None,
        resume: bool = False,
    ) -> None:
        if not isinstance(run_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id
        ):
            raise ValueError("invalid run_id")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be in [1, 20]")
        request = validate_formula_request(formula)
        contract = None if evaluation_contract is None else deepcopy(dict(evaluation_contract))
        synth_contract = (
            None if synthesis_contract is None else deepcopy(dict(synthesis_contract))
        )
        if type(max_synthesis_evaluations) is not int or max_synthesis_evaluations < 0:
            raise ValueError("max_synthesis_evaluations must be a nonnegative integer")
        if (synth_contract is None) != (max_synthesis_evaluations == 0):
            raise ValueError("synthesis contract and positive synthesis budget are required together")
        metadata = None if run_metadata is None else deepcopy(dict(run_metadata))
        self.path = Path(output_root) / run_id
        self._manifest = {
            "schema_version": "verievolve-development-planning-run-v1",
            "evidence_role": "development_only",
            "run_id": run_id,
            "formula_sha256": formula_hash(request),
            "formula_request": request,
            "max_attempts": max_attempts,
            "evaluation_contract": contract,
            "evaluation_contract_sha256": None if contract is None else _digest(contract),
            "synthesis_contract": synth_contract,
            "synthesis_contract_sha256": (
                None if synth_contract is None else _digest(synth_contract)
            ),
            "max_synthesis_evaluations": max_synthesis_evaluations,
            "run_metadata": metadata,
            "sources": _sources(),
            "resume_policy": "continue only after fully committed attempts; never overwrite",
        }
        if resume:
            self._open_existing()
        else:
            self._create()

    def _create(self) -> None:
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "attempts").mkdir()
        (self.path / "candidates").mkdir()
        (self.path / "exports").mkdir()
        _write_new(self.path / "manifest.json", self._manifest)
        (self.path / "attempts.jsonl").touch(exist_ok=False)
        self._manifest_sha256 = _sha(self.path / "manifest.json")

    def _open_existing(self) -> None:
        actual = json.loads((self.path / "manifest.json").read_text(encoding="utf-8"))
        if actual != self._manifest:
            raise ValueError("resume manifest differs from the requested run contract")
        if (self.path / "result.json").exists():
            raise ValueError("completed run cannot be resumed")
        self._manifest_sha256 = _sha(self.path / "manifest.json")
        self.transcript()

    def _check_manifest(self) -> None:
        if _sha(self.path / "manifest.json") != self._manifest_sha256:
            raise RuntimeError("planning manifest drifted")
        if _sources() != self._manifest["sources"]:
            raise RuntimeError("planning sources drifted")

    def transcript(self) -> list[dict[str, Any]]:
        self._check_manifest()
        ledger_path = self.path / "attempts.jsonl"
        ledger = [
            json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        rows = []
        for attempt, entry in enumerate(ledger, 1):
            if entry.get("attempt") != attempt:
                raise RuntimeError("attempt ledger is not contiguous")
            path = self.path / "attempts" / f"attempt-{attempt:04d}.json"
            if not path.is_file() or _sha(path) != entry.get("sha256"):
                raise RuntimeError("attempt file is missing or drifted")
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("attempt") != attempt:
                raise RuntimeError("attempt file identity mismatch")
            rows.append(row)
        files = sorted((self.path / "attempts").glob("attempt-*.json"))
        if len(files) != len(rows):
            raise RuntimeError("uncommitted or extra attempt file exists")
        return rows

    def _candidate_directory(self, candidate: Mapping[str, Any]) -> tuple[str, Path]:
        validate_candidate(candidate)
        identity = candidate_hash(candidate)
        directory = self.path / "candidates" / identity
        canonical = json.loads(canonical_json(candidate))
        if directory.exists():
            stored = json.loads((directory / "candidate.json").read_text(encoding="utf-8"))
            if stored != canonical or candidate_hash(stored) != identity:
                raise RuntimeError("candidate archive identity drifted")
        else:
            directory.mkdir()
            _write_new(directory / "candidate.json", canonical)
        return identity, directory

    def record_attempt(self, row: Mapping[str, Any]) -> None:
        """Commit one charged planner attempt after its compile/evaluation result exists."""
        self._check_manifest()
        value = deepcopy(dict(row))
        existing = self.transcript()
        attempt = len(existing) + 1
        if value.get("attempt") != attempt or attempt > self._manifest["max_attempts"]:
            raise RuntimeError("attempt is out of order or outside the frozen budget")
        result = value.get("result")
        if isinstance(result, Mapping) and result.get("status") == "ok":
            identity, _ = self._candidate_directory(result["candidate"])
            if candidate_hash(result["candidate"]) != identity:
                raise RuntimeError("compiled candidate identity mismatch")
        path = self.path / "attempts" / f"attempt-{attempt:04d}.json"
        _write_new(path, value)
        entry = {"attempt": attempt, "sha256": _sha(path)}
        with (self.path / "attempts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(_json(entry) + "\n")
            handle.flush()

    def cached_evaluate(
        self,
        candidate: Mapping[str, Any],
        formula: Any,
        evaluator: Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate once per candidate/contract and return an explicit cache status."""
        self._check_manifest()
        request = validate_formula_request(formula)
        if formula_hash(request) != self._manifest["formula_sha256"]:
            raise ValueError("evaluation formula differs from the planning manifest")
        if self._manifest["evaluation_contract"] is None:
            raise ValueError("this run has no evaluation contract")
        identity, directory = self._candidate_directory(candidate)
        path = directory / "evaluation.json"
        contract_hash = self._manifest["evaluation_contract_sha256"]
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                record.get("candidate_hash") != identity
                or record.get("evaluation_contract_sha256") != contract_hash
            ):
                raise RuntimeError("cached evaluation identity drifted")
            result = normalize_candidate_evaluation(record["result"])
            return {**result, "cache": {"hit": True, "source": str(path)}}
        result = normalize_candidate_evaluation(
            evaluator(deepcopy(dict(candidate)), deepcopy(request))
        )
        _write_new(path, {
            "candidate_hash": identity,
            "evaluation_contract_sha256": contract_hash,
            "result": result,
        })
        return {**result, "cache": {"hit": False, "source": str(path)}}

    def _synthesis_charged(self) -> int:
        return sum(
            1 for path in (self.path / "candidates").glob("*/synthesis.json")
            if path.is_file()
        )

    def cached_synthesize(
        self,
        candidate: Mapping[str, Any],
        formula: Any,
        evaluator: Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Run or reuse one synthesis evaluation under its separately frozen budget."""
        self._check_manifest()
        request = validate_formula_request(formula)
        if formula_hash(request) != self._manifest["formula_sha256"]:
            raise ValueError("synthesis formula differs from the planning manifest")
        contract_hash = self._manifest["synthesis_contract_sha256"]
        if contract_hash is None:
            raise ValueError("this run has no synthesis contract")
        identity, directory = self._candidate_directory(candidate)
        path = directory / "synthesis.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                record.get("candidate_hash") != identity
                or record.get("synthesis_contract_sha256") != contract_hash
            ):
                raise RuntimeError("cached synthesis identity drifted")
            return {**record["result"], "cache": {"hit": True, "source": str(path)}}
        charged = self._synthesis_charged()
        limit = self._manifest["max_synthesis_evaluations"]
        if charged >= limit:
            return {
                "status": "budget_exhausted",
                "cache": {"hit": False, "source": None},
                "budget": {"limit": limit, "charged": charged, "remaining": 0},
            }
        result = deepcopy(dict(evaluator(deepcopy(dict(candidate)), deepcopy(request))))
        if result.get("status") not in {"ok", "timeout", "failed"}:
            raise ValueError("synthesis evaluator returned an unknown status")
        _write_new(path, {
            "candidate_hash": identity,
            "synthesis_contract_sha256": contract_hash,
            "result": result,
        })
        return {**result, "cache": {"hit": False, "source": str(path)}}

    def budget_status(self) -> dict[str, Any]:
        charged = len(self.transcript())
        result = {
            "limit": self._manifest["max_attempts"],
            "charged": charged,
            "remaining": self._manifest["max_attempts"] - charged,
        }
        if self._manifest["max_synthesis_evaluations"]:
            synth_charged = self._synthesis_charged()
            result["synthesis"] = {
                "limit": self._manifest["max_synthesis_evaluations"],
                "charged": synth_charged,
                "remaining": self._manifest["max_synthesis_evaluations"] - synth_charged,
            }
        return result

    def finalize(self, result: Mapping[str, Any]) -> Path:
        self._check_manifest()
        value = deepcopy(dict(result))
        if value.get("transcript") != self.transcript():
            raise RuntimeError("final result transcript differs from committed attempts")
        if value.get("status") not in {"success", "exhausted", "inconclusive"}:
            raise ValueError("cannot finalize a nonterminal planning status")
        value["budget"] = self.budget_status()
        value["manifest_sha256"] = self._manifest_sha256
        path = self.path / "result.json"
        _write_new(path, value)
        return path

    def export_selected(self, name: str = "selected") -> Path:
        """Materialize the successful candidate and generated RTL without rerunning tools."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
            raise ValueError("invalid export name")
        self._check_manifest()
        result = json.loads((self.path / "result.json").read_text(encoding="utf-8"))
        if result.get("status") != "success":
            raise RuntimeError("only a successful run has a selected design")
        candidate = result["compile_result"]["candidate"]
        identity, _ = self._candidate_directory(candidate)
        rtl = lower_ddc_rtl(candidate)
        target = self.path / "exports" / name
        target.mkdir(exist_ok=False)
        _write_new(target / "candidate.json", json.loads(canonical_json(candidate)))
        (target / "design.v").write_text(rtl, encoding="utf-8")
        _write_new(target / "manifest.json", {
            "schema_version": "verievolve-development-export-v1",
            "evidence_role": "development_only",
            "source_manifest_sha256": self._manifest_sha256,
            "source_result_sha256": _sha(self.path / "result.json"),
            "candidate_hash": identity,
            "rtl_sha256": hashlib.sha256(rtl.encode("utf-8")).hexdigest(),
        })
        return target
