"""Typed design IR for formula-conditioned fixed-point hardware search.

The package deliberately starts with representation, canonicalization, and
legality.  Search algorithms and LLM backends are layered on only after the
representation gates in ``thesis/SEARCH_PROTOCOL_v1.md`` pass.
"""

from .canonicalize import candidate_hash, canonical_json
from .lower_bittrue import (
    emulate_fir_decimator,
    emulate_nco_accumulators,
    fir_node_config,
    leaf_nco_config,
    resolve_fir_coefficients,
    split_phase_accumulators,
)
from .lower_rtl import lower_fir_decimator_rtl, lower_nco_map_rtl
from .schema import (
    CONTRACT_VERSION,
    FORMULA_VERSION,
    SCHEMA_VERSION,
    cordic_sincos,
    ddc_candidate,
    direct_symmetric_fir,
    lut_sincos,
    phasor_compose,
    polyphase_decimator,
)
from .validate import (
    IRValidationError,
    validate_candidate,
    validate_fir_node,
    validate_nco_node,
)

__all__ = [
    "CONTRACT_VERSION",
    "FORMULA_VERSION",
    "IRValidationError",
    "SCHEMA_VERSION",
    "candidate_hash",
    "canonical_json",
    "cordic_sincos",
    "ddc_candidate",
    "direct_symmetric_fir",
    "emulate_fir_decimator",
    "emulate_nco_accumulators",
    "fir_node_config",
    "leaf_nco_config",
    "lower_nco_map_rtl",
    "lower_fir_decimator_rtl",
    "lut_sincos",
    "phasor_compose",
    "polyphase_decimator",
    "resolve_fir_coefficients",
    "split_phase_accumulators",
    "validate_candidate",
    "validate_fir_node",
    "validate_nco_node",
]
