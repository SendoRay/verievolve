"""固定开发用例的 DDC 评价；不运行正式场景或推断部署可行性。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from chains.ddc import candidates, metrics, ref_chain, spec

from .canonicalize import candidate_hash
from .lower_bittrue import emulate_ddc_candidate, resolve_fir_coefficients
from .validate import validate_candidate


class EvaluationError(ValueError):
    """开发评价的输入、输出或覆盖范围不满足要求。"""


@dataclass(frozen=True)
class DevCase:
    """显式准备的开发输入；reference 与候选共享量化 ADC 输入。"""

    case_id: str
    i12: np.ndarray
    q12: np.ndarray
    fcw: int
    desired_input: np.ndarray
    y_ref: np.ndarray
    y_des_ref: np.ndarray
    output_indices: np.ndarray
    n_pre_out: int


def array_identity(value: np.ndarray) -> dict[str, Any]:
    array = np.ascontiguousarray(value)
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
    }


def _vector(value: Any, label: str, integer: bool = False) -> np.ndarray:
    array = np.asarray(value)
    kinds = "iu" if integer else "iufc"
    if array.ndim != 1 or array.size == 0 or array.dtype.kind not in kinds:
        raise EvaluationError(f"{label}: 需要非空的一维{'整数' if integer else '数值'}数组")
    if not np.all(np.isfinite(array)):
        raise EvaluationError(f"{label}: 含非有限值")
    # 码字/tag 保留整数；信号能量与相关积必须在浮点域计算，避免整数静默溢出。
    return array if integer else array.astype(np.complex128, copy=False)


def _input_vectors(i12: np.ndarray, q12: np.ndarray, fcw: int) -> None:
    i = _vector(i12, "i12", integer=True)
    q = _vector(q12, "q12", integer=True)
    if len(i) != len(q) or len(i) <= spec.N_TAPS:
        raise EvaluationError("ADC 输入必须等长且长于 FIR 预热段")
    if any(np.any((x < -2048) | (x > 2047)) for x in (i, q)):
        raise EvaluationError("ADC 输入超出 Q1.11 范围")
    if type(fcw) is not int or not 0 <= fcw <= 0xFFFFFFFF:
        raise EvaluationError("fcw 必须为无符号 32 位整数")


def _ideal_output(x: np.ndarray, fcw: int) -> np.ndarray:
    f_mhz = fcw * spec.FS_IN / (1 << spec.W_P_ACC) / 1e6
    mixed = ref_chain.mixer_ideal(x, f_mhz, len(x))
    return ref_chain.fir_float(mixed, ref_chain.prototype_taps())[::spec.R]


def prepare_case(
    case_id: str, i12: np.ndarray, q12: np.ndarray, fcw: int,
    desired_input: np.ndarray, n_pre_out: int,
) -> DevCase:
    """从调用者提供的合成输入构造 reference；不生成 witness 场景。"""
    _input_vectors(i12, q12, fcw)
    desired = _vector(desired_input, "desired_input")
    if len(desired) != len(i12):
        raise EvaluationError("desired_input 与 ADC 输入必须等长")
    i, q = np.array(i12, copy=True), np.array(q12, copy=True)
    desired = np.array(desired, copy=True)
    adc = (i.astype(np.float64) + 1j * q.astype(np.float64)) / (1 << 11)
    case = DevCase(
        case_id, i, q, fcw, desired, _ideal_output(adc, fcw),
        _ideal_output(desired, fcw),
        np.arange(spec.N_TAPS - 1, len(i), spec.R, dtype=np.int64), n_pre_out,
    )
    validate_case(case)
    return case


def _validate_segments(y_ref: np.ndarray, y_des: np.ndarray, n_pre: int) -> None:
    if type(n_pre) is not int or not 0 < n_pre < len(y_ref):
        raise EvaluationError("n_pre_out 必须分隔非空前导段与测量段")
    if len(y_ref) != len(y_des):
        raise EvaluationError("reference 与 desired reference 必须等长")
    with np.errstate(over="raise", invalid="raise"):
        energy = float(np.sum(np.abs(y_ref[:n_pre]) ** 2))
        power = float(np.mean(np.abs(y_des[n_pre:]) ** 2))
    if not np.isfinite(energy) or not np.isfinite(power) or energy <= 0 or power <= 0:
        raise EvaluationError("参考前导能量与 desired-only 测量功率必须有限且为正")


def validate_case(case: DevCase) -> None:
    if not isinstance(case.case_id, str) or not case.case_id.strip():
        raise EvaluationError("case_id 必须是非空字符串")
    _input_vectors(case.i12, case.q12, case.fcw)
    desired = _vector(case.desired_input, "desired_input")
    ref = _vector(case.y_ref, "y_ref")
    des = _vector(case.y_des_ref, "y_des_ref")
    tags = _vector(case.output_indices, "output_indices", integer=True)
    expected_tags = np.arange(spec.N_TAPS - 1, len(case.i12), spec.R)
    if not np.array_equal(tags, expected_tags) or len(ref) != len(tags):
        raise EvaluationError("reference 的 sequence tags 不符合 valid FIR / phase-0 R=2")
    if len(desired) != len(case.i12):
        raise EvaluationError("desired_input 与 ADC 输入必须等长")
    _validate_segments(ref, des, case.n_pre_out)
    adc = (case.i12.astype(np.float64) + 1j * case.q12.astype(np.float64)) / (1 << 11)
    if not np.array_equal(ref, _ideal_output(adc, case.fcw)):
        raise EvaluationError("reference 与当前 ADC 输入/FCW/原型 FIR 不匹配")
    if not np.array_equal(des, _ideal_output(desired, case.fcw)):
        raise EvaluationError("desired reference 与当前 desired 输入不匹配")


def case_identity(case: DevCase) -> dict[str, Any]:
    validate_case(case)
    return {
        "case_id": case.case_id,
        "fcw": case.fcw,
        "n_pre_out": case.n_pre_out,
        **{field: array_identity(getattr(case, field)) for field in (
            "i12", "q12", "desired_input", "y_ref", "y_des_ref", "output_indices"
        )},
    }


def score_outputs(
    y_ref: np.ndarray, y_candidate: np.ndarray, y_des_ref: np.ndarray, n_pre_out: int,
) -> dict[str, float]:
    """只在前导估计增益；拒绝无效线性质量，不序列化零误差的 -inf dB。"""
    ref = _vector(y_ref, "y_ref")
    got = _vector(y_candidate, "y_candidate")
    desired = _vector(y_des_ref, "y_des_ref")
    if len(ref) != len(got):
        raise EvaluationError("候选与 reference 输出长度不一致")
    _validate_segments(ref, desired, n_pre_out)
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        scored = metrics.aligned_impl_error(ref, got, n_pre_out, y_des_ref=desired)
    result = {
        "q_raw": scored["err_raw"], "q_aligned": scored["err_aligned"],
        "gain_re": scored["gain_re"], "gain_im": scored["gain_im"],
        "desired_power": scored["p_ref"],
    }
    if not all(np.isfinite(v) for v in result.values()):
        raise EvaluationError("质量评价返回非有限值")
    if result["q_raw"] < 0 or result["q_aligned"] < 0:
        raise EvaluationError("线性实现误差不得为负")
    return result


def aggregate_rows(rows: Sequence[Mapping[str, Any]], expected_ids: Sequence[str]) -> float:
    ids = [row["case_id"] for row in rows]
    if (not expected_ids or len(set(expected_ids)) != len(expected_ids)
            or len(set(ids)) != len(ids) or set(ids) != set(expected_ids)):
        raise EvaluationError("开发 case 覆盖不完整或含重复/额外 case")
    values = [row["q_aligned"] for row in rows]
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not np.isfinite(v) or v < 0 for v in values):
        raise EvaluationError("聚合质量必须为有限非负线性值")
    return float(max(values))


def evaluate_candidate(candidate: Mapping[str, Any], cases: Sequence[DevCase]) -> dict:
    """评价单个 IR，结果仅属于本次固定开发 case 集。"""
    validate_candidate(candidate)
    ids = [case.case_id for case in cases]
    if not ids or len(set(ids)) != len(ids):
        raise EvaluationError("开发 case 集为空或包含重复 ID")
    for case in cases:
        validate_case(case)
    hq = resolve_fir_coefficients(candidate["filter_decimator"])
    mask = candidates.check_fir_mask(hq, ref_chain.prototype_taps())
    result = {
        "schema_version": "search-ir-dev-evaluation-v1",
        "candidate_hash": candidate_hash(candidate),
        "scope": "development-only; not Q_main or an S/R gate",
        "evidence_role": "development_only",
        "coefficients": {"values": hq.tolist(), **array_identity(hq)},
        "fir_mask": mask,
        "deployment_feasibility": "pending" if mask["legal"] else "failed",
        "saturation_scope": {
            "mixer": "all accepted input samples; real+imag output clipping events",
            "fir": "retained valid decimated outputs; real+imag accumulator+output clipping events",
            "includes_preamble": True,
            "legacy_fir_count_compatible": False,
            "formal_saturation_gate": "pending",
        },
        "area": {"status": "unavailable", "scope": "full-DDC", "value_um2": None,
                 "reason": "development stage does not synthesize"},
        "rows": [], "Q_dev": None,
    }
    if not mask["legal"]:
        return {**result, "status": "mask_failed"}
    for case in cases:
        got = emulate_ddc_candidate(candidate, case.i12, case.q12, case.fcw)
        tags = _vector(got["output_indices"], "candidate output_indices", integer=True)
        if not np.array_equal(tags, case.output_indices):
            raise EvaluationError("候选输出 sequence tags 与 reference 不一致")
        re = _vector(got["y_re"], "candidate y_re", integer=True)
        im = _vector(got["y_im"], "candidate y_im", integer=True)
        if len(re) != len(tags) or len(im) != len(tags):
            raise EvaluationError("候选输出长度与 sequence tags 不一致")
        if any(np.any((x < -32768) | (x > 32767)) for x in (re, im)):
            raise EvaluationError("候选输出超出 Q1.15")
        scored = score_outputs(case.y_ref, (re + 1j * im) / (1 << 15),
                               case.y_des_ref, case.n_pre_out)
        counts = {key: got[key] for key in ("n_sat_mix", "n_sat_fir")}
        if any(type(v) is not int or v < 0 for v in counts.values()):
            raise EvaluationError("饱和计数必须是非负整数")
        result["rows"].append({
            "case_id": case.case_id, "case_identity": case_identity(case),
            "n_samples": len(re) - case.n_pre_out, **scored, **counts,
        })
    result["Q_dev"] = aggregate_rows(result["rows"], ids)
    return {**result, "status": "ok"}


def project_feedback(result: Mapping[str, Any], mode: str, q_budget: float) -> dict:
    """开发接口的单向信息投影；完整搜索器的隔离仍须后续 R5 验收。"""
    if mode not in ("numerical", "satisfaction"):
        raise ValueError("unknown feedback mode")
    if isinstance(q_budget, bool) or not np.isfinite(q_budget) or q_budget <= 0:
        raise ValueError("q_budget 必须有限且为正")
    if result["status"] != "ok":
        return {"status": "failed"}
    rows = result["rows"]
    q = aggregate_rows(rows, [row["case_id"] for row in rows])
    if q != result["Q_dev"]:
        raise EvaluationError("Q_dev 与逐 case 质量不一致")
    if mode == "satisfaction":
        return {"status": "ok", "pass_count": sum(r["q_aligned"] <= q_budget for r in rows),
                "case_count": len(rows)}
    return {"status": "ok", "Q_dev": q}
