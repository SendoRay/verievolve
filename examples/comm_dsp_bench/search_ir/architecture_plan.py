"""Strict architecture-plan language and deterministic lowering to typed IR.

An LLM or a non-LLM proposer may emit the same complete plan.  The plan can
choose several coupled structures at once, but it cannot add arbitrary RTL or
escape the verified constructors in :mod:`search_ir.schema`.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from numeric_semantics import (
    EXPLICIT_ROUNDING_MODES,
    LEGACY_ROUNDING_ALIASES,
    normalize_rounding_mode,
)

from .canonicalize import candidate_hash
from .formula_contract import FormulaContractError, formula_hash, validate_formula_request
from .schema import (
    cordic_sincos,
    ddc_candidate,
    direct_symmetric_fir,
    lut_sincos,
    phasor_compose,
    polyphase_decimator,
)
from .validate import IRValidationError, validate_candidate


ARCHITECTURE_PLAN_SCHEMA = "verievolve-architecture-plan-v1"
_TOP_REQUIRED = {"schema_version", "formula_sha256", "kind", "nco", "filter_decimator"}
_TOP_OPTIONAL = {"rationale"}
_DEPTHS = {64, 128, 256, 512, 1024}
_INTERPOLATIONS = {"nearest", "linear", "quad"}
_ROUNDING = set(EXPLICIT_ROUNDING_MODES) | set(LEGACY_ROUNDING_ALIASES)


class ArchitecturePlanError(ValueError):
    """A plan is malformed, incompatible, or cannot lower to verified IR."""

    def __init__(self, code: str, path: str, message: str, detail: Any = None) -> None:
        super().__init__(f"{path}: {message}")
        self.code = code
        self.path = path
        self.message = message
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "detail": self.detail,
        }


def _fail(path: str, message: str, code: str = "schema", detail: Any = None) -> None:
    raise ArchitecturePlanError(code, path, message, detail)


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            _fail("$", f"duplicate JSON key {key!r}", "duplicate_key")
        out[key] = value
    return out


def _reject_constant(token: str) -> None:
    _fail("$", f"non-finite JSON number {token}", "non_finite_number")


def _decode(payload: Any) -> Any:
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            _fail("$", f"plan is not UTF-8: {exc}", "not_json")
    if isinstance(payload, str):
        try:
            return json.loads(
                payload, object_pairs_hook=_reject_pairs, parse_constant=_reject_constant
            )
        except json.JSONDecodeError as exc:
            _fail("$", f"plan is not valid JSON: {exc}", "not_json")
    return payload


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "expected an object")
    return value


def _keys(value: Mapping[str, Any], path: str, required: set[str],
          optional: set[str] | None = None) -> None:
    optional = optional or set()
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required - optional)
    if missing:
        _fail(path, f"missing fields {missing}")
    if extra:
        _fail(path, f"unknown fields {extra}")


def _integer(value: Any, path: str, low: int, high: int,
             choices: set[int] | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "expected an integer")
    if not low <= value <= high or (choices is not None and value not in choices):
        allowed = sorted(choices) if choices is not None else f"[{low}, {high}]"
        _fail(path, f"value {value!r} outside {allowed}")
    return value


def _choice(value: Any, path: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        _fail(path, f"must be one of {sorted(choices)}")
    return value


def _validate_lut(value: Any, path: str) -> dict[str, Any]:
    node = _object(value, path)
    _keys(node, path, {"strategy", "depth", "interpolation", "phase_bits"})
    if node["strategy"] != "lut":
        _fail(f"{path}.strategy", "must be lut")
    _integer(node["depth"], f"{path}.depth", 64, 1024, _DEPTHS)
    _choice(node["interpolation"], f"{path}.interpolation", _INTERPOLATIONS)
    _integer(node["phase_bits"], f"{path}.phase_bits", 8, 16)
    return node


def _validate_cordic(value: Any, path: str) -> dict[str, Any]:
    node = _object(value, path)
    _keys(node, path, {"strategy", "stages", "phase_bits"})
    if node["strategy"] != "cordic":
        _fail(f"{path}.strategy", "must be cordic")
    _integer(node["stages"], f"{path}.stages", 7, 20)
    _integer(node["phase_bits"], f"{path}.phase_bits", 8, 16)
    return node


def _validate_nco(value: Any, path: str) -> dict[str, Any]:
    node = _object(value, path)
    strategy = node.get("strategy")
    if strategy == "lut":
        return _validate_lut(node, path)
    if strategy == "cordic":
        return _validate_cordic(node, path)
    if strategy == "coarse_residual":
        _keys(node, path, {
            "strategy", "split_bits", "product_rounding", "coarse", "residual",
        })
        _integer(node["split_bits"], f"{path}.split_bits", 2, 14)
        _choice(node["product_rounding"], f"{path}.product_rounding", _ROUNDING)
        _validate_lut(node["coarse"], f"{path}.coarse")
        _validate_cordic(node["residual"], f"{path}.residual")
        return node
    _fail(f"{path}.strategy", f"unsupported NCO strategy {strategy!r}")


def _validate_fir(value: Any, path: str) -> dict[str, Any]:
    node = _object(value, path)
    _keys(node, path, {
        "strategy", "coefficient_bits", "product_drop", "accumulator_bits", "rounding",
    })
    _choice(node["strategy"], f"{path}.strategy", {"direct_symmetric", "polyphase"})
    _integer(node["coefficient_bits"], f"{path}.coefficient_bits", 8, 24)
    _integer(node["product_drop"], f"{path}.product_drop", 0, 8)
    accumulator = _integer(node["accumulator_bits"], f"{path}.accumulator_bits", 0, 48)
    if accumulator not in {0, *range(20, 49)}:
        _fail(f"{path}.accumulator_bits", "must be 0 or in [20, 48]")
    _choice(node["rounding"], f"{path}.rounding", _ROUNDING)
    return node


def architecture_plan(
    formula: Any,
    *,
    nco: Mapping[str, Any],
    filter_decimator: Mapping[str, Any],
    rationale: list[str] | None = None,
) -> dict[str, Any]:
    nco_plan = deepcopy(dict(nco))
    if nco_plan.get("strategy") == "coarse_residual" and isinstance(
        nco_plan.get("product_rounding"), str
    ):
        nco_plan["product_rounding"] = normalize_rounding_mode(
            nco_plan["product_rounding"]
        )
    filter_plan = deepcopy(dict(filter_decimator))
    if isinstance(filter_plan.get("rounding"), str):
        filter_plan["rounding"] = normalize_rounding_mode(filter_plan["rounding"])
    plan: dict[str, Any] = {
        "schema_version": ARCHITECTURE_PLAN_SCHEMA,
        "formula_sha256": formula_hash(formula),
        "kind": "ddc-architecture-plan",
        "nco": nco_plan,
        "filter_decimator": filter_plan,
    }
    if rationale is not None:
        plan["rationale"] = list(rationale)
    return plan


def parse_architecture_plan(payload: Any) -> dict[str, Any]:
    plan = _object(_decode(payload), "$plan")
    _keys(plan, "$plan", _TOP_REQUIRED, _TOP_OPTIONAL)
    if plan["schema_version"] != ARCHITECTURE_PLAN_SCHEMA:
        _fail("$plan.schema_version", f"expected {ARCHITECTURE_PLAN_SCHEMA}")
    digest = plan["formula_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        _fail("$plan.formula_sha256", "expected a SHA-256 hex digest")
    try:
        int(digest, 16)
    except ValueError:
        _fail("$plan.formula_sha256", "expected a SHA-256 hex digest")
    if plan["kind"] != "ddc-architecture-plan":
        _fail("$plan.kind", "unsupported plan kind")
    _validate_nco(plan["nco"], "$plan.nco")
    _validate_fir(plan["filter_decimator"], "$plan.filter_decimator")
    if "rationale" in plan:
        rationale = plan["rationale"]
        if (not isinstance(rationale, list) or len(rationale) > 8
                or any(not isinstance(item, str) or not item.strip() or len(item) > 400
                       for item in rationale)):
            _fail("$plan.rationale", "expected at most 8 nonempty strings of ≤400 characters")
    return deepcopy(plan)


def _semantic_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in plan.items() if key != "rationale"}


def plan_json(payload: Any) -> str:
    plan = parse_architecture_plan(payload)
    return json.dumps(
        _semantic_plan(plan), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def plan_hash(payload: Any) -> str:
    return hashlib.sha256(plan_json(payload).encode("utf-8")).hexdigest()


def _lower_nco(plan: Mapping[str, Any]) -> dict[str, Any]:
    strategy = plan["strategy"]
    if strategy == "lut":
        return lut_sincos(plan["depth"], plan["interpolation"], plan["phase_bits"])
    if strategy == "cordic":
        return cordic_sincos(plan["stages"], plan["phase_bits"])
    return phasor_compose(
        lut_sincos(
            plan["coarse"]["depth"],
            plan["coarse"]["interpolation"],
            plan["coarse"]["phase_bits"],
        ),
        cordic_sincos(plan["residual"]["stages"], plan["residual"]["phase_bits"]),
        plan["split_bits"],
        plan["product_rounding"],
    )


def _lower_fir(plan: Mapping[str, Any]) -> dict[str, Any]:
    constructor = (
        direct_symmetric_fir if plan["strategy"] == "direct_symmetric"
        else polyphase_decimator
    )
    return constructor(
        coefficient_bits=plan["coefficient_bits"],
        product_drop=plan["product_drop"],
        accumulator_bits=plan["accumulator_bits"],
        rounding=plan["rounding"],
    )


def compile_architecture_plan(formula: Any, plan_payload: Any) -> dict[str, Any]:
    """Compile a complete plan into the existing verified typed IR."""
    request = validate_formula_request(formula)
    plan = parse_architecture_plan(plan_payload)
    expected_formula = formula_hash(request)
    if plan["formula_sha256"] != expected_formula:
        _fail(
            "$plan.formula_sha256", "plan was produced for a different formula request",
            "formula_mismatch",
            {"expected": expected_formula, "observed": plan["formula_sha256"]},
        )
    p_hash = plan_hash(plan)
    candidate = ddc_candidate(
        _lower_nco(plan["nco"]),
        _lower_fir(plan["filter_decimator"]),
        label=f"formula-plan:{p_hash[:12]}",
    )
    try:
        validate_candidate(candidate)
    except IRValidationError as exc:
        _fail("$plan", f"lowered typed IR is invalid: {exc}", "lowering")
    return {
        "status": "ok",
        "formula_sha256": expected_formula,
        "plan_sha256": p_hash,
        "candidate_sha256": candidate_hash(candidate),
        "candidate": candidate,
        "lowering_trace": [
            {"formula_node": "phasor", "selected": plan["nco"]["strategy"]},
            {"formula_node": "filtered+y", "selected": plan["filter_decimator"]["strategy"]},
        ],
    }


def try_compile_architecture_plan(formula: Any, plan_payload: Any) -> dict[str, Any]:
    """Non-throwing entrypoint suitable for structured LLM repair feedback."""
    try:
        return compile_architecture_plan(formula, plan_payload)
    except (ArchitecturePlanError, FormulaContractError) as exc:
        return {"status": "rejected", "error": exc.as_dict()}
