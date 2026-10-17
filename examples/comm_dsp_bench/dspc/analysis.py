"""G0 静态检查：近似点清单、精确性传播、区间分析、承诺合法性。全部只看原语程序，不执行。

- 精确性：一个信号“精确”指它在两种解释下取值相同。输入精确；精确运算的结果在参数都精确时精确；
  近似点（会丢小数位的 q、可能饱和的 q、不可表示的 const/rom、lut）的结果不精确。反馈按不动点求解。
- 区间：按实数值传播；对契约输入类（|x| ≤ input_max）判断每个 q 能否排除饱和（sat）或回绕（wrap）。
  回绕本身是模运算语义，结果标为 modular（例如相位累加、CIC 积分器），由仿真复核。
- 承诺：fold 不能超过该段的可用时钟数（每个样点占用的时钟数）。
"""
from __future__ import annotations

from fractions import Fraction

import numpy as np

from .prog import Prog

WIDEN_AFTER = 12


def _hull(a, b):
    return (min(a[0], b[0]), max(a[1], b[1]))


def intervals(prog: Prog, input_max: float = 1.0) -> list:
    """每个节点的实数值区间（定点解释）。input_max：输入幅度上限（相对满量程）。"""
    nodes = prog.nodes
    iv = [None] * len(nodes)
    states = [i for i, n in enumerate(nodes) if n.op == "state"]
    for i in states:
        c = nodes[i].params["init"]
        iv[i] = (c, c)
    for it in range(WIDEN_AFTER + 2):
        changed = False
        for i, n in enumerate(nodes):
            if n.op == "state":
                nx = n.params["next"]
                new = iv[i] if iv[nx] is None else _hull(iv[i], iv[nx])
                if it >= WIDEN_AFTER and new != iv[i]:
                    new = n.fmt.range()                       # 迭代不收敛：放宽到格式全范围
                if new != iv[i]:
                    iv[i], changed = new, True
                continue
            new = _transfer(n, [iv[a] for a in n.args], input_max)
            if new != iv[i]:
                iv[i], changed = new, True
        if not changed:
            break
    return iv


def _transfer(n, a, input_max):
    op, p, fx = n.op, n.params, n.fmt
    if op == "input":
        lo, hi = fx.range()
        return (max(lo, -input_max), min(hi, input_max))
    if op == "const":
        return (p["value"], p["value"])
    if any(x is None for x in a):
        return None
    if op == "add":
        return (a[0][0] + a[1][0], a[0][1] + a[1][1])
    if op == "sub":
        return (a[0][0] - a[1][1], a[0][1] - a[1][0])
    if op == "neg":
        return (-a[0][1], -a[0][0])
    if op == "mul":
        c = [x * y for x in a[0] for y in a[1]]
        return (min(c), max(c))
    if op == "shift":
        k = 2.0 ** p["k"]
        return (a[0][0] * k, a[0][1] * k)
    if op == "q":
        lo, hi = fx.range()
        lsb = 2.0 ** -fx.F
        x0, x1 = a[0][0] - lsb, a[0][1] + lsb                 # 舍入最多改变一个 LSB
        if p["ovf"] == "wrap" and (x0 < lo or x1 > hi):
            return (lo, hi)
        return (max(x0, lo), min(x1, hi))
    if op in ("cmp",):
        return (0.0, 1.0)
    if op == "abs":
        m = max(abs(a[0][0]), abs(a[0][1]))
        return (0.0 if a[0][0] <= 0 <= a[0][1] else min(abs(a[0][0]), abs(a[0][1])), m)
    if op in ("min", "max"):
        f = min if op == "min" else max
        return (f(a[0][0], a[1][0]), f(a[0][1], a[1][1]))
    if op == "select":
        return _hull(a[1], a[2])
    if op in ("bits", "band", "bor", "bxor"):
        return (0.0, float((1 << fx.W) - 1))
    if op == "rom":
        v = [c * 2.0 ** -fx.F for c in p["codes"]]
        return (min(v), max(v))
    if op == "lut":
        v = [c * 2.0 ** -fx.F for c in p["codes"]]
        return (min(v), max(v))
    if op == "interpolate":
        return _hull(a[0], (0.0, 0.0))
    if op in ("delay",):
        return _hull(a[0], (0.0, 0.0))
    if op in ("decimate", "repeat", "reframe"):
        return a[0]
    if op == "interleave":
        lo, hi = a[0]
        for x in a[1:]:
            lo, hi = min(lo, x[0]), max(hi, x[1])
        return (lo, hi)
    raise ValueError(f"no interval transfer for {op}")


def exactness(prog: Prog, iv=None) -> list:
    """每个节点在两种解释下是否取值相同（保守：判为 False 不代表一定不同）。"""
    nodes = prog.nodes
    iv = iv or intervals(prog)
    local = {a["node"] for a in approx_points(prog, iv)}
    ex = [True] * len(nodes)
    for _ in range(len(nodes) + 1):
        changed = False
        for i, n in enumerate(nodes):
            if n.op == "state":
                new = ex[n.params["next"]]
            else:
                new = i not in local and all(ex[a] for a in n.args)
            if new != ex[i]:
                ex[i], changed = new, True
        if not changed:
            break
    return ex


def approx_points(prog: Prog, iv=None) -> list:
    """全部近似点：两种解释可能不同的地方。"""
    nodes = prog.nodes
    iv = iv or intervals(prog)
    out = []
    for i, n in enumerate(nodes):
        kinds = []
        if n.op == "q":
            fa = nodes[n.args[0]].fmt
            if fa.F > n.fmt.F:
                kinds.append(n.params["rnd"])
            lo, hi = n.fmt.range()
            src = iv[n.args[0]]
            if n.params["ovf"] == "sat" and src is not None and (src[0] < lo or src[1] > hi):
                kinds.append("sat")
        elif n.op == "const":
            if float(n.params["code"]) != n.params["value"] * 2.0 ** n.fmt.F:
                kinds.append("coef")
        elif n.op == "rom":
            if not all(float(c) == v * 2.0 ** n.fmt.F for c, v in zip(n.params["codes"], n.params["values"])):
                kinds.append("table")
        elif n.op == "lut":
            kinds.append("lut")
        if kinds:
            out.append({"node": i, "op": n.op, "kind": kinds, "fmt": str(n.fmt), "scope": n.scope,
                        "where": n.where})
    return out


def modular_points(prog: Prog, iv=None) -> list:
    """可能发生回绕的 wrap 量化点（模运算语义，需要仿真复核其下游是否正确恢复）。"""
    iv = iv or intervals(prog)
    out = []
    for i, n in enumerate(prog.nodes):
        if n.op == "q" and n.params["ovf"] == "wrap":
            lo, hi = n.fmt.range()
            src = iv[n.args[0]]
            if src is None or src[0] < lo or src[1] > hi:
                out.append({"node": i, "fmt": str(n.fmt), "scope": n.scope, "where": n.where})
    return out


def check_commitments(prog: Prog) -> list:
    """承诺合法性。返回错误列表（空表示合法）。"""
    errs = []
    scopes = {}
    for n in prog.nodes:
        if n.rate is None:
            continue
        parts = n.scope.split("/") if n.scope else []
        for k in range(1, len(parts) + 1):
            sc = "/".join(parts[:k])
            scopes[sc] = max(scopes.get(sc, Fraction(0)), n.rate)
    for sc, c in prog.commits.items():
        if sc not in scopes:
            errs.append({"scope": sc, "code": "unknown_scope", "message": f"no signal is computed in scope '{sc}'"})
            continue
        clocks = Fraction(prog.in_period) / scopes[sc]
        if "fold" in c and c["fold"] > clocks:
            errs.append({"scope": sc, "code": "fold", "message":
                         f"fold={c['fold']} exceeds the {float(clocks):g} clock(s) available per sample in '{sc}' "
                         f"(fastest rate {scopes[sc]} of the input rate)"})
    ii = prog.iface.get("ii")
    if ii is not None and ii != prog.in_period:
        errs.append({"scope": "", "code": "interface",
                     "message": f"ii={ii} differs from the task interface ({prog.in_period} clock(s) per input)"})
    return errs


def g0(prog: Prog, input_max: float = 1.0) -> dict:
    """G0 静态检查报告。"""
    iv = intervals(prog, input_max)
    aps = approx_points(prog, iv)
    errs = check_commitments(prog)
    ops = {}
    for n in prog.nodes:
        ops[n.op] = ops.get(n.op, 0) + 1
    return {"ok": not errs, "errors": errs,
            "approx_points": aps,
            "saturation_possible": [a for a in aps if "sat" in a["kind"]],
            "modular": modular_points(prog, iv),
            "summary": {"nodes": len(prog.nodes), "ops": ops, "a_hash": prog.a_hash(), "b_hash": prog.b_hash(),
                        "rates": sorted({str(n.rate) for n in prog.nodes if n.rate is not None})}}


def local_noise(prog: Prog, res) -> list:
    """每个近似点在定点解释中注入的局部误差（相对其输入的 SQNR），按从差到好排序。res：interp.run 的定点结果。"""
    out = []
    for i, n in enumerate(prog.nodes):
        if n.op != "q" or prog.nodes[n.args[0]].fmt.F <= n.fmt.F:
            continue
        x = np.asarray(res.real(prog, n.args[0]), dtype=float)
        y = np.asarray(res.real(prog, i), dtype=float)
        if x.ndim != 2 or y.ndim != 2:
            continue
        m = min(x.shape[1], y.shape[1])
        e = y[:, :m] - x[:, :m]
        ps, pe = float(np.mean(x[:, :m] ** 2)), float(np.mean(e ** 2))
        out.append({"node": i, "scope": n.scope, "fmt": str(n.fmt), "where": n.where,
                    "local_sqnr_db": round(10 * np.log10(max(ps, 1e-300) / max(pe, 1e-300)), 2)})
    out.sort(key=lambda r: r["local_sqnr_db"])
    return out
