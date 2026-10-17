"""双重解释：同一原语程序按理想（实数）或定点（逐位整数码）执行。

- 定点解释（mode='fixed'）：每个信号是整数码数组，数值 = 码 × 2^-F。结果即实现契约的参考序列。
- 理想解释（mode='ideal'）：每个信号是实数数组。q 不舍入、不饱和（wrap 仍按模运算回绕），
  const 取精确值，lut 取 fn(x)。其余原语与定点解释精确一致。

数组形状为 (场景数, 样点数)，常数为标量。反馈（state/close）按强连通分量求值：
累加器形态（state → add(state, 外部) → q(wrap, 不丢小数位)）用累加和向量化，其余逐样点求值。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .prog import Node, Prog
from .fixtype import ContractError, Fx

INT64_SAFE = 62
_POINTWISE = {"const", "add", "sub", "neg", "mul", "shift", "q", "cmp", "abs", "min", "max", "select", "bits",
              "band", "bor", "bxor", "rom", "lut", "state"}


@dataclass
class Result:
    mode: str
    values: dict                      # 节点号 → 值（定点为整数码，理想为实数）
    y: np.ndarray | None              # 输出（实数或复数，按满量程 1 归一）
    sat: dict = field(default_factory=dict)   # 节点号 → 饱和样点数（只在定点解释中统计）
    qstats: dict = field(default_factory=dict)  # 丢小数位的 q 节点 → (输入功率, 量化误差功率)

    def real(self, prog: Prog, i: int):
        """节点 i 的实数值（定点解释把码乘以 2^-F）。"""
        v = self.values[i]
        if self.mode == "ideal":
            return v
        return np.asarray(v, dtype=float) * 2.0 ** -prog.nodes[i].fmt.F


# ---------------------------------------------------------------------- 整数码工具
def _wide(v, W):
    if isinstance(v, np.ndarray) and W > INT64_SAFE and v.dtype != object:
        return v.astype(object)
    return v


def _narrow(v, W):
    if isinstance(v, np.ndarray) and W <= INT64_SAFE and v.dtype == object:
        return v.astype(np.int64)
    return v


def _shl(v, k, W):
    if k <= 0:
        return v
    v = _wide(v, W)
    if isinstance(v, np.ndarray):
        return v << (np.int64(k) if v.dtype != object else k)
    return int(v) << k


def _wrap(v, fx: Fx):
    m = 1 << fx.W
    if isinstance(v, np.ndarray):
        if v.dtype == object or fx.W > INT64_SAFE:
            v = v.astype(object)
            r = v % m
            return (r - m * (r > fx.hi)).astype(object) if fx.signed else r
        with np.errstate(over="ignore"):
            r = v & np.int64(m - 1)
        return np.where(r > fx.hi, r - np.int64(m), r) if fx.signed else r
    r = int(v) % m
    return r - m if fx.signed and r > fx.hi else r


def _align(*vs):
    """同速率信号按样点序号配对：截到最短长度（不同相位的抽取可能差一个样点）。"""
    ns = [v.shape[1] for v in vs if isinstance(v, np.ndarray) and v.ndim == 2]
    if not ns:
        return vs
    n = min(ns)
    return tuple(v[:, :n] if isinstance(v, np.ndarray) and v.ndim == 2 else v for v in vs)


# ---------------------------------------------------------------------- 逐元素原语
def _fixed(op: str, nd: Node, fmts, a, *, sat_out=None):
    """定点解释：a 为参数的整数码。返回结果的整数码。"""
    fx = nd.fmt
    p = nd.params
    if op == "const":
        return p["code"]
    if op in ("add", "sub"):
        (x, y), (fa, fb) = _align(*a), fmts
        F = fx.F
        x, y = _shl(_wide(x, fx.W), F - fa.F, fx.W), _shl(_wide(y, fx.W), F - fb.F, fx.W)
        return _narrow(x + y if op == "add" else x - y, fx.W)
    if op == "neg":
        return _narrow(-_wide(a[0], fx.W), fx.W)
    if op == "mul":
        x, y = _align(*a)
        return _narrow(_wide(x, fx.W) * _wide(y, fx.W), fx.W)
    if op == "shift":
        return a[0]
    if op == "q":
        return _q_fixed(a[0], fmts[0], fx, p["rnd"], p["ovf"], sat_out)
    if op in ("cmp", "min", "max"):
        (x, y), (fa, fb) = _align(*a), fmts
        F, W = max(fa.F, fb.F), max(fa.W, fb.W) + abs(fa.F - fb.F) + 1
        x, y = _shl(_wide(x, W), F - fa.F, W), _shl(_wide(y, W), F - fb.F, W)
        if op == "cmp":
            r = {"lt": x < y, "le": x <= y, "gt": x > y, "ge": x >= y, "eq": x == y, "ne": x != y}[p["op"]]
            return np.asarray(r, dtype=np.int64) if isinstance(r, np.ndarray) else int(bool(r))
        r = np.minimum(x, y) if op == "min" else np.maximum(x, y)
        return _narrow(r, fx.W)
    if op == "abs":
        return _narrow(np.abs(_wide(a[0], fx.W + 1)), fx.W)
    if op == "select":
        c, x, y = _align(*a)
        F = fx.F
        x, y = _shl(_wide(x, fx.W), F - fmts[1].F, fx.W), _shl(_wide(y, fx.W), F - fmts[2].F, fx.W)
        return _narrow(np.where(np.asarray(c) != 0, x, y), fx.W)
    if op == "bits":
        u = _wrap(a[0], Fx(fmts[0].W, 0, False))
        return _narrow((u >> p["lo"]) & ((1 << (p["hi"] - p["lo"] + 1)) - 1), fx.W)
    if op in ("band", "bor", "bxor"):
        x, y = _align(*a)
        return {"band": x & y, "bor": x | y, "bxor": x ^ y}[op]
    if op == "rom":
        return np.asarray(p["codes"], dtype=np.int64)[np.asarray(a[0], dtype=np.int64)]
    if op == "lut":
        fa = fmts[0]
        idx = (_wide(a[0], fa.W + 1) - fa.lo) >> (fa.W - p["addr_bits"])
        return np.asarray(p["codes"], dtype=np.int64)[np.asarray(idx, dtype=np.int64)]
    raise ContractError("internal", f"no fixed semantics for {op}")


def _q_fixed(v, fa: Fx, fx: Fx, rnd, ovf, sat_out):
    s = fa.F - fx.F
    W = max(fa.W, fx.W) + abs(s) + 1
    v = _wide(v, W)
    if s > 0:
        if rnd == "round":
            v = v + (1 << (s - 1)) if not isinstance(v, np.ndarray) or v.dtype == object else v + np.int64(1 << (s - 1))
        v = v >> s if not isinstance(v, np.ndarray) or v.dtype == object else v >> np.int64(s)
    elif s < 0:
        v = _shl(v, -s, W)
    if ovf == "wrap":
        return _narrow(_wrap(v, fx), fx.W)
    if isinstance(v, np.ndarray):
        if sat_out is not None:
            sat_out[0] += int(np.count_nonzero((v > fx.hi) | (v < fx.lo)))
        if v.dtype == object:
            v = np.minimum(np.maximum(v, fx.lo), fx.hi)
        else:
            v = np.clip(v, fx.lo, fx.hi)
        return _narrow(v, fx.W)
    if sat_out is not None and not fx.lo <= v <= fx.hi:
        sat_out[0] += 1
    return min(max(int(v), fx.lo), fx.hi)


def _ideal(op: str, nd: Node, fmts, a):
    """理想解释：a 为参数的实数值。"""
    fx, p = nd.fmt, nd.params
    if op == "const":
        return p["value"]
    if op in ("add", "sub"):
        x, y = _align(*a)
        return x + y if op == "add" else x - y
    if op == "neg":
        return -a[0]
    if op == "mul":
        x, y = _align(*a)
        return x * y
    if op == "shift":
        return a[0] * 2.0 ** p["k"]
    if op == "q":
        if p["ovf"] != "wrap":
            return a[0]
        lo = fx.lo * 2.0 ** -fx.F
        m = 2.0 ** (fx.W - fx.F)
        return np.mod(a[0] - lo, m) + lo
    if op == "cmp":
        x, y = _align(*a)
        r = {"lt": x < y, "le": x <= y, "gt": x > y, "ge": x >= y, "eq": x == y, "ne": x != y}[p["op"]]
        return np.asarray(r, dtype=float) if isinstance(r, np.ndarray) else float(r)
    if op == "abs":
        return np.abs(a[0])
    if op in ("min", "max"):
        x, y = _align(*a)
        return np.minimum(x, y) if op == "min" else np.maximum(x, y)
    if op == "select":
        c, x, y = _align(*a)
        return np.where(np.asarray(c) != 0, x, y)
    if op == "bits":
        code = np.floor(np.asarray(a[0]) * 2.0 ** fmts[0].F).astype(np.int64)
        u = _wrap(code, Fx(fmts[0].W, 0, False))
        return ((u >> p["lo"]) & ((1 << (p["hi"] - p["lo"] + 1)) - 1)).astype(float)
    if op in ("band", "bor", "bxor"):
        x, y = (np.asarray(v).astype(np.int64) for v in _align(*a))
        return {"band": x & y, "bor": x | y, "bxor": x ^ y}[op].astype(float)
    if op == "rom":
        idx = np.clip(np.floor(np.asarray(a[0])).astype(np.int64), 0, len(p["values"]) - 1)
        return np.asarray(p["values"], dtype=float)[idx]
    if op == "lut":
        return np.asarray(p["fn"](np.asarray(a[0], dtype=float)), dtype=float)
    raise ContractError("internal", f"no ideal semantics for {op}")


# ---------------------------------------------------------------------- 结构原语
def _structural(op, nd, v, mode):
    p = nd.params
    if not isinstance(v, np.ndarray):
        raise ContractError("internal", f"{op} on a constant")
    S, n = v.shape
    if op == "delay":
        k = p["n"]
        if k == 0:
            return v
        z = np.zeros((S, min(k, n)), dtype=v.dtype)
        return np.concatenate([z, v[:, :n - k]], axis=1) if k < n else z
    if op == "decimate":
        return v[:, p["phase"]::p["r"]]
    if op == "interpolate":
        y = np.zeros((S, n * p["n"]), dtype=v.dtype)
        y[:, ::p["n"]] = v
        return y
    if op == "repeat":
        return np.repeat(v, p["n"], axis=1)
    if op == "reframe":
        frames = n // p["n_in"]
        idx = (np.arange(frames)[:, None] * p["n_in"] + np.asarray(p["picks"])[None, :]).ravel()
        return v[:, idx]
    raise ContractError("internal", f"unknown structural op {op}")


def _interleave(nd, fmts, args, mode):
    """y[k·m + j] = args[j][m]；定点解释先把各参数对齐到结果格式的小数位。"""
    arrs = [a for a in args if isinstance(a, np.ndarray)]
    S = arrs[0].shape[0]
    n = min(a.shape[1] for a in arrs)
    k = len(args)
    cols = []
    for a, fa in zip(args, fmts):
        if mode == "fixed":
            a = _shl(_wide(a, nd.fmt.W), nd.fmt.F - fa.F, nd.fmt.W)
        a = np.broadcast_to(a, (S, n)) if not isinstance(a, np.ndarray) else a[:, :n]
        cols.append(a)
    dtype = object if any(c.dtype == object for c in cols) else cols[0].dtype
    y = np.empty((S, n * k), dtype=dtype)
    for j, c in enumerate(cols):
        y[:, j::k] = c
    return y


# ---------------------------------------------------------------------- 强连通分量（反馈）
def _sccs(prog: Prog):
    """Tarjan：依赖边 arg→node，以及 state 的 next→state。返回按拓扑序排列的分量。"""
    n = len(prog.nodes)
    deps = [list(nd.args) + ([nd.params["next"]] if nd.op == "state" else []) for nd in prog.nodes]
    index, low, on, stack, out = [None] * n, [0] * n, [False] * n, [], []
    counter = [0]
    for root in range(n):
        if index[root] is not None:
            continue
        work = [(root, 0)]
        while work:
            v, k = work.pop()
            if k == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                on[v] = True
            recurse = False
            for j in range(k, len(deps[v])):
                w = deps[v][j]
                if index[w] is None:
                    work.append((v, j + 1))
                    work.append((w, 0))
                    recurse = True
                    break
                if on[w]:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on[w] = False
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp))
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    return out


def _accumulator(prog: Prog, comp):
    """识别累加器形态：{state s, add(s, x), q(add, wrap, 不丢小数位)}，next(s) = q。返回 (s, add, q, x) 或 None。"""
    if len(comp) != 3:
        return None
    nodes = {i: prog.nodes[i] for i in comp}
    st = [i for i in comp if nodes[i].op == "state"]
    if len(st) != 1:
        return None
    s = st[0]
    qn = nodes[s].params["next"]
    if qn not in nodes or nodes[qn].op != "q" or nodes[qn].params["ovf"] != "wrap":
        return None
    ad = nodes[qn].args[0]
    if ad not in nodes or nodes[ad].op != "add" or s not in nodes[ad].args:
        return None
    others = [a for a in nodes[ad].args if a != s]
    x = others[0] if others else s
    if x in nodes or prog.nodes[x].fmt.F > nodes[s].fmt.F or nodes[ad].fmt.F != nodes[s].fmt.F:
        return None
    return s, ad, qn, x


# ---------------------------------------------------------------------- 入口
def run(prog: Prog, inputs, mode: str = "fixed", keep=None) -> Result:
    """执行原语程序。inputs：每个 input() 信号一个整数码数组，形状 (场景数, 样点数)。

    keep：需要保留取值的节点（缺省只保留输出与输入）；keep="all" 保留全部（只适合小程序）。
    其余节点在最后一次被使用后释放，以控制长 FIR 等大程序的内存。
    定点解释中，每个丢小数位的 q 就地统计输入功率与量化误差功率（Result.qstats），用于近似点噪声清单。"""
    if mode not in ("fixed", "ideal"):
        raise ValueError("mode in {fixed, ideal}")
    if prog.outputs is None:
        raise ContractError("structure", "build() never called g.output(...)")
    if len(inputs) != len(prog.inputs):
        raise ContractError("interface", f"expected {len(prog.inputs)} input array(s), got {len(inputs)}")
    nodes = prog.nodes
    vals: dict = {}
    sat: dict = {}
    qstats: dict = {}
    for k, i in enumerate(prog.inputs):
        x = np.atleast_2d(np.asarray(inputs[k], dtype=np.int64))
        vals[i] = x if mode == "fixed" else x * 2.0 ** -nodes[i].fmt.F

    comps = _sccs(prog)
    keep_all = keep == "all"
    keep = set(prog.outputs) | set(prog.inputs) | set(keep or ()) if not keep_all else None
    last = {}
    for pos, comp in enumerate(comps):
        for i in comp:
            for a in nodes[i].args:
                last[a] = pos
            if nodes[i].op == "state" and nodes[i].params["like"] is not None:
                last[nodes[i].params["like"]] = pos
    if prog.inputs:
        for pos, comp in enumerate(comps):
            if any(nodes[i].op == "state" and nodes[i].params["like"] is None for i in comp):
                last[prog.inputs[0]] = max(last.get(prog.inputs[0], 0), pos)

    def ev(i, args):
        nd = nodes[i]
        fmts = [nodes[a].fmt for a in nd.args]
        if nd.op in _POINTWISE:
            if mode == "fixed":
                box = [0]
                r = _fixed(nd.op, nd, fmts, args, sat_out=box)
                if box[0]:
                    sat[i] = sat.get(i, 0) + box[0]
                return r
            return _ideal(nd.op, nd, fmts, args)
        if nd.op == "interleave":
            return _interleave(nd, fmts, args, mode)
        return _structural(nd.op, nd, args[0], mode)

    for pos, comp in enumerate(comps):
        if len(comp) == 1 and nodes[comp[0]].op != "state":
            i = comp[0]
            if nodes[i].op != "input":
                vals[i] = ev(i, [vals[a] for a in nodes[i].args])
        else:
            _run_loop(prog, comp, vals, ev, mode)
        if mode == "fixed":
            for i in comp:
                nd = nodes[i]
                if nd.op == "q" and nodes[nd.args[0]].fmt.F > nd.fmt.F:
                    qstats[i] = _qstat(vals[nd.args[0]], nodes[nd.args[0]].fmt, vals[i], nd.fmt)
        if not keep_all:
            for i in comp:
                for a in set(nodes[i].args):
                    if last.get(a) == pos and a not in keep:
                        vals.pop(a, None)
            for i in comp:
                if i not in last and i not in keep:
                    vals.pop(i, None)

    outs = [vals[i] for i in prog.outputs]
    if mode == "fixed":
        sc = float(1 << (prog.out_bits - 1))
        outs = [np.asarray(o, dtype=float) / sc for o in outs]
    outs = _align(*[np.asarray(o, dtype=float) for o in outs])
    y = outs[0] if len(outs) == 1 else outs[0] + 1j * outs[1]
    r = Result(mode, vals, y, sat)
    r.qstats = qstats
    return r


def _qstat(x, fx: Fx, y, fy: Fx):
    """量化点的输入功率与误差功率（实数值）。"""
    if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
        return None
    m = min(x.shape[1], y.shape[1])
    xr = np.asarray(x[:, :m], dtype=float) * 2.0 ** -fx.F
    yr = np.asarray(y[:, :m], dtype=float) * 2.0 ** -fy.F
    return float(np.mean(xr ** 2)), float(np.mean((yr - xr) ** 2))


def _chunked_cumsum(x, init: float, wrap_fx, chunk: int = 1024):
    """理想解释的累加：wrap_fx 给出时每块之后按模回绕，避免长序列上中间值无界增长而丢失浮点精度。"""
    if wrap_fx is None:
        return np.cumsum(x, axis=1) + init
    lo = wrap_fx.lo * 2.0 ** -wrap_fx.F
    m = 2.0 ** (wrap_fx.W - wrap_fx.F)
    out = np.empty_like(x)
    carry = np.full(x.shape[0], float(init))
    for k in range(0, x.shape[1], chunk):
        c = np.cumsum(x[:, k:k + chunk], axis=1) + carry[:, None]
        c = np.mod(c - lo, m) + lo
        out[:, k:k + chunk] = c
        carry = c[:, -1]
    return out


def _run_loop(prog: Prog, comp, vals, ev, mode):
    nodes = prog.nodes
    for i in comp:
        if nodes[i].op not in _POINTWISE:
            raise ContractError("loop", f"{nodes[i].op} inside a feedback loop is not allowed; use state() for "
                                        f"extra delay", nodes[i].where)
    states = [i for i in comp if nodes[i].op == "state"]
    ext = sorted({a for i in comp for a in nodes[i].args if a not in comp})
    ext += [nodes[s].params["like"] if nodes[s].params["like"] is not None else prog.inputs[0] for s in states]
    n = None
    S = None
    for a in ext:
        v = vals[a]
        if isinstance(v, np.ndarray):
            S = v.shape[0]
            n = v.shape[1] if n is None else min(n, v.shape[1])
    if n is None:
        raise ContractError("loop", "feedback loop has no time-varying input; drive it with like=<signal>",
                            nodes[states[0]].where)

    acc = _accumulator(prog, comp)
    if acc is not None:
        s, ad, qn, x = acc
        sf, xf = nodes[s].fmt, nodes[x].fmt
        xv = vals[x]
        xv = (np.broadcast_to(xv, (S, n)) if not isinstance(xv, np.ndarray) else xv[:, :n])
        if mode == "fixed" and sf.W <= INT64_SAFE and xf.W <= INT64_SAFE:
            xa = _shl(np.asarray(xv, dtype=np.int64), sf.F - xf.F, sf.W)
            with np.errstate(over="ignore"):
                cs = np.cumsum(xa, axis=1, dtype=np.int64) + np.int64(nodes[s].params["code"])
            qv = _wrap(cs, nodes[qn].fmt)
            sv = np.concatenate([np.full((S, 1), nodes[s].params["code"], dtype=np.int64), qv[:, :-1]], axis=1)
            vals[s], vals[qn] = sv, qv
            vals[ad] = ev(ad, [vals[a] for a in nodes[ad].args])
            return
        if mode == "ideal":
            qv = ev(qn, [_chunked_cumsum(np.asarray(xv, dtype=float), nodes[s].params["init"],
                                         nodes[qn].fmt if nodes[qn].params["ovf"] == "wrap" else None)])
            sv = np.concatenate([np.full((S, 1), nodes[s].params["init"]), qv[:, :-1]], axis=1)
            vals[s], vals[qn] = sv, qv
            vals[ad] = ev(ad, [vals[a] for a in nodes[ad].args])
            return

    # 通用：逐样点求值
    cols = {i: [] for i in comp}
    cur = {}
    for s in states:
        init = nodes[s].params["code"] if mode == "fixed" else nodes[s].params["init"]
        cur[s] = np.full(S, init, dtype=np.int64 if mode == "fixed" else float)
    order = [i for i in comp if nodes[i].op != "state"]
    for m in range(n):
        for s in states:
            cols[s].append(cur[s])
        step = dict(cur)
        for i in order:
            args = []
            for a in nodes[i].args:
                if a in step:
                    args.append(step[a])
                else:
                    v = vals[a]
                    args.append(v[:, m] if isinstance(v, np.ndarray) else v)
            step[i] = ev(i, [np.asarray(x) if isinstance(x, np.ndarray) else x for x in args])
            cols[i].append(step[i])
        for s in states:
            cur[s] = step[nodes[s].params["next"]]
    for i in comp:
        vals[i] = np.stack([np.broadcast_to(c, (S,)) for c in cols[i]], axis=1)
