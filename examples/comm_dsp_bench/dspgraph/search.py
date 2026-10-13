"""通用搜索：评价账本、schema 驱动的变异、联合进化搜索与“按角色分阶段”基线。

本模块不含任何链或算子特定代码：所有操作都由积木的 Param schema 推导。
- 联合设计 = 在 structure/precision/micro 全部角色上同时搜索；
- 强分阶段 = 先只搜 structure（精度取 wide、微架构取默认），再在冻结结构上做
  precision 坐标下降，最后逐块选代价最小的 micro 取值。
两者共用同一 Evaluator、同一预算口径（新计划的真实评价次数）。
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from typing import Callable

from .core import REGISTRY, PlanError, chain_cost, plan_hash

ALL_ROLES = frozenset({"structure", "precision", "micro"})


# ---------------------------------------------------------------------------
# 评价器
# ---------------------------------------------------------------------------

@dataclass
class Evaluator:
    spec: object
    build: Callable            # (plan, spec) -> Chain
    evaluate: Callable         # (chain, attribution=bool) -> quality dict
    budget: int
    margin: dict = field(default_factory=dict)   # 规格收紧（分阶段结构阶段使用）
    ideal: bool = False                           # True：理想算术评价（结构阶段）
    cache: dict = field(default_factory=dict)
    used: int = 0
    invalid: int = 0
    history: list = field(default_factory=list)

    def exhausted(self) -> bool:
        return self.used >= self.budget

    def passed(self, q: dict) -> bool:
        if not self.margin:
            return q["passed"]
        s = self.spec
        return (q["snr_db"] >= s.snr_min_db + self.margin.get("snr_db", 0)
                and q["alias_rejection_db"] >= s.alias_min_db + self.margin.get("alias_db", 0)
                and q["ripple_db"] <= s.ripple_max_db * self.margin.get("ripple_scale", 1.0))

    def __call__(self, plan: dict, *, attribution: bool = False, tag: str = "") -> dict:
        try:
            chain = self.build(plan, self.spec)
        except PlanError as e:
            self.invalid += 1
            return {"valid": False, "error": e.as_dict()}
        h = chain.hash + (":ideal" if self.ideal else "")
        if h in self.cache:
            r = self.cache[h]
            if attribution and "attribution" not in r["quality"]:
                r["quality"] = self.evaluate(chain, attribution=True)
            return r | {"cache_hit": True}
        if self.exhausted():
            return {"valid": True, "budget_exhausted": True}
        self.used += 1
        q = (self.evaluate(chain, ideal=True) if self.ideal
             else self.evaluate(chain, attribution=attribution))
        c = chain_cost(chain)
        r = {"valid": True, "plan": chain.plan, "hash": h, "quality": q, "area": c["total"],
             "area_per_block": c["per_block"], "eval_index": self.used,
             "ok": self.passed(q), "ideal": self.ideal}
        self.cache[h] = r
        self.history.append({"i": self.used, "hash": h, "area": c["total"], "ok": r["ok"],
                             "passed": q["passed"] and not self.ideal, "tag": tag})
        return r

    def best(self, require_spec: bool = True) -> dict | None:
        ok = [r for r in self.cache.values() if not r.get("ideal")
              and (r["quality"]["passed"] if require_spec else r["ok"])]
        return min(ok, key=lambda r: r["area"]) if ok else None

    def curve(self) -> list:
        cur, out = math.inf, []
        for h in self.history:
            if h["passed"]:
                cur = min(cur, h["area"])
            out.append(cur)
        return out


def violation(q: dict, spec) -> float:
    return (max(0.0, spec.snr_min_db - q["snr_db"])
            + max(0.0, spec.alias_min_db - q["alias_rejection_db"])
            + 3.0 * max(0.0, q["ripple_db"] - spec.ripple_max_db) / max(spec.ripple_max_db, 1e-3))


# ---------------------------------------------------------------------------
# schema 驱动的计划操作
# ---------------------------------------------------------------------------

def _applicable(blk, params: dict):
    return [q for q in blk.params if q.applies(params)]


def _sample_param(q, rng: random.Random, around=None):
    if q.kind == "choice":
        return rng.choice(q.choices)
    if q.kind == "bool":
        return rng.random() < 0.5
    if q.kind == "float":
        lo, hi = math.log(q.lo), math.log(q.hi)
        return float(round(math.exp(rng.uniform(lo, hi)), 3))
    base = around if around is not None else q.default
    if q.role == "structure" or base is None:
        hi = min(q.hi, q.lo + 64 * q.step)
        v = rng.randint(int(q.lo), int(hi))
    else:
        v = int(base) + q.step * rng.randint(-6, 6)
    if q.step > 1:
        v = int(q.lo) + ((v - int(q.lo)) // q.step) * q.step
    return int(min(max(v, q.lo), q.hi))


def random_block(typ: str, rng: random.Random) -> dict:
    blk = REGISTRY[typ]
    p: dict = {}
    for q in blk.params:
        if not q.applies(p):
            continue
        p[q.name] = None if (q.nullable and rng.random() < 0.2) else _sample_param(q, rng)
    return {"type": typ, "params": p}


def _rate_params(plan: dict):
    out = []
    for i, b in enumerate(plan["blocks"]):
        blk = REGISTRY[b["type"]]
        for q in blk.params:
            if q.rate and q.name in b["params"] and q.name not in blk.locked(b["params"]):
                out.append((i, q))
    return out


def rebalance(plan: dict, target: int, rng: random.Random) -> bool:
    rp = _rate_params(plan)
    fixed = 1
    for b in plan["blocks"]:
        blk = REGISTRY[b["type"]]
        for q in blk.params:
            if q.rate and q.name in blk.locked(b["params"]):
                fixed *= b["params"][q.name]
    if target % fixed:
        return False
    target //= fixed
    if not rp:
        return target == 1
    prod = 1
    for i, q in rp:
        prod *= plan["blocks"][i]["params"][q.name]
    if prod == target:
        return True
    order = rp[:]
    rng.shuffle(order)
    for i, q in order:
        v = plan["blocks"][i]["params"][q.name]
        rest = prod // v
        if target % rest == 0 and q.lo <= target // rest <= q.hi:
            plan["blocks"][i]["params"][q.name] = target // rest
            return True
    # 重新分解：按顺序贪心分配
    rem = target
    for k, (i, q) in enumerate(order):
        if k == len(order) - 1:
            v = rem
        else:
            divs = [d for d in range(int(q.lo), int(q.hi) + 1) if rem % d == 0 and rem // d >= 1]
            if not divs:
                return False
            v = rng.choice(divs)
        if not q.lo <= v <= q.hi:
            return False
        plan["blocks"][i]["params"][q.name] = v
        rem //= v
    return rem == 1


def repair(plan: dict, spec, rng: random.Random) -> dict:
    """通用修复：调用积木自带 repair、统一末级输出位宽、重平衡速率。"""
    for b in plan["blocks"]:
        blk = REGISTRY[b["type"]]
        if hasattr(blk, "repair"):
            b["params"] = blk.repair(b["params"])
        # 去掉不再适用的参数，补上新适用参数的默认值
        p = {}
        for q in blk.params:
            if q.applies(p | b["params"]):
                p[q.name] = b["params"].get(q.name, q.default)
        b["params"] = p
    last = plan["blocks"][-1]["params"]
    if "out_bits" in last:
        last["out_bits"] = spec.output_bits
    rebalance(plan, spec.r_total, rng)
    return plan


def mutate(plan: dict, spec, rng: random.Random, roles=ALL_ROLES,
           frozen: dict | None = None) -> dict:
    p = copy.deepcopy(plan)
    blocks = p["blocks"]
    structural = "structure" in roles and rng.random() < 0.2
    if structural:
        op = rng.choice(["insert", "delete", "replace", "swap"])
        mids = [t for t, b in REGISTRY.items() if b.in_kind == "complex" and b.out_kind == "complex"]
        if op == "insert" and len(blocks) < 6:
            k = rng.randint(1, len(blocks))
            blocks.insert(k, random_block(rng.choice(mids), rng))
        elif op == "delete" and len(blocks) > 2:
            k = rng.randint(1, len(blocks) - 1)
            blocks.pop(k)
        elif op == "replace" and len(blocks) > 1:
            k = rng.randint(1, len(blocks) - 1)
            blocks[k] = random_block(rng.choice(mids), rng)
        elif op == "swap" and len(blocks) > 2:
            k = rng.randint(1, len(blocks) - 2)
            blocks[k], blocks[k + 1] = blocks[k + 1], blocks[k]
    else:
        for _ in range(1 + (rng.random() < 0.3)):
            k = rng.randrange(len(blocks))
            b = blocks[k]
            blk = REGISTRY[b["type"]]
            qs = [q for q in _applicable(blk, b["params"]) if q.role in roles]
            if not qs:
                continue
            q = rng.choice(qs)
            v = b["params"].get(q.name, q.default)
            if q.nullable and (v is None or rng.random() < 0.1):
                b["params"][q.name] = q.default if v is None else None
            elif q.kind == "int":
                d = q.step * rng.choice([-2, -1, -1, 1, 1, 2])
                if q.role == "micro":
                    v2 = int(round(v * rng.choice([0.5, 2.0]))) if rng.random() < 0.6 else v + d
                else:
                    v2 = v + d
                b["params"][q.name] = int(min(max(v2, q.lo), q.hi))
            elif q.kind == "float":
                b["params"][q.name] = float(min(max(v * rng.choice([0.3, 3.0]), q.lo), q.hi))
            elif q.kind == "bool":
                b["params"][q.name] = not v
            else:
                b["params"][q.name] = rng.choice([c for c in q.choices if c != v] or [v])
    return repair(p, spec, rng)


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    """同构（积木类型序列相同）时逐块交换参数；否则返回 a 的拷贝。"""
    c = copy.deepcopy(a)
    if [x["type"] for x in a["blocks"]] == [x["type"] for x in b["blocks"]]:
        for i in range(len(c["blocks"])):
            if rng.random() < 0.5:
                c["blocks"][i] = copy.deepcopy(b["blocks"][i])
    return c


def random_plan(spec, rng: random.Random, n_mid: int | None = None) -> dict:
    heads = [t for t, b in REGISTRY.items() if b.in_kind == "real"]
    mids = [t for t, b in REGISTRY.items() if b.in_kind == "complex" and b.out_kind == "complex"]
    n_mid = n_mid or rng.randint(1, 4)
    plan = {"blocks": [random_block(rng.choice(heads), rng)] +
            [random_block(rng.choice(mids), rng) for _ in range(n_mid)]}
    return repair(plan, spec, rng)


def set_roles(plan: dict, role: str, how: str) -> dict:
    """把某角色的全部参数设为 wide（how='wide'）或默认值（how='default'）。"""
    p = copy.deepcopy(plan)
    for b in p["blocks"]:
        blk = REGISTRY[b["type"]]
        for q in _applicable(blk, b["params"]):
            if q.role == role:
                b["params"][q.name] = (q.wide if how == "wide" else q.default)
    return p


# ---------------------------------------------------------------------------
# 联合进化搜索
# ---------------------------------------------------------------------------

def _rank(r: dict, spec) -> tuple:
    return (0, r["area"]) if r["ok"] else (1, violation(r["quality"], spec))


def evolve(ev: Evaluator, spec, rng: random.Random, *, roles=ALL_ROLES, init: list | None = None,
           pop_size: int = 24, budget_end: int | None = None, transform=None) -> list:
    """(μ+1) 进化：约束优先、代理面积次之。transform 用于分阶段时固定非搜索角色。"""
    budget_end = budget_end or ev.budget
    transform = transform or (lambda x: x)
    pop, seeds, tries = [], list(init or []), 0
    while len(pop) < pop_size and ev.used < budget_end and tries < 40 * pop_size:
        tries += 1
        cand = transform(seeds.pop(0) if seeds else random_plan(spec, rng))
        r = ev(cand, tag="init")
        if r.get("valid") and "quality" in r:
            pop.append(r)
    stall = 0
    while ev.used < budget_end and pop and stall < 2000:
        pop.sort(key=lambda r: _rank(r, spec))
        parents = pop[: max(4, len(pop) // 2)]
        a = rng.choice(parents)["plan"]
        child = crossover(a, rng.choice(parents)["plan"], rng) if rng.random() < 0.3 else a
        child = transform(mutate(child, spec, rng, roles))
        if rng.random() < 0.3:
            child = transform(mutate(child, spec, rng, roles))
        r = ev(child, tag="evolve")
        if not r.get("valid") or "quality" not in r or r.get("cache_hit"):
            stall += 1
            continue
        stall = 0
        pop.append(r)
        pop.sort(key=lambda r: _rank(r, spec))
        pop = pop[:pop_size]
    return pop


def joint_search(ev: Evaluator, spec, seed: int, init: list | None = None) -> dict:
    rng = random.Random(seed)
    evolve(ev, spec, rng, roles=ALL_ROLES, init=init)
    best = ev.best()
    return {"plan": best["plan"] if best else None, "best": best}


# ---------------------------------------------------------------------------
# 按角色分阶段的强基线
# ---------------------------------------------------------------------------

def _precision_descent(ev: Evaluator, plan: dict, spec, rng: random.Random) -> dict:
    """冻结结构与微架构，逐参数坐标下降：定标参数取局部 SNR 最优，其余取合格且代价最小。"""
    cur = ev(plan, tag="prec")
    if not (cur.get("valid") and "quality" in cur):
        return cur
    # 1) 定标参数：按信号流顺序，各自取使系统 SNR 最大的值（局部最优定标）
    for i, b in enumerate(cur["plan"]["blocks"]):
        blk = REGISTRY[b["type"]]
        for q in _applicable(blk, b["params"]):
            if q.role != "precision" or not q.scaling:
                continue
            best = cur
            for v in range(int(q.lo), int(q.hi) + 1):
                trial = copy.deepcopy(cur["plan"])
                trial["blocks"][i]["params"][q.name] = v
                r = ev(trial, tag="prec_scale")
                if r.get("valid") and "quality" in r and \
                        r["quality"]["snr_db"] > best["quality"]["snr_db"]:
                    best = r
                if ev.exhausted():
                    break
            cur = best
    if not cur["quality"]["passed"]:
        return cur
    # 2) 其余精度参数：反复扫描，接受“仍合格且代价下降”的邻点
    improved = True
    while improved and not ev.exhausted():
        improved = False
        for i, b in enumerate(cur["plan"]["blocks"]):
            blk = REGISTRY[b["type"]]
            for q in _applicable(blk, b["params"]):
                if q.role != "precision" or q.scaling:
                    continue
                v = cur["plan"]["blocks"][i]["params"].get(q.name)
                if q.kind == "int":
                    cands = ([q.default] if v is None else
                             [v - q.step, v + q.step] + ([None] if q.nullable else []))
                elif q.kind == "choice":
                    cands = [c for c in q.choices if c != v]
                else:
                    continue
                for v2 in cands:
                    if v2 is not None and q.kind == "int" and not q.lo <= v2 <= q.hi:
                        continue
                    trial = copy.deepcopy(cur["plan"])
                    trial["blocks"][i]["params"][q.name] = v2
                    trial = repair(trial, spec, rng)
                    r = ev(trial, tag="prec")
                    if r.get("valid") and "quality" in r and r["quality"]["passed"] and \
                            r["area"] < cur["area"] - 1e-9:
                        cur, improved = r, True
                        break
                    if ev.exhausted():
                        return cur
    return cur


def _micro_select(ev: Evaluator, plan: dict, spec) -> dict:
    """逐块逐参数枚举 micro 取值，取代理面积最小者（不改变数值，无需重新评价质量）。"""
    from .core import chain_cost
    p = copy.deepcopy(plan)
    for i, b in enumerate(p["blocks"]):
        blk = REGISTRY[b["type"]]
        for q in _applicable(blk, b["params"]):
            if q.role != "micro":
                continue
            best = None
            for v in sorted({1, 2, 3, 4, 5, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128}):
                if not q.lo <= v <= q.hi:
                    continue
                trial = copy.deepcopy(p)
                trial["blocks"][i]["params"][q.name] = v
                try:
                    ch = ev.build(trial, spec)
                except PlanError:
                    continue
                a = chain_cost(ch)["total"]
                if best is None or a < best[0]:
                    best = (a, ch.plan["blocks"][i]["params"][q.name])
            if best:
                p["blocks"][i]["params"][q.name] = best[1]
    return p


def staged_search(ev: Evaluator, spec, seed: int, structure_share: float = 0.6,
                  margins: tuple = ((0.5, 3.0, 0.8), (0.65, 6.0, 0.6), (0.8, 10.0, 0.5))) -> dict:
    """结构阶段（理想算术、收紧规格裕量）→ 精度坐标下降 → 微架构逐块最优；失败则加大裕量重做。

    margins：(结构阶段占用的实现损失比例, 混叠裕量 dB, 纹波上限缩放)。结构阶段要求
    理想算术 SNR ≥ snr_min + 比例·impl_loss，把其余损失留给精度阶段（经典噪声预算分配）。
    """
    rng = random.Random(seed)
    log = []
    total = ev.budget
    best_final = None
    for rep, (snr_frac, m_alias, r_scale) in enumerate(margins):
        m_snr = snr_frac * spec.impl_loss_db
        if ev.exhausted():
            break
        remaining = total - ev.used
        s_end = ev.used + int(remaining * structure_share / (len(margins) - rep) * 1.0)
        ev.margin = {"snr_db": m_snr, "alias_db": m_alias, "ripple_scale": r_scale}
        ev.ideal = True

        def fix(pl):
            pl = set_roles(pl, "precision", "wide")
            pl = set_roles(pl, "micro", "default")
            return repair(pl, spec, rng)
        evolve(ev, spec, rng, roles=frozenset({"structure"}), budget_end=s_end, transform=fix)
        ev.margin = {}
        ev.ideal = False
        # 结构阶段最优：理想算术下满足收紧规格、宽精度下代理面积最小
        cands = [r for r in ev.cache.values() if r.get("ideal") and
                 _meets_margin(r["quality"], spec, m_snr, m_alias, r_scale) and
                 _is_wide(r["plan"])]
        if not cands:
            log.append({"repair": rep, "structure": None})
            continue
        # 依结构阶段排序依次细化不同结构，直至预算用尽（取最好的最终实现）
        tried = set()
        for struct in sorted(cands, key=lambda r: r["area"]):
            sig = _structure_signature(struct["plan"])
            if sig in tried:
                continue
            tried.add(sig)
            if ev.exhausted():
                break
            prec = _precision_descent(ev, struct["plan"], spec, rng)
            if not (prec.get("valid") and "quality" in prec):
                continue
            final_plan = _micro_select(ev, prec["plan"], spec)
            final = ev(final_plan, tag="staged_final")
            ok = bool(final.get("quality", {}).get("passed"))
            log.append({"repair": rep, "structure_area": struct["area"],
                        "final_area": final.get("area"), "passed": ok})
            if ok and (best_final is None or final["area"] < best_final["area"]):
                best_final = final
        if best_final is not None:
            break
    return {"plan": best_final["plan"] if best_final else None, "best": best_final, "log": log}


def _structure_signature(plan: dict) -> str:
    """结构签名：积木类型序列及全部 structure 角色参数。"""
    sig = []
    for b in plan["blocks"]:
        blk = REGISTRY[b["type"]]
        sig.append((b["type"], tuple(sorted((q.name, str(b["params"].get(q.name)))
                                            for q in blk.params if q.role == "structure"))))
    return str(sig)


def _meets_margin(q, spec, m_snr, m_alias, r_scale) -> bool:
    return (q["snr_db"] >= spec.snr_min_db + m_snr and
            q["alias_rejection_db"] >= spec.alias_min_db + m_alias and
            q["ripple_db"] <= spec.ripple_max_db * r_scale)


def _is_wide(plan: dict) -> bool:
    for b in plan["blocks"]:
        blk = REGISTRY[b["type"]]
        for q in _applicable(blk, b["params"]):
            if q.role == "precision" and q.name != "out_bits" and b["params"].get(q.name) != q.wide:
                return False
    return True
