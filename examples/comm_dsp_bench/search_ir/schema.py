"""Constructors for the first VeriEvolve typed design IR.

The IR is JSON-shaped on purpose: every proposer will emit the same language,
and the exact object that is validated can be persisted in an experiment
manifest.  Constructors are conveniences, not hidden candidate registries.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from numeric_semantics import NEAREST_TIES_TO_POS_INF, normalize_rounding_mode


SCHEMA_VERSION = "verievolve-search-ir-v1"
FORMULA_VERSION = "ddc-formula-v1"
CONTRACT_VERSION = "CONTRACT_DDC_v1"


def fixed_format(width: int, frac: int, signed: bool = True) -> dict[str, Any]:
    """Return an explicit scalar fixed-point type."""
    return {
        "kind": "fixed",
        "signed": bool(signed),
        "width": int(width),
        "frac": int(frac),
    }


def complex_format(component: Mapping[str, Any]) -> dict[str, Any]:
    """Return a complex type whose real and imaginary fields share a format."""
    return {"kind": "complex", "component": deepcopy(dict(component))}


def stream_type(value: Mapping[str, Any], rate_num: int, rate_den: int) -> dict[str, Any]:
    """Return a rational-rate stream type."""
    return {
        "kind": "stream",
        "value": deepcopy(dict(value)),
        "rate": {"num": int(rate_num), "den": int(rate_den)},
    }


def _nco_output_type() -> dict[str, Any]:
    return complex_format(fixed_format(16, 15, signed=True))


def lut_sincos(
    depth: int,
    interpolation: str,
    phase_bits: int,
) -> dict[str, Any]:
    """Quarter-wave LUT realization of a complex phasor."""
    return {
        "kind": "lut_sincos",
        "table": "quarter_wave",
        "depth": int(depth),
        "interpolation": str(interpolation),
        "phase_bits": int(phase_bits),
        "output": _nco_output_type(),
    }


def cordic_sincos(stages: int, phase_bits: int) -> dict[str, Any]:
    """Rotation-mode CORDIC realization of a complex phasor."""
    return {
        "kind": "cordic_sincos",
        "mode": "rotation",
        "stages": int(stages),
        "phase_bits": int(phase_bits),
        "output": _nco_output_type(),
    }


def phasor_compose(
    coarse: Mapping[str, Any],
    residual: Mapping[str, Any],
    split_bits: int,
    product_rounding: str = NEAREST_TIES_TO_POS_INF,
) -> dict[str, Any]:
    """Compose coarse and residual phasors using exp(jt)=exp(jc)exp(jr).

    This is the first non-tabular constructor: its children are realization
    nodes, not names in a candidate table.
    """
    return {
        "kind": "phasor_compose",
        "identity": "exp(j*theta)=exp(j*coarse)*exp(j*residual)",
        "split_bits": int(split_bits),
        "coarse": deepcopy(dict(coarse)),
        "residual": deepcopy(dict(residual)),
        "product_rounding": normalize_rounding_mode(product_rounding),
        "product_saturation": "sat",
        "output": _nco_output_type(),
    }


def _fir_common(
    coefficients_id: str,
    coefficient_bits: int,
    product_drop: int,
    accumulator_bits: int,
    rounding: str,
) -> dict[str, Any]:
    return {
        "coefficients_id": str(coefficients_id),
        "coefficient_bits": int(coefficient_bits),
        "product_drop": int(product_drop),
        "accumulator_bits": int(accumulator_bits),
        "rounding": normalize_rounding_mode(rounding),
        "saturation": "sat",
        "input": stream_type(complex_format(fixed_format(16, 15)), 1, 1),
        "output": stream_type(complex_format(fixed_format(16, 15)), 1, 2),
    }


def direct_symmetric_fir(
    coefficient_bits: int,
    product_drop: int = 0,
    accumulator_bits: int = 0,
    rounding: str = NEAREST_TIES_TO_POS_INF,
    coefficients_id: str = "ddc-v1-h33",
) -> dict[str, Any]:
    """Direct symmetric FIR followed by the contract's R=2 decimator."""
    return {
        "kind": "direct_symmetric_fir_decimator",
        "decimation": 2,
        **_fir_common(
            coefficients_id,
            coefficient_bits,
            product_drop,
            accumulator_bits,
            rounding,
        ),
    }


def polyphase_decimator(
    coefficient_bits: int,
    product_drop: int = 0,
    accumulator_bits: int = 0,
    rounding: str = NEAREST_TIES_TO_POS_INF,
    coefficients_id: str = "ddc-v1-h33",
) -> dict[str, Any]:
    """Two-branch polyphase FIR decimator with the same real semantics."""
    return {
        "kind": "polyphase_fir_decimator",
        "decimation": 2,
        "phases": 2,
        **_fir_common(
            coefficients_id,
            coefficient_bits,
            product_drop,
            accumulator_bits,
            rounding,
        ),
    }


def ddc_candidate(
    nco: Mapping[str, Any],
    filter_decimator: Mapping[str, Any],
    *,
    label: str | None = None,
) -> dict[str, Any]:
    """Build a complete DDC implementation candidate."""
    candidate: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "formula_version": FORMULA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "kind": "ddc",
        "adc_input": stream_type(complex_format(fixed_format(12, 11)), 1, 1),
        "phase_accumulator": {"kind": "phase_accumulator", "width": 32},
        "nco": deepcopy(dict(nco)),
        "mixer": {
            "kind": "complex_multiply",
            "product_drop": 0,
            "rounding": NEAREST_TIES_TO_POS_INF,
            "saturation": "sat",
            "output": stream_type(complex_format(fixed_format(16, 15)), 1, 1),
        },
        "filter_decimator": deepcopy(dict(filter_decimator)),
    }
    if label is not None:
        candidate["metadata"] = {"label": str(label)}
    return candidate
