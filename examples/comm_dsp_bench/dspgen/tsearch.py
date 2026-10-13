"""通用版（dspgen Task + 任意专家模板模块）：按角色强分阶段 vs 联合搜索。由 dspgraph/template_search.py 改写。

python -m dspgen.tsearch --template duc --out DIR --tasks duc_l4_narrow,... --seeds 0-2 --budget 400 --jobs 6

原说明：命题 1：在专家模板参数空间上比较“按角色强分阶段设计”与“联合搜索”。

两者共用：同一模板、同一编译器与裁判、同一代理面积、同一评价预算（新参数组合的评价次数）。

强分阶段（经典流程，按角色依次冻结）：
  1 结构：精度取宽、微架构取默认，用进化搜索选“理想精度下留出一半实现损失裕量、面积最小”的结构；
  2 精度：冻结结构，先选输出增益使 SNR 最大，再逐参数坐标下降（保持达标、面积减小）；
  3 微架构：冻结结构与精度，逐参数选面积最小的复用因子；
  不达标则加大结构裕量重做；剩余预算继续细化次优结构。
联合：在全部参数上同时进化（约束优先、面积其次）。

python -m dspgraph.template_search --out DIR --specs dev --seeds 0-4 --budget 400 --jobs 8
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import importlib

from .task import evaluate_program, get

T = None


def _use(template):
    global T
    T = importlib.import_module(f"dspgen.templates.{template}")


class Ledger:
    def __init__(self, spec, budget):
        self.spec, self.budget = spec, budget
        self.cache, self.hist = {}, []
        self.used = 0

    def key(self, p):
        return json.dumps(p, sort_keys=True)

    def done(self):
        return self.used >= self.budget

    def __call__(self, p, tag=""):
        k = self.key(p)
        if k in self.cache:
            return self.cache[k]
        if self.done():
            return None
        self.used += 1
        r = evaluate_program(T.code(p), self.spec.name)
        row = {"params": dict(p), "valid": r.get("valid", False), "tag": tag, "i": self.used}
        if r.get("valid"):
            q = r["quality"]
            row.update(passed=q["passed"], margin=q["snr_margin_db"], ripple=q["ripple_db"],
                       ripple_max=q["ripple_max_db"], area=r["area"], sat=sum(q["saturation"].values()))
        else:
            row.update(passed=False, error=r.get("error"))
        self.cache[k] = row
        self.hist.append({"i": self.used, "area": row.get("area"), "passed": row["passed"], "tag": tag})
        return row

    def best(self):
        ok = [r for r in self.cache.values() if r["passed"]]
        return min(ok, key=lambda r: r["area"]) if ok else None

    def curve(self):
        cur, out = math.inf, []
        for h in self.hist:
            if h["passed"]:
                cur = min(cur, h["area"])
            out.append(cur)
        return out


def badness(r, need_margin=0.0):
    if r is None or not r["valid"]:
        return (2, 1e9)
    v = max(0.0, need_margin - r["margin"]) + 3 * max(0.0, r["ripple"] - r["ripple_max"]) / r["ripple_max"]
    if v == 0:
        return (0, r["area"])
    return (1, v)


def neighbors(spec, p, roles, rng, n_changes=None):
    sp = [s for s in T.space(spec) if s[1] in roles]
    q = dict(p)
    for _ in range(n_changes or (1 if rng.random() < 0.6 else 2)):
        name, _, vals = rng.choice(sp)
        i = vals.index(q[name]) if q[name] in vals else len(vals) // 2
        if rng.random() < 0.2:
            q[name] = rng.choice(vals)
        else:
            q[name] = vals[min(max(i + rng.choice([-2, -1, 1, 2]), 0), len(vals) - 1)]
    return q


def evolve(led, spec, rng, roles, init, need_margin=0.0, budget_end=None, fix=lambda p: p, pop=16):
    budget_end = budget_end or led.budget
    P = []
    for p in init:
        r = led(fix(p), "init")
        if r:
            P.append(r)
    stall = 0
    while led.used < budget_end and P and stall < 500:
        P.sort(key=lambda r: badness(r, need_margin))
        par = rng.choice(P[: max(3, len(P) // 2)])["params"]
        child = fix(neighbors(spec, par, roles, rng))
        if led.key(child) in led.cache:
            stall += 1
            continue
        stall = 0
        r = led(child, "evolve")
        if r is None:
            break
        P.append(r)
        P.sort(key=lambda r: badness(r, need_margin))
        P = P[:pop]
    return P


def joint(spec, budget, seed):
    rng = random.Random(seed)
    led = Ledger(spec, budget)
    init = [T.baseline_params(spec)] + [T.random_params(spec, rng) for _ in range(11)]
    evolve(led, spec, rng, {"structure", "precision", "micro"}, init)
    return led


def staged(spec, budget, seed, struct_share=0.5):
    rng = random.Random(seed)
    led = Ledger(spec, budget)
    space = T.space(spec)
    prec = [s for s in space if s[1] == "precision"]
    micro = [s for s in space if s[1] == "micro"]

    def wide(p):
        q = dict(p)
        q.update(T.WIDE)
        q.update(T.MICRO_DEFAULT)
        return q
    log = []
    for rep, frac in enumerate((0.5, 0.75, 1.0)):
        if led.done():
            break
        need = frac * spec.tolerance["snr_loss_db"]
        end = led.used + int((led.budget - led.used) * struct_share)
        init = [T.baseline_params(spec)] + [T.random_params(spec, rng) for _ in range(11)]
        # 结构阶段：G 也在结构阶段一起找（经典流程先定增益使宽精度下 SNR 最高）
        evolve(led, spec, rng, {"structure"} | {"G"}, init, need, end, wide)
        cands = sorted([r for r in led.cache.values() if r["valid"] and badness(r, need)[0] == 0
                        and all(r["params"][k] == v for k, v in T.WIDE.items())],
                       key=lambda r: r["area"])
        seen_struct = set()
        for s in cands:
            sk = json.dumps({k: s["params"][k] for k, role, _ in space if role == "structure"}, sort_keys=True)
            if sk in seen_struct:
                continue
            seen_struct.add(sk)
            if led.done():
                break
            cur = s
            # 精度：先增益（SNR 最大），再坐标下降
            for g in T.space(spec)[[n for n, *_ in T.space(spec)].index("G")][2]:
                r = led(dict(cur["params"], G=g), "prec_gain")
                if r and r["valid"] and r["margin"] > cur["margin"]:
                    cur = r
            improved = True
            while improved and not led.done():
                improved = False
                for name, _, vals in prec:
                    if name == "G":
                        continue
                    i = vals.index(cur["params"][name])
                    if i == 0:
                        continue
                    r = led(dict(cur["params"], **{name: vals[i - 1]}), "prec")
                    if r and r["passed"] and r["area"] < cur["area"]:
                        cur, improved = r, True
            if not cur["passed"]:
                log.append({"rep": rep, "struct_area": s["area"], "final": None})
                continue
            for name, _, vals in micro:
                best = cur
                for v in vals:
                    r = led(dict(cur["params"], **{name: v}), "micro")
                    if r and r["passed"] and r["area"] < best["area"]:
                        best = r
                cur = best
            log.append({"rep": rep, "struct_area": s["area"], "final": cur["area"]})
        if led.best() is not None:
            break
    led.log = log
    return led


METHODS = {"staged": staged, "joint": joint}


def one(args):
    spec_name, method, seed, budget, template = args
    _use(template)
    spec = get(spec_name)
    t0 = time.time()
    led = METHODS[method](spec, budget, seed * 7919 + 13)
    b = led.best()
    curve = led.curve()
    marks = sorted({int(budget * f) for f in (0.1, 0.25, 0.5, 0.75, 1.0)})
    return {"spec": spec_name, "method": method, "seed": seed, "budget": budget, "used": led.used,
            "seconds": time.time() - t0, "best": b,
            "curve_at": {str(m): (curve[m - 1] if m - 1 < len(curve) and math.isfinite(curve[m - 1]) else None)
                         for m in marks},
            "n_valid": sum(r["valid"] for r in led.cache.values()),
            "n_passed": sum(r["passed"] for r in led.cache.values()),
            "log": getattr(led, "log", None)}


def analyze(rows):
    by = {(r["spec"], r["seed"], r["method"]): r for r in rows}
    pairs, ratios = [], []
    for (s, sd, m), r in by.items():
        if m != "joint":
            continue
        st = by.get((s, sd, "staged"))
        if not st:
            continue
        a_j = r["best"]["area"] if r["best"] else None
        a_s = st["best"]["area"] if st["best"] else None
        pairs.append({"spec": s, "seed": sd, "joint": a_j, "staged": a_s})
        if a_j and a_s:
            ratios.append(a_j / a_s)
    out = {"pairs": pairs, "n_both_found": len(ratios)}
    if ratios:
        lr = np.log(ratios)
        rng = np.random.default_rng(0)
        bs = [np.exp(rng.choice(lr, len(lr)).mean()) for _ in range(4000)]
        out.update(geomean_joint_over_staged=float(np.exp(lr.mean())),
                   ci95=[float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
                   joint_better=int(sum(x < 1 for x in ratios)), n=len(ratios))
        if len(ratios) >= 6 and np.any(lr != 0):
            from scipy.stats import wilcoxon
            out["wilcoxon_p"] = float(wilcoxon(lr).pvalue)
    out["found"] = {m: sum(1 for r in rows if r["method"] == m and r["best"]) for m in METHODS}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--seeds", default="0-2")
    ap.add_argument("--budget", type=int, default=400)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args(argv)
    if a.out.exists():
        sys.exit(f"refusing to overwrite {a.out}")
    a.out.mkdir(parents=True)
    _use(a.template)
    specs = a.tasks.split(",")
    lo, hi = (a.seeds.split("-") + [a.seeds])[:2]
    seeds = list(range(int(lo), int(hi) + 1))
    manifest = {"schema": "dspgen-tsearch-v1", "template": a.template, "tasks": specs, "seeds": seeds,
                "budget_evals": a.budget, "methods": list(METHODS),
                "space": {s: [(n, r, v) for n, r, v in T.space(get(s))] for s in specs}, "started": time.time()}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    tasks = [(s, m, sd, a.budget, a.template) for sd in seeds for s in specs for m in METHODS]
    rows = []
    with ProcessPoolExecutor(a.jobs) as ex:
        for r in ex.map(one, tasks):
            rows.append(r)
            (a.out / "progress.json").write_text(json.dumps(rows, indent=1, default=float))
    res = {"rows": rows, "summary": analyze(rows)}
    (a.out / "results.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res["summary"], indent=1, default=float))


if __name__ == "__main__":
    main()
