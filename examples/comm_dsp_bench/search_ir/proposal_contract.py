"""Proposer-neutral 的严格 JSON action-program 层（公开意图层）。

两类 proposer 共用同一份公开提案语言：

- LLM 臂直接产出 1–2 步语义意图的 JSON 文本；
- GP 臂把 ``actions.propose`` 的成功日志经 :func:`program_from_action_log`
  投影成同一语言。

公开意图只允许 ``{"kind", "path"}``（结构动作）或
``{"kind", "path", "value"}``（仅 ``change_interpolation``/``numeric``）。
RNG 状态、before/after、mode/direction、status 等抽样 provenance 不是公开
字段，出现即拒绝。执行时由本层基于中间候选树内部派生 before/after，并
复用 ``actions`` 的合法性内核（确定性结构默认值 ``_structure_after``、值域
``DOMAINS``、逐级 ``validate_candidate``），因此两类 proposer 的可达一步
邻域一致：结构动作的结果只能是确定性默认，数值 value 覆盖与 GP
jump/uniform/toggle 相同的值域；谁也无法借任意子树或指定抽样方式扩大
动作空间。

严格性：JSON 文本入口拒绝重复键与 ``NaN``/``Infinity`` 字面量（对象入口
无法携带重复键，等价保护由未知字段检查承担）；所有标量做严格类型检查
（拒绝 bool/float 冒充 int）；value 一律做值域检查；path 做语法检查，
语义合法性（目标存在、属于该动作的目标集合）在执行的中间树上检查——
``formula_version``/``contract_version`` 等契约字段不在任何动作的目标
集合内，公开层无法触碰。

失败是结构化的（:class:`ProposalContractError` 的 ``code``/``index``），
从不重采样；提案预算由调用者在调用 parse/apply 之前计费。
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .actions import (
    DOMAINS,
    INTERPOLATIONS,
    STRUCTURE_KINDS,
    _apply,
    _get,
    _numeric_paths,
    _structure_after,
    _structure_paths,
    ActionError,
)
from .validate import IRValidationError, validate_candidate


NUMERIC_KIND = "numeric"
VALUE_KINDS = ("change_interpolation", NUMERIC_KIND)
PUBLIC_KINDS = (*STRUCTURE_KINDS, NUMERIC_KIND)
_INTENT_KEYS = frozenset({"kind", "path", "value"})

# 内部派生的数值抽样口径，只为满足 actions._apply 的回放校验；对公开层
# 不可见，提案人不得指定。jump/uniform/toggle 的可达值域与公开 value 语义
# 完全一致，GP 的 neighbor/direction 属于其抽样 provenance，不进入公开层。
_TOGGLE_FIELDS = ("rounding", "product_rounding")
_UNIFORM_FIELDS = ("accumulator_bits",)


class ProposalContractError(ValueError):
    """公开提案层拒绝或执行失败；结构化携带 code/index，不重采样。"""

    def __init__(self, code: str, message: str, index: int | None = None,
                 detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.index = index
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "index": self.index, "detail": self.detail}


def _load_json(payload: Any) -> Any:
    if isinstance(payload, (str, bytes, bytearray)):
        try:
            text = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else payload
        except UnicodeDecodeError as exc:
            raise ProposalContractError("not_json", f"输入不是 UTF-8 文本：{exc}") from exc
        try:
            return json.loads(
                text,
                object_pairs_hook=lambda pairs: _reject_duplicate_keys(pairs),
                parse_constant=_reject_constant,
            )
        except json.JSONDecodeError as exc:
            raise ProposalContractError("not_json", f"JSON 解析失败：{exc}") from exc
    return payload


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise ProposalContractError(
                "duplicate_key", f"JSON 对象出现重复键：{key!r}")
        seen.add(key)
    return dict(pairs)


def _reject_constant(token: str) -> None:
    raise ProposalContractError(
        "non_finite_number", f"JSON 含非有限数值字面量：{token}")


def _field_of(path: str) -> str:
    return path.rsplit("/", 1)[1]


def _fail_schema(message: str, index: int | None = None,
                 detail: Any = None) -> None:
    raise ProposalContractError("schema", message, index=index, detail=detail)


def _validate_intent(intent: Any, index: int) -> dict[str, Any]:
    if not isinstance(intent, dict):
        _fail_schema(f"第 {index + 1} 个意图必须是 JSON 对象", index)
    unknown = sorted(set(intent) - _INTENT_KEYS)
    if unknown:
        _fail_schema(
            f"第 {index + 1} 个意图含未知字段 {unknown}；公开层只允许 kind/path/value",
            index, {"unknown_fields": unknown})
    for required in ("kind", "path"):
        if required not in intent:
            _fail_schema(f"第 {index + 1} 个意图缺少字段 {required}", index)
    kind, path = intent["kind"], intent["path"]
    if type(kind) is not str or kind not in PUBLIC_KINDS:
        _fail_schema(f"第 {index + 1} 个意图 kind 非法：{kind!r}", index)
    if (type(path) is not str or not path.startswith("/")
            or any(segment == "" for segment in path[1:].split("/"))):
        _fail_schema(f"第 {index + 1} 个意图 path 非法：{path!r}", index)
    if kind not in VALUE_KINDS:
        if "value" in intent:
            _fail_schema(f"结构意图 {kind} 不接受 value（结果由确定性规则生成）", index)
        return {"kind": kind, "path": path}
    if "value" not in intent:
        _fail_schema(f"意图 {kind} 必须携带标量 value", index)
    value = intent["value"]
    if kind == "change_interpolation":
        if type(value) is not str or value not in INTERPOLATIONS:
            _fail_schema(
                f"change_interpolation 的 value 必须是 {INTERPOLATIONS} 之一", index)
        if _field_of(path) != "interpolation":
            _fail_schema("change_interpolation 的 path 必须以 interpolation 结尾", index)
        return {"kind": kind, "path": path, "value": value}
    field = _field_of(path)
    if field not in DOMAINS:
        _fail_schema(f"数值意图的字段名不在动作集合内：{field!r}", index)
    values = DOMAINS[field]
    expected = str if field in _TOGGLE_FIELDS else int
    if type(value) is not expected:
        _fail_schema(
            f"{field} 的 value 必须是 {expected.__name__}（拒绝 bool/float 等类型别名）",
            index)
    if value not in values:
        _fail_schema(f"{field} 的 value {value!r} 越界；合法值域 {list(values)}", index)
    return {"kind": kind, "path": path, "value": value}


def parse_program(payload: Any) -> list[dict[str, Any]]:
    """严格解析公开提案；接受 JSON 文本或已解码对象，返回规范化意图列表。"""
    data = _load_json(payload)
    if not isinstance(data, list) or len(data) not in (1, 2):
        raise ProposalContractError("schema", "程序必须是恰含 1–2 个意图的 JSON 数组")
    return [_validate_intent(intent, index) for index, intent in enumerate(data)]


def program_to_json(program: Any) -> str:
    """规范化序列化；同一程序反复 encode/decode 结果逐字节稳定。"""
    return json.dumps(parse_program(program), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def program_from_action_log(action_log: Any) -> list[dict[str, Any]]:
    """GP adapter：把 actions.propose 的成功日志投影成公开程序。

    只保留 kind/path（结构动作）与 kind/path/after（change_interpolation、
    numeric）；family、before、after、mode、direction、rng_*、status 全部
    丢弃——它们是抽样 provenance，不属于公开语义。
    """
    if not isinstance(action_log, list) or len(action_log) not in (1, 2):
        raise ProposalContractError("action_log", "动作日志必须恰含 1–2 步")
    program: list[dict[str, Any]] = []
    for index, log in enumerate(action_log):
        if not isinstance(log, dict) or log.get("status") != "ok":
            raise ProposalContractError(
                "action_log", f"第 {index + 1} 步不是成功动作日志", index=index)
        kind, path = log.get("kind"), log.get("path")
        if type(kind) is not str or kind not in PUBLIC_KINDS or type(path) is not str:
            raise ProposalContractError(
                "action_log", f"第 {index + 1} 步 kind/path 非法", index=index)
        intent: dict[str, Any] = {"kind": kind, "path": path}
        if kind in VALUE_KINDS:
            intent["value"] = log.get("after")
        program.append(intent)
    return parse_program(program)


def apply_program(candidate: dict[str, Any], program: Any) -> dict[str, Any]:
    """在中间候选树上顺序执行公开程序；返回新候选，不修改输入。"""
    intents = parse_program(program)
    if not isinstance(candidate, dict):
        raise ProposalContractError("base_candidate", "基础候选必须是 IR 对象")
    try:
        validate_candidate(candidate)
        json.dumps(candidate, allow_nan=False)
    except (IRValidationError, TypeError, ValueError) as exc:
        raise ProposalContractError("base_candidate", f"基础候选非法：{exc}") from exc
    tree = deepcopy(candidate)
    for index, intent in enumerate(intents):
        _apply_intent(tree, intent, index)
    return tree


def _apply_intent(tree: dict[str, Any], intent: dict[str, Any], index: int) -> None:
    def fail(message: str, detail: Any = None) -> None:
        raise ProposalContractError(
            "apply", f"第 {index + 1} 步失败：{message}", index=index, detail=detail)

    kind, path = intent["kind"], intent["path"]
    allowed = (_numeric_paths(tree) if kind == NUMERIC_KIND
               else _structure_paths(tree, kind))
    if path not in allowed:
        fail(f"动作 {kind} 在当前中间树上没有目标 {path}",
             {"allowed": sorted(allowed)})
    before = deepcopy(_get(tree, path))
    log: dict[str, Any] = {
        "kind": kind,
        "family": "numeric" if kind == NUMERIC_KIND else "structure",
        "path": path,
        "before": before,
        "status": "ok",
    }
    if kind in VALUE_KINDS:
        log["after"] = intent["value"]
        if kind == NUMERIC_KIND:
            field = _field_of(path)
            log["mode"] = ("toggle" if field in _TOGGLE_FIELDS
                           else "uniform" if field in _UNIFORM_FIELDS else "jump")
    else:
        log["after"] = _structure_after(kind, before)
    try:
        _apply(tree, log)
    except (ActionError, IRValidationError, KeyError, TypeError, ValueError) as exc:
        fail(str(exc))
