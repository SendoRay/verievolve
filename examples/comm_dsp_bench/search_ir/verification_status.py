"""Status composition for development-only formula-to-RTL verification."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .formula_contract import validate_formula_request


def synthesis_status(result: Mapping[str, Any]) -> str:
    """Keep an evaluation timeout distinct from an invalid synthesis result."""
    if result.get("status") == "ok":
        return "ok"
    process = result.get("process")
    if isinstance(process, Mapping) and process.get("timed_out") is True:
        return "timeout"
    return "failed"


def quality_requirement_status(
    formula: Mapping[str, Any], evaluation: Mapping[str, Any]
) -> dict[str, Any]:
    """Separate successful measurement from satisfaction of the requested limit."""
    request = validate_formula_request(formula)
    requirement = request["requirements"]["quality"]
    measured = evaluation.get("Q_dev")
    measurement_status = evaluation.get("status")
    evidence_scope = evaluation.get("scope")
    evidence_role = evaluation.get("evidence_role", "unspecified")
    result = {
        "metric": requirement["metric"],
        "requirement_scope": requirement["evaluation_scope"],
        "evidence_scope": evidence_scope,
        "evidence_role": evidence_role,
        "deployment_acceptance": (
            evidence_role == "deployment_acceptance"
            and evidence_scope == requirement["evaluation_scope"]
        ),
        "maximum": float(requirement["maximum"]),
        "observed": None,
        "measurement_status": measurement_status,
        "requirement_status": "measurement_failed",
    }
    if measurement_status != "ok":
        return result
    if isinstance(measured, bool) or not isinstance(measured, (int, float)):
        return result
    observed = float(measured)
    if not math.isfinite(observed) or observed < 0.0:
        return result
    result["observed"] = observed
    result["requirement_status"] = (
        "satisfied" if observed <= result["maximum"] else "not_satisfied"
    )
    return result


def verification_status(
    *, rtl: str, quality_measurement: str, quality_requirement: str, synthesis: str
) -> str:
    """Compose functional, measurement, requirement, and cost states."""
    if (
        rtl != "ok"
        or quality_measurement != "ok"
        or quality_requirement != "satisfied"
    ):
        return "failed"
    if synthesis == "ok":
        return "ok"
    if synthesis == "timeout":
        return "inconclusive"
    return "failed"
