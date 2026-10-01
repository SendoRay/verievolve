import copy
from dataclasses import replace

import numpy as np
import pytest

from search_ir_dev_fixtures import make_candidate, make_case
from search_ir import validate_candidate
from search_ir import evaluate
from search_ir.evaluate import (
    EvaluationError, aggregate_rows, evaluate_candidate, project_feedback,
    score_outputs, validate_case,
)


@pytest.mark.parametrize("kind", ["lut", "cordic", "compose"])
def test_fixed_fixtures_evaluate_without_claiming_formal_feasibility(kind):
    case = make_case()
    result = evaluate_candidate(make_candidate(kind), [case])
    assert result["status"] == "ok"
    assert result["Q_dev"] == result["rows"][0]["q_aligned"]
    assert result["rows"][0]["n_samples"] == 32
    assert result["deployment_feasibility"] == "pending"
    assert result["area"]["status"] == "unavailable"
    assert result["area"]["value_um2"] is None
    assert result["saturation_scope"]["includes_preamble"] is True
    assert result["saturation_scope"]["legacy_fir_count_compatible"] is False
    assert "Q_main" not in result


def test_mask_failure_is_not_a_schema_failure_and_does_not_run_model(monkeypatch):
    candidate = make_candidate(coefficient_bits=8)
    validate_candidate(candidate)

    def forbidden(*args):
        pytest.fail("mask 失败的候选不得进入模型评价")

    monkeypatch.setattr(evaluate, "emulate_ddc_candidate", forbidden)
    result = evaluate_candidate(candidate, [make_case()])
    assert result["status"] == "mask_failed"
    assert result["deployment_feasibility"] == "failed"
    assert result["Q_dev"] is None and result["rows"] == []
    assert project_feedback(result, "satisfaction", 1e-5) == {"status": "failed"}


def test_exact_and_nonzero_error_calibrations_use_only_preamble():
    ref = np.ones(16, dtype=complex)
    desired = ref * 0.5
    assert score_outputs(ref, ref, desired, 4)["q_aligned"] == 0
    got = ref * (1.0 + 0.25j)
    got[4:] += 0.125 * (1.0 + 0.25j)
    score = score_outputs(ref, got, desired, 4)
    assert score["gain_re"] == 1.0 and score["gain_im"] == 0.25
    assert score["q_aligned"] == pytest.approx(0.125**2 / 0.5**2)
    assert score["q_raw"] > score["q_aligned"]


@pytest.mark.parametrize("field,value", [
    ("y_ref", np.full(48, np.nan, dtype=complex)),
    ("y_des_ref", np.full(48, np.inf, dtype=complex)),
    ("i12", np.ones(128, dtype=float)),
    ("i12", np.full(128, 2048, dtype=np.int64)),
    ("fcw", True),
    ("n_pre_out", 0),
    ("n_pre_out", 48),
    ("n_pre_out", 16.0),
    ("output_indices", np.arange(48)),
    ("y_ref", np.ones(48, dtype=complex)),
    ("y_des_ref", np.ones(48, dtype=complex)),
])
def test_rejects_bad_case_arrays_mapping_or_reference(field, value):
    with pytest.raises(EvaluationError):
        validate_case(replace(make_case(), **{field: value}))


@pytest.mark.parametrize("where", ["reference", "desired", "candidate"])
def test_zero_energy_or_gain_is_rejected(where):
    ref = np.ones(16, dtype=complex)
    got, desired = ref.copy(), ref.copy()
    if where == "reference":
        ref[:4] = 0
    elif where == "desired":
        desired[4:] = 0
    else:
        got[:4] = 0
    with pytest.raises(ValueError):
        score_outputs(ref, got, desired, 4)


@pytest.mark.parametrize("value", [np.nan, np.inf, -1.0, True])
def test_aggregation_rejects_invalid_values_independent_of_order(value):
    rows = [{"case_id": "a", "q_aligned": 0.1}, {"case_id": "b", "q_aligned": value}]
    for order in (rows, list(reversed(rows))):
        with pytest.raises(EvaluationError):
            aggregate_rows(order, ["a", "b"])


@pytest.mark.parametrize("actual", [[], ["a"], ["a", "a"], ["a", "b", "c"]])
def test_aggregation_rejects_incomplete_duplicate_or_extra_cases(actual):
    with pytest.raises(EvaluationError):
        aggregate_rows([{"case_id": x, "q_aligned": 0.0} for x in actual], ["a", "b"])


def test_candidate_duplicate_cases_are_rejected():
    case = make_case()
    with pytest.raises(EvaluationError):
        evaluate_candidate(make_candidate(), [case, case])


@pytest.mark.parametrize("field", ["output_indices", "y_re"])
def test_candidate_output_mapping_and_length_are_validated(monkeypatch, field):
    original = evaluate.emulate_ddc_candidate

    def broken(*args):
        result = original(*args)
        result[field] = result[field][1:]
        return result

    monkeypatch.setattr(evaluate, "emulate_ddc_candidate", broken)
    with pytest.raises(EvaluationError):
        evaluate_candidate(make_candidate(), [make_case()])


def test_feedback_projection_is_an_allowlist_not_a_dict_filter():
    result = evaluate_candidate(make_candidate(), [make_case()])
    result["private_diagnostics"] = {"q": 123.0}
    q = result["Q_dev"]
    assert project_feedback(result, "numerical", q) == {"status": "ok", "Q_dev": q}
    assert project_feedback(result, "satisfaction", q) == {
        "status": "ok", "pass_count": 1, "case_count": 1,
    }
    altered = copy.deepcopy(result)
    altered["rows"][0]["q_aligned"] *= 10
    altered["Q_dev"] *= 10
    assert project_feedback(altered, "satisfaction", q / 2) == project_feedback(
        result, "satisfaction", q / 2
    )


@pytest.mark.parametrize("dtype", [np.int8, np.uint8, np.int16, np.int32, np.float32, np.complex64])
def test_scoring_promotes_signals_before_energy_and_correlation(dtype):
    ref = np.full(8, 100, dtype=dtype)
    got = np.full(8, 101, dtype=dtype)
    got[4:] = 102
    result = score_outputs(ref, got, ref, 4)
    expected = score_outputs(ref.astype(np.complex128), got.astype(np.complex128),
                             ref.astype(np.complex128), 4)
    assert result == expected
    assert result["gain_re"] == pytest.approx(1.01)
    assert result["desired_power"] == 10000.0
    assert result["q_aligned"] == pytest.approx((102 / 1.01 - 100) ** 2 / 10000)
