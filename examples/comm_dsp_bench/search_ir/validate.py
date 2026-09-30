"""Structural and type/rate validation for search IR v1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .schema import CONTRACT_VERSION, FORMULA_VERSION, SCHEMA_VERSION


class IRValidationError(ValueError):
    """Raised when a candidate cannot enter any search arm."""


def _fail(path: str, message: str) -> None:
    raise IRValidationError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "expected an object")
    return value


def _exact_keys(
    obj: Mapping[str, Any],
    path: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - set(obj)
    extra = set(obj) - required - optional
    if missing:
        _fail(path, f"missing fields {sorted(missing)}")
    if extra:
        _fail(path, f"unknown fields {sorted(extra)}")


def _integer(value: Any, path: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "expected an integer")
    if not low <= value <= high:
        _fail(path, f"must be in [{low}, {high}]")
    return value


def _choice(value: Any, path: str, choices: set[str]) -> str:
    if value not in choices:
        _fail(path, f"must be one of {sorted(choices)}")
    return str(value)


def _validate_fixed(value: Any, path: str, expected: tuple[int, int, bool]) -> None:
    obj = _mapping(value, path)
    _exact_keys(obj, path, {"kind", "signed", "width", "frac"})
    if obj["kind"] != "fixed":
        _fail(f"{path}.kind", "must be fixed")
    got = (obj["width"], obj["frac"], obj["signed"])
    if got != expected:
        _fail(path, f"expected width/frac/signed={expected}, got {got}")


def _validate_complex(value: Any, path: str, expected: tuple[int, int, bool]) -> None:
    obj = _mapping(value, path)
    _exact_keys(obj, path, {"kind", "component"})
    if obj["kind"] != "complex":
        _fail(f"{path}.kind", "must be complex")
    _validate_fixed(obj["component"], f"{path}.component", expected)


def _validate_stream(
    value: Any,
    path: str,
    expected_format: tuple[int, int, bool],
    expected_rate: tuple[int, int],
) -> None:
    obj = _mapping(value, path)
    _exact_keys(obj, path, {"kind", "value", "rate"})
    if obj["kind"] != "stream":
        _fail(f"{path}.kind", "must be stream")
    _validate_complex(obj["value"], f"{path}.value", expected_format)
    rate = _mapping(obj["rate"], f"{path}.rate")
    _exact_keys(rate, f"{path}.rate", {"num", "den"})
    if (rate["num"], rate["den"]) != expected_rate:
        _fail(f"{path}.rate", f"expected {expected_rate}")


def _validate_nco(value: Any, path: str, depth: int = 0) -> None:
    obj = _mapping(value, path)
    kind = obj.get("kind")
    output_fields = {"kind", "output"}
    if kind == "lut_sincos":
        required = output_fields | {"table", "depth", "interpolation", "phase_bits"}
        _exact_keys(obj, path, required)
        if obj["table"] != "quarter_wave":
            _fail(f"{path}.table", "v1 supports quarter_wave only")
        if obj["depth"] not in {64, 128, 256, 512, 1024}:
            _fail(f"{path}.depth", "must be one of 64,128,256,512,1024")
        _choice(obj["interpolation"], f"{path}.interpolation", {"nearest", "linear", "quad"})
        _integer(obj["phase_bits"], f"{path}.phase_bits", 8, 16)
    elif kind == "cordic_sincos":
        required = output_fields | {"mode", "stages", "phase_bits"}
        _exact_keys(obj, path, required)
        if obj["mode"] != "rotation":
            _fail(f"{path}.mode", "v1 supports rotation only")
        _integer(obj["stages"], f"{path}.stages", 7, 20)
        _integer(obj["phase_bits"], f"{path}.phase_bits", 8, 16)
    elif kind == "phasor_compose":
        required = output_fields | {
            "identity",
            "split_bits",
            "coarse",
            "residual",
            "product_rounding",
            "product_saturation",
        }
        _exact_keys(obj, path, required)
        if depth >= 1:
            _fail(path, "v1 permits one phasor_compose level")
        if obj["identity"] != "exp(j*theta)=exp(j*coarse)*exp(j*residual)":
            _fail(f"{path}.identity", "unknown exact identity")
        _integer(obj["split_bits"], f"{path}.split_bits", 2, 14)
        _choice(obj["product_rounding"], f"{path}.product_rounding", {"rne", "trunc"})
        if obj["product_saturation"] != "sat":
            _fail(f"{path}.product_saturation", "must be sat")
        _validate_nco(obj["coarse"], f"{path}.coarse", depth + 1)
        _validate_nco(obj["residual"], f"{path}.residual", depth + 1)
    else:
        _fail(f"{path}.kind", f"unsupported NCO node {kind!r}")
    _validate_complex(obj["output"], f"{path}.output", (16, 15, True))


def _validate_fir(value: Any, path: str) -> None:
    obj = _mapping(value, path)
    common = {
        "kind",
        "decimation",
        "coefficients_id",
        "coefficient_bits",
        "product_drop",
        "accumulator_bits",
        "rounding",
        "saturation",
        "input",
        "output",
    }
    kind = obj.get("kind")
    if kind == "direct_symmetric_fir_decimator":
        _exact_keys(obj, path, common)
    elif kind == "polyphase_fir_decimator":
        _exact_keys(obj, path, common | {"phases"})
        if obj["phases"] != 2:
            _fail(f"{path}.phases", "must equal the R=2 contract")
    else:
        _fail(f"{path}.kind", f"unsupported FIR node {kind!r}")
    if obj["decimation"] != 2:
        _fail(f"{path}.decimation", "must equal the R=2 contract")
    if obj["coefficients_id"] != "ddc-v1-h33":
        _fail(f"{path}.coefficients_id", "must use the frozen coefficient family")
    _integer(obj["coefficient_bits"], f"{path}.coefficient_bits", 8, 24)
    _integer(obj["product_drop"], f"{path}.product_drop", 0, 8)
    accumulator_bits = obj["accumulator_bits"]
    if accumulator_bits != 0:
        _integer(accumulator_bits, f"{path}.accumulator_bits", 20, 48)
    _choice(obj["rounding"], f"{path}.rounding", {"rne", "trunc"})
    if obj["saturation"] != "sat":
        _fail(f"{path}.saturation", "must be sat")
    _validate_stream(obj["input"], f"{path}.input", (16, 15, True), (1, 1))
    _validate_stream(obj["output"], f"{path}.output", (16, 15, True), (1, 2))


def validate_candidate(candidate: Mapping[str, Any]) -> None:
    """Validate a complete DDC candidate or raise ``IRValidationError``."""
    obj = _mapping(candidate, "candidate")
    required = {
        "schema_version",
        "formula_version",
        "contract_version",
        "kind",
        "adc_input",
        "phase_accumulator",
        "nco",
        "mixer",
        "filter_decimator",
    }
    _exact_keys(obj, "candidate", required, {"metadata"})
    if obj["schema_version"] != SCHEMA_VERSION:
        _fail("candidate.schema_version", f"expected {SCHEMA_VERSION}")
    if obj["formula_version"] != FORMULA_VERSION:
        _fail("candidate.formula_version", f"expected {FORMULA_VERSION}")
    if obj["contract_version"] != CONTRACT_VERSION:
        _fail("candidate.contract_version", f"expected {CONTRACT_VERSION}")
    if obj["kind"] != "ddc":
        _fail("candidate.kind", "must be ddc")
    _validate_stream(obj["adc_input"], "candidate.adc_input", (12, 11, True), (1, 1))

    phase = _mapping(obj["phase_accumulator"], "candidate.phase_accumulator")
    _exact_keys(phase, "candidate.phase_accumulator", {"kind", "width"})
    if phase != {"kind": "phase_accumulator", "width": 32}:
        _fail("candidate.phase_accumulator", "must be the frozen 32-bit accumulator")

    _validate_nco(obj["nco"], "candidate.nco")

    mixer = _mapping(obj["mixer"], "candidate.mixer")
    _exact_keys(
        mixer,
        "candidate.mixer",
        {"kind", "product_drop", "rounding", "saturation", "output"},
    )
    if (
        mixer["kind"],
        mixer["product_drop"],
        mixer["rounding"],
        mixer["saturation"],
    ) != ("complex_multiply", 0, "rne", "sat"):
        _fail("candidate.mixer", "v1 mixer is frozen to exact/rne/sat")
    _validate_stream(mixer["output"], "candidate.mixer.output", (16, 15, True), (1, 1))
    _validate_fir(obj["filter_decimator"], "candidate.filter_decimator")

    if "metadata" in obj and not isinstance(obj["metadata"], Mapping):
        _fail("candidate.metadata", "expected an object")


def validate_nco_node(node: Mapping[str, Any]) -> None:
    """Validate a standalone NCO realization node."""
    _validate_nco(node, "nco")


def validate_fir_node(node: Mapping[str, Any]) -> None:
    """Validate a standalone FIR / decimator realization node."""
    _validate_fir(node, "filter_decimator")
