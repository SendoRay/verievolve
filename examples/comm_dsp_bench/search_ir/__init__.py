"""Typed design IR for formula-conditioned fixed-point hardware search.

The package deliberately starts with representation, canonicalization, and
legality.  Search algorithms and LLM backends are layered on only after the
representation gates in ``thesis/SEARCH_PROTOCOL_v1.md`` pass.
"""

from .canonicalize import candidate_hash, canonical_json
from .architecture_plan import (
    ARCHITECTURE_PLAN_SCHEMA,
    ArchitecturePlanError,
    architecture_plan,
    compile_architecture_plan,
    parse_architecture_plan,
    plan_hash,
    plan_json,
    try_compile_architecture_plan,
)
from .formula_contract import (
    DDC_FORMULA_ID,
    FORMULA_REQUEST_SCHEMA,
    FormulaContractError,
    ddc_formula_request,
    formula_hash,
    formula_json,
    validate_formula_request,
)
from .lower_bittrue import (
    emulate_ddc_candidate,
    emulate_fir_decimator,
    emulate_nco_accumulators,
    fir_node_config,
    leaf_nco_config,
    resolve_fir_coefficients,
    split_phase_accumulators,
)
from .lower_rtl import lower_ddc_rtl, lower_fir_decimator_rtl, lower_nco_map_rtl
from .planning_loop import (
    capability_manifest,
    planner_context,
    run_planning_loop,
)
from .llm_planner import (
    SYSTEM_MESSAGE as LLM_PLANNER_SYSTEM_MESSAGE,
    extract_json_payload,
    render_planner_prompt,
    run_llm_planning_loop,
)
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
    "ARCHITECTURE_PLAN_SCHEMA",
    "CONTRACT_VERSION",
    "DDC_FORMULA_ID",
    "FORMULA_REQUEST_SCHEMA",
    "FORMULA_VERSION",
    "LLM_PLANNER_SYSTEM_MESSAGE",
    "ArchitecturePlanError",
    "FormulaContractError",
    "IRValidationError",
    "SCHEMA_VERSION",
    "candidate_hash",
    "capability_manifest",
    "canonical_json",
    "architecture_plan",
    "compile_architecture_plan",
    "cordic_sincos",
    "ddc_candidate",
    "ddc_formula_request",
    "direct_symmetric_fir",
    "emulate_ddc_candidate",
    "emulate_fir_decimator",
    "emulate_nco_accumulators",
    "extract_json_payload",
    "fir_node_config",
    "leaf_nco_config",
    "lower_nco_map_rtl",
    "lower_fir_decimator_rtl",
    "lower_ddc_rtl",
    "lut_sincos",
    "phasor_compose",
    "parse_architecture_plan",
    "plan_hash",
    "plan_json",
    "planner_context",
    "polyphase_decimator",
    "resolve_fir_coefficients",
    "render_planner_prompt",
    "run_llm_planning_loop",
    "run_planning_loop",
    "split_phase_accumulators",
    "try_compile_architecture_plan",
    "validate_candidate",
    "validate_formula_request",
    "validate_fir_node",
    "validate_nco_node",
    "formula_hash",
    "formula_json",
]
