import copy
import json
import sys
from pathlib import Path

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.formula_contract import (
    FormulaContractError,
    ddc_formula_request,
    formula_hash,
    formula_json,
    validate_formula_request,
)


def test_ddc_formula_is_explicit_and_has_stable_identity():
    request = ddc_formula_request()
    validated = validate_formula_request(request)
    assert [node["op"] for node in validated["nodes"]] == [
        "phase_accumulate", "complex_exp", "complex_multiply", "fir", "decimate"
    ]
    assert validated["requirements"]["quality"]["maximum"] > 0.0
    assert formula_hash(request) == formula_hash(json.loads(formula_json(request)))


def test_usage_requirements_are_part_of_formula_identity():
    a = ddc_formula_request(max_aligned_nmse=1e-5)
    b = ddc_formula_request(max_aligned_nmse=2e-5)
    assert formula_hash(a) != formula_hash(b)


def test_formula_rejects_hidden_graph_and_interface_changes():
    request = ddc_formula_request()
    request["nodes"][2]["op"] = "approximate_multiply"
    with pytest.raises(FormulaContractError) as err:
        validate_formula_request(request)
    assert err.value.path == "$formula.nodes"

    request = ddc_formula_request()
    request["output"]["type"]["rate"]["den"] = 4
    with pytest.raises(FormulaContractError) as err:
        validate_formula_request(request)
    assert err.value.path == "$formula.output.type"


def test_formula_parser_rejects_duplicate_and_nonfinite_json():
    text = formula_json(ddc_formula_request())
    duplicate = text.replace(
        '"formula_id":"ddc-baseband-v1"',
        '"formula_id":"ddc-baseband-v1","formula_id":"ddc-baseband-v1"',
    )
    with pytest.raises(FormulaContractError) as err:
        validate_formula_request(duplicate)
    assert err.value.code == "duplicate_key"

    bad = copy.deepcopy(ddc_formula_request())
    bad["requirements"]["quality"]["maximum"] = float("nan")
    with pytest.raises(FormulaContractError):
        validate_formula_request(bad)
