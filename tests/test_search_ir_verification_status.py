from __future__ import annotations

from pathlib import Path
import sys


BENCH = Path(__file__).resolve().parents[1] / "examples/comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.formula_contract import ddc_formula_request
from search_ir.verification_status import (
    quality_requirement_status,
    synthesis_status,
    verification_status,
)


def test_synthesis_timeout_is_not_a_design_failure():
    raw = {
        "status": "failed",
        "area_um2": None,
        "process": {"returncode": -9, "timed_out": True, "wall_seconds": 600.0},
    }
    assert synthesis_status(raw) == "timeout"
    assert verification_status(
        rtl="ok",
        quality_measurement="ok",
        quality_requirement="satisfied",
        synthesis="timeout",
    ) == "inconclusive"


def test_successful_mapping_completes_verification():
    assert synthesis_status({"status": "ok", "process": {"timed_out": False}}) == "ok"
    assert verification_status(
        rtl="ok",
        quality_measurement="ok",
        quality_requirement="satisfied",
        synthesis="ok",
    ) == "ok"


def test_real_failures_remain_failures():
    assert synthesis_status({"status": "failed", "process": {"timed_out": False}}) == "failed"
    assert verification_status(
        rtl="failed",
        quality_measurement="ok",
        quality_requirement="satisfied",
        synthesis="ok",
    ) == "failed"
    assert verification_status(
        rtl="ok",
        quality_measurement="failed",
        quality_requirement="measurement_failed",
        synthesis="ok",
    ) == "failed"
    assert verification_status(
        rtl="ok",
        quality_measurement="ok",
        quality_requirement="not_satisfied",
        synthesis="ok",
    ) == "failed"
    assert verification_status(
        rtl="ok",
        quality_measurement="ok",
        quality_requirement="satisfied",
        synthesis="failed",
    ) == "failed"


def test_quality_measurement_is_distinct_from_requirement_satisfaction():
    formula = ddc_formula_request(max_aligned_nmse=1e-5)
    metadata = {
        "scope": "development-only; not Q_main or an S/R gate",
        "evidence_role": "development_only",
    }
    passing = quality_requirement_status(
        formula, {"status": "ok", "Q_dev": 1e-5, **metadata}
    )
    failing = quality_requirement_status(
        formula, {"status": "ok", "Q_dev": 1.01e-5, **metadata}
    )
    missing = quality_requirement_status(
        formula, {"status": "mask_failed", "Q_dev": None, **metadata}
    )
    deployment = quality_requirement_status(
        formula,
        {
            "status": "ok",
            "Q_dev": 1e-5,
            "scope": "frozen-ddc-chain",
            "evidence_role": "deployment_acceptance",
        },
    )
    assert passing["requirement_status"] == "satisfied"
    assert passing["measurement_status"] == "ok"
    assert passing["evidence_role"] == "development_only"
    assert passing["deployment_acceptance"] is False
    assert deployment["deployment_acceptance"] is True
    assert failing["requirement_status"] == "not_satisfied"
    assert missing["requirement_status"] == "measurement_failed"
