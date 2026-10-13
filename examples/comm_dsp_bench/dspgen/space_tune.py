"""内层：在候选程序自己声明的参数空间内做确定性参数搜索（取代只调位宽/复用的 tune）。

约定：程序里用字面量写出 SPACE = {名字: [可取值...]} 与 P = {名字: 当前值}，build 只通过 P 读取参数。
搜索：按 SPACE 的键序轮询，每个键尝试相邻取值（索引 ±1）；以 (违规量, 面积) 字典序比较，
达标定义为搜索场景达标且裕量 ≥ min_margin；接受更优者；一整轮无改进或评价用完即停。
没有 SPACE/P 的程序退回 dspgraph.tune 的通用位宽/复用旋钮。
"""
from __future__ import annotations

import ast

from dspgraph import tune as width_tune


def read_space(code: str):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    sp = p = None
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try:
                if n.targets[0].id == "SPACE":
                    sp = ast.literal_eval(n.value)
                elif n.targets[0].id == "P":
                    p = ast.literal_eval(n.value)
            except Exception:
                return None
    if not isinstance(sp, dict) or not isinstance(p, dict):
        return None
    sp = {k: list(v) for k, v in sp.items() if isinstance(v, (list, tuple)) and len(v) > 0 and k in p}
    return sp, p


def write_p(code: str, p: dict) -> str:
    tree = ast.parse(code)
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id == "P":
            n.value = ast.parse(repr(p), mode="eval").body
    return ast.unparse(tree)


def badness(r, min_margin):
    if not r.get("valid"):
        return (2, 0.0)
    q = r["quality"]
    v = max(0.0, min_margin - q["snr_margin_db"]) + 3 * max(0.0, q["ripple_db"] - q["ripple_max_db"]) / q["ripple_max_db"]
    if q["passed"] and v == 0:
        return (0, r["area"])
    return (1, v)


def tune(code: str, task: str, budget: int, min_margin: float, evaluate) -> dict:
    sp = read_space(code)
    if sp is None:
        t = width_tune.tune(code, task, budget, min_margin, evaluate=lambda c, s: evaluate(c, s))
        return t | {"mode": "width_knobs"}
    space, p = sp
    cur_code = write_p(code, p)
    cur = evaluate(cur_code, task)
    start = cur
    used, accepted = 0, 0
    keys = list(space)
    improved = True
    while improved and used < budget:
        improved = False
        for k in keys:
            vals = space[k]
            try:
                i = vals.index(p[k])
            except ValueError:
                i = min(range(len(vals)), key=lambda j: abs(vals[j] - p[k]) if isinstance(p[k], (int, float)) else 0)
            for j in (i - 1, i + 1):
                if used >= budget or not 0 <= j < len(vals):
                    continue
                q = dict(p, **{k: vals[j]})
                c2 = write_p(code, q)
                r = evaluate(c2, task)
                used += 1
                if badness(r, min_margin) < badness(cur, min_margin):
                    p, cur, cur_code, improved = q, r, c2, True
                    accepted += 1
                    break
    return {"status": "ok" if cur.get("valid") else "invalid", "mode": "declared_space", "start": start, "final": cur,
            "code": cur_code, "params": p, "evals_used": used, "accepted": accepted,
            "start_area": start.get("area"), "area": cur.get("area")}
