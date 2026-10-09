import copy
import sys
from pathlib import Path

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir import (
    IRValidationError,
    candidate_hash,
    cordic_sincos,
    ddc_candidate,
    direct_symmetric_fir,
    lut_sincos,
    phasor_compose,
    polyphase_decimator,
    validate_candidate,
)


def test_registered_leaf_structures_are_valid_ir_nodes():
    lut = ddc_candidate(
        lut_sincos(depth=512, interpolation="nearest", phase_bits=16),
        direct_symmetric_fir(coefficient_bits=16),
        label="human-readable-only",
    )
    cordic = ddc_candidate(
        cordic_sincos(stages=8, phase_bits=16),
        polyphase_decimator(coefficient_bits=12, product_drop=2),
    )
    validate_candidate(lut)
    validate_candidate(cordic)


def test_unregistered_phasor_composition_is_a_valid_tree():
    hybrid = ddc_candidate(
        phasor_compose(
            coarse=lut_sincos(depth=128, interpolation="nearest", phase_bits=10),
            residual=cordic_sincos(stages=7, phase_bits=12),
            split_bits=8,
        ),
        polyphase_decimator(
            coefficient_bits=14,
            rounding="nearest_ties_to_pos_inf",
        ),
    )
    validate_candidate(hybrid)
    assert hybrid["nco"]["coarse"]["kind"] == "lut_sincos"
    assert hybrid["nco"]["residual"]["kind"] == "cordic_sincos"


def test_candidate_hash_ignores_metadata_and_mapping_order():
    candidate = ddc_candidate(
        cordic_sincos(stages=9, phase_bits=16),
        direct_symmetric_fir(coefficient_bits=12),
        label="first label",
    )
    reordered = {key: candidate[key] for key in reversed(candidate)}
    reordered["metadata"] = {"label": "another label", "notes": "not semantic"}
    assert candidate_hash(candidate) == candidate_hash(reordered)

    changed = copy.deepcopy(candidate)
    changed["nco"]["stages"] = 10
    assert candidate_hash(candidate) != candidate_hash(changed)


def test_validator_rejects_contract_drift_and_hidden_fields():
    candidate = ddc_candidate(
        lut_sincos(depth=256, interpolation="linear", phase_bits=12),
        direct_symmetric_fir(coefficient_bits=16),
    )
    candidate["filter_decimator"]["decimation"] = 3
    with pytest.raises(IRValidationError, match="decimation"):
        validate_candidate(candidate)

    candidate = ddc_candidate(
        lut_sincos(depth=256, interpolation="linear", phase_bits=12),
        direct_symmetric_fir(coefficient_bits=16),
    )
    candidate["nco"]["secret_selector"] = "candidate-name"
    with pytest.raises(IRValidationError, match="unknown fields"):
        validate_candidate(candidate)


def test_validator_rejects_nested_composition_in_v1():
    leaf = cordic_sincos(stages=7, phase_bits=12)
    nested = phasor_compose(
        coarse=phasor_compose(
            coarse=lut_sincos(128, "nearest", 10),
            residual=leaf,
            split_bits=8,
        ),
        residual=leaf,
        split_bits=6,
    )
    candidate = ddc_candidate(nested, direct_symmetric_fir(coefficient_bits=12))
    with pytest.raises(IRValidationError, match="one phasor_compose level"):
        validate_candidate(candidate)


@pytest.mark.parametrize("path,value", [
    ("adc_input.value.component.width", 12.0),
    ("adc_input.value.component.frac", 11.0),
    ("adc_input.value.component.signed", 1),
    ("adc_input.rate.num", True),
    ("adc_input.rate.den", 1.0),
    ("phase_accumulator.width", 32.0),
    ("mixer.product_drop", False),
    ("mixer.product_drop", 0.0),
    ("filter_decimator.decimation", 2.0),
    ("filter_decimator.phases", 2.0),
    ("filter_decimator.accumulator_bits", False),
    ("filter_decimator.accumulator_bits", 0.0),
    ("filter_decimator.output.rate.den", 2.0),
    ("nco.depth", 256.0),
    ("nco.depth", []),
    ("nco.depth", {}),
    ("nco.interpolation", []),
    ("nco.interpolation", {}),
    ("filter_decimator.rounding", []),
])
def test_raw_json_rejects_type_aliases_and_containers(path, value):
    # 直接改原始对象，不让 constructor 的强制转换修饰非法 JSON。
    candidate = ddc_candidate(lut_sincos(256, "linear", 12), polyphase_decimator(16))
    fields = path.split(".")
    target = candidate
    for field in fields[:-1]:
        target = target[field]
    target[fields[-1]] = value
    with pytest.raises(IRValidationError, match=fields[-1]):
        validate_candidate(candidate)


def test_valid_candidate_identity_is_unchanged_by_strict_validation():
    candidate = ddc_candidate(lut_sincos(256, "linear", 12), direct_symmetric_fir(16))
    validate_candidate(candidate)
    assert candidate_hash(candidate) == "5a616173021041c0423dfb863171958dd8f2f8748be68c2c7bbb07eb5527beac"
