import copy
import json
import sys
from pathlib import Path

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.architecture_plan import (
    ArchitecturePlanError,
    architecture_plan,
    compile_architecture_plan,
    parse_architecture_plan,
    plan_hash,
    try_compile_architecture_plan,
)
from search_ir.formula_contract import ddc_formula_request
from search_ir.lower_rtl import lower_ddc_rtl
from search_ir.validate import validate_candidate


def _filter(strategy="polyphase"):
    return {
        "strategy": strategy,
        "coefficient_bits": 14,
        "product_drop": 1,
        "accumulator_bits": 28,
        "rounding": "nearest_ties_to_pos_inf",
    }


def _hybrid_nco():
    return {
        "strategy": "coarse_residual",
        "split_bits": 8,
        "product_rounding": "nearest_ties_to_pos_inf",
        "coarse": {
            "strategy": "lut", "depth": 128,
            "interpolation": "nearest", "phase_bits": 10,
        },
        "residual": {"strategy": "cordic", "stages": 7, "phase_bits": 16},
    }


def test_complete_multistructure_plan_lowers_to_existing_typed_ir_and_rtl():
    formula = ddc_formula_request()
    plan = architecture_plan(
        formula,
        nco=_hybrid_nco(),
        filter_decimator=_filter("polyphase"),
        rationale=["coarse LUT handles quadrants", "polyphase avoids discarded outputs"],
    )
    result = compile_architecture_plan(formula, plan)
    candidate = result["candidate"]
    validate_candidate(candidate)
    assert candidate["nco"]["kind"] == "phasor_compose"
    assert candidate["filter_decimator"]["kind"] == "polyphase_fir_decimator"
    assert result["candidate_sha256"]
    rtl = lower_ddc_rtl(candidate)
    assert "Complete DDC generated from search IR" in rtl
    assert "module top" in rtl


def test_plan_lowering_is_deterministic_and_rationale_is_nonsemantic():
    formula = ddc_formula_request()
    plan = architecture_plan(
        formula,
        nco={"strategy": "cordic", "stages": 11, "phase_bits": 15},
        filter_decimator=_filter("direct_symmetric"),
        rationale=["first explanation"],
    )
    changed_words = copy.deepcopy(plan)
    changed_words["rationale"] = ["different explanation"]
    assert plan_hash(plan) == plan_hash(changed_words)
    assert (compile_architecture_plan(formula, plan)["candidate_sha256"]
            == compile_architecture_plan(formula, changed_words)["candidate_sha256"])


def test_legacy_rounding_inputs_are_normalized_before_new_candidates_are_built():
    formula = ddc_formula_request()
    plan = architecture_plan(
        formula,
        nco=_hybrid_nco() | {"product_rounding": "rne"},
        filter_decimator=_filter() | {"rounding": "trunc"},
    )
    assert plan["nco"]["product_rounding"] == "nearest_ties_to_pos_inf"
    assert plan["filter_decimator"]["rounding"] == "floor"
    candidate = compile_architecture_plan(formula, plan)["candidate"]
    assert candidate["nco"]["product_rounding"] == "nearest_ties_to_pos_inf"
    assert candidate["filter_decimator"]["rounding"] == "floor"


def test_formula_mismatch_is_structured_repair_feedback():
    formula = ddc_formula_request(max_aligned_nmse=1e-5)
    other = ddc_formula_request(max_aligned_nmse=2e-5)
    plan = architecture_plan(
        other,
        nco={
            "strategy": "lut", "depth": 256,
            "interpolation": "linear", "phase_bits": 12,
        },
        filter_decimator=_filter(),
    )
    result = try_compile_architecture_plan(formula, plan)
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "formula_mismatch"
    assert result["error"]["path"] == "$plan.formula_sha256"


@pytest.mark.parametrize("mutation,path", [
    (lambda p: p["nco"].update(depth=63), "$plan.nco.depth"),
    (lambda p: p["filter_decimator"].update(accumulator_bits=19),
     "$plan.filter_decimator.accumulator_bits"),
    (lambda p: p["nco"].update(secret_rtl="assign y=1"), "$plan.nco"),
])
def test_plan_cannot_escape_verified_component_domains(mutation, path):
    formula = ddc_formula_request()
    plan = architecture_plan(
        formula,
        nco={
            "strategy": "lut", "depth": 256,
            "interpolation": "linear", "phase_bits": 12,
        },
        filter_decimator=_filter(),
    )
    mutation(plan)
    with pytest.raises(ArchitecturePlanError) as err:
        parse_architecture_plan(plan)
    assert err.value.path == path


def test_plan_parser_rejects_duplicate_json_keys():
    formula = ddc_formula_request()
    plan = architecture_plan(
        formula,
        nco={"strategy": "cordic", "stages": 12, "phase_bits": 16},
        filter_decimator=_filter(),
    )
    text = json.dumps(plan)
    duplicate = text.replace('"kind": "ddc-architecture-plan"',
                             '"kind": "ddc-architecture-plan", "kind": "x"')
    with pytest.raises(ArchitecturePlanError) as err:
        parse_architecture_plan(duplicate)
    assert err.value.code == "duplicate_key"
