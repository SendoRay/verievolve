"""Backend-neutral architecture planning and structured repair loop.

The loop deliberately knows nothing about an LLM provider.  A proposer is a
callable that receives one JSON-shaped context and returns one plan payload.
Every rejected proposal is retained and counted before feedback is supplied to
the next attempt.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from .architecture_plan import (
    ARCHITECTURE_PLAN_SCHEMA,
    try_compile_architecture_plan,
)
from .formula_contract import formula_hash, validate_formula_request


PlanProposer = Callable[[dict[str, Any]], Any]


def capability_manifest() -> dict[str, Any]:
    """Return the public component grammar shared by all future proposers."""
    return {
        "architecture_plan_schema": ARCHITECTURE_PLAN_SCHEMA,
        "nco_strategies": {
            "lut": {
                "depth": [64, 128, 256, 512, 1024],
                "interpolation": ["nearest", "linear", "quad"],
                "phase_bits": {"minimum": 8, "maximum": 16},
            },
            "cordic": {
                "stages": {"minimum": 7, "maximum": 20},
                "phase_bits": {"minimum": 8, "maximum": 16},
            },
            "coarse_residual": {
                "coarse": {
                    "strategy": "lut",
                    "depth": [64, 128, 256, 512, 1024],
                    "interpolation": ["nearest", "linear", "quad"],
                    "phase_bits": {"minimum": 8, "maximum": 16},
                },
                "residual": {
                    "strategy": "cordic",
                    "stages": {"minimum": 7, "maximum": 20},
                    "phase_bits": {"minimum": 8, "maximum": 16},
                },
                "split_bits": {"minimum": 2, "maximum": 14},
                "product_rounding": ["rne", "trunc"],
            },
        },
        "filter_strategies": ["direct_symmetric", "polyphase"],
        "filter_numeric_domains": {
            "coefficient_bits": {"minimum": 8, "maximum": 24},
            "product_drop": {"minimum": 0, "maximum": 8},
            "accumulator_bits": [0, *range(20, 49)],
            "rounding": ["rne", "trunc"],
        },
        "arbitrary_rtl_allowed": False,
        "unknown_fields_allowed": False,
    }


def planner_context(formula: Any, previous_feedback: dict[str, Any] | None = None,
                    attempt: int = 1) -> dict[str, Any]:
    """Build the exact machine context that may be rendered into an LLM prompt."""
    request = validate_formula_request(formula)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    return {
        "task": "produce-one-complete-architecture-plan",
        "attempt": attempt,
        "formula_sha256": formula_hash(request),
        "formula_request": request,
        "capabilities": capability_manifest(),
        "previous_feedback": deepcopy(previous_feedback),
        "response_rule": "return exactly one JSON architecture-plan object",
    }


def run_planning_loop(formula: Any, proposer: PlanProposer,
                      max_attempts: int = 3) -> dict[str, Any]:
    """Run a bounded, fully accounted repair loop around a proposer callable."""
    request = validate_formula_request(formula)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be an integer")
    if not 1 <= max_attempts <= 20:
        raise ValueError("max_attempts must be in [1, 20]")
    if not callable(proposer):
        raise TypeError("proposer must be callable")

    transcript: list[dict[str, Any]] = []
    feedback: dict[str, Any] | None = None
    for attempt in range(1, max_attempts + 1):
        context = planner_context(request, feedback, attempt)
        try:
            proposal = proposer(deepcopy(context))
            result = try_compile_architecture_plan(request, proposal)
        except Exception as exc:  # provider failures count and become repair feedback
            proposal = None
            result = {
                "status": "rejected",
                "error": {
                    "code": "proposer_exception",
                    "path": "$proposer",
                    "message": f"{type(exc).__name__}: {exc}",
                    "detail": None,
                },
            }
        transcript.append({
            "attempt": attempt,
            "proposal": deepcopy(proposal),
            "result": deepcopy(result),
        })
        if result["status"] == "ok":
            return {
                "status": "success",
                "formula_sha256": formula_hash(request),
                "attempt_count": attempt,
                "failed_attempts": attempt - 1,
                "compile_result": result,
                "transcript": transcript,
            }
        feedback = deepcopy(result["error"])
    return {
        "status": "exhausted",
        "formula_sha256": formula_hash(request),
        "attempt_count": max_attempts,
        "failed_attempts": max_attempts,
        "last_error": feedback,
        "transcript": transcript,
    }
