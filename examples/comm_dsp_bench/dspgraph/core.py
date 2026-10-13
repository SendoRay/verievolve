"""dspgraph 核心：积木（Block）协议、参数 schema、计划校验与通用运行器。

设计原则：
- 算子只登记一次（blocks/ 下一个类），之后任何链、任何实验、任何搜索方法都通过
  同一接口使用它；链与实验是数据，不写适配代码。
- 每个参数带角色标签：structure（算法结构）、precision（数值精度）、micro（微架构）。
  “分阶段设计”与“联合设计”的区别只在于按角色分阶段还是同时优化，因此命题 1
  在任何链上都有统一定义。
- 级间统一传递归一化数值（Q1.(W-1) 码 / 2^(W-1)），任何一块都可单独切换为理想
  算术，用于通用的逐块误差归因。

计划格式：{"blocks": [{"type": <积木名>, "params": {...}}, ...]}
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

ROLES = ("structure", "precision", "micro")


class PlanError(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(f"{code} at {path}: {message}")
        self.code, self.path, self.message = code, path, message

    def as_dict(self) -> dict:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class Param:
    name: str
    kind: str                       # int | choice | bool | float
    role: str                       # structure | precision | micro
    doc: str
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    default: Any = None
    wide: Any = None                # 结构阶段使用的“宽裕”取值（精度参数）
    step: int = 1
    nullable: bool = False          # 允许 None（例如“不剪枝”）
    rate: bool = False              # 该参数是速率变化因子
    scaling: bool = False           # 该参数是增益/定标（分阶段时按局部 SNR 最优选取）
    numeric: bool = True            # False：不改变数值行为（纯微架构）
    when: Callable[[dict], bool] | None = None

    def applies(self, params: dict) -> bool:
        return self.when is None or self.when(params)

    def coerce(self, v: Any, path: str) -> Any:
        if v is None:
            if self.nullable:
                return None
            raise PlanError("missing", path, "value required")
        if self.kind == "int":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or \
                    (isinstance(v, float) and not v.is_integer()):
                raise PlanError("type", path, f"expected integer, got {v!r}")
            v = int(v)
        elif self.kind == "float":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise PlanError("type", path, f"expected number, got {v!r}")
            v = float(v)
        elif self.kind == "bool":
            if not isinstance(v, bool):
                raise PlanError("type", path, f"expected boolean, got {v!r}")
        elif self.kind == "choice":
            if v not in self.choices:
                raise PlanError("choice", path, f"{v!r} not in {list(self.choices)}")
            return v
        if self.kind in ("int", "float"):
            if self.lo is not None and v < self.lo or self.hi is not None and v > self.hi:
                raise PlanError("range", path, f"{v} outside [{self.lo}, {self.hi}]")
        return v

    def describe(self) -> dict:
        d = {"name": self.name, "type": self.kind, "role": self.role, "doc": self.doc}
        if self.kind in ("int", "float"):
            d["range"] = [self.lo, self.hi]
        if self.choices:
            d["choices"] = list(self.choices)
        if self.nullable:
            d["nullable"] = True
        if self.default is not None:
            d["default"] = self.default
        return d


class Block:
    """积木基类。子类声明 type/doc/in_kind/out_kind/params 并实现各方法。"""

    type: str = ""
    doc: str = ""
    in_kind: str = "complex"        # real | complex
    out_kind: str = "complex"
    params: tuple = ()

    # ---- 校验与上下文 ----
    def check(self, p: dict, ctx: dict) -> tuple[dict, dict]:
        """返回 (规范化参数, 输出上下文增量)。增量至少含 width_out 与 decim。"""
        raise NotImplementedError

    def prepare(self, p: dict, ctx: dict) -> Any:
        """确定性预计算（如滤波器系数）；结果作为 aux 传给其余方法。"""
        return None

    # ---- 数值 ----
    def run(self, x: np.ndarray, p: dict, ctx: dict, aux: Any, *, exact: bool,
            ideal_coef: bool, stats: dict) -> np.ndarray:
        raise NotImplementedError

    def response(self, f: np.ndarray, p: dict, ctx: dict, aux: Any,
                 quantized: bool = True) -> np.ndarray | None:
        """线性时不变部分的频响（f 以链输入采样率归一化）；非 LTI 返回 None。"""
        return None

    def delay(self, p: dict, ctx: dict, aux: Any) -> float:
        """群时延（链输入样点）。"""
        return 0.0

    # ---- 硬件 ----
    def cost(self, p: dict, ctx: dict, aux: Any) -> dict:
        raise NotImplementedError

    def rtl(self, p: dict, ctx: dict, aux: Any, module: str) -> str:
        raise NotImplementedError

    def repair(self, p: dict) -> dict:
        """可选：把参数修正到本积木的结构约束内（如奇数抽头）。"""
        return p

    def locked(self, p: dict) -> set:
        """可选：在当前参数下被结构约束锁定、不可由速率重平衡修改的参数名。"""
        return set()

    def param(self, name: str) -> Param:
        for q in self.params:
            if q.name == name:
                return q
        raise KeyError(name)

    def describe(self) -> dict:
        return {"type": self.type, "doc": self.doc, "in": self.in_kind, "out": self.out_kind,
                "params": [q.describe() for q in self.params]}


REGISTRY: dict[str, Block] = {}


def register(cls):
    REGISTRY[cls.type] = cls()
    return cls


def canonical(plan: dict) -> str:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), default=str)


def plan_hash(plan: dict) -> str:
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


# ---------------------------------------------------------------------------
# 计划校验与上下文传播
# ---------------------------------------------------------------------------

@dataclass
class Stage:
    block: Block
    params: dict
    ctx: dict
    aux: Any = None


@dataclass
class Chain:
    plan: dict                      # 规范化计划
    stages: list
    spec: Any
    hash: str = ""

    @property
    def keys(self) -> list[str]:
        return [f"b{i}_{s.block.type}" for i, s in enumerate(self.stages)]


_PREP_CACHE: dict = {}


def build(plan: dict, spec, *, interface=None) -> Chain:
    """校验计划、传播上下文、执行确定性预计算。失败抛出 PlanError。"""
    if not isinstance(plan, dict) or set(plan) - {"blocks"}:
        raise PlanError("fields", "$", "plan must be {\"blocks\": [...]}")
    blocks = plan.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise PlanError("type", "blocks", "non-empty list required")
    if len(blocks) > 8:
        raise PlanError("range", "blocks", "at most 8 blocks")
    ctx = {"spec": spec, "rate_in": 1, "width_in": spec.input_bits, "kind_in": "real",
           "upstream": []}
    stages, norm = [], []
    for i, b in enumerate(blocks):
        path = f"blocks[{i}]"
        if not isinstance(b, dict) or "type" not in b:
            raise PlanError("type", path, "block must have a type")
        blk = REGISTRY.get(b["type"])
        if blk is None:
            raise PlanError("choice", f"{path}.type",
                            f"unknown block {b['type']!r}; available {sorted(REGISTRY)}")
        if blk.in_kind != ctx["kind_in"]:
            raise PlanError("interface", path,
                            f"{blk.type} expects {blk.in_kind} input, got {ctx['kind_in']}")
        raw = b.get("params", {})
        if not isinstance(raw, dict):
            raise PlanError("type", f"{path}.params", "object required")
        known = {q.name for q in blk.params}
        extra = set(raw) - known
        if extra:
            raise PlanError("fields", f"{path}.params", f"unknown params {sorted(extra)}")
        p = {}
        for q in blk.params:
            if not q.applies(p | raw):
                continue
            v = raw.get(q.name, q.default)
            p[q.name] = q.coerce(v, f"{path}.params.{q.name}")
        c = dict(ctx, index=i, path=path)
        p, delta = blk.check(p, c)
        c.update(delta)
        key = (blk.type, canonical(p), canonical({k: v for k, v in c.items()
                                                  if k in ("rate_in", "width_in")}),
               spec.sha256(), canonical([(u[0], canonical(u[1]), u[2]) for u in ctx["upstream"]]))
        if key not in _PREP_CACHE:
            _PREP_CACHE[key] = blk.prepare(p, c)
        aux = _PREP_CACHE[key]
        stages.append(Stage(blk, p, c, aux))
        norm.append({"type": blk.type, "params": p})
        ctx = {"spec": spec, "rate_in": c["rate_in"] * delta.get("decim", 1),
               "width_in": delta["width_out"], "kind_in": blk.out_kind,
               "upstream": ctx["upstream"] + [(blk.type, p, c["rate_in"])]}
    nplan = {"blocks": norm}
    chain = Chain(nplan, stages, spec, plan_hash(nplan))
    if interface is not None:
        interface(chain, ctx)
    return chain


def upstream_response(chain_or_upstream, f: np.ndarray, spec) -> np.ndarray:
    """给定上游 (type, params, rate_in) 列表，计算其 LTI 频响乘积。"""
    H = np.ones(len(f), dtype=np.complex128)
    for typ, p, rate_in in chain_or_upstream:
        blk = REGISTRY[typ]
        ctx = {"spec": spec, "rate_in": rate_in}
        r = blk.response(f, p, ctx, None, quantized=False)
        if r is not None:
            H = H * r
    return H


# ---------------------------------------------------------------------------
# 通用运行器
# ---------------------------------------------------------------------------

def quantize_grid(x: np.ndarray, width: int) -> np.ndarray:
    lsb = 2.0 ** -(width - 1)

    def q(v):
        return np.clip(np.round(v / lsb) * lsb, -1.0, 1.0 - lsb)
    if np.iscomplexobj(x):
        return q(x.real) + 1j * q(x.imag)
    return q(x)


def run_chain(chain: Chain, x: np.ndarray, *, exact: dict | None = None,
              ideal_coef: bool = False) -> tuple[np.ndarray, dict]:
    """x：链输入（归一化值，位于输入网格）。exact[key]=False 时该块用理想算术。"""
    exact = {k: True for k in chain.keys} | (exact or {})
    stats: dict = {}
    prev_exact = True
    for key, st in zip(chain.keys, chain.stages):
        e = exact[key]
        if e and not prev_exact:
            x = quantize_grid(x, st.ctx["width_in"])
        sub: dict = {}
        x = st.block.run(x, st.params, st.ctx, st.aux, exact=e, ideal_coef=ideal_coef,
                         stats=sub)
        for k, v in sub.items():
            stats[f"{key}.{k}"] = v
        prev_exact = e
    return x, stats


def composite_response(chain: Chain, f: np.ndarray, quantized: bool = True) -> np.ndarray:
    H = np.ones(len(f), dtype=np.complex128)
    for st in chain.stages:
        r = st.block.response(f, st.params, st.ctx, st.aux, quantized=quantized)
        if r is not None:
            H = H * r
    return H


def block_response(chain: Chain, i: int, f: np.ndarray, quantized: bool = True):
    st = chain.stages[i]
    return st.block.response(f, st.params, st.ctx, st.aux, quantized=quantized)


def total_delay(chain: Chain) -> float:
    return float(sum(st.block.delay(st.params, st.ctx, st.aux) for st in chain.stages))


def chain_cost(chain: Chain) -> dict:
    per, comps = {}, {}
    for key, st in zip(chain.keys, chain.stages):
        c = st.block.cost(st.params, st.ctx, st.aux)
        comps[key] = {k: float(v) for k, v in c.items()}
        per[key] = float(sum(c.values()))
    return {"total": float(sum(per.values())), "per_block": per, "components": comps}


def catalog() -> list[dict]:
    return [b.describe() for b in REGISTRY.values()]


def with_param(plan: dict, i: int, name: str, value) -> dict:
    p = copy.deepcopy(plan)
    p["blocks"][i]["params"][name] = value
    return p
