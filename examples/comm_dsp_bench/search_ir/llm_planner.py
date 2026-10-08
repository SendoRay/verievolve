"""LLM adapter for the architecture planning loop.

This module only translates between an :class:`LLMInterface` response and the
strict architecture-plan compiler. It does not grant the model access to RTL
or silently repair its answer. Every model call, parse failure, and rejected
plan remains visible and counts against the attempt budget.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .architecture_plan import try_compile_architecture_plan
from .formula_contract import formula_hash, validate_formula_request
from .planning_loop import planner_context


SYSTEM_MESSAGE = """You are a fixed-point communication-DSP hardware planner.
Choose one complete architecture using only the supplied component grammar.
Do not write Verilog, explanations, Markdown, or fields outside that grammar.
Return exactly one JSON object. All numeric values must be JSON numbers."""


def render_planner_prompt(context: dict[str, Any]) -> str:
    """Render the public machine context without adding hidden design choices."""
    return (
        "Produce one complete architecture plan for this request.\n"
        "The top-level object must contain exactly: schema_version, "
        "formula_sha256, kind, nco, filter_decimator; rationale is optional.\n"
        "kind must be ddc-architecture-plan. Copy formula_sha256 exactly.\n"
        "Use the strategy-specific fields shown by the capability grammar.\n"
        "Machine context:\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2)
    )


def extract_json_payload(response: Any) -> str:
    """Accept exact JSON or one JSON code fence; reject surrounding prose."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("model response must be a nonempty string")
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ValueError("unterminated JSON code fence")
        if lines[0].strip() not in {"```", "```json", "```JSON"}:
            raise ValueError("only a JSON code fence is accepted")
        text = "\n".join(lines[1:-1]).strip()
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError("response must contain only one JSON object")
    return text


async def run_llm_planning_loop(
    formula: Any,
    llm: Any,
    *,
    max_attempts: int = 3,
    system_message: str = SYSTEM_MESSAGE,
) -> dict[str, Any]:
    """Run a bounded real-LLM repair loop with a complete audit transcript."""
    request = validate_formula_request(formula)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be an integer")
    if not 1 <= max_attempts <= 20:
        raise ValueError("max_attempts must be in [1, 20]")
    if not hasattr(llm, "generate_with_context"):
        raise TypeError("llm must implement generate_with_context")

    transcript: list[dict[str, Any]] = []
    feedback: dict[str, Any] | None = None
    for attempt in range(1, max_attempts + 1):
        context = planner_context(request, feedback, attempt)
        prompt = render_planner_prompt(context)
        raw_response: str | None = None
        proposal: str | None = None
        try:
            raw_response = await llm.generate_with_context(
                system_message,
                [{"role": "user", "content": prompt}],
            )
            proposal = extract_json_payload(raw_response)
            result = try_compile_architecture_plan(request, proposal)
        except Exception as exc:
            result = {
                "status": "rejected",
                "error": {
                    "code": "llm_response_error",
                    "path": "$llm_response",
                    "message": f"{type(exc).__name__}: {exc}",
                    "detail": None,
                },
            }
        transcript.append({
            "attempt": attempt,
            "prompt": prompt,
            "raw_response": raw_response,
            "proposal": proposal,
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
