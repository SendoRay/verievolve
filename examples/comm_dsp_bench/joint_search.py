"""Task-independent evaluation loop for joint hardware candidates.

This module is deliberately small.  Task adapters own numerical evaluation,
RTL lowering, and physical-cost measurement; this layer owns the experimental
semantics shared by all tasks:

* structural admission is separate from the independent quality gate;
* a proposal and an evaluation request are charged even on a cache hit;
* real tool executions are counted separately;
* tool failures remain *undetermined*, never design failures; and
* feedback/no-feedback arms receive identical measurements and accounting.

The cache key binds a semantic candidate hash to an evaluator-context hash, so
results cannot silently cross task manifests, test vectors, or tool versions.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Callable, Mapping, MutableMapping

from joint_design_ir import (
    JointDesignValidationError,
    candidate_hash,
    quality_gate_passes,
    validate_candidate,
)


UNDETERMINED_STATUSES = frozenset({"tool_failure", "timeout", "unknown"})


@dataclass
class SearchLedger:
    """Persistent counters whose meanings do not change on cache hits."""

    proposal_count: int = 0
    evaluation_request_count: int = 0
    tool_execution_count: int = 0
    duplicate_proposal_count: int = 0
    seen_candidate_sha256: set[str] = field(default_factory=set)

    def snapshot(self) -> dict[str, int]:
        return {
            "proposal_count": self.proposal_count,
            "evaluation_request_count": self.evaluation_request_count,
            "tool_execution_count": self.tool_execution_count,
            "duplicate_proposal_count": self.duplicate_proposal_count,
        }


class EvaluationStatusError(RuntimeError):
    """A callback failure with an explicit, non-design status."""

    def __init__(self, status: str, message: str):
        if status not in UNDETERMINED_STATUSES:
            raise ValueError(f"unsupported undetermined status: {status}")
        super().__init__(message)
        self.status = status
        self.message = message


def evaluation_cache_key(candidate_sha256: str, context_sha256: str) -> str:
    if not isinstance(context_sha256, str) or len(context_sha256) != 64:
        raise ValueError("context_sha256 must be a 64-character hexadecimal digest")
    try:
        bytes.fromhex(context_sha256)
    except ValueError as exc:
        raise ValueError("context_sha256 must be hexadecimal") from exc
    payload = f"verievolve-joint-evaluation-v1\0{candidate_sha256}\0{context_sha256}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _status_result(stage: str, status: str, message: str) -> dict[str, Any]:
    return {
        "status": status,
        "decision": "undetermined",
        "failure_stage": stage,
        "verified_reason": None,
        "diagnostic": message,
    }


def _invoke(stage: str, callback: Callable[..., Any], *args: Any) -> tuple[Any, int, dict[str, Any] | None]:
    """Invoke one adapter and normalize status/tool accounting.

    A callback may return its payload directly, or an envelope containing
    ``status``, ``value`` and ``tool_executions``.  Analytic evaluators should
    report zero executions; simulator/synthesis adapters should report the
    number of real processes they started, including failed ones.
    """
    try:
        raw = callback(*args)
    except TimeoutError as exc:
        return None, 1, _status_result(stage, "timeout", str(exc))
    except EvaluationStatusError as exc:
        return None, 1, _status_result(stage, exc.status, exc.message)
    except Exception as exc:  # an adapter crash cannot convict a candidate
        return None, 1, _status_result(stage, "tool_failure", f"{type(exc).__name__}: {exc}")
    if isinstance(raw, Mapping) and "status" in raw:
        status = raw["status"]
        executions = raw.get("tool_executions", 0)
        if type(executions) is not int or executions < 0:
            return None, 0, _status_result(stage, "tool_failure", "invalid tool_executions")
        if status in UNDETERMINED_STATUSES:
            return None, executions, _status_result(stage, status, str(raw.get("diagnostic", status)))
        if status != "ok":
            return None, executions, _status_result(stage, "tool_failure", f"invalid callback status: {status}")
        # Accept both the explicit envelope and the repository's conventional
        # result object (``{"status":"ok","area_um2":...}``).
        if "value" in raw:
            return raw["value"], executions, None
        value = dict(raw)
        value.pop("tool_executions", None)
        return value, executions, None
    return raw, 0, None


def evaluate_candidate(
    candidate: Mapping[str, Any],
    *,
    context_sha256: str,
    quality_evaluator: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    rtl_lowerer: Callable[[Mapping[str, Any]], str],
    area_evaluator: Callable[[str], Mapping[str, Any]],
    ledger: SearchLedger | None = None,
    cache: MutableMapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate one proposal without conflating rejection and tool failure."""
    ledger = ledger if ledger is not None else SearchLedger()
    cache = cache if cache is not None else {}
    before = ledger.snapshot()
    ledger.proposal_count += 1
    ledger.evaluation_request_count += 1

    try:
        structural = validate_candidate(candidate)
        digest = candidate_hash(candidate)
    except JointDesignValidationError as exc:
        result = {
            "status": "invalid_structure",
            "decision": "rejected",
            "candidate_sha256": None,
            "cache_hit": False,
            "measured_metrics": {},
            "verified_reason": exc.as_dict(),
        }
        return _finish_event(result, before, ledger)

    duplicate = digest in ledger.seen_candidate_sha256
    if duplicate:
        ledger.duplicate_proposal_count += 1
    ledger.seen_candidate_sha256.add(digest)
    key = evaluation_cache_key(digest, context_sha256)
    if key in cache:
        result = deepcopy(dict(cache[key]))
        result.update({"cache_hit": True, "duplicate_proposal": duplicate})
        return _finish_event(result, before, ledger)

    base = {
        "candidate_sha256": digest,
        "evaluation_cache_key": key,
        "cache_hit": False,
        "duplicate_proposal": duplicate,
        "structural_validation": structural,
        "measured_metrics": {},
    }
    metrics, executions, failed = _invoke("quality", quality_evaluator, candidate)
    ledger.tool_execution_count += executions
    if failed is not None:
        result = {**base, **failed}
        return _finish_event(result, before, ledger)
    if not isinstance(metrics, Mapping):
        result = {**base, **_status_result("quality", "tool_failure", "quality evaluator returned no metric object")}
        return _finish_event(result, before, ledger)
    base["measured_metrics"] = deepcopy(dict(metrics))
    try:
        passed = quality_gate_passes(candidate, metrics)
    except JointDesignValidationError as exc:
        result = {**base, **_status_result("quality", "unknown", str(exc))}
        return _finish_event(result, before, ledger)
    if not passed:
        contract = structural["quality_contract"]
        result = {
            **base,
            "status": "quality_failed",
            "decision": "rejected",
            "verified_reason": {
                "code": "quality_threshold",
                "metric": contract["metric"],
                "direction": contract["direction"],
                "threshold": contract["threshold"],
                "measured": metrics[contract["metric"]],
            },
        }
        cache[key] = deepcopy(result)
        return _finish_event(result, before, ledger)

    rtl, executions, failed = _invoke("rtl_lowering", rtl_lowerer, candidate)
    ledger.tool_execution_count += executions
    if failed is not None:
        result = {**base, **failed}
        return _finish_event(result, before, ledger)
    if not isinstance(rtl, str) or not rtl.strip():
        result = {**base, **_status_result("rtl_lowering", "tool_failure", "RTL lowerer returned empty text")}
        return _finish_event(result, before, ledger)

    area, executions, failed = _invoke("area", area_evaluator, rtl)
    ledger.tool_execution_count += executions
    if failed is not None:
        result = {**base, **failed}
        return _finish_event(result, before, ledger)
    if not isinstance(area, Mapping):
        result = {**base, **_status_result("area", "tool_failure", "area evaluator returned no result object")}
        return _finish_event(result, before, ledger)
    result = {
        **base,
        "status": "qualified",
        "decision": "accepted",
        "verified_reason": None,
        "area": deepcopy(dict(area)),
        "rtl_sha256": hashlib.sha256(rtl.encode()).hexdigest(),
    }
    cache[key] = deepcopy(result)
    return _finish_event(result, before, ledger)


def _finish_event(result: dict[str, Any], before: Mapping[str, int], ledger: SearchLedger) -> dict[str, Any]:
    after = ledger.snapshot()
    result["budget_event"] = {key: after[key] - before[key] for key in after}
    result["budget_totals"] = after
    return result


def feedback_payload(result: Mapping[str, Any], *, include_verified_reason: bool) -> dict[str, Any]:
    """Build paired-arm feedback without changing measurements or accounting."""
    payload = {
        "status": result.get("status"),
        "decision": result.get("decision"),
        "measured_metrics": deepcopy(result.get("measured_metrics", {})),
        "area": deepcopy(result.get("area")),
        "budget_event": deepcopy(result.get("budget_event", {})),
        "cache_hit": bool(result.get("cache_hit", False)),
    }
    if include_verified_reason:
        payload["verified_reason"] = deepcopy(result.get("verified_reason"))
        if result.get("decision") == "undetermined":
            payload["failure_stage"] = result.get("failure_stage")
            payload["diagnostic"] = result.get("diagnostic")
    return payload
