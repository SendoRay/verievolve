"""无缓存、无恢复、无搜索器的固定 fixture 开发运行记录。"""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import scipy

from chains.ddc import ref_chain

from .canonicalize import candidate_hash, canonical_json
from .evaluate import (
    DevCase, EvaluationError, aggregate_rows, array_identity, case_identity, evaluate_candidate,
)
from .validate import validate_candidate


BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parent.parent
THRESHOLD_SOURCE = BENCH / "experiments_system/ddc_witness_v1/preflight_manifest.json"
_SOURCE_PATHS = [
    BENCH / "numeric_semantics.py",
    *(BENCH / "search_ir" / name for name in (
        "__init__.py", "schema.py", "validate.py", "canonicalize.py",
        "lower_bittrue.py", "lower_rtl.py", "evaluate.py", "dev_run.py", "dev_fixtures.py",
    )),
    *(BENCH / "chains/ddc" / name for name in (
        "__init__.py", "spec.py", "fixed_chain.py", "ref_chain.py", "scenarios.py",
        "metrics.py", "candidates.py", "rtl_gen.py",
    )),
    BENCH / "certfit/tpl_cordic.py", BENCH / "design_gen.py",
]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _file_identity(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _source_fingerprints() -> list[dict]:
    return [_file_identity(path) for path in _SOURCE_PATHS]


# 已加载代码的文件身份；运行中改源码必须在新进程里重新导入，不沿用旧函数。
_LOADED_SOURCES = _source_fingerprints()


def _thresholds() -> dict:
    document = json.loads(THRESHOLD_SOURCE.read_text(encoding="utf-8"))
    calibration = document["quality_contract"]["calibration"]
    values = {key: calibration[key] for key in ("q_budget", "q_cal", "epsilon_q")}
    if any(type(v) not in (int, float) or not np.isfinite(v) or v < 0
           for v in values.values()) or values["q_budget"] <= 0:
        raise EvaluationError("历史质量阈值必须是有限合法数值")
    if values["epsilon_q"] != max(values["q_cal"], 0.1 * values["q_budget"]):
        raise EvaluationError("历史 epsilon_Q 与校准定义不一致")
    return {"values": values, "source": _file_identity(THRESHOLD_SOURCE),
            "use": "development feedback only; no formal gate decision"}


def build_context(cases: Sequence[DevCase]) -> dict:
    """计算身份不包含 run/attempt ID，也不包含反向引用此身份的 RTL。"""
    identities = [case_identity(case) for case in cases]
    ids = [item["case_id"] for item in identities]
    if not ids or len(set(ids)) != len(ids):
        raise EvaluationError("固定开发用例集为空或有重复 ID")
    sources = _source_fingerprints()
    if sources != _LOADED_SOURCES:
        raise EvaluationError("源码在导入后发生变化，请在新进程中运行")
    return {
        "schema_version": "search-ir-dev-context-v1",
        "scope": "fixed development fixtures only",
        "cases": identities,
        "sources": sources,
        "protocols": [_file_identity(ROOT / "thesis" / name) for name in (
            "CONTRACT_DDC_v1.md", "WITNESS_FROZEN_DDC_v1.md",
        )],
        "prototype_coefficients": array_identity(ref_chain.prototype_taps()),
        "quality": {
            "definition": "aligned sample-domain implementation NMSE; desired-only denominator",
            "aggregation": "max over exactly the declared development cases",
            "alignment": "prefix-only LS complex gain; no shift search",
            "sample_mapping": "33-tap valid FIR; phase-0 R=2; initial accumulator=0",
            "thresholds": _thresholds(),
        },
        "environment": {"python": sys.version, "numpy": np.__version__,
                        "scipy": scipy.__version__, "platform": platform.platform()},
        "cache_enabled": False, "resume_enabled": False, "proposer_enabled": False,
        "formal_truth_allowed": False, "synthesis_enabled": False,
    }


def _write_new(path: Path, value: Any) -> None:
    text = _json(value)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text + "\n")


def _strict_json(raw: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"重复 JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"JSON 不允许 {value}")

    def floating(value):
        number = float(value)
        if not np.isfinite(number):
            raise ValueError("JSON 浮点数溢出")
        return number

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant,
                      parse_float=floating)


class DevRun:
    """单进程、单写者开发运行；每次 submit 恰占用一次提案预算。"""

    def __init__(self, output_root: Path, run_id: str, cases: Sequence[DevCase],
                 *, max_attempts: int):
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
            raise ValueError("非法 run_id")
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts 必须是正整数")
        self._cases = copy.deepcopy(tuple(cases))
        self._context = build_context(self._cases)
        self._context_hash = _digest(self._context)
        self._run_id = run_id
        self._max_attempts = max_attempts
        self._attempts = 0
        self._failed = False
        self.path = Path(output_root) / run_id
        historical = BENCH / "experiments_system"
        if self.path.resolve().is_relative_to(historical.resolve()):
            raise ValueError("开发运行不能写入历史 experiments_system 产物目录")
        self.path.mkdir(parents=True, exist_ok=False)
        inputs = []
        for index, case in enumerate(self._cases):
            name = f"input-{index:03d}.npz"
            with (self.path / name).open("xb") as handle:
                np.savez(handle, **{field: getattr(case, field) for field in (
                    "i12", "q12", "desired_input", "y_ref", "y_des_ref", "output_indices"
                )})
            inputs.append({"case_id": case.case_id, "path": name,
                           "sha256": hashlib.sha256((self.path / name).read_bytes()).hexdigest()})
        self._inputs = inputs
        manifest = {"schema_version": "search-ir-dev-run-v1", "run_id": run_id,
                    "context_sha256": self._context_hash, "context": self._context,
                    "max_attempts": max_attempts, "inputs": inputs}
        _write_new(self.path / "manifest.json", manifest)
        self._manifest_digest = hashlib.sha256((self.path / "manifest.json").read_bytes()).hexdigest()
        (self.path / "attempts.jsonl").touch(exist_ok=False)

    def _event(self, value: dict) -> None:
        with (self.path / "attempts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(_json(value) + "\n")
            handle.flush()

    def _check_context(self) -> None:
        if _digest(build_context(self._cases)) != self._context_hash:
            raise EvaluationError("运行上下文身份漂移")
        if hashlib.sha256((self.path / "manifest.json").read_bytes()).hexdigest() != self._manifest_digest:
            raise EvaluationError("运行 manifest 被修改")
        for item in self._inputs:
            if hashlib.sha256((self.path / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
                raise EvaluationError("开发输入快照发生漂移")

    def submit(self, raw_proposal: str) -> dict:
        if self._failed:
            raise RuntimeError("上下文或执行异常后运行已封闭；不支持恢复，请使用新 run_id")
        if not isinstance(raw_proposal, str):
            raise TypeError("submit 只接受原始 JSON 文本")
        if self._attempts >= self._max_attempts:
            raise RuntimeError("提案预算已用完")
        self._attempts += 1
        attempt_id = self._attempts
        envelope = {"run_id": self._run_id, "attempt_id": attempt_id,
                    "context_sha256": self._context_hash}
        try:
            self._event({**envelope, "event": "attempt_started", "budget_units": 1,
                         "raw_proposal": raw_proposal})
        except BaseException:
            self._failed = True
            raise
        stage = "context"
        identity = None
        try:
            self._check_context()
            stage = "parse"
            candidate = _strict_json(raw_proposal)
            stage = "validate"
            validate_candidate(candidate)
            identity = candidate_hash(candidate)
            stage = "persist_candidate"
            _write_new(self.path / f"candidate-{attempt_id:04d}.json",
                       json.loads(canonical_json(candidate)))
            stage = "evaluate"
            evaluation = evaluate_candidate(candidate, self._cases)
            if evaluation["candidate_hash"] != identity:
                raise EvaluationError("评价回显的 candidate hash 不匹配")
            if evaluation["status"] not in ("ok", "mask_failed"):
                raise EvaluationError("评价器返回未知状态")
            if evaluation["status"] == "ok":
                # 校验逐行输入身份和完整覆盖，避免错误 adapter 回传别的 case。
                actual = [row["case_identity"] for row in evaluation["rows"]]
                if actual != self._context["cases"]:
                    raise EvaluationError("评价回显的开发输入身份不匹配")
                q = aggregate_rows(evaluation["rows"], [c.case_id for c in self._cases])
                if q != evaluation["Q_dev"] or evaluation["fir_mask"]["legal"] is not True:
                    raise EvaluationError("聚合质量或 FIR mask 状态不一致")
            elif (evaluation["Q_dev"] is not None or evaluation["rows"]
                  or evaluation["fir_mask"]["legal"] is not False):
                raise EvaluationError("mask 失败不应返回有效质量")
            stage = "context"
            self._check_context()
            result = {**envelope, "candidate_hash": identity,
                      "status": evaluation["status"], "evaluation": evaluation}
        except Exception as exc:
            if stage not in ("parse", "validate"):
                self._failed = True
            result = {**envelope, "candidate_hash": identity,
                      "status": "invalid_proposal" if stage in ("parse", "validate") else "evaluation_failed",
                      "stage": stage, "error_type": type(exc).__name__, "error": str(exc)}
        except BaseException:
            self._failed = True
            raise
        # I/O 失败不吞掉：started 记录及目录保留，下次同 run_id 仍拒绝重启。
        try:
            _write_new(self.path / f"result-{attempt_id:04d}.json", result)
            self._event({**envelope, "event": "attempt_finished", "budget_units": 0,
                         "candidate_hash": identity, "status": result["status"]})
        except BaseException:
            self._failed = True
            raise
        return result
