"""确定性位宽/复用坐标下降（A2 / E3.4 分工混合的“工具”部分）。对任意 build 程序通用，不依赖具体结构。

旋钮（在语法树上按出现顺序编号）：
  qpair  : g.q(x, w, f) 中 w、f 均为整数字面量 → 同时减 1（丢最低位，整数位不变）
  qw     : g.q(x, w, expr) 中只有 w 是字面量 → w 减 1
  lutpair: g.lut(a, vals, w, f) 中 w、f 均为字面量 → 同时减 1
  kw     : coef_bits= / bits= 的整数字面量 → 减 1
  share  : g.mac(..., share=k) → k×2；没有 share 关键字的 g.mac → 加 share=2
  name   : 被上述位置的表达式引用、且以整数字面量赋值的变量 → 减 1（出现在 share 表达式里的 → ×2）
接受条件：搜索场景仍达标且面积下降。一整轮无改进或评价次数用完即停。

python -m dspgraph.tune OUT.json BUDGET NAME=SPEC=PATH ...
"""

from __future__ import annotations

import ast
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .rtl_judge import evaluate_program


def _is_int(n):
    return isinstance(n, ast.Constant) and type(n.value) is int


def _gcall(n, name=None):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "g"
            and (name is None or n.func.attr == name))


DICT_KEYS: tuple = ()      # 允许调的“参数字典”键（如专家模板 P_ 中的精度与复用参数）；以 sh 开头的键 ×2，其余 −1


def knobs(tree):
    """返回旋钮列表 [(kind, 应用函数)]；顺序由 ast.walk 决定，对同一结构的程序稳定。"""
    out, width_names, share_names = [], set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict):
            for kk, vv in zip(n.value.keys, n.value.values):
                if isinstance(kk, ast.Constant) and kk.value in DICT_KEYS and _is_int(vv):
                    if str(kk.value).startswith("sh"):
                        out.append(("dict_share", lambda v=vv: _dbl(v)))
                    else:
                        out.append(("dict", lambda v=vv: _dec(v, lo=4)))

    def names_in(e, into):
        for x in ast.walk(e):
            if isinstance(x, ast.Name):
                into.add(x.id)
    for n in ast.walk(tree):
        if _gcall(n, "q") and len(n.args) >= 3:
            w, f = n.args[1], n.args[2]
            if _is_int(w) and _is_int(f):
                out.append(("qpair", lambda w=w, f=f: (_dec(w), _dec(f, lo=-64))))
            elif _is_int(w):
                out.append(("qw", lambda w=w: _dec(w)))
            for e in (w, f):
                names_in(e, width_names)
        if _gcall(n, "lut") and len(n.args) >= 4:
            w, f = n.args[2], n.args[3]
            if _is_int(w) and _is_int(f):
                out.append(("lutpair", lambda w=w, f=f: (_dec(w), _dec(f, lo=-64))))
            for e in (w, f):
                names_in(e, width_names)
        if _gcall(n):
            for kw in n.keywords:
                if kw.arg in ("coef_bits", "bits"):
                    if _is_int(kw.value):
                        out.append(("kw", lambda v=kw.value: _dec(v)))
                    names_in(kw.value, width_names)
                if kw.arg == "share":
                    if _is_int(kw.value):
                        out.append(("share", lambda v=kw.value: _dbl(v)))
                    names_in(kw.value, share_names)
        if _gcall(n, "mac") and not any(kw.arg == "share" for kw in n.keywords):
            out.append(("share_add", lambda n=n: n.keywords.append(
                ast.keyword(arg="share", value=ast.Constant(2))) or True))
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and _is_int(n.value):
            nm = n.targets[0].id
            if nm in share_names:
                out.append(("name_share", lambda v=n.value: _dbl(v)))
            elif nm in width_names:
                out.append(("name", lambda v=n.value: _dec(v)))
    return out


def _dec(c, lo=2):
    if c.value - 1 < lo:
        return False
    c.value -= 1
    return True


def _dbl(c):
    if c.value < 1 or c.value >= 256:
        return False
    c.value *= 2
    return True


def apply(code: str, k: int):
    tree = ast.parse(code)
    ks = knobs(tree)
    if k >= len(ks):
        return None
    r = ks[k][1]()
    ok = all(r) if isinstance(r, tuple) else bool(r)
    if not ok:
        return None
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def tune(code: str, spec: str, budget: int, min_margin: float = 0.0, evaluate=None) -> dict:
    evaluate_program = evaluate or globals()["evaluate_program"]
    code = ast.unparse(ast.parse(code))
    cur = evaluate_program(code, spec)
    if not (cur.get("valid") and cur["quality"]["passed"] and cur["quality"]["snr_margin_db"] >= min_margin):
        return {"status": "start_not_passing", "start": cur}
    start_area, used, accepted, trace = cur["area"], 0, 0, []
    improved = True
    while improved and used < budget:
        improved = False
        k = 0
        while used < budget:
            n = len(knobs(ast.parse(code)))
            if k >= n:
                break
            child = apply(code, k)
            if child is None or child == code:
                k += 1
                continue
            r = evaluate_program(child, spec)
            used += 1
            ok = bool(r.get("valid") and r["quality"]["passed"] and r["quality"]["snr_margin_db"] >= min_margin
                      and r["area"] < cur["area"] - 1e-9)
            if ok:
                code, cur, improved = child, r, True
                accepted += 1            # 同一旋钮继续尝试
            else:
                k += 1
            trace.append(cur["area"])
    return {"status": "ok", "start_area": start_area, "area": cur["area"], "evals_used": used,
            "accepted": accepted, "n_knobs": len(knobs(ast.parse(code))),
            "search_margin_db": cur["quality"]["snr_margin_db"], "code": code, "trace": trace, "final": cur}


def job(it):
    name, spec, path, budget = it
    t0 = time.time()
    r = tune(Path(path).read_text(), spec, budget)
    return {"name": name, "spec": spec, "path": path, "budget": budget, "seconds": time.time() - t0} | r


if __name__ == "__main__":
    out, budget = Path(sys.argv[1]), int(sys.argv[2])
    items = [tuple(a.split("=", 2)) + (budget,) for a in sys.argv[3:]]
    rows = []
    with ProcessPoolExecutor(3) as ex:
        for r in ex.map(job, items):
            rows.append(r)
            out.write_text(json.dumps(rows, indent=1, default=float))
            print(r["name"], r["spec"], r.get("status"), r.get("start_area"), r.get("area"),
                  r.get("evals_used"), r.get("accepted"), flush=True)
