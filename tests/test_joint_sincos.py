from copy import deepcopy
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from joint_sincos import (  # noqa: E402
    SincosCandidateError,
    backend_parameters,
    candidate_hash,
    cordic_candidate,
    evaluate_exact,
    evaluator_binding,
    lower_rtl,
    lut_candidate,
    quality_gate,
    validate_candidate,
)
import evaluator  # noqa: E402
from certfit import tpl_cordic  # noqa: E402


@pytest.mark.parametrize("candidate", [
    lut_candidate(64, "nearest"),
    lut_candidate(256, "linear", phase_bits=14),
    cordic_candidate(12),
])
def test_candidate_exposes_three_joint_axes_without_formula_node_lock(candidate):
    result = validate_candidate(candidate)
    assert result["exact_formula_equality_required"] is False
    assert set(candidate) >= {"algorithm", "precision", "microarchitecture"}
    assert result["candidate_hash"] == candidate_hash(candidate)


def test_two_algorithm_families_reuse_checked_backends_and_real_task_interface():
    lut = lut_candidate(128, "linear")
    cordic = cordic_candidate(10)
    assert backend_parameters(lut) == {"algo": "lut", "depth": 128, "order": "linear"}
    assert backend_parameters(cordic) == {"algo": "cordic", "stages": 10}
    for candidate in (lut, cordic):
        binding = evaluator_binding(candidate)
        source = lower_rtl(candidate)
        assert binding["task"] == "cordic_sincos"
        assert binding["protocol"] == "stream_v1"
        assert "module top (" in source
        assert "in_valid" in source and "in_ready" in source
        assert "sin_out" in source and "cos_out" in source


def test_binding_matches_the_task_card_loaded_by_the_real_evaluator(monkeypatch):
    monkeypatch.setattr(evaluator, "TASK_NAME", "cordic_sincos")
    task = evaluator._load_task()
    binding = evaluator_binding(lut_candidate(64, "nearest"))
    assert task["task"] == binding["task"]
    assert task["dut_module"] == binding["dut_module"]
    assert task["io_protocol"]["base"] == binding["protocol"]
    assert [
        {"name": port["name"], "width": port["width"], "signed": port["signed"]}
        for port in task["io_protocol"]["inputs"]
    ] == binding["input_ports"]
    assert [
        {"name": port["name"], "width": port["width"], "signed": port["signed"]}
        for port in task["io_protocol"]["outputs"]
    ] == binding["output_ports"]
    assert task["metric"]["type"] == binding["metric"]


def test_phase_precision_is_semantic_in_exact_model_and_rtl():
    full = lut_candidate(256, "linear", phase_bits=16)
    reduced = lut_candidate(256, "linear", phase_bits=10)
    full_metrics = evaluate_exact(full)
    reduced_metrics = evaluate_exact(reduced)
    assert full_metrics["enumerated_input_codes"] == 65536
    assert reduced_metrics["enumerated_input_codes"] == 65536
    assert reduced_metrics["sqnr_db"] < full_metrics["sqnr_db"]
    assert "module joint_sincos_core" in lower_rtl(reduced)
    assert "z_quantized = {z[15:6], 6'b0}" in lower_rtl(reduced)
    assert candidate_hash(full) != candidate_hash(reduced)


@pytest.mark.parametrize("candidate", [
    lut_candidate(128, "linear"),
    cordic_candidate(14),
])
def test_exact_metrics_match_the_existing_checked_family_model(candidate):
    params = backend_parameters(candidate)
    expected = tpl_cordic.cert_metrics(params)["precision"]
    assert evaluate_exact(candidate)["sqnr_db"] == pytest.approx(expected, abs=5e-5)


def test_quality_gate_is_separate_from_structural_admission():
    candidate = lut_candidate(64, "nearest", minimum_sqnr_db=200.0)
    validate_candidate(candidate)  # a low-quality implementation remains representable
    metrics = evaluate_exact(candidate)
    verdict = quality_gate(candidate, metrics)
    assert verdict["passed"] is False
    assert verdict["verified_reason"].startswith("sqnr_db")

    relaxed = deepcopy(candidate)
    relaxed["quality_contract"]["threshold"] = -100.0
    relaxed_metrics = evaluate_exact(relaxed)
    assert quality_gate(relaxed, relaxed_metrics)["passed"] is True


def test_metrics_cannot_be_attached_to_a_different_candidate():
    first = lut_candidate(64, "nearest")
    second = lut_candidate(128, "linear")
    with pytest.raises(ValueError, match="not bound"):
        quality_gate(second, evaluate_exact(first))


def test_structurally_legal_unimplemented_microarchitecture_is_not_silently_ignored():
    candidate = cordic_candidate(12)
    candidate["microarchitecture"] = {
        "datapath": "fully_pipelined_shift_add",
        "pipeline_stages": 12,
        "latency_cycles": 12,
        "initiation_interval": 1,
        "resource_sharing": False,
    }
    validate_candidate(candidate)
    with pytest.raises(ValueError, match="does not lower"):
        lower_rtl(candidate)


@pytest.mark.parametrize("mutation,match", [
    (lambda c: c["algorithm"].update({"table_depth": 63}), "table_depth"),
    (lambda c: c["precision"].update({"phase_bits": 7}), "phase_bits"),
    (lambda c: c["quality_contract"].update({"metric": "binary_correct"}), "minimum SQNR"),
])
def test_invalid_candidates_are_rejected_before_evaluation(mutation, match):
    candidate = lut_candidate(64, "nearest")
    mutation(candidate)
    with pytest.raises(SincosCandidateError, match=match):
        validate_candidate(candidate)
