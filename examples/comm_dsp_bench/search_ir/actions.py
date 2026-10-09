"""两臂共享的有界 IR 动作；非法步骤不重采样，日志可严格回放。"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import numpy as np

from numeric_semantics import (
    FLOOR,
    NEAREST_TIES_TO_POS_INF,
    normalize_rounding_mode,
)

from .schema import cordic_sincos, lut_sincos, phasor_compose
from .validate import IRValidationError, validate_candidate


STRUCTURE_KINDS = (
    "swap_leaf", "change_interpolation", "wrap_compose", "unwrap_compose", "swap_fir",
)
INTERPOLATIONS = ("nearest", "linear", "quad")
DOMAINS = {
    "depth": (64, 128, 256, 512, 1024),
    "stages": tuple(range(7, 21)),
    "phase_bits": tuple(range(8, 17)),
    "split_bits": tuple(range(2, 15)),
    "coefficient_bits": tuple(range(8, 25)),
    "product_drop": tuple(range(9)),
    "accumulator_bits": (0, *range(20, 49)),
    "rounding": (NEAREST_TIES_TO_POS_INF, FLOOR),
    "product_rounding": (NEAREST_TIES_TO_POS_INF, FLOOR),
}
LEGACY_V1_DOMAINS = {
    **DOMAINS,
    "rounding": ("rne", "trunc"),
    "product_rounding": ("rne", "trunc"),
}
SEMANTIC_PROFILES = ("current", "legacy_v1")


class ActionError(ValueError):
    """动作或回放日志违反已声明规则。"""


def _pick(values, rng):
    if not values:
        raise ActionError("没有该动作可用的目标")
    return values[int(rng.integers(0, len(values)))]


def _get(tree: dict, path: str):
    if not isinstance(path, str) or not path.startswith("/"):
        raise ActionError("动作路径必须是绝对 JSON 字段路径")
    value = tree
    try:
        for key in path[1:].split("/"):
            value = value[key]
    except (KeyError, TypeError) as exc:
        raise ActionError(f"动作路径不存在：{path}") from exc
    return value


def _set(tree: dict, path: str, value) -> None:
    parent_path, key = path.rsplit("/", 1)
    parent = tree if not parent_path else _get(tree, parent_path)
    if not isinstance(parent, dict) or key not in parent:
        raise ActionError("动作只能替换已存在的字段或子树")
    parent[key] = deepcopy(value)


def _same(left, right) -> bool:
    # JSON 比较区分 bool/int/float，不能让类型别名绕过 before 校验。
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def _leaves(tree: dict) -> list[str]:
    if tree["nco"]["kind"] == "phasor_compose":
        return ["/nco/coarse", "/nco/residual"]
    return ["/nco"]


def _structure_paths(tree: dict, kind: str) -> list[str]:
    if kind == "swap_leaf":
        return _leaves(tree)
    if kind == "change_interpolation":
        return [path + "/interpolation" for path in _leaves(tree)
                if _get(tree, path)["kind"] == "lut_sincos"]
    if kind == "wrap_compose":
        return ["/nco"] if tree["nco"]["kind"] != "phasor_compose" else []
    if kind == "unwrap_compose":
        return ["/nco"] if tree["nco"]["kind"] == "phasor_compose" else []
    if kind == "swap_fir":
        return ["/filter_decimator"]
    raise ActionError(f"未知结构动作：{kind}")


def _domains(semantic_profile: str) -> dict:
    if semantic_profile not in SEMANTIC_PROFILES:
        raise ValueError(f"unknown semantic profile: {semantic_profile}")
    return LEGACY_V1_DOMAINS if semantic_profile == "legacy_v1" else DOMAINS


def _structure_after(kind: str, before, semantic_profile: str = "current"):
    if kind == "swap_leaf":
        if before["kind"] == "lut_sincos":
            return cordic_sincos(12, before["phase_bits"])
        return lut_sincos(256, "linear", before["phase_bits"])
    if kind == "wrap_compose":
        result = phasor_compose(
            before,
            cordic_sincos(12, 16),
            8,
            NEAREST_TIES_TO_POS_INF,
        )
        if semantic_profile == "legacy_v1":
            result["product_rounding"] = "rne"
        return result
    if kind == "unwrap_compose":
        return deepcopy(before["coarse"])
    if kind == "swap_fir":
        after = deepcopy(before)
        if before["kind"] == "direct_symmetric_fir_decimator":
            after.update(kind="polyphase_fir_decimator", phases=2)
        else:
            after["kind"] = "direct_symmetric_fir_decimator"
            del after["phases"]
        return after
    raise ActionError(f"没有确定性默认值的结构动作：{kind}")


def _numeric_paths(tree: dict) -> list[str]:
    paths = []
    for path in _leaves(tree):
        node = _get(tree, path)
        names = ("depth", "phase_bits") if node["kind"] == "lut_sincos" else ("stages", "phase_bits")
        paths.extend(f"{path}/{name}" for name in names)
    if tree["nco"]["kind"] == "phasor_compose":
        paths.extend(("/nco/split_bits", "/nco/product_rounding"))
    paths.extend(f"/filter_decimator/{name}" for name in (
        "coefficient_bits", "product_drop", "accumulator_bits", "rounding",
    ))
    return sorted(paths)


def _sample_step(
    tree: dict, rng, phase: str, log: dict, semantic_profile: str = "current"
) -> None:
    family = phase if phase != "mixed" else _pick(("structure", "numeric"), rng)
    log["family"] = family
    if family == "structure":
        kind = _pick(STRUCTURE_KINDS, rng)
        log["kind"] = kind
        log["path"] = _pick(_structure_paths(tree, kind), rng)
        before = deepcopy(_get(tree, log["path"]))
        log["before"] = before
        if kind == "change_interpolation":
            log["after"] = _pick([x for x in INTERPOLATIONS if x != before], rng)
        else:
            log["after"] = _structure_after(kind, before, semantic_profile)
        return
    log.update(kind="numeric", path=_pick(_numeric_paths(tree), rng))
    field = log["path"].rsplit("/", 1)[1]
    before = deepcopy(_get(tree, log["path"]))
    log["before"] = before
    values = _domains(semantic_profile)[field]
    if field in ("rounding", "product_rounding"):
        current = before if semantic_profile == "legacy_v1" else normalize_rounding_mode(before)
        log.update(mode="toggle", after=next(x for x in values if x != current))
    elif field == "accumulator_bits":
        log.update(mode="uniform", after=_pick([x for x in values if x != before], rng))
    elif rng.random() < 0.8:
        direction = int(_pick((-1, 1), rng))
        # 越界值也写进日志，随后整次提案失败，不重采样。
        after = (before * 2 if direction == 1 else before // 2) if field == "depth" else before + direction
        log.update(mode="neighbor", direction=direction, after=after)
    else:
        log.update(mode="jump", after=_pick([x for x in values if x != before], rng))


def _apply(tree: dict, log: dict, semantic_profile: str = "current") -> None:
    if log.get("status") == "error":
        raise ActionError("不能回放含失败步骤的提案")
    kind, path = log["kind"], log["path"]
    before, after = log["before"], log["after"]
    if not _same(_get(tree, path), before):
        raise ActionError(f"before 与当前树不一致：{path}")
    if kind in STRUCTURE_KINDS:
        if log.get("family") != "structure" or path not in _structure_paths(tree, kind):
            raise ActionError("结构动作与目标或动作族不一致")
        if kind == "change_interpolation":
            if not isinstance(after, str) or after not in INTERPOLATIONS or after == before:
                raise ActionError("插值切换必须选择另一合法类别")
        elif not _same(after, _structure_after(kind, before, semantic_profile)):
            raise ActionError("结构动作违反字段继承或固定默认值")
    elif kind == "numeric":
        if log.get("family") != "numeric" or path not in _numeric_paths(tree):
            raise ActionError("数值动作目标不在允许参数集合")
        field = path.rsplit("/", 1)[1]
        values = _domains(semantic_profile)[field]
        expected_type = str if field in ("rounding", "product_rounding") else int
        same_value = after == before
        if expected_type is str and type(after) is str and type(before) is str:
            same_value = normalize_rounding_mode(after) == normalize_rounding_mode(before)
        if type(after) is not expected_type or after not in values or same_value:
            raise ActionError("数值动作越界、类型错误或未改变参数")
        mode = log.get("mode")
        if expected_type is str:
            valid_mode = mode == "toggle"
        elif field == "accumulator_bits":
            valid_mode = mode == "uniform"
        elif mode == "neighbor":
            direction = log.get("direction")
            valid_mode = type(direction) is int and direction in (-1, 1) and values.index(after) - values.index(before) == direction
        else:
            valid_mode = mode == "jump"
        if not valid_mode:
            raise ActionError("数值动作不符合声明的抽样方式")
    else:
        raise ActionError(f"未知动作：{kind}")
    _set(tree, path, after)
    validate_candidate(tree)


def propose(
    candidate: dict,
    rng: np.random.Generator,
    phase: str,
    *,
    semantic_profile: str = "current",
) -> dict[str, Any]:
    """产生1或2步提案；任一步失败返回None，同时保留已经尝试的动作。"""
    if phase not in ("mixed", "structure", "numeric"):
        raise ValueError("phase 必须为 mixed/structure/numeric")
    _domains(semantic_profile)
    tree = deepcopy(candidate)
    actions = []
    try:
        validate_candidate(tree)
        json.dumps(tree, allow_nan=False)
    except (IRValidationError, TypeError, ValueError) as exc:
        return {"candidate": None, "actions": actions, "error": str(exc)}
    count = int(rng.integers(1, 3))
    for _ in range(count):
        log = {"kind": None, "family": None, "path": None, "before": None, "after": None,
               "rng_before": deepcopy(rng.bit_generator.state)}
        try:
            _sample_step(tree, rng, phase, log, semantic_profile)
            _apply(tree, log, semantic_profile)
            log["status"] = "ok"
        except (ActionError, IRValidationError) as exc:
            log.update(status="error", error=str(exc))
            log["rng_after"] = deepcopy(rng.bit_generator.state)
            actions.append(log)
            return {"candidate": None, "actions": actions, "error": str(exc)}
        log["rng_after"] = deepcopy(rng.bit_generator.state)
        actions.append(log)
    return {"candidate": tree, "actions": actions, "error": None}


def replay(
    candidate: dict, actions: list[dict], *, semantic_profile: str = "current"
) -> dict:
    """严格回放合法日志；不抽随机数，不接受改变契约的伪造patch。"""
    if not isinstance(actions, list) or len(actions) not in (1, 2):
        raise ActionError("回放必须恰有1或2个动作")
    tree = deepcopy(candidate)
    _domains(semantic_profile)
    validate_candidate(tree)
    for log in actions:
        if not isinstance(log, dict) or log.get("status") != "ok":
            raise ActionError("回放只接受成功动作日志")
        try:
            _apply(tree, log, semantic_profile)
        except (KeyError, TypeError, ValueError) as exc:
            raise ActionError(f"无效回放日志：{exc}") from exc
    return tree
