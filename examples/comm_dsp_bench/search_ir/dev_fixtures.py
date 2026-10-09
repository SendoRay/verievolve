"""阶段 B/C 共用的固定开发输入与候选；不读取正式或留出任务。"""

import numpy as np

from chains.ddc import ref_chain

from .evaluate import case_identity, evaluate_candidate, prepare_case
from .verification_status import quality_requirement_status

from .schema import (
    cordic_sincos,
    ddc_candidate,
    direct_symmetric_fir,
    lut_sincos,
    phasor_compose,
    polyphase_decimator,
)


def make_candidate(kind="lut", coefficient_bits=16):
    """保持最初开发 fixture 的结构与参数，不按结果挑选候选。"""
    if kind == "lut":
        return ddc_candidate(
            lut_sincos(256, "linear", 12),
            direct_symmetric_fir(coefficient_bits),
        )
    if kind == "cordic":
        return ddc_candidate(
            cordic_sincos(12, 16), polyphase_decimator(coefficient_bits)
        )
    if kind == "compose":
        return ddc_candidate(
            phasor_compose(
                lut_sincos(128, "nearest", 10),
                cordic_sincos(7, 16),
                split_bits=8,
            ),
            polyphase_decimator(coefficient_bits),
        )
    raise ValueError(kind)


def development_candidates():
    """按固定顺序返回三份独立 IR：LUT、CORDIC、单层 compose。"""
    return [make_candidate(kind) for kind in ("lut", "cordic", "compose")]


def development_case():
    """Return the public synthetic tone used only for method development."""
    n = np.arange(128)
    fcw = 0x31415927
    theta = 2 * np.pi * fcw * n / (1 << 32)
    desired = 0.2 * np.exp(1j * theta)
    x = desired + 0.001 * np.exp(0.13j * n)
    i = np.rint(x.real * 2048).astype(np.int64)
    q = np.rint(x.imag * 2048).astype(np.int64)
    return prepare_case("public-synthetic-tone-v1", i, q, fcw, desired, n_pre_out=16)


def development_candidate_evaluator(candidate, formula):
    """Measure one candidate and decide only the public development requirement."""
    evaluation = evaluate_candidate(candidate, [development_case()])
    acceptance = quality_requirement_status(formula, evaluation)
    saturation = {
        key: sum(int(row[key]) for row in evaluation["rows"])
        for key in ("n_sat_mix", "n_sat_fir")
    }
    measurements = {
        "quality": acceptance,
        "fir_mask": evaluation["fir_mask"],
        "saturation": saturation,
        "scope": evaluation["scope"],
    }
    if acceptance["requirement_status"] == "satisfied":
        return {"status": "accepted", "measurements": measurements, "feedback": None}
    return {
        "status": "rejected",
        "measurements": measurements,
        "feedback": {
            "reason": "quality_measurement_failed"
            if acceptance["measurement_status"] != "ok"
            else "quality_limit_not_satisfied",
            "quality": acceptance,
            "fir_mask": evaluation["fir_mask"],
            "saturation": saturation,
        },
    }


def development_evaluation_contract():
    """Identity of the deterministic public-fixture evaluator used for caching."""
    return {
        "schema_version": "development-evaluation-contract-v1",
        "adapter": "search_ir.dev_fixtures.development_candidate_evaluator",
        "case": case_identity(development_case()),
        "evidence_role": "development_only",
        "deployment_acceptance": False,
        "cache_scope": "candidate + formula + this exact contract",
    }
