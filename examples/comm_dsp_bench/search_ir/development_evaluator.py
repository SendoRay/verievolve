"""Compose development quality and optional real-synthesis feedback."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any


def evaluate_with_optional_synthesis(
    candidate: dict[str, Any],
    formula: dict[str, Any],
    *,
    archive: Any,
    quality_evaluator: Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]],
    synthesis_evaluator: Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Return one planner evaluation while keeping tool failures non-candidate failures."""
    quality = archive.cached_evaluate(candidate, formula, quality_evaluator)
    if quality["status"] != "accepted" or synthesis_evaluator is None:
        return quality
    synthesis = archive.cached_synthesize(candidate, formula, synthesis_evaluator)
    measurements = deepcopy(quality.get("measurements", {}))
    measurements["synthesis"] = deepcopy(synthesis)
    if synthesis["status"] == "ok":
        return {
            "status": "accepted",
            "measurements": measurements,
            "feedback": None,
        }
    reason = {
        "timeout": "synthesis_timeout",
        "failed": "synthesis_infrastructure_failure",
        "budget_exhausted": "synthesis_budget_exhausted",
    }[synthesis["status"]]
    return {
        "status": "inconclusive",
        "measurements": measurements,
        "feedback": {"reason": reason, "synthesis": synthesis},
    }

