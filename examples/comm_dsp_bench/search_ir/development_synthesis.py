"""Real Nangate45 area adapter for a development planning archive."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from . import synthesize as synth
from .canonicalize import candidate_hash
from .formula_contract import formula_hash, validate_formula_request
from .lower_rtl import lower_ddc_rtl
from .verification_status import synthesis_status


class DevelopmentSynthesisEvaluator:
    """Run each candidate in its own immutable job directory."""

    def __init__(self, run_root: Path, contract: Mapping[str, Any]) -> None:
        self.root = Path(run_root) / "synthesis"
        self.contract = deepcopy(dict(contract))
        synth._check_contract(self.contract)
        self.root.mkdir(exist_ok=False)
        with (self.root / "cells.lib").open("xb") as handle:
            handle.write(Path(self.contract["liberty"]["path"]).read_bytes())
        self.areas = synth.liberty_areas((self.root / "cells.lib").read_text())

    @classmethod
    def resume(cls, run_root: Path, contract: Mapping[str, Any]):
        self = cls.__new__(cls)
        self.root = Path(run_root) / "synthesis"
        self.contract = deepcopy(dict(contract))
        synth._check_contract(self.contract)
        if synth._sha((self.root / "cells.lib").read_bytes()) != self.contract["liberty"]["sha256"]:
            raise RuntimeError("synthesis Liberty snapshot drifted")
        self.areas = synth.liberty_areas((self.root / "cells.lib").read_text())
        return self

    def __call__(self, candidate: dict[str, Any], formula: dict[str, Any]) -> dict[str, Any]:
        request = validate_formula_request(formula)
        if request["requirements"]["cost"] != {
            "metric": "synthesis_area", "backend": "nangate45"
        }:
            raise ValueError("development synthesis supports Nangate45 area only")
        identity = candidate_hash(candidate)
        rtl = lower_ddc_rtl(candidate)
        binding = {
            "candidate_hash": identity,
            "formula_sha256": formula_hash(request),
            "rtl_sha256": synth._sha(rtl.encode("utf-8")),
            "contract_sha256": synth._digest(self.contract),
        }
        directory = self.root / identity
        if directory.exists():
            result_path = directory / "result.json"
            if not result_path.is_file():
                return {
                    "status": "failed",
                    "reason": "interrupted_synthesis_job",
                    "binding": binding,
                }
            row = json.loads(result_path.read_text())
            if row.get("binding") != binding:
                raise RuntimeError("existing synthesis job has a different identity")
        else:
            row = synth.run_job(
                directory, binding, self.contract, rtl, self.areas
            )
        status = synthesis_status(row)
        result = {
            "status": status,
            "binding": binding,
            "source": str(directory / "result.json"),
            "raw_status": row.get("status"),
            "process": deepcopy(row.get("process")),
        }
        if status == "ok":
            result.update({
                "area_um2": row["area_um2"],
                "num_cells": row["num_cells"],
                "cells_by_type": row["cells_by_type"],
                "netlist_semantic_sha256": row["netlist_semantic_sha256"],
            })
        else:
            result.update({
                "stage": row.get("stage"),
                "error_type": row.get("error_type"),
                "error": row.get("error"),
            })
        return result

