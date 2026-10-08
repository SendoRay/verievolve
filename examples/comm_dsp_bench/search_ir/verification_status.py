"""Status composition for development-only formula-to-RTL verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def synthesis_status(result: Mapping[str, Any]) -> str:
    """Keep an evaluation timeout distinct from an invalid synthesis result."""
    if result.get("status") == "ok":
        return "ok"
    process = result.get("process")
    if isinstance(process, Mapping) and process.get("timed_out") is True:
        return "timeout"
    return "failed"


def verification_status(*, rtl: str, quality: str, synthesis: str) -> str:
    """Compose independent functional, quality, and cost-evaluation states."""
    if rtl != "ok" or quality != "ok":
        return "failed"
    if synthesis == "ok":
        return "ok"
    if synthesis == "timeout":
        return "inconclusive"
    return "failed"
