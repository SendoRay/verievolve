"""Backend-neutral architecture planning and structured repair loop.

The loop deliberately knows nothing about an LLM provider.  A proposer is a
callable that receives one JSON-shaped context and returns one plan payload.
Every rejected proposal is retained and counted before feedback is supplied to
the next attempt.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Callable, Sequence

from numeric_semantics import EXPLICIT_ROUNDING_MODES, numeric_semantics_manifest

from .architecture_plan import (
    ARCHITECTURE_PLAN_SCHEMA,
    try_compile_architecture_plan,
)
from .formula_contract import formula_hash, validate_formula_request


PlanProposer = Callable[[dict[str, Any]], Any]
CandidateEvaluator = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]
AttemptRecorder = Callable[[dict[str, Any]], None]


def normalize_candidate_evaluation(value: Any) -> dict[str, Any]:
    """Validate the common evaluator response used by every proposer type."""
    if not isinstance(value, Mapping):
        raise TypeError("candidate evaluator must return a mapping")
    result = deepcopy(dict(value))
    status = result.get("status")
    if status not in {"accepted", "rejected", "inconclusive"}:
        raise ValueError(
            "candidate evaluator status must be accepted, rejected, or inconclusive"
        )
    feedback = result.get("feedback")
    if feedback is not None and not isinstance(feedback, Mapping):
        raise TypeError("candidate evaluator feedback must be a mapping or null")
    if status == "rejected" and not feedback:
        raise ValueError("a rejected candidate must include nonempty feedback")
    return result


def evaluation_feedback(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap measured rejection feedback so it cannot be confused with schema errors."""
    return {
        "code": "candidate_not_accepted",
        "path": "$candidate_evaluation",
        "message": "candidate did not satisfy the measured requirements",
        "detail": deepcopy(dict(evaluation)),
    }


def resume_planning_transcript(
    formula: Any, transcript: Sequence[Mapping[str, Any]] | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Validate a nonterminal transcript and recover the next repair feedback."""
    request = validate_formula_request(formula)
    rows = [] if transcript is None else deepcopy(list(transcript))
    feedback = None
    for attempt, row in enumerate(rows, 1):
        if not isinstance(row, Mapping) or row.get("attempt") != attempt:
            raise ValueError("resume transcript attempts must be contiguous and one-based")
        result = row.get("result")
        if not isinstance(result, Mapping) or result.get("status") not in {"ok", "rejected"}:
            raise ValueError("resume transcript contains an invalid compile result")
        if result["status"] == "rejected":
            if row.get("candidate_evaluation") is not None or not isinstance(
                result.get("error"), Mapping
            ):
                raise ValueError("rejected compile row has inconsistent evaluation state")
            feedback = deepcopy(dict(result["error"]))
            continue
        candidate = result.get("candidate")
        if not isinstance(candidate, Mapping):
            raise ValueError("compiled resume row is missing its candidate")
        # Recompile the persisted proposal so a changed compiler cannot silently resume.
        replayed = try_compile_architecture_plan(request, row.get("proposal"))
        if replayed.get("status") != "ok" or replayed.get("candidate") != candidate:
            raise ValueError("resume transcript no longer compiles to the stored candidate")
        evaluation = row.get("candidate_evaluation")
        if evaluation is None or normalize_candidate_evaluation(evaluation)["status"] != "rejected":
            raise ValueError("only a nonterminal rejected evaluation can be resumed")
        feedback = evaluation_feedback(evaluation)
    return rows, feedback


def capability_manifest() -> dict[str, Any]:
    """Return the public component grammar shared by all future proposers."""
    rounding_modes = list(EXPLICIT_ROUNDING_MODES)
    return {
        "architecture_plan_schema": ARCHITECTURE_PLAN_SCHEMA,
        "numeric_semantics": numeric_semantics_manifest(),
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
                "product_rounding": rounding_modes,
            },
        },
        "filter_strategies": ["direct_symmetric", "polyphase"],
        "filter_numeric_domains": {
            "coefficient_bits": {"minimum": 8, "maximum": 24},
            "product_drop": {"minimum": 0, "maximum": 8},
            "accumulator_bits": [0, *range(20, 49)],
            "rounding": rounding_modes,
        },
        "arbitrary_rtl_allowed": False,
        "unknown_fields_allowed": False,
    }


def planner_context(
    formula: Any,
    previous_feedback: dict[str, Any] | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
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


def run_planning_loop(
    formula: Any,
    proposer: PlanProposer,
    max_attempts: int = 3,
    candidate_evaluator: CandidateEvaluator | None = None,
    resume_transcript: Sequence[Mapping[str, Any]] | None = None,
    attempt_recorder: AttemptRecorder | None = None,
) -> dict[str, Any]:
    """Run a bounded, fully accounted repair loop around a proposer callable."""
    request = validate_formula_request(formula)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be an integer")
    if not 1 <= max_attempts <= 20:
        raise ValueError("max_attempts must be in [1, 20]")
    if not callable(proposer):
        raise TypeError("proposer must be callable")
    if candidate_evaluator is not None and not callable(candidate_evaluator):
        raise TypeError("candidate_evaluator must be callable")
    if attempt_recorder is not None and not callable(attempt_recorder):
        raise TypeError("attempt_recorder must be callable")

    transcript, feedback = resume_planning_transcript(request, resume_transcript)
    if len(transcript) >= max_attempts:
        raise ValueError("resume transcript already exhausts the proposal budget")
    for attempt in range(len(transcript) + 1, max_attempts + 1):
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
        row = {
            "attempt": attempt,
            "proposal": deepcopy(proposal),
            "result": deepcopy(result),
            "candidate_evaluation": None,
        }
        if result["status"] == "ok":
            if candidate_evaluator is not None:
                try:
                    evaluated = candidate_evaluator(
                        deepcopy(result["candidate"]), deepcopy(request)
                    )
                    evaluation = normalize_candidate_evaluation(evaluated)
                except Exception as exc:
                    evaluation = {
                        "status": "inconclusive",
                        "feedback": {
                            "code": "candidate_evaluator_exception",
                            "message": f"{type(exc).__name__}: {exc}",
                        },
                    }
                row["candidate_evaluation"] = deepcopy(evaluation)
                transcript.append(row)
                if attempt_recorder is not None:
                    attempt_recorder(deepcopy(row))
                if evaluation["status"] == "rejected":
                    feedback = evaluation_feedback(evaluation)
                    continue
                if evaluation["status"] == "inconclusive":
                    return {
                        "status": "inconclusive",
                        "formula_sha256": formula_hash(request),
                        "attempt_count": attempt,
                        "failed_attempts": attempt - 1,
                        "compile_result": result,
                        "evaluation_result": evaluation,
                        "transcript": transcript,
                    }
            else:
                transcript.append(row)
                if attempt_recorder is not None:
                    attempt_recorder(deepcopy(row))
                evaluation = None
            return {
                "status": "success",
                "formula_sha256": formula_hash(request),
                "attempt_count": attempt,
                "failed_attempts": attempt - 1,
                "compile_result": result,
                "evaluation_result": evaluation,
                "transcript": transcript,
            }
        transcript.append(row)
        if attempt_recorder is not None:
            attempt_recorder(deepcopy(row))
        feedback = deepcopy(result["error"])
    return {
        "status": "exhausted",
        "formula_sha256": formula_hash(request),
        "attempt_count": max_attempts,
        "failed_attempts": max_attempts,
        "last_error": feedback,
        "transcript": transcript,
    }
