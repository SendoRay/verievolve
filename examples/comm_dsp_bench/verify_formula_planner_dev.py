#!/usr/bin/env python3
"""Verify one development LLM plan with model/RTL, chain quality, and synthesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np


BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import ref_chain
from search_ir.canonicalize import candidate_hash
from search_ir.evaluate import evaluate_candidate, prepare_case
from search_ir.lower_rtl import lower_ddc_rtl
from search_ir.rtl_verify import verify_candidate_rtl
from search_ir import synthesize
from search_ir.verification_status import synthesis_status, verification_status


def _development_case():
    n = np.arange(128)
    fcw = 0x31415927
    theta = 2 * np.pi * fcw * n / (1 << 32)
    desired = 0.2 * np.exp(1j * theta)
    x = desired + 0.001 * np.exp(0.13j * n)
    i = np.rint(x.real * 2048).astype(np.int64)
    q = np.rint(x.imag * 2048).astype(np.int64)
    return prepare_case("public-synthetic-tone-v1", i, q, fcw, desired, n_pre_out=16)


def _write_new(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = (ROOT / args.run_dir).resolve()
    run_dir.relative_to(ROOT)
    manifest = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "development_only" or manifest["result"]["status"] != "success":
        raise SystemExit("run is not a successful development-only plan")
    candidate = json.loads((run_dir / "candidate.json").read_text(encoding="utf-8"))
    expected_hash = manifest["result"]["compile_result"]["candidate_sha256"]
    if candidate_hash(candidate) != expected_hash:
        raise SystemExit("candidate identity mismatch")
    rtl = lower_ddc_rtl(candidate)
    if (run_dir / "design.v").read_text(encoding="utf-8") != rtl:
        raise SystemExit("RTL identity mismatch")

    rtl_result = verify_candidate_rtl(candidate, run_dir / "rtl_verification")
    quality = evaluate_candidate(candidate, [_development_case()])
    _write_new(run_dir / "quality.json", quality)

    synthesis_root = run_dir / "mapped_synthesis"
    synthesis_root.mkdir(exist_ok=False)
    contract = synthesize.build_contract()
    shutil.copyfile(contract["liberty"]["path"], synthesis_root / "cells.lib")
    contract_sha = synthesize._digest(contract)
    rtl_sha = hashlib.sha256(rtl.encode()).hexdigest()
    binding = {
        "scope": "formula-to-rtl-development-only",
        "candidate_hash": expected_hash,
        "rtl_sha256": rtl_sha,
        "contract_sha256": contract_sha,
    }
    _write_new(synthesis_root / "manifest.json", {
        "binding": binding, "contract": contract,
        "note": "development-only mapped area; not a formal comparison",
    })
    mapped = synthesize.run_job(
        synthesis_root / "job", binding, contract, rtl,
        synthesize.liberty_areas((synthesis_root / "cells.lib").read_text()),
    )
    mapped_status = synthesis_status(mapped)
    overall_status = verification_status(
        rtl=rtl_result["status"], quality=quality["status"], synthesis=mapped_status,
    )
    summary = {
        "status": overall_status,
        "scope": "development-only; no LLM advantage claim",
        "candidate_sha256": expected_hash,
        "rtl_verification": rtl_result,
        "quality": {
            "status": quality["status"], "Q_dev": quality["Q_dev"],
            "fir_mask": quality["fir_mask"],
        },
        "synthesis": {
            "status": mapped_status, "area_um2": mapped["area_um2"],
            "num_cells": mapped.get("num_cells"),
            "timed_out": mapped.get("process", {}).get("timed_out", False),
            "result_path": "mapped_synthesis/job/result.json",
        },
    }
    _write_new(run_dir / "verification.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return {"ok": 0, "inconclusive": 3, "failed": 2}[summary["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
