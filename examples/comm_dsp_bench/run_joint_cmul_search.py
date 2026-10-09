#!/usr/bin/env python3
"""Run a joint CMUL structure-and-precision LLM search.

One provider response describes an exact algebraic operation graph and the
approximate fixed-point policy applied to every product.  The experiment does
not first choose a graph and then run a separate word-length optimizer.

The command line is deliberately dry by default.  A real provider call and
Nangate45 synthesis are made only when ``--execute-api`` is supplied.  Tests
can inject provider and area callbacks without touching either service.
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

import yaml


BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

import mapped_area
from cmul_graph import ALLOWED_DROPS, ALLOWED_MODES, GraphValidationError
from joint_cmul import candidate_from_graph, evaluate_analytic, lower_rtl
from joint_search import SearchLedger, evaluate_candidate, feedback_payload
import rotation_llm_client as llm_client


SCHEMA_VERSION = "joint-cmul-search-run-v5"
RESPONSE_SCHEMA_VERSION = "joint-cmul-proposal-v4"
DEFAULT_OUTPUT = BENCH / "experiments_m5/joint_cmul_search_v4"
TASK_FILE = BENCH / "tasks/cmul_w16_free/task.yaml"
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
    "label": "frozen_peak_tariff_supplied_for_joint_cmul_v4",
}


class ProposalError(ValueError):
    """A provider response that cannot become a joint candidate."""

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


def _compact_feedback(result: Mapping[str, Any], *, include_reason: bool) -> dict[str, Any]:
    """Keep both arms identical except for the optional verified reason."""
    shared = feedback_payload(result, include_verified_reason=False)
    metrics = shared.get("measured_metrics")
    if isinstance(metrics, Mapping):
        shared["measured_metrics"] = {
            key: deepcopy(metrics[key])
            for key in ("sqnr_db", "quality_threshold_db", "quality_passed")
            if key in metrics
        }
    area = shared.get("area")
    if isinstance(area, Mapping):
        shared["area"] = {
            key: deepcopy(area[key])
            for key in ("status", "area_um2", "num_cells", "timing", "power")
            if key in area
        }
    candidate_summary = result.get("candidate_summary")
    if isinstance(candidate_summary, Mapping):
        shared["candidate_summary"] = deepcopy(dict(candidate_summary))
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
    # Only the bounded feedback window enters the next provider request.  All
    # attempts remain present in their immutable call directories and results.
    history = [
        _compact_feedback(result, include_reason=include_verified_reason)
        for result in prior_results[-3:]
    ]
    request = {
        "proposal_index": proposal_index,
        "formula": {
            "y_re": "a*c-b*d",
            "y_im": "a*d+b*c",
            "inputs": "a,b,c,d are signed 16-bit Q1.15 integers",
            "outputs": "signed 33-bit",
        },
        "optimization_objective": {
            "constraint": f"sqnr_db >= {minimum_sqnr_db}",
            "objective": "minimize strict Nangate45 mapped area among feasible candidates",
            "precision_policy": (
                "precision is negotiable: deliberately explore nonzero product-LSB drops "
                "when the SQNR constraint permits; an exact point remains legal"
            ),
        },
        "joint_search_space": {
            "body_nodes": {
                "node_shape": {
                    "id": "unique_identifier_string",
                    "op": "add | sub | multiply",
                    "inputs": ["first_prior_value_id", "second_prior_value_id"],
                },
                "rules": [
                    "4..40 topologically ordered arithmetic nodes",
                    "a,b,c,d are predefined values and must not be emitted as nodes",
                    "each input reference is a,b,c,d or an earlier body-node id",
                    "register, input, and output nodes are forbidden in body_nodes",
                    "no dead nodes",
                    "each multiply combines a linear form of a/b with a linear form of c/d",
                    "the unquantized graph must implement both formulas exactly",
                ],
            },
            "outputs": {
                "field_shape": {"y_re": "body_node_id", "y_im": "body_node_id"},
                "rule": "both values reference body_nodes; the framework adds output registers",
            },
            "multiply_drops": {
                "keys": "every and only multiply-node id in body_nodes",
                "allowed_values": list(ALLOWED_DROPS),
                "meaning": "clear this many product LSBs immediately after the multiply",
            },
            "rounding": list(ALLOWED_MODES),
            "minimum_sqnr_db": {
                "required_value": minimum_sqnr_db,
                "rule": "this is the frozen external constraint; copy it exactly",
            },
        },
        "response_schema": {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "body_nodes": "array of the strict arithmetic node shape above",
            "outputs": {"y_re": "body_node_id", "y_im": "body_node_id"},
            "multiply_drops": "object keyed by multiply node id",
            "rounding": "rne or trunc",
            "minimum_sqnr_db": minimum_sqnr_db,
        },
        "prior_evaluations": history,
        "instruction": (
            "Return one JSON object only. Jointly choose arithmetic-body factorization and "
            "per-product precision in this single response. Do not emit input/register/output "
            "nodes, Verilog, a template name, or prose."
        ),
    }
    return [
        {
            "role": "system",
            "content": (
                "Generate one restricted joint hardware candidate as strict JSON. "
                "The quality threshold is an external constraint and cannot be relaxed."
            ),
        },
        {"role": "user", "content": _canonical(request)},
    ]


def _construct_graph(
    body_nodes: list[Mapping[str, Any]], outputs: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Alpha-rename a body, then mechanically add the fixed CMUL shell.

    Every body identifier is renamed, not only a currently colliding one.  The
    fixed namespace therefore remains safe if later shells add more port or
    control names.  Operations, node order, and reference topology are not
    changed; the returned normalization is sufficient to recover the original
    body projection exactly.
    """
    body = deepcopy(body_nodes)
    binding = deepcopy(dict(outputs))
    identity = _digest({"body_nodes": body, "outputs": binding})[:16]
    body_id_map = {
        node["id"]: f"joint_body_{index:03d}" for index, node in enumerate(body)
    }
    normalized_body = []
    for node in body:
        normalized_body.append(
            {
                "id": body_id_map[node["id"]],
                "op": node["op"],
                "inputs": [body_id_map.get(ref, ref) for ref in node["inputs"]],
            }
        )
    normalized_outputs = {
        port: body_id_map[source] for port, source in binding.items()
    }
    nodes = [{"id": name, "op": "input"} for name in ("a", "b", "c", "d")]
    nodes.extend(normalized_body)
    nodes.extend(
        [
            {
                "id": "joint_y_re_reg",
                "op": "register",
                "input": normalized_outputs["y_re"],
            },
            {
                "id": "joint_y_im_reg",
                "op": "register",
                "input": normalized_outputs["y_im"],
            },
            {"id": "y_re", "op": "output", "input": "joint_y_re_reg"},
            {"id": "y_im", "op": "output", "input": "joint_y_im_reg"},
        ]
    )
    graph = {
        "schema_version": "cmul-operation-graph-v1",
        "formula_version": "cmul-w16-exact-v1",
        "name": f"joint_cmul_model_{identity}",
        "nodes": nodes,
    }
    normalization = {
        "method": "deterministic_complete_alpha_renaming_v1",
        "preserved_external_inputs": ["a", "b", "c", "d"],
        "body_id_map": [
            {"original": node["id"], "normalized": body_id_map[node["id"]]}
            for node in body
        ],
        "outputs_before": binding,
        "outputs_after": normalized_outputs,
        "body_before_sha256": _digest(body),
        "body_after_sha256": _digest(normalized_body),
        "changes": "identifiers and their references only; op and node order unchanged",
    }
    return graph, normalization


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
        "body_nodes",
        "outputs",
        "multiply_drops",
        "rounding",
        "minimum_sqnr_db",
    }
    if set(proposal) != required:
        raise ProposalError(
            "response_fields",
            f"proposal fields must be exactly {sorted(required)}",
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
    drops = proposal["multiply_drops"]
    if not isinstance(drops, dict) or any(
        not isinstance(key, str)
        or type(value) is not int
        or value not in ALLOWED_DROPS
        for key, value in drops.items()
    ):
        raise ProposalError("multiply_drops", "invalid product precision allocation")
    if proposal["rounding"] not in ALLOWED_MODES:
        raise ProposalError("rounding", "unsupported rounding mode")
    body = proposal["body_nodes"]
    if not isinstance(body, list):
        raise ProposalError("body_nodes", "body_nodes must be an array")
    known = {"a", "b", "c", "d"}
    for index, node in enumerate(body):
        if not isinstance(node, dict) or set(node) != {"id", "op", "inputs"}:
            raise ProposalError(
                "body_node_fields",
                f"body_nodes[{index}] must contain exactly id, op, inputs",
            )
        node_id, op, inputs = node["id"], node["op"], node["inputs"]
        if (
            not isinstance(node_id, str)
            or not node_id.isidentifier()
            or len(node_id) > 48
            or node_id in known
        ):
            raise ProposalError("body_node_id", f"body_nodes[{index}] has invalid id")
        if op not in {"add", "sub", "multiply"}:
            raise ProposalError(
                "body_node_op", f"body_nodes[{index}] uses forbidden op {op!r}"
            )
        if (
            not isinstance(inputs, list)
            or len(inputs) != 2
            or not all(isinstance(ref, str) and ref in known for ref in inputs)
        ):
            raise ProposalError(
                "body_topology",
                f"body_nodes[{index}] must reference two prior values",
            )
        known.add(node_id)
    multiply_ids = {
        node["id"] for node in body if node["op"] == "multiply"
    }
    if set(drops) != multiply_ids:
        raise ProposalError(
            "multiply_drops",
            "multiply_drops must name every and only multiply node in body_nodes",
        )
    outputs = proposal["outputs"]
    if (
        not isinstance(outputs, dict)
        or set(outputs) != {"y_re", "y_im"}
        or not all(isinstance(source, str) and source in known - {"a", "b", "c", "d"}
                   for source in outputs.values())
    ):
        raise ProposalError(
            "outputs", "outputs must bind y_re and y_im to body-node ids"
        )
    graph, normalization = _construct_graph(body, outputs)
    rename = {
        row["original"]: row["normalized"] for row in normalization["body_id_map"]
    }
    normalized_drops = {rename[node_id]: value for node_id, value in drops.items()}
    try:
        candidate = candidate_from_graph(
            graph,
            multiply_drops=normalized_drops,
            rounding=proposal["rounding"],
            minimum_sqnr_db=float(minimum_sqnr_db),
            name=graph["name"],
        )
    except GraphValidationError as exc:
        reason = exc.as_dict()
        raise ProposalError(str(reason.get("code", "graph_validation")), str(reason)) from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise ProposalError("candidate_validation", str(exc)) from exc
    return {
        "proposal": proposal,
        "normalization": normalization,
        "constructed_graph": graph,
        "candidate": candidate,
    }


def _candidate_summary(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """The model-authored decisions needed to learn from one evaluation."""
    return {
        "body_nodes": deepcopy(proposal["body_nodes"]),
        "outputs": deepcopy(proposal["outputs"]),
        "multiply_drops": deepcopy(proposal["multiply_drops"]),
        "rounding": proposal["rounding"],
    }


def _rejected_proposal(
    ledger: SearchLedger, reason: Mapping[str, Any]
) -> dict[str, Any]:
    """Charge a provider/parse rejection as a proposal, but not an evaluation."""
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
    """Charge a provider attempt without blaming the proposed design."""
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
    task: dict,
    contract: dict,
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
    minimum_sqnr_db: float = 140.0,
    model: str = DEFAULT_MODEL,
    api_base: str = DEFAULT_API_BASE,
    key_file: Path | None = DEFAULT_KEY_FILE,
    temperature: float = 0.9,
    provider_seed: int | None = None,
    liberty: Path = DEFAULT_LIBERTY,
    generate_fn: Callable[..., Mapping[str, Any]] = llm_client.generate,
    area_evaluator: Callable[[str], Mapping[str, Any]] | None = None,
    task: dict | None = None,
    area_contract: dict | None = None,
) -> Path:
    """Execute a real or injected run in a new evidence directory."""
    if type(calls) is not int or calls < 1:
        raise ValueError("calls must be a positive integer")
    if (
        isinstance(minimum_sqnr_db, bool)
        or not isinstance(minimum_sqnr_db, (int, float))
        or not math.isfinite(minimum_sqnr_db)
    ):
        raise ValueError("minimum_sqnr_db must be finite")
    task = deepcopy(task) if task is not None else yaml.safe_load(
        TASK_FILE.read_text(encoding="utf-8")
    )
    if area_contract is None and area_evaluator is None:
        area_contract = mapped_area.build_contract(
            task,
            liberty=Path(liberty),
            timeout_seconds=600,
            source_files=[
                Path(__file__),
                BENCH / "joint_design_ir.py",
                BENCH / "joint_cmul.py",
                BENCH / "joint_search.py",
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
        "quality_evaluator": "joint_cmul.evaluate_analytic",
        "rtl_lowerer": "joint_cmul.lower_rtl",
        "area_contract": area_contract if area_contract is not None else "injected-test-double",
    }
    context_sha256 = _digest(context)
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
        "allowed_product_drops": list(ALLOWED_DROPS),
        "allowed_rounding_modes": list(ALLOWED_MODES),
        "verified_failure_feedback": verified_feedback,
        "prompt_feedback_window": {
            "most_recent_attempts": 3,
            "complete_history_storage": "llm_calls/* and results.json records",
        },
        "paired_arm_rule": (
            "prompts contain identical measured status/metrics/area/accounting; only the "
            "verified_reason member is omitted by the control arm"
        ),
        "context_sha256": context_sha256,
        "task": task,
        "task_sha256": mapped_area.digest(task),
        "task_file": str(TASK_FILE.resolve()),
        "task_file_sha256": _file_sha(TASK_FILE),
        "source_sha256": {
            name: _file_sha(BENCH / name)
            for name in ("joint_design_ir.py", "joint_cmul.py", "joint_search.py")
        },
        "tariff": TARIFF,
        "area_contract": area_contract,
        "liberty": str(Path(liberty).resolve()),
        "interpretation_boundary": (
            "The LLM jointly emits only the arithmetic body and approximate per-product "
            "precision. The parser performs a fully recorded alpha-renaming, then "
            "mechanically adds fixed inputs, output registers, and output nodes without "
            "changing operations or topology; the audited adapter supplies stream-control "
            "RTL. The frozen SQNR constraint is not model-controlled."
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
                evaluation["candidate_summary"] = _candidate_summary(
                    parsed["proposal"]
                )
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
                key: deepcopy((evaluation.get("measured_metrics") or {}).get(key))
                for key in ("sqnr_db", "quality_threshold_db", "quality_passed")
                if key in (evaluation.get("measured_metrics") or {})
            },
            "area": {
                key: deepcopy((evaluation.get("area") or {}).get(key))
                for key in ("status", "area_um2", "num_cells", "timing", "power")
                if key in (evaluation.get("area") or {})
            },
            "verified_reason": deepcopy(evaluation.get("verified_reason")),
            "usage": usage,
            "cost": cost,
        }
        _write_new(call_dir / "record.json", record)
        records.append(record)
        print(
            f"[joint-cmul] {index}/{calls} {record['status']} "
            f"decision={record['decision']} cache={record['cache_hit']}",
            flush=True,
        )

    qualified = [
        row for row in records
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
                "proposal_index", "candidate_sha256", "candidate_summary",
                "measured_metrics", "area", "evaluation_sha256",
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
        "undetermined_candidates": sum(row["decision"] == "undetermined" for row in records),
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
            "CMUL is the first adapter; this run alone does not establish cross-operator generality",
            "the current backend accepts exact source algebra with approximate product quantization",
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
    parser.add_argument("--minimum-sqnr-db", type=float, default=140.0)
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
