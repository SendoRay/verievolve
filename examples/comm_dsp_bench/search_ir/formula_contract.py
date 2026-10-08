"""Strict formula-and-requirements contract for formula-to-RTL development.

The first vertical slice describes the already verified DDC task as an
explicit mathematical dataflow graph.  It does not choose an implementation:
LUT/CORDIC, direct/polyphase FIR, word lengths, and rounding belong to the
architecture plan compiled in :mod:`search_ir.architecture_plan`.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any, Mapping

from .schema import complex_format, fixed_format, stream_type


FORMULA_REQUEST_SCHEMA = "verievolve-formula-request-v1"
DDC_FORMULA_ID = "ddc-baseband-v1"
_TOP_KEYS = frozenset({
    "schema_version", "formula_id", "inputs", "nodes", "output", "requirements",
})


class FormulaContractError(ValueError):
    """A formula request is not a supported, reproducible task description."""

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
    raise FormulaContractError(code, path, message, detail)


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
            _fail("$", f"formula request is not UTF-8: {exc}", "not_json")
    if isinstance(payload, str):
        try:
            return json.loads(
                payload,
                object_pairs_hook=_reject_pairs,
                parse_constant=_reject_constant,
            )
        except json.JSONDecodeError as exc:
            _fail("$", f"formula request is not valid JSON: {exc}", "not_json")
    return payload


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "expected an object")
    return value


def _exact_keys(value: Mapping[str, Any], path: str, required: set[str]) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        _fail(path, f"missing fields {missing}")
    if extra:
        _fail(path, f"unknown fields {extra}")


def _exact_stream(value: Any, path: str, width: int, frac: int,
                  rate_num: int, rate_den: int) -> None:
    expected = stream_type(
        complex_format(fixed_format(width, frac, signed=True)), rate_num, rate_den
    )
    if value != expected:
        _fail(path, f"expected frozen stream type {expected}")


def _node(node_id: str, op: str, inputs: list[str], expression: str,
          **parameters: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "op": op,
        "inputs": list(inputs),
        "expression": expression,
        "parameters": parameters,
    }


def ddc_formula_request(
    *,
    max_aligned_nmse: float = 2.32929922807541e-5,
    area_backend: str = "nangate45",
) -> dict[str, Any]:
    """Return the first explicit formula + deployment-requirements object."""
    return {
        "schema_version": FORMULA_REQUEST_SCHEMA,
        "formula_id": DDC_FORMULA_ID,
        "inputs": {
            "x": stream_type(complex_format(fixed_format(12, 11)), 1, 1),
            "fcw": {"kind": "unsigned_integer", "width": 32},
        },
        "nodes": [
            _node(
                "phase", "phase_accumulate", ["fcw"],
                "phi[n+1]=(phi[n]+fcw) mod 2^32",
                state_width=32,
            ),
            _node(
                "phasor", "complex_exp", ["phase"],
                "p[n]=exp(-j*2*pi*phi[n]/2^32)",
            ),
            _node(
                "mixed", "complex_multiply", ["x", "phasor"],
                "u[n]=x[n]*p[n]",
            ),
            _node(
                "filtered", "fir", ["mixed"],
                "v[n]=sum(k=0..32,h[k]*u[n-k])",
                coefficients_id="ddc-v1-h33",
            ),
            _node(
                "y", "decimate", ["filtered"], "y[m]=v[2*m]", factor=2,
            ),
        ],
        "output": {
            "node": "y",
            "type": stream_type(complex_format(fixed_format(16, 15)), 1, 2),
        },
        "requirements": {
            "quality": {
                "metric": "aligned_impl_nmse",
                "maximum": float(max_aligned_nmse),
                "evaluation_scope": "frozen-ddc-chain",
            },
            "cost": {"metric": "synthesis_area", "backend": str(area_backend)},
            "objectives": ["minimize_quality_error", "minimize_area"],
        },
    }


def validate_formula_request(payload: Any) -> dict[str, Any]:
    """Strictly validate and return a defensive copy of a formula request."""
    request = _object(_decode(payload), "$formula")
    _exact_keys(request, "$formula", set(_TOP_KEYS))
    if request["schema_version"] != FORMULA_REQUEST_SCHEMA:
        _fail("$formula.schema_version", f"expected {FORMULA_REQUEST_SCHEMA}")
    if request["formula_id"] != DDC_FORMULA_ID:
        _fail("$formula.formula_id", f"unsupported formula {request['formula_id']!r}")

    inputs = _object(request["inputs"], "$formula.inputs")
    _exact_keys(inputs, "$formula.inputs", {"x", "fcw"})
    _exact_stream(inputs["x"], "$formula.inputs.x", 12, 11, 1, 1)
    if inputs["fcw"] != {"kind": "unsigned_integer", "width": 32}:
        _fail("$formula.inputs.fcw", "expected unsigned 32-bit frequency word")

    expected_nodes = ddc_formula_request()["nodes"]
    if request["nodes"] != expected_nodes:
        _fail(
            "$formula.nodes",
            "v1 requires the explicit phase→phasor→multiply→FIR→decimate graph",
        )
    output = _object(request["output"], "$formula.output")
    _exact_keys(output, "$formula.output", {"node", "type"})
    if output["node"] != "y":
        _fail("$formula.output.node", "must reference y")
    _exact_stream(output["type"], "$formula.output.type", 16, 15, 1, 2)

    requirements = _object(request["requirements"], "$formula.requirements")
    _exact_keys(requirements, "$formula.requirements", {"quality", "cost", "objectives"})
    quality = _object(requirements["quality"], "$formula.requirements.quality")
    _exact_keys(quality, "$formula.requirements.quality",
                {"metric", "maximum", "evaluation_scope"})
    if quality["metric"] != "aligned_impl_nmse":
        _fail("$formula.requirements.quality.metric", "unsupported quality metric")
    maximum = quality["maximum"]
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
        _fail("$formula.requirements.quality.maximum", "expected a finite positive number")
    if not math.isfinite(float(maximum)) or float(maximum) <= 0.0:
        _fail("$formula.requirements.quality.maximum", "must be finite and positive")
    if quality["evaluation_scope"] != "frozen-ddc-chain":
        _fail("$formula.requirements.quality.evaluation_scope", "unsupported scope")
    cost = _object(requirements["cost"], "$formula.requirements.cost")
    _exact_keys(cost, "$formula.requirements.cost", {"metric", "backend"})
    if cost["metric"] != "synthesis_area" or cost["backend"] not in {"nangate45", "ice40"}:
        _fail("$formula.requirements.cost", "unsupported synthesis cost request")
    if requirements["objectives"] != ["minimize_quality_error", "minimize_area"]:
        _fail("$formula.requirements.objectives", "v1 objective order is frozen")
    return deepcopy(request)


def formula_json(payload: Any) -> str:
    request = validate_formula_request(payload)
    return json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def formula_hash(payload: Any) -> str:
    return hashlib.sha256(formula_json(payload).encode("utf-8")).hexdigest()
