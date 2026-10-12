#!/usr/bin/env python3
"""Run a joint sin/cos algorithm, precision, and microarchitecture search.

The provider proposes one bounded family candidate.  The audited adapter then
enumerates every 16-bit phase code, applies the frozen SQNR constraint, and
starts strict Nangate45 mapped-area synthesis only for qualified candidates.
The command is dry by default; tests inject provider and area callbacks.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping


BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

from joint_search import SearchLedger, evaluation_cache_key, feedback_payload
from joint_sincos import (
    FORMULA_ID,
    SCHEMA_VERSION as CANDIDATE_SCHEMA_VERSION,
    TASK_ID,
    SincosCandidateError,
    candidate_hash,
    evaluate_exact,
    lower_rtl,
    quality_gate,
    validate_candidate,
)
import mapped_area
import rotation_llm_client as llm_client


SCHEMA_VERSION = "joint-sincos-search-run-v1"
RESPONSE_SCHEMA_VERSION = "joint-sincos-proposal-v1"
DEFAULT_OUTPUT = BENCH / "experiments_m5/joint_sincos_search_v1"
DEFAULT_LIBERTY = BENCH / "pdk/NangateOpenCellLibrary_typical.lib"
DEFAULT_KEY_FILE = Path(
    "/Users/chengzhy/verievolve/examples/comm_dsp_bench/.api_key_deepseek"
)
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_API_BASE = "https://api.deepseek.com"
TARIFF = {
    "currency": "USD",
    "input_per_million": 0.3,
    "cache_input_per_million": 0.006,
    "output_per_million": 1.2,
    "label": "frozen_peak_tariff_supplied_for_joint_sincos_v1",
}
TASK = {
    "spec_version": 1,
    "task": TASK_ID,
    "dut_module": "top",
    "io_protocol": {
        "base": "stream_v1",
        "inputs": [{"name": "z", "width": 16, "signed": True}],
        "outputs": [
            {"name": "sin_out", "width": 16, "signed": True},
            {"name": "cos_out", "width": 16, "signed": True},
        ],
        "extensions": [],
    },
    "formula_version": FORMULA_ID,
}


class ProposalError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_reason(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(_canonical(value) + "\n")


def _compact_feedback(
    result: Mapping[str, Any], *, include_reason: bool
) -> dict[str, Any]:
    shared = feedback_payload(result, include_verified_reason=False)
    metrics = shared.get("measured_metrics")
    if isinstance(metrics, Mapping):
        shared["measured_metrics"] = {
            key: deepcopy(metrics[key])
            for key in (
                "sqnr_db",
                "component_sqnr_db",
                "maximum_error_lsb",
                "quality_threshold_db",
                "quality_passed",
                "algorithm_family",
                "phase_bits",
            )
            if key in metrics
        }
    area = shared.get("area")
    if isinstance(area, Mapping):
        shared["area"] = {
            key: deepcopy(area[key])
            for key in ("status", "area_um2", "num_cells", "timing", "power")
            if key in area
        }
    if isinstance(result.get("candidate_summary"), Mapping):
        shared["candidate_summary"] = deepcopy(result["candidate_summary"])
    if include_reason:
        shared["verified_reason"] = deepcopy(result.get("verified_reason"))
    return shared


def build_messages(
    proposal_index: int,
    prior_results: list[Mapping[str, Any]],
    *,
    minimum_sqnr_db: float,
    include_verified_reason: bool,
) -> list[dict[str, str]]:
    history = [
        _compact_feedback(row, include_reason=include_verified_reason)
        for row in prior_results[-3:]
    ]
    request = {
        "proposal_index": proposal_index,
        "formula": {
            "input": "signed 16-bit z; theta=z*pi/2^15 over [-pi,pi)",
            "outputs": "signed Q1.15 sin(theta), cos(theta)",
        },
        "optimization_objective": {
            "constraint": f"exhaustive_sqnr_db >= {minimum_sqnr_db}",
            "objective": "minimize strict Nangate45 mapped area",
            "secondary_axes": "latency_cycles and initiation_interval are recorded",
        },
        "joint_search_space": {
            "algorithm": [
                {
                    "family": "quarter_wave_lut",
                    "table_depth": [64, 128, 256, 512, 1024],
                    "interpolation": ["nearest", "linear", "quad"],
                    "required_microarchitecture": {
                        "datapath": "combinational_lookup",
                        "pipeline_stages": 1,
                        "latency_cycles": 1,
                        "initiation_interval": 1,
                        "resource_sharing": False,
                    },
                },
                {
                    "family": "iterative_cordic",
                    "iterations": "integer 7..20",
                    "required_microarchitecture": {
                        "datapath": "iterative_shift_add",
                        "pipeline_stages": 1,
                        "latency_cycles": "iterations+1",
                        "initiation_interval": "iterations+2",
                        "resource_sharing": True,
                    },
                },
            ],
            "precision": {
                "phase_bits": "integer 8..16",
                "output_width": 16,
                "output_frac": 15,
                "rounding": "nearest_ties_up",
                "overflow": "saturate",
            },
            "quality_evaluation": "all 65536 phase codes; min SQNR across sin/cos",
        },
        "response_schema": {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "algorithm": "one algorithm object above",
            "precision": "one complete precision object above",
            "microarchitecture": "the matching complete microarchitecture object",
            "minimum_sqnr_db": minimum_sqnr_db,
            "name": "1..64 character descriptive name",
        },
        "prior_evaluation": history,
        "instruction": (
            "Return one JSON object only. Jointly choose algorithm, precision, and "
            "microarchitecture. Do not return Verilog, Markdown, or prose. The external "
            "quality threshold cannot be relaxed."
        ),
    }
    return [
        {
            "role": "system",
            "content": (
                "Generate one bounded joint sin/cos hardware candidate as strict JSON. "
                "Use only configurations implemented by the checked backend."
            ),
        },
        {"role": "user", "content": _canonical(request)},
    ]


def parse_proposal(text: str | None, *, minimum_sqnr_db: float) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ProposalError("empty_response", "provider returned no proposal")
    if len(text.encode("utf-8")) > 12_000:
        raise ProposalError("response_size", "response exceeds 12000 bytes")
    try:
        proposal = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProposalError("json_syntax", f"invalid JSON: {exc.msg} at byte {exc.pos}") from exc
    required = {
        "schema_version",
        "algorithm",
        "precision",
        "microarchitecture",
        "minimum_sqnr_db",
        "name",
    }
    if not isinstance(proposal, dict) or set(proposal) != required:
        raise ProposalError("response_fields", f"proposal fields must be exactly {sorted(required)}")
    if proposal["schema_version"] != RESPONSE_SCHEMA_VERSION:
        raise ProposalError("schema_version", "unsupported proposal schema")
    threshold = proposal["minimum_sqnr_db"]
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or float(threshold) != float(minimum_sqnr_db)
    ):
        raise ProposalError("quality_constraint", "minimum_sqnr_db must equal the frozen threshold")
    name = proposal["name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 64:
        raise ProposalError("name", "name must contain 1..64 characters")
    candidate = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "task": {"task_id": TASK_ID, "formula_id": FORMULA_ID},
        "algorithm": deepcopy(proposal["algorithm"]),
        "precision": deepcopy(proposal["precision"]),
        "microarchitecture": deepcopy(proposal["microarchitecture"]),
        "quality_contract": {
            "metric": "sqnr_db",
            "direction": "max",
            "threshold": float(minimum_sqnr_db),
            "aggregation": "minimum_across_sin_cos",
            "evaluation": "integer-domain exhaustive enumeration of 65536 angle codes",
        },
        "metadata": {"name": name},
    }
    try:
        structural = validate_candidate(candidate)
        # Probe the lowering contract without generating RTL.  This rejects
        # structurally representable but currently unsupported schedules as a
        # proposal error, rather than mislabelling them as an EDA failure.
        from joint_sincos import backend_parameters

        backend_parameters(candidate)
    except (SincosCandidateError, ValueError, KeyError, TypeError) as exc:
        raise ProposalError("candidate_validation", str(exc)) from exc
    return {"proposal": proposal, "candidate": candidate, "structural_validation": structural}


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": candidate["metadata"]["name"],
        "algorithm": deepcopy(candidate["algorithm"]),
        "precision": deepcopy(candidate["precision"]),
        "microarchitecture": deepcopy(candidate["microarchitecture"]),
    }


def _finish(result: dict[str, Any], before: Mapping[str, int], ledger: SearchLedger) -> dict[str, Any]:
    after = ledger.snapshot()
    result["budget_event"] = {key: after[key] - before[key] for key in after}
    result["budget_totals"] = after
    return result


def _rejected_proposal(ledger: SearchLedger, reason: Mapping[str, Any]) -> dict[str, Any]:
    before = ledger.snapshot()
    ledger.proposal_count += 1
    return _finish(
        {
            "status": "invalid_structure",
            "decision": "rejected",
            "candidate_sha256": None,
            "cache_hit": False,
            "measured_metrics": {},
            "area": None,
            "verified_reason": deepcopy(dict(reason)),
        },
        before,
        ledger,
    )


def _undetermined_provider_attempt(
    ledger: SearchLedger, *, provider_status: object, diagnostic: object
) -> dict[str, Any]:
    before = ledger.snapshot()
    ledger.proposal_count += 1
    status = (
        "timeout"
        if provider_status == "timeout"
        else "tool_failure"
        if provider_status in {"api_error", "invalid_request", "invalid_response"}
        else "unknown"
    )
    return _finish(
        {
            "status": status,
            "decision": "undetermined",
            "candidate_sha256": None,
            "cache_hit": False,
            "measured_metrics": {},
            "area": None,
            "verified_reason": None,
            "diagnostic": deepcopy(diagnostic),
        },
        before,
        ledger,
    )


def _evaluate_candidate(
    candidate: Mapping[str, Any],
    *,
    context_sha256: str,
    area_evaluator: Callable[[str], Mapping[str, Any]],
    ledger: SearchLedger,
    cache: dict[str, Mapping[str, Any]],
) -> dict[str, Any]:
    before = ledger.snapshot()
    ledger.proposal_count += 1
    ledger.evaluation_request_count += 1
    digest = candidate_hash(candidate)
    duplicate = digest in ledger.seen_candidate_sha256
    if duplicate:
        ledger.duplicate_proposal_count += 1
    ledger.seen_candidate_sha256.add(digest)
    key = evaluation_cache_key(digest, context_sha256)
    if key in cache:
        cached = deepcopy(dict(cache[key]))
        cached.update({"cache_hit": True, "duplicate_proposal": duplicate})
        return _finish(cached, before, ledger)

    base = {
        "candidate_sha256": digest,
        "evaluation_cache_key": key,
        "cache_hit": False,
        "duplicate_proposal": duplicate,
        "measured_metrics": {},
    }
    try:
        metrics = dict(evaluate_exact(candidate))
        verdict = quality_gate(candidate, metrics)
    except Exception as exc:
        return _finish(
            {
                **base,
                "status": "tool_failure",
                "decision": "undetermined",
                "failure_stage": "quality",
                "verified_reason": None,
                "diagnostic": f"{type(exc).__name__}: {exc}",
            },
            before,
            ledger,
        )
    metrics.update(
        {
            "quality_threshold_db": verdict["threshold"],
            "quality_passed": verdict["passed"],
        }
    )
    base["measured_metrics"] = metrics
    if not verdict["passed"]:
        result = {
            **base,
            "status": "quality_failed",
            "decision": "rejected",
            "verified_reason": {
                "code": "quality_threshold",
                "metric": "sqnr_db",
                "direction": "max",
                "threshold": verdict["threshold"],
                "measured": verdict["measured"],
            },
        }
        cache[key] = deepcopy(result)
        return _finish(result, before, ledger)
    try:
        rtl = lower_rtl(candidate)
    except Exception as exc:
        return _finish(
            {
                **base,
                "status": "tool_failure",
                "decision": "undetermined",
                "failure_stage": "rtl_lowering",
                "verified_reason": None,
                "diagnostic": f"{type(exc).__name__}: {exc}",
            },
            before,
            ledger,
        )
    try:
        raw_area = area_evaluator(rtl)
    except TimeoutError as exc:
        ledger.tool_execution_count += 1
        return _finish(
            {**base, "status": "timeout", "decision": "undetermined", "failure_stage": "area", "verified_reason": None, "diagnostic": str(exc)},
            before,
            ledger,
        )
    except Exception as exc:
        ledger.tool_execution_count += 1
        return _finish(
            {**base, "status": "tool_failure", "decision": "undetermined", "failure_stage": "area", "verified_reason": None, "diagnostic": f"{type(exc).__name__}: {exc}"},
            before,
            ledger,
        )
    executions = raw_area.get("tool_executions", 0) if isinstance(raw_area, Mapping) else 0
    if type(executions) is not int or executions < 0:
        executions = 0
    ledger.tool_execution_count += executions
    if not isinstance(raw_area, Mapping):
        return _finish(
            {**base, "status": "tool_failure", "decision": "undetermined", "failure_stage": "area", "verified_reason": None, "diagnostic": "area evaluator returned no object"},
            before,
            ledger,
        )
    status = raw_area.get("status")
    if status in {"tool_failure", "timeout", "unknown"}:
        return _finish(
            {**base, "status": status, "decision": "undetermined", "failure_stage": "area", "verified_reason": None, "diagnostic": str(raw_area.get("diagnostic", status))},
            before,
            ledger,
        )
    if status != "ok":
        return _finish(
            {**base, "status": "tool_failure", "decision": "undetermined", "failure_stage": "area", "verified_reason": None, "diagnostic": f"invalid area status: {status}"},
            before,
            ledger,
        )
    area = raw_area.get("value", raw_area)
    result = {
        **base,
        "status": "qualified",
        "decision": "accepted",
        "verified_reason": None,
        "area": deepcopy(dict(area)),
        "rtl_sha256": hashlib.sha256(rtl.encode()).hexdigest(),
    }
    cache[key] = deepcopy(result)
    return _finish(result, before, ledger)


def _default_area_callback(
    output: Path, task: dict[str, Any], contract: dict[str, Any]
) -> Callable[[str], Mapping[str, Any]]:
    counter = 0

    def evaluate(rtl: str) -> Mapping[str, Any]:
        nonlocal counter
        counter += 1
        result = mapped_area.run_job(
            output / "synthesis" / f"job-{counter:03d}",
            rtl,
            task,
            contract,
            binding={"experiment": SCHEMA_VERSION, "tool_execution_index": counter},
        )
        if result.get("status") == "ok":
            return {"status": "ok", "value": deepcopy(result), "tool_executions": 1}
        return {
            "status": "timeout" if result.get("status") == "timeout" else "tool_failure",
            "diagnostic": result.get("error") or result.get("status"),
            "tool_executions": 1,
        }

    return evaluate


def run(
    output: Path,
    calls: int,
    *,
    verified_feedback: bool,
    minimum_sqnr_db: float = 60.0,
    model: str = DEFAULT_MODEL,
    api_base: str = DEFAULT_API_BASE,
    key_file: Path | None = DEFAULT_KEY_FILE,
    temperature: float = 0.9,
    provider_seed: int | None = None,
    liberty: Path = DEFAULT_LIBERTY,
    generate_fn: Callable[..., Mapping[str, Any]] = llm_client.generate,
    area_evaluator: Callable[[str], Mapping[str, Any]] | None = None,
    task: dict[str, Any] | None = None,
    area_contract: dict[str, Any] | None = None,
) -> Path:
    if type(calls) is not int or calls < 1:
        raise ValueError("calls must be a positive integer")
    if isinstance(minimum_sqnr_db, bool) or not isinstance(minimum_sqnr_db, (int, float)) or not math.isfinite(minimum_sqnr_db):
        raise ValueError("minimum_sqnr_db must be finite")
    task = deepcopy(task) if task is not None else deepcopy(TASK)
    if area_contract is None and area_evaluator is None:
        area_contract = mapped_area.build_contract(
            task,
            liberty=Path(liberty),
            timeout_seconds=600,
            source_files=[Path(__file__), BENCH / "joint_sincos.py", BENCH / "joint_search.py"],
        )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if area_evaluator is None:
        if area_contract is None:
            raise AssertionError("area contract was not built")
        area_evaluator = _default_area_callback(output, task, area_contract)
    context = {
        "task": task,
        "minimum_sqnr_db": float(minimum_sqnr_db),
        "quality_evaluator": "joint_sincos.evaluate_exact:all-65536-phase-codes",
        "rtl_lowerer": "joint_sincos.lower_rtl",
        "area_contract": area_contract if area_contract is not None else "injected-test-double",
    }
    context_sha256 = _digest(context)
    source_names = ("run_joint_sincos_search.py", "joint_sincos.py", "joint_search.py")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "started_unix": time.time(),
        "proposal_budget": calls,
        "model": model,
        "api_base": api_base,
        "temperature": temperature,
        "provider_seed": provider_seed,
        "automatic_retry": False,
        "minimum_sqnr_db": float(minimum_sqnr_db),
        "verified_failure_feedback": verified_feedback,
        "quality_evaluation": "integer-domain exhaustive enumeration of all 65536 phase codes",
        "paired_arm_rule": "same measured evidence/accounting; only verified_reason omitted in control",
        "context_sha256": context_sha256,
        "task": task,
        "task_sha256": mapped_area.digest(task),
        "source_sha256": {name: _file_sha(BENCH / name) for name in source_names},
        "tariff": TARIFF,
        "area_contract": area_contract,
        "liberty": str(Path(liberty).resolve()),
        "interpretation_boundary": (
            "The model selects between checked quarter-wave LUT and iterative CORDIC families, "
            "phase precision, and each family's supported microarchitecture. This v1 runner does "
            "not synthesize arbitrary datapaths or a fully pipelined CORDIC."
        ),
    }
    _write_new(output / "manifest.json", manifest)

    ledger = SearchLedger()
    cache: dict[str, Mapping[str, Any]] = {}
    prior_results: list[Mapping[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index in range(1, calls + 1):
        call_dir = output / "llm_calls" / f"call-{index:03d}"
        messages = build_messages(
            index,
            prior_results,
            minimum_sqnr_db=float(minimum_sqnr_db),
            include_verified_reason=verified_feedback,
        )
        request = {
            "model": model,
            "messages": messages,
            "max_output_tokens": 4000,
            "temperature": temperature,
            "seed": provider_seed,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        _write_new(call_dir / "prompt.json", request)
        response = dict(
            generate_fn(
                messages,
                model=model,
                api_base=api_base,
                key_file=key_file,
                max_output_tokens=4000,
                timeout=180,
                temperature=temperature,
                seed=provider_seed,
                extra_body=request["extra_body"],
            )
        )
        usage = deepcopy(response.get("usage"))
        if not isinstance(usage, dict):
            usage = {"status": "unknown", "reported": False, "input_tokens": None, "output_tokens": None, "cache_tokens": None, "actual_billed_cost": None}
            response["usage"] = usage
        cost = llm_client.calculate_cost(usage, TARIFF)
        response["cost"] = cost
        _write_new(call_dir / "raw_response.json", response)
        _write_new(call_dir / "tokens.json", usage)
        _write_new(call_dir / "cost.json", cost)

        if response.get("status") != "ok":
            diagnostic = deepcopy(response.get("error") or {"provider_status": response.get("status")})
            parsed = {"status": "not_parsed_provider_undetermined", "proposal": None, "candidate": None, "verified_reason": None, "diagnostic": diagnostic}
            evaluation = _undetermined_provider_attempt(ledger, provider_status=response.get("status"), diagnostic=diagnostic)
        else:
            try:
                parsed = {"status": "ok", **parse_proposal(response.get("text"), minimum_sqnr_db=float(minimum_sqnr_db))}
                evaluation = _evaluate_candidate(
                    parsed["candidate"],
                    context_sha256=context_sha256,
                    area_evaluator=area_evaluator,
                    ledger=ledger,
                    cache=cache,
                )
                evaluation["candidate_summary"] = _candidate_summary(parsed["candidate"])
            except ProposalError as exc:
                reason = exc.as_reason()
                parsed = {"status": "rejected", "proposal": None, "candidate": None, "verified_reason": reason}
                evaluation = _rejected_proposal(ledger, reason)
        _write_new(call_dir / "parsed.json", parsed)
        _write_new(call_dir / "evaluation.json", evaluation)
        prior_results.append(evaluation)
        metrics = evaluation.get("measured_metrics") or {}
        area = evaluation.get("area") or {}
        record = {
            "proposal_index": index,
            "provider_status": response.get("status"),
            "prompt_sha256": _file_sha(call_dir / "prompt.json"),
            "raw_response_sha256": _file_sha(call_dir / "raw_response.json"),
            "parsed_sha256": _file_sha(call_dir / "parsed.json"),
            "evaluation_sha256": _file_sha(call_dir / "evaluation.json"),
            "tokens_sha256": _file_sha(call_dir / "tokens.json"),
            "cost_sha256": _file_sha(call_dir / "cost.json"),
            "candidate_sha256": evaluation.get("candidate_sha256"),
            "status": evaluation.get("status"),
            "decision": evaluation.get("decision"),
            "cache_hit": evaluation.get("cache_hit"),
            "budget_event": deepcopy(evaluation.get("budget_event")),
            "candidate_summary": deepcopy(evaluation.get("candidate_summary")),
            "measured_metrics": {
                key: deepcopy(metrics.get(key))
                for key in ("sqnr_db", "component_sqnr_db", "maximum_error_lsb", "enumerated_input_codes", "quality_threshold_db", "quality_passed", "algorithm_family", "phase_bits")
                if key in metrics
            },
            "area": {key: deepcopy(area.get(key)) for key in ("status", "area_um2", "num_cells", "timing", "power") if key in area},
            "verified_reason": deepcopy(evaluation.get("verified_reason")),
            "usage": usage,
            "cost": cost,
        }
        _write_new(call_dir / "record.json", record)
        records.append(record)
        print(f"[joint-sincos] {index}/{calls} {record['status']} decision={record['decision']} cache={record['cache_hit']}", flush=True)

    qualified = [row for row in records if row["status"] == "qualified" and isinstance(row["area"].get("area_um2"), (int, float))]
    best = None
    if qualified:
        selected = min(qualified, key=lambda row: (float(row["area"]["area_um2"]), row["proposal_index"]))
        best = {key: deepcopy(selected[key]) for key in ("proposal_index", "candidate_sha256", "candidate_summary", "measured_metrics", "area", "evaluation_sha256")}
    results = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "manifest_sha256": _file_sha(output / "manifest.json"),
        "proposal_calls": len(records),
        "provider_ok_calls": sum(row["provider_status"] == "ok" for row in records),
        "qualified_candidates": sum(row["status"] == "qualified" for row in records),
        "rejected_candidates": sum(row["decision"] == "rejected" for row in records),
        "undetermined_candidates": sum(row["decision"] == "undetermined" for row in records),
        "budget_totals": ledger.snapshot(),
        "best_qualified_by_area": best,
        "reported_input_tokens": sum(row["usage"].get("input_tokens") or 0 for row in records),
        "reported_output_tokens": sum(row["usage"].get("output_tokens") or 0 for row in records),
        "estimated_cost": math.fsum(row["cost"].get("estimated_cost") or 0.0 for row in records),
        "actual_billed_cost": None,
        "records": records,
        "finished_unix": time.time(),
        "limitations": [
            "the v1 family space contains checked LUT and iterative CORDIC implementations, not arbitrary RTL",
            "the iterative CORDIC is resource-shared and is not an II=1 implementation",
            "strict mapped area has no STA or physical implementation claim",
            "statistical conclusions require paired multi-seed runs",
        ],
    }
    _write_new(output / "results.json", results)
    return output / "results.json"


def preview(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "status": "dry_run",
        "message": "No API, exhaustive evaluation, or synthesis was started; pass --execute-api to run.",
        "output": str(args.output),
        "calls": args.calls,
        "verified_failure_feedback": not args.disable_verified_feedback,
        "minimum_sqnr_db": args.minimum_sqnr_db,
        "first_messages": build_messages(1, [], minimum_sqnr_db=args.minimum_sqnr_db, include_verified_reason=not args.disable_verified_feedback),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--calls", type=int, default=8)
    parser.add_argument("--minimum-sqnr-db", type=float, default=60.0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--provider-seed", type=int)
    parser.add_argument("--liberty", type=Path, default=DEFAULT_LIBERTY)
    parser.add_argument("--disable-verified-feedback", action="store_true")
    parser.add_argument("--execute-api", action="store_true", help="start provider calls, exhaustive evaluation, and synthesis")
    args = parser.parse_args(argv)
    if not args.execute_api:
        print(_canonical(preview(args)))
        return 0
    print(
        run(
            args.output,
            args.calls,
            verified_feedback=not args.disable_verified_feedback,
            minimum_sqnr_db=args.minimum_sqnr_db,
            model=args.model,
            api_base=args.api_base,
            key_file=args.key_file,
            temperature=args.temperature,
            provider_seed=args.provider_seed,
            liberty=args.liberty,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
