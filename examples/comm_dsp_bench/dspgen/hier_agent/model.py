"""Persistent records for the adaptive-granularity search prototype."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    ROOT = "ROOT"
    EXPAND = "EXPAND"
    DECOMPOSE = "DECOMPOSE"
    FUSE = "FUSE"
    TUNE = "TUNE"


@dataclass(frozen=True)
class SignalContract:
    name: str
    width: int
    frac: int
    signed: bool
    rate_domain: int | None
    clocks_per_sample: int | None
    latency: int
    held: bool


@dataclass
class RegionContract:
    region_id: str
    name: str
    line: int
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    input_signals: list[SignalContract] = field(default_factory=list)
    output_signals: list[SignalContract] = field(default_factory=list)
    area_um2_est: float = 0.0
    occurrences: int = 0


@dataclass
class MacroAction:
    kind: ActionKind
    target_regions: list[str]
    rationale: str
    parameter_edits: dict[str, Any] = field(default_factory=dict)
    proposed_by: str = "llm_agent"


@dataclass
class RootEvaluation:
    valid: bool
    passed: bool = False
    margin_db: float | None = None
    ripple_db: float | None = None
    area_um2_est: float | None = None
    error: dict[str, Any] | None = None
    per_scope_area: dict[str, float] = field(default_factory=dict)


@dataclass
class Candidate:
    candidate_id: str
    source_path: str
    source_sha256: str
    parent_id: str | None
    action: MacroAction
    evaluation: RootEvaluation
    regions: list[RegionContract] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Attribution:
    scope: str
    area_um2_est: float
    baseline_margin_db: float
    widened_margin_db: float | None
    margin_gain_db: float | None
    widened_ripple_db: float | None
    status: str


def dominates(a: Candidate, b: Candidate, min_margin_db: float) -> bool:
    """Root-level dominance; invalid or under-contract candidates never dominate."""
    ea, eb = a.evaluation, b.evaluation
    if not ea.valid or not ea.passed or ea.margin_db is None or ea.margin_db < min_margin_db:
        return False
    if not eb.valid or not eb.passed or eb.margin_db is None or eb.margin_db < min_margin_db:
        return True
    av = (ea.area_um2_est, -ea.margin_db, ea.ripple_db)
    bv = (eb.area_um2_est, -eb.margin_db, eb.ripple_db)
    if any(x is None for x in av + bv):
        return False
    return all(x <= y for x, y in zip(av, bv)) and any(x < y for x, y in zip(av, bv))

