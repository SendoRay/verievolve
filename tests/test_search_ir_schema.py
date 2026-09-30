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
        polyphase_decimator(coefficient_bits=14, rounding="rne"),
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
