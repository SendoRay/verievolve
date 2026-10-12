#!/usr/bin/env python3
"""Run a joint FIR structure-and-coefficient-precision LLM search.

Each provider response contains one complete, exact source arithmetic graph
and a low-bit drop decision for every explicit coefficient multiply.  The
task adapter converts both decisions into one generic joint-design candidate,
uses its deterministic FIR error model as the quality gate, and maps only
qualified RTL with the strict Nangate45 flow.

The command is dry by default.  Provider calls and synthesis are started only
with ``--execute-api``.  Tests inject both callbacks and never touch either
external service.
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

import mapped_area
from fir_decim_graph import (
    COEFFICIENTS_Q15,
    GraphValidationError,
    graph_sha256,
    validate_graph,
)
from joint_fir import candidate_from_graph, evaluate_analytic, lower_rtl
from joint_search import SearchLedger, evaluate_candidate, feedback_payload
import rotation_llm_client as llm_client


SCHEMA_VERSION = "joint-fir-search-run-v1"
RESPONSE_SCHEMA_VERSION = "joint-fir-proposal-v1"
DEFAULT_OUTPUT = BENCH / "experiments_m5/joint_fir_search_v1"
DEFAULT_LIBERTY = BENCH / "pdk/NangateOpenCellLibrary_typical.lib"
DEFAULT_KEY_FILE = Path(
    "/Users/chengzhy/verievolve/examples/comm_dsp_bench/.api_key_deepseek"
)
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_API_BASE = "https://api.deepseek.com"
ALLOWED_COEFFICIENT_DROPS = tuple(range(16))
TARIFF = {
    "currency": "USD",
    "input_per_million": 0.3,
    "cache_input_per_million": 0.006,
    "output_per_million": 1.2,
    "label": "frozen_peak_tariff_supplied_for_joint_fir_v1",
}
TASK = {
    "spec_version": 2,
    "task": "fir_decim_t16_r2_joint",
    "dut_module": "top",
    "io_protocol": {
        "base": "stream_v1",
        "inputs": [{"name": "x", "width": 16, "signed": True}],
        "outputs": [{"name": "y", "width": 40, "signed": True}],
        "extensions": [],
    },
    "formula_version": "fir16-q15-decimate2-v1",
}


class ProposalError(ValueError):
    """A provider response that cannot become a joint FIR candidate."""

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
    """Keep paired-arm evidence identical except for the verified reason."""
    shared = feedback_payload(result, include_verified_reason=False)
    metrics = shared.get("measured_metrics")
    if isinstance(metrics, Mapping):
        shared["measured_metrics"] = {
            key: deepcopy(metrics[key])
            for key in (
                "sqnr_db",
                "quality_threshold_db",
                "quality_passed",
                "candidate_semantics",
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
    summary = result.get("candidate_summary")
    if isinstance(summary, Mapping):
        shared["candidate_summary"] = deepcopy(dict(summary))
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
    # One complete FIR graph is already a substantial prompt object.  Keeping
    # only the last evaluation prevents an arm-dependent context overflow while
    # immutable run artifacts retain the complete history.
    history = [
        _compact_feedback(result, include_reason=include_verified_reason)
        for result in prior_results[-1:]
    ]
    graph_contract = {
        "schema_version": "fir-decim-arithmetic-graph-v1",
        "formula_version": "fir16-q15-decimate2-v1",
        "name": "1..64 character descriptive name",
        "phase_control": {
            "counter_modulus": 2,
            "emit_remainder": 1,
            "warmup_samples": 15,
        },
        "node_forms": [
            {"id": "x", "op": "input"},
            {"id": "d1", "op": "delay", "source": "x", "cycles": "integer 1..15"},
            {"id": "a", "op": "add", "inputs": ["prior_id", "prior_id"]},
            {"id": "s", "op": "sub", "inputs": ["prior_id", "prior_id"]},
            {
                "id": "p",
                "op": "constant_multiply",
                "input": "prior_id",
                "coefficient": "signed16 integer",
            },
            {"id": "y_reg", "op": "register", "input": "prior_id"},
            {"id": "y", "op": "output", "input": "y_reg"},
        ],
        "rules": [
            "topological order; first node is exactly input x",
            "delay nodes use source x and absolute accepted-sample cycles 1..15",
            "exactly one register directly feeds the final output",
            "every non-output node is used; 4..96 total nodes",
            "the unquantized graph impulse response exactly equals coefficients_q15",
            "shift and all unlisted operations are forbidden by the current backend",
        ],
    }
    request = {
        "proposal_index": proposal_index,
        "formula": {
            "coefficients_q15": list(COEFFICIENTS_Q15),
            "meaning": "sum coefficient[k]*accepted_input[n-k]; emit n=15,17,19,...",
            "input": "signed 16-bit integer",
            "output": "signed 40-bit Q15 product-domain integer",
        },
        "optimization_objective": {
            "constraint": f"sqnr_db >= {minimum_sqnr_db}",
            "objective": "minimize strict Nangate45 mapped area among feasible candidates",
            "precision_policy": (
                "precision is negotiable: jointly choose graph factorization and a 0..15 "
                "low-bit drop for every coefficient; exact zero-drop points remain legal"
            ),
        },
        "joint_search_space": {
            "graph": graph_contract,
            "coefficient_drops": {
                "keys": "every and only constant_multiply node id in graph",
                "allowed_values": list(ALLOWED_COEFFICIENT_DROPS),
                "meaning": "clear magnitude low bits of that coefficient toward zero",
            },
            "minimum_sqnr_db": {
                "required_value": minimum_sqnr_db,
                "rule": "frozen external constraint; copy exactly",
            },
        },
        "response_schema": {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "graph": "one complete graph satisfying graph_contract",
            "coefficient_drops": "object keyed by every constant_multiply node id",
            "minimum_sqnr_db": minimum_sqnr_db,
        },
        "prior_evaluation": history,
        "instruction": (
            "Return one JSON object only. Jointly choose the complete arithmetic graph and "
            "all coefficient precisions in this response. Do not return Verilog, a named "
            "template selector, Markdown, or prose. Structural reuse and algebraic regrouping "
            "must be expressed by graph nodes."
        ),
    }
    return [
        {
            "role": "system",
            "content": (
                "Generate one restricted joint FIR hardware candidate as strict JSON. "
                "The formula and quality threshold are external and cannot be relaxed."
            ),
        },
        {"role": "user", "content": _canonical(request)},
    ]


def _validate_backend_numeric_envelope(graph: Mapping[str, Any]) -> None:
    """Reject graphs whose integer semantics the current lowerer cannot preserve.

    The generic FIR adapter represents a one-level sample pre-add as signed
    17-bit and all product-domain arithmetic as signed 40-bit.  Its analytic
    model is unbounded integer algebra, so admitting a graph that can overflow
    either domain would silently compare different numerical functions.  This
    independent interval pass is conservative and runs before quality scoring.
    """
    intervals: dict[str, tuple[int, int]] = {}
    kinds: dict[str, str] = {}
    limit40 = (-(1 << 39), (1 << 39) - 1)
    for node in graph["nodes"]:
        node_id, op = node["id"], node["op"]
        if op in {"input", "delay"}:
            interval, kind = (-32768, 32767), "sample_leaf"
        elif op in {"add", "sub"}:
            left_id, right_id = node["inputs"]
            left, right = intervals[left_id], intervals[right_id]
            if op == "add":
                interval = (left[0] + right[0], left[1] + right[1])
            else:
                interval = (left[0] - right[1], left[1] - right[0])
            left_kind, right_kind = kinds[left_id], kinds[right_id]
            if left_kind.startswith("sample") and right_kind.startswith("sample"):
                if {left_kind, right_kind} != {"sample_leaf"}:
                    raise ProposalError(
                        "unsupported_sample_tree",
                        "the current 17-bit sample pre-add backend supports only pairs of input/delay leaves",
                    )
                kind = "sample_preadd"
                if interval[0] < -(1 << 16) or interval[1] > (1 << 16) - 1:
                    raise ProposalError(
                        "backend_numeric_envelope", "sample pre-add can overflow signed 17-bit"
                    )
            elif left_kind == right_kind == "product":
                kind = "product"
            else:
                raise ProposalError(
                    "mixed_numeric_domain",
                    "add/sub cannot mix sample-domain and product-domain values",
                )
        elif op == "constant_multiply":
            source = intervals[node["input"]]
            coefficient = node["coefficient"]
            endpoints = (source[0] * coefficient, source[1] * coefficient)
            interval, kind = (min(endpoints), max(endpoints)), "product"
        elif op in {"register", "output"}:
            interval = intervals[node["input"]]
            kind = kinds[node["input"]]
        else:
            raise ProposalError(
                "unsupported_backend_op", f"current joint FIR backend does not support {op!r}"
            )
        if interval[0] < limit40[0] or interval[1] > limit40[1]:
            raise ProposalError(
                "backend_numeric_envelope",
                f"node {node_id!r} can exceed the signed 40-bit RTL domain",
            )
        intervals[node_id] = interval
        kinds[node_id] = kind


def parse_proposal(text: str | None, *, minimum_sqnr_db: float) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ProposalError("empty_response", "provider returned no proposal")
    if len(text.encode("utf-8")) > 30_000:
        raise ProposalError("response_size", "response exceeds 30000 bytes")
    try:
        proposal = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProposalError(
            "json_syntax", f"invalid JSON: {exc.msg} at byte {exc.pos}"
        ) from exc
    if not isinstance(proposal, dict):
        raise ProposalError("response_type", "proposal must be a JSON object")
    required = {
        "schema_version",
        "graph",
        "coefficient_drops",
        "minimum_sqnr_db",
    }
    if set(proposal) != required:
        raise ProposalError(
            "response_fields", f"proposal fields must be exactly {sorted(required)}"
        )
    if proposal["schema_version"] != RESPONSE_SCHEMA_VERSION:
        raise ProposalError("schema_version", "unsupported proposal schema")
    threshold = proposal["minimum_sqnr_db"]
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or float(threshold) != float(minimum_sqnr_db)
    ):
        raise ProposalError(
            "quality_constraint",
            "minimum_sqnr_db must equal the frozen experiment threshold",
        )
    graph = proposal["graph"]
    try:
        graph_validation = validate_graph(graph)
    except GraphValidationError as exc:
        reason = exc.as_dict()
        raise ProposalError(str(reason["code"]), str(reason["message"])) from exc
    _validate_backend_numeric_envelope(graph)
    multiply_ids = {
        node["id"] for node in graph["nodes"] if node["op"] == "constant_multiply"
    }
    drops = proposal["coefficient_drops"]
    if (
        not isinstance(drops, dict)
        or set(drops) != multiply_ids
        or any(
            not isinstance(key, str)
            or type(value) is not int
            or value not in ALLOWED_COEFFICIENT_DROPS
            for key, value in drops.items()
        )
    ):
        raise ProposalError(
            "coefficient_drops",
            "coefficient_drops must name every and only constant_multiply node with values 0..15",
        )
    try:
        candidate = candidate_from_graph(
            graph,
            coefficient_drops=drops,
            minimum_sqnr_db=float(minimum_sqnr_db),
            name=graph["name"],
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ProposalError("candidate_validation", str(exc)) from exc
    return {
        "proposal": proposal,
        "graph_validation": graph_validation,
        "candidate": candidate,
    }


def _candidate_summary(proposal: Mapping[str, Any]) -> dict[str, Any]:
    graph = proposal["graph"]
    register = next(node for node in graph["nodes"] if node["op"] == "register")
    return {
        "graph_name": graph["name"],
        "graph_sha256": graph_sha256(graph),
        "delay_taps": [
            [node["id"], node["cycles"]]
            for node in graph["nodes"]
            if node["op"] == "delay"
        ],
        "arithmetic_nodes": [
            deepcopy(node)
            for node in graph["nodes"]
            if node["op"] in {"add", "sub", "constant_multiply"}
        ],
        "output_source": register["input"],
        "coefficient_drops": deepcopy(proposal["coefficient_drops"]),
    }


def _rejected_proposal(
    ledger: SearchLedger, reason: Mapping[str, Any]
) -> dict[str, Any]:
    before = ledger.snapshot()
    ledger.proposal_count += 1
    after = ledger.snapshot()
    return {
        "status": "invalid_structure",
        "decision": "rejected",
        "candidate_sha256": None,
        "cache_hit": False,
        "measured_metrics": {},
        "area": None,
        "verified_reason": deepcopy(dict(reason)),
        "budget_event": {key: after[key] - before[key] for key in after},
        "budget_totals": after,
    }


def _undetermined_provider_attempt(
    ledger: SearchLedger,
    *,
    provider_status: object,
    diagnostic: object,
) -> dict[str, Any]:
    before = ledger.snapshot()
    ledger.proposal_count += 1
    after = ledger.snapshot()
    if provider_status == "timeout":
        status = "timeout"
    elif provider_status in {"api_error", "invalid_request", "invalid_response"}:
        status = "tool_failure"
    else:
        status = "unknown"
    return {
        "status": status,
        "decision": "undetermined",
        "candidate_sha256": None,
        "cache_hit": False,
        "measured_metrics": {},
        "area": None,
        "verified_reason": None,
        "diagnostic": deepcopy(diagnostic),
        "budget_event": {key: after[key] - before[key] for key in after},
        "budget_totals": after,
    }


def _default_area_callback(
    output: Path,
    task: dict[str, Any],
    contract: dict[str, Any],
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
            summary = {
                key: deepcopy(result.get(key))
                for key in (
                    "status",
                    "area_um2",
                    "num_cells",
                    "cells_by_type",
                    "timing",
                    "power",
                    "binding",
                    "artifacts",
                )
            }
            return {"status": "ok", "value": summary, "tool_executions": 1}
        status = "timeout" if result.get("status") == "timeout" else "tool_failure"
        return {
            "status": status,
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
    """Execute a real or injected run in a new immutable evidence directory."""
    if type(calls) is not int or calls < 1:
        raise ValueError("calls must be a positive integer")
    if (
        isinstance(minimum_sqnr_db, bool)
        or not isinstance(minimum_sqnr_db, (int, float))
        or not math.isfinite(minimum_sqnr_db)
    ):
        raise ValueError("minimum_sqnr_db must be finite")
    task = deepcopy(task) if task is not None else deepcopy(TASK)
    if area_contract is None and area_evaluator is None:
        area_contract = mapped_area.build_contract(
            task,
            liberty=Path(liberty),
            timeout_seconds=600,
            source_files=[
                Path(__file__),
                BENCH / "joint_design_ir.py",
                BENCH / "joint_fir.py",
                BENCH / "joint_search.py",
                BENCH / "fir_decim_graph/core.py",
            ],
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
        "quality_evaluator": "joint_fir.evaluate_analytic",
        "rtl_lowerer": "joint_fir.lower_rtl",
        "area_contract": area_contract if area_contract is not None else "injected-test-double",
    }
    context_sha256 = _digest(context)
    source_names = (
        "run_joint_fir_search.py",
        "joint_design_ir.py",
        "joint_fir.py",
        "joint_search.py",
        "fir_decim_graph/core.py",
    )
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
        "allowed_coefficient_drops": list(ALLOWED_COEFFICIENT_DROPS),
        "coefficient_rounding": "magnitude low-bit clearing toward zero",
        "verified_failure_feedback": verified_feedback,
        "prompt_feedback_window": {
            "most_recent_attempts": 1,
            "complete_history_storage": "llm_calls/* and results.json records",
        },
        "paired_arm_rule": (
            "prompts contain identical measured status/metrics/area/accounting; only the "
            "verified_reason member is omitted by the control arm"
        ),
        "context_sha256": context_sha256,
        "task": task,
        "task_sha256": mapped_area.digest(task),
        "source_sha256": {name: _file_sha(BENCH / name) for name in source_names},
        "tariff": TARIFF,
        "area_contract": area_contract,
        "liberty": str(Path(liberty).resolve()),
        "interpretation_boundary": (
            "The LLM jointly emits a complete exact source FIR arithmetic graph and all "
            "coefficient low-bit drops. The audited adapter supplies native constant/delay "
            "joint IR nodes and the frozen R=2 stream shell. Pipeline scheduling, resource "
            "sharing, and arbitrary approximate source formulas are not model-controlled in v1."
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
            usage = {
                "status": "unknown",
                "reported": False,
                "input_tokens": None,
                "output_tokens": None,
                "cache_tokens": None,
                "actual_billed_cost": None,
            }
            response["usage"] = usage
        cost = llm_client.calculate_cost(usage, TARIFF)
        response["cost"] = cost
        _write_new(call_dir / "raw_response.json", response)
        _write_new(call_dir / "tokens.json", usage)
        _write_new(call_dir / "cost.json", cost)

        parsed: dict[str, Any]
        if response.get("status") != "ok":
            parsed = {
                "status": "not_parsed_provider_undetermined",
                "proposal": None,
                "candidate": None,
                "verified_reason": None,
                "diagnostic": deepcopy(
                    response.get("error")
                    if response.get("error") is not None
                    else {"provider_status": response.get("status")}
                ),
            }
            evaluation = _undetermined_provider_attempt(
                ledger,
                provider_status=response.get("status"),
                diagnostic=parsed["diagnostic"],
            )
        else:
            try:
                parsed = parse_proposal(
                    response.get("text"), minimum_sqnr_db=float(minimum_sqnr_db)
                )
                parsed = {"status": "ok", **parsed}
                evaluation = evaluate_candidate(
                    parsed["candidate"],
                    context_sha256=context_sha256,
                    quality_evaluator=evaluate_analytic,
                    rtl_lowerer=lower_rtl,
                    area_evaluator=area_evaluator,
                    ledger=ledger,
                    cache=cache,
                )
                evaluation["candidate_summary"] = _candidate_summary(parsed["proposal"])
            except ProposalError as exc:
                reason = exc.as_reason()
                parsed = {
                    "status": "rejected",
                    "proposal": None,
                    "candidate": None,
                    "verified_reason": reason,
                }
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
                for key in (
                    "sqnr_db",
                    "quality_threshold_db",
                    "quality_passed",
                    "candidate_semantics",
                )
                if key in metrics
            },
            "area": {
                key: deepcopy(area.get(key))
                for key in ("status", "area_um2", "num_cells", "timing", "power")
                if key in area
            },
            "verified_reason": deepcopy(evaluation.get("verified_reason")),
            "usage": usage,
            "cost": cost,
        }
        _write_new(call_dir / "record.json", record)
        records.append(record)
        print(
            f"[joint-fir] {index}/{calls} {record['status']} "
            f"decision={record['decision']} cache={record['cache_hit']}",
            flush=True,
        )

    qualified = [
        row
        for row in records
        if row["status"] == "qualified"
        and isinstance(row["area"].get("area_um2"), (int, float))
    ]
    best_qualified = None
    if qualified:
        selected = min(
            qualified,
            key=lambda row: (float(row["area"]["area_um2"]), row["proposal_index"]),
        )
        best_qualified = {
            key: deepcopy(selected[key])
            for key in (
                "proposal_index",
                "candidate_sha256",
                "candidate_summary",
                "measured_metrics",
                "area",
                "evaluation_sha256",
            )
        }
    results = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "manifest_sha256": _file_sha(output / "manifest.json"),
        "proposal_calls": len(records),
        "provider_ok_calls": sum(row["provider_status"] == "ok" for row in records),
        "qualified_candidates": sum(row["status"] == "qualified" for row in records),
        "rejected_candidates": sum(row["decision"] == "rejected" for row in records),
        "undetermined_candidates": sum(
            row["decision"] == "undetermined" for row in records
        ),
        "budget_totals": ledger.snapshot(),
        "parse_rejections": sum(
            row["status"] == "invalid_structure"
            and row["budget_event"].get("evaluation_request_count", 0) == 0
            for row in records
        ),
        "provider_undetermined": sum(
            row["decision"] == "undetermined"
            and row["budget_event"].get("evaluation_request_count", 0) == 0
            for row in records
        ),
        "best_qualified_by_area": best_qualified,
        "reported_input_tokens": sum(
            row["usage"].get("input_tokens") or 0 for row in records
        ),
        "reported_output_tokens": sum(
            row["usage"].get("output_tokens") or 0 for row in records
        ),
        "estimated_cost": math.fsum(
            row["cost"].get("estimated_cost") or 0.0 for row in records
        ),
        "actual_billed_cost": None,
        "records": records,
        "finished_unix": time.time(),
        "limitations": [
            "this v1 search requires an exact unquantized source graph before coefficient approximation",
            "the current FIR backend fixes pipeline scheduling and does not lower resource sharing",
            "strict mapped area has no STA or physical implementation claim",
            "statistical conclusions require paired multi-seed runs, not one batch",
        ],
    }
    _write_new(output / "results.json", results)
    return output / "results.json"


def preview(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "status": "dry_run",
        "message": "No API, simulation, or synthesis was started; pass --execute-api to run.",
        "output": str(args.output),
        "calls": args.calls,
        "verified_failure_feedback": not args.disable_verified_feedback,
        "minimum_sqnr_db": args.minimum_sqnr_db,
        "first_messages": build_messages(
            1,
            [],
            minimum_sqnr_db=args.minimum_sqnr_db,
            include_verified_reason=not args.disable_verified_feedback,
        ),
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
    parser.add_argument(
        "--execute-api",
        action="store_true",
        help="explicitly authorize provider calls and synthesis; default is dry-run",
    )
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
