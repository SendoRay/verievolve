from __future__ import annotations

from pathlib import Path
import sys


BENCH = Path(__file__).resolve().parents[1] / "examples/comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.verification_status import synthesis_status, verification_status


def test_synthesis_timeout_is_not_a_design_failure():
    raw = {
        "status": "failed",
        "area_um2": None,
        "process": {"returncode": -9, "timed_out": True, "wall_seconds": 600.0},
    }
    assert synthesis_status(raw) == "timeout"
    assert verification_status(rtl="ok", quality="ok", synthesis="timeout") == "inconclusive"


def test_successful_mapping_completes_verification():
    assert synthesis_status({"status": "ok", "process": {"timed_out": False}}) == "ok"
    assert verification_status(rtl="ok", quality="ok", synthesis="ok") == "ok"


def test_real_failures_remain_failures():
    assert synthesis_status({"status": "failed", "process": {"timed_out": False}}) == "failed"
    assert verification_status(rtl="failed", quality="ok", synthesis="ok") == "failed"
    assert verification_status(rtl="ok", quality="failed", synthesis="ok") == "failed"
    assert verification_status(rtl="ok", quality="ok", synthesis="failed") == "failed"
