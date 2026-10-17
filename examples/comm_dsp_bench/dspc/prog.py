"""原语程序：A 层（数值语义）与 B 层（微结构承诺）。

候选程序写成 build(g, spec)，g 是 Prog。调用原语只记录节点与类型，不计算数值，也不生成硬件；
数值由 interp.run 按理想或定点两种解释执行。

A 层原语与两种解释（见 FRAMEWORK_v5.md §3）：
- 精确运算（两种解释一致）：add sub neg mul shift cmp abs min max select delay decimate interpolate
  repeat reframe state/close，以及在精确整数信号上的 bits / 位运算 / rom；
- 近似点（误差只能从这里进入）：q（舍入、饱和；回绕是模运算语义，两种解释一致）、const（值不可表示时）、
  lut（理想解释为 f(x)，定点解释为查表）。

速率：每个信号的速率是相对输入样点率的有理数（Fraction）；常数没有速率，可与任何速率组合。
相同速率的两个信号按样点序号逐一配对，与相位无关；硬件中的时延对齐由 lowering 负责。

B 层承诺挂在分段（scope）上，只约束“怎样造”，不改变任何数值。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction

from .fixtype import BOOL, ContractError, Fx

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_NODES = 60000
MAX_TABLE_BITS = 16

# 只有这些原语可能使两种解释不同（另有 bits/位运算/rom 作用在非精确信号上时，由 analysis 判定）
APPROX_OPS = ("q", "const", "lut")
COMMIT_KEYS = ("fold", "mul_max", "add_max", "latency_max", "storage", "reset", "warmup")


@dataclass
class Node:
    op: str
    args: tuple
    params: dict
    fmt: Fx
    rate: Fraction | None
    scope: str
    where: str


class Sig:
    """信号句柄。只携带类型与速率；数值由解释器给出。"""
    __slots__ = ("g", "i")

    def __init__(self, g: "Prog", i: int):
        self.g, self.i = g, i

    @property
    def node(self) -> Node:
        return self.g.nodes[self.i]

    @property
    def fmt(self) -> Fx:
        return self.node.fmt

    @property
    def rate(self):
        return self.node.rate

    def __repr__(self):
        r = "const" if self.rate is None else str(self.rate)
        return f"Sig#{self.i}({self.fmt}, rate={r})"

    def __add__(self, o):
        return self.g.add(self, o)

    def __sub__(self, o):
        return self.g.sub(self, o)

    def __mul__(self, o):
        return self.g.mul(self, o)

    def __neg__(self):
        return self.g.neg(self)


def _where() -> str:
    f = sys._getframe(2)
    while f is not None and os.path.dirname(os.path.abspath(f.f_code.co_filename)) == _PKG_DIR:
        f = f.f_back
    if f is None:
        return "?"
    return f"{os.path.basename(f.f_code.co_filename)}:{f.f_lineno}"


def _union(a: Fx, b: Fx) -> Fx:
    """能同时容纳 a 与 b 的最小格式。"""
    if a.signed != b.signed:
        a, b = a.as_signed(), b.as_signed()
    F = max(a.F, b.F)
    return Fx(max(a.IB, b.IB) + F, F, a.signed)


class Prog:
    """原语程序构造器。

    in_kind/out_kind: 'real' 或 'complex'；out_rate: 输出样点率相对输入样点率（例如抽取 32 为 1/32）；
    in_period: 每个输入样点占用的时钟数（决定各段可折叠的上限）。"""

    def __init__(self, *, in_bits: int, out_bits: int, in_kind: str = "real", out_kind: str = "complex",
                 out_rate=Fraction(1), in_period: int = 1, spec=None):
        self.in_bits, self.out_bits = int(in_bits), int(out_bits)
        self.in_kind, self.out_kind = in_kind, out_kind
        self.out_rate, self.in_period = Fraction(out_rate), int(in_period)
        self.spec = spec
        self.nodes: list[Node] = []
        self.outputs: list[int] | None = None
        self.inputs: list[int] = []
        self.commits: dict[str, dict] = {}
        self.iface: dict = {}
        self._scope = [""]
        self._open_states: set[int] = set()

    # ------------------------------------------------------------------ 基础
    def _new(self, op, args, params, fmt, rate) -> Sig:
        if len(self.nodes) >= MAX_NODES:
            raise ContractError("size", f"more than {MAX_NODES} primitive nodes", _where())
        self.nodes.append(Node(op, tuple(a.i for a in args), params, fmt, rate, self._scope[-1], _where()))
        return Sig(self, len(self.nodes) - 1)

    def _chk(self, *sigs):
        for s in sigs:
            if not isinstance(s, Sig) or s.g is not self:
                raise ContractError("type", f"expected a signal of this program, got {type(s).__name__}", _where())

    def _rate(self, *sigs):
        rs = {s.rate for s in sigs if s.rate is not None}
        if len(rs) > 1:
            raise ContractError("rate_mismatch",
                                "operands run at different sample rates " + ", ".join(sorted(map(str, rs)))
                                + "; use decimate/interpolate/repeat/reframe first", _where())
        return rs.pop() if rs else None

    @contextmanager
    def scope(self, name: str):
        """命名分段：用于承诺、面积与关键路径的回映。可嵌套，路径用 '/' 连接。"""
        if not name or "/" in name:
            raise ContractError("scope", "scope name must be non-empty and contain no '/'", _where())
        self._scope.append(f"{self._scope[-1]}/{name}" if self._scope[-1] else name)
        try:
            yield
        finally:
            self._scope.pop()

    # ------------------------------------------------------------------ 接口
    def input(self):
        """输入：实数接口返回一个信号，复数接口返回 (i, q)。有符号 in_bits 位，F = in_bits-1。"""
        if self.inputs:
            raise ContractError("structure", "input() called twice", _where())
        fx = Fx(self.in_bits, self.in_bits - 1, True)
        n = 1 if self.in_kind == "real" else 2
        sigs = [self._new("input", (), {"k": k}, fx, Fraction(1)) for k in range(n)]
        self.inputs = [s.i for s in sigs]
        return sigs[0] if n == 1 else tuple(sigs)

    def output(self, *sigs) -> None:
        """输出：必须是有符号 out_bits 位、F = out_bits-1，速率等于接口规定的输出速率。"""
        n = 1 if self.out_kind == "real" else 2
        if len(sigs) != n:
            raise ContractError("interface", f"output() expects {n} signal(s) for a {self.out_kind} output",
                                _where())
        self._chk(*sigs)
        if self.outputs is not None:
            raise ContractError("structure", "output() called twice", _where())
        want = Fx(self.out_bits, self.out_bits - 1, True)
        for s in sigs:
            if s.fmt != want:
                raise ContractError("interface", f"output must be {want} (got {s.fmt}); finish with "
                                                 f"g.q(x, {self.out_bits}, {self.out_bits - 1})", _where())
        r = self._rate(*sigs)
        if r != self.out_rate:
            raise ContractError("rate_mismatch", f"output rate {r} differs from the interface rate {self.out_rate}",
                                _where())
        if self._open_states:
            raise ContractError("structure", f"state() never closed: nodes {sorted(self._open_states)[:4]}",
                                _where())
        self.outputs = [s.i for s in sigs]

    # ------------------------------------------------------------------ 常数与精确运算
    def const(self, value: float, w: int, f: int, signed: bool = True) -> Sig:
        """常数。值不能精确表示时是近似点（理想解释取精确值，定点解释取舍入后的码）。"""
        fx = Fx(int(w), int(f), signed)
        c = int(round(float(value) * 2.0 ** fx.F))
        if not fx.lo <= c <= fx.hi:
            raise ContractError("range", f"constant {value} does not fit {fx}", _where())
        return self._new("const", (), {"value": float(value), "code": c}, fx, None)

    def add(self, a: Sig, b: Sig) -> Sig:
        return self._addsub("add", a, b)

    def sub(self, a: Sig, b: Sig) -> Sig:
        return self._addsub("sub", a, b)

    def _addsub(self, op, a, b):
        self._chk(a, b)
        fa, fb = a.fmt, b.fmt
        signed = fa.signed or fb.signed or op == "sub"
        if signed:
            fa, fb = fa.as_signed(), fb.as_signed()
        F = max(fa.F, fb.F)
        fx = Fx(max(fa.IB, fb.IB) + 1 + F, F, signed)
        return self._new(op, (a, b), {}, fx, self._rate(a, b))

    def neg(self, a: Sig) -> Sig:
        self._chk(a)
        fa = a.fmt.as_signed()
        return self._new("neg", (a,), {}, Fx(fa.W + 1, fa.F, True), a.rate)

    def mul(self, a: Sig, b: Sig) -> Sig:
        """全精度乘法（不丢位）。常数乘法也用它：mul(x, g.const(c, w, f))。"""
        self._chk(a, b)
        fa, fb = a.fmt, b.fmt
        if fa.signed != fb.signed:
            fa, fb = fa.as_signed(), fb.as_signed()
        return self._new("mul", (a, b), {}, Fx(fa.W + fb.W, fa.F + fb.F, fa.signed), self._rate(a, b))

    def scale(self, a: Sig, c: float, bits: int = 16) -> Sig:
        """乘以实常数 c：c 量化为 bits 位有效位（近似点，在 const 上），再做全精度乘法。"""
        if not 2 <= bits <= 32:
            raise ContractError("range", "scale bits in [2, 32]", _where())
        if c == 0:
            return self.const(0.0, 2, 0)
        f = bits - 1 - math.ceil(math.log2(abs(c)) + 1e-12)
        while abs(round(c * 2.0 ** f)) > (1 << (bits - 1)) - 1:
            f -= 1
        return self.mul(a, self.const(c, bits, f))

    def shift(self, a: Sig, k: int) -> Sig:
        """乘以 2^k：只移动小数点，两种解释一致。"""
        self._chk(a)
        return self._new("shift", (a,), {"k": int(k)}, Fx(a.fmt.W, a.fmt.F - int(k), a.fmt.signed), a.rate)

    def cmp(self, a: Sig, b: Sig, op: str) -> Sig:
        """比较：op in lt le gt ge eq ne，结果为 1 位无符号。"""
        self._chk(a, b)
        if op not in ("lt", "le", "gt", "ge", "eq", "ne"):
            raise ContractError("choice", "cmp op in {lt, le, gt, ge, eq, ne}", _where())
        return self._new("cmp", (a, b), {"op": op}, BOOL, self._rate(a, b))

    def abs(self, a: Sig) -> Sig:
        self._chk(a)
        fx = a.fmt if not a.fmt.signed else Fx(a.fmt.W, a.fmt.F, False)
        return self._new("abs", (a,), {}, fx, a.rate)

    def min(self, a: Sig, b: Sig) -> Sig:
        self._chk(a, b)
        return self._new("min", (a, b), {}, _union(a.fmt, b.fmt), self._rate(a, b))

    def max(self, a: Sig, b: Sig) -> Sig:
        self._chk(a, b)
        return self._new("max", (a, b), {}, _union(a.fmt, b.fmt), self._rate(a, b))

    def select(self, c: Sig, a: Sig, b: Sig) -> Sig:
        """c 非零取 a，否则取 b。"""
        self._chk(c, a, b)
        return self._new("select", (c, a, b), {}, _union(a.fmt, b.fmt), self._rate(c, a, b))

    # ------------------------------------------------------------------ 码字级运算
    def bits(self, a: Sig, hi: int, lo: int) -> Sig:
        """取整数码的第 hi..lo 位，结果为无符号整数（F=0）。"""
        self._chk(a)
        if not 0 <= lo <= hi < a.fmt.W:
            raise ContractError("range", f"bits({hi}, {lo}) outside a {a.fmt.W}-bit signal", _where())
        return self._new("bits", (a,), {"hi": int(hi), "lo": int(lo)}, Fx(hi - lo + 1, 0, False), a.rate)

    def band(self, a: Sig, b: Sig) -> Sig:
        return self._bitop("band", a, b)

    def bor(self, a: Sig, b: Sig) -> Sig:
        return self._bitop("bor", a, b)

    def bxor(self, a: Sig, b: Sig) -> Sig:
        return self._bitop("bxor", a, b)

    def _bitop(self, op, a, b):
        self._chk(a, b)
        for s in (a, b):
            if s.fmt.signed or s.fmt.F != 0:
                raise ContractError("type", f"{op} needs unsigned integers (F=0); use bits() first", _where())
        return self._new(op, (a, b), {}, Fx(max(a.fmt.W, b.fmt.W), 0, False), self._rate(a, b))

    def rom(self, addr: Sig, values, w: int, f: int, signed: bool = True) -> Sig:
        """按整数地址查表：values[addr]。值不可精确表示时是近似点。"""
        self._chk(addr)
        if addr.fmt.signed or addr.fmt.F != 0 or addr.fmt.W > MAX_TABLE_BITS:
            raise ContractError("type", f"rom address must be unsigned F=0 with at most {MAX_TABLE_BITS} bits",
                                _where())
        vals = [float(v) for v in values]
        if len(vals) != 1 << addr.fmt.W:
            raise ContractError("range", f"rom needs {1 << addr.fmt.W} values, got {len(vals)}", _where())
        fx = Fx(int(w), int(f), signed)
        codes = [int(round(v * 2.0 ** fx.F)) for v in vals]
        if any(not fx.lo <= c <= fx.hi for c in codes):
            raise ContractError("range", f"rom values do not fit {fx}", _where())
        return self._new("rom", (addr,), {"values": vals, "codes": codes}, fx, addr.rate)

    def lut(self, x: Sig, fn, addr_bits: int, w: int, f: int, mid: bool = False, signed: bool = True) -> Sig:
        """函数查表（近似点）：理想解释为 fn(x)；定点解释取 x 码的高 addr_bits 位作地址查表。

        表项 i 对应 x_i = (lo + i·Δ [+ Δ/2 若 mid]) · 2^-F，Δ = 2^(W - addr_bits)，值舍入到 (w, f) 并饱和。
        fn 必须能逐元素作用于 numpy 数组。"""
        self._chk(x)
        if not 1 <= addr_bits <= min(MAX_TABLE_BITS, x.fmt.W):
            raise ContractError("range", f"lut addr_bits in [1, min({MAX_TABLE_BITS}, {x.fmt.W})]", _where())
        import numpy as np
        fx = Fx(int(w), int(f), signed)
        step = 1 << (x.fmt.W - addr_bits)
        xi = (x.fmt.lo + np.arange(1 << addr_bits) * step + (step // 2 if mid else 0)) * 2.0 ** -x.fmt.F
        try:
            yi = np.asarray(fn(xi), dtype=float)
        except Exception as e:  # noqa: BLE001
            raise ContractError("lut", f"fn failed on the table grid: {e}", _where())
        if yi.shape != xi.shape or not np.all(np.isfinite(yi)):
            raise ContractError("lut", "fn must return one finite value per table entry", _where())
        codes = np.clip(np.round(yi * 2.0 ** fx.F), fx.lo, fx.hi).astype(np.int64).tolist()
        return self._new("lut", (x,), {"fn": fn, "addr_bits": int(addr_bits), "mid": bool(mid), "codes": codes},
                         fx, x.rate)

    # ------------------------------------------------------------------ 近似点：重量化
    def q(self, a: Sig, w: int, f: int, rnd: str = "round", ovf: str = "sat", signed: bool = True) -> Sig:
        """重量化到 (w, f)。rnd: round（四舍五入，0.5 向 +∞）| trunc（向 −∞）；ovf: sat | wrap。

        理想解释：舍入与饱和都视为不发生（取精确值）；wrap 是模运算语义，两种解释都按模 2^(w-f) 回绕。"""
        self._chk(a)
        if rnd not in ("round", "trunc") or ovf not in ("sat", "wrap"):
            raise ContractError("choice", "rnd in {round, trunc}, ovf in {sat, wrap}", _where())
        return self._new("q", (a,), {"rnd": rnd, "ovf": ovf}, Fx(int(w), int(f), signed), a.rate)

    # ------------------------------------------------------------------ 时间与速率
    def delay(self, a: Sig, n: int = 1) -> Sig:
        """y[m] = a[m-n]，初值为 0。"""
        self._chk(a)
        if n < 0:
            raise ContractError("range", "delay n >= 0", _where())
        if a.rate is None:
            return a
        return self._new("delay", (a,), {"n": int(n)}, a.fmt, a.rate)

    def decimate(self, a: Sig, r: int, phase: int = 0) -> Sig:
        """y[m] = a[m·r + phase]。"""
        self._chk(a)
        if r < 1 or not 0 <= phase < r:
            raise ContractError("range", "decimate needs r >= 1 and 0 <= phase < r", _where())
        if a.rate is None:
            raise ContractError("rate_mismatch", "cannot decimate a constant", _where())
        return self._new("decimate", (a,), {"r": int(r), "phase": int(phase)}, a.fmt, a.rate / r)

    def interpolate(self, a: Sig, n: int) -> Sig:
        """零值内插：y[m·n] = a[m]，其余为 0。"""
        return self._up("interpolate", a, n)

    def repeat(self, a: Sig, n: int) -> Sig:
        """保持内插：y[m] = a[m // n]。"""
        return self._up("repeat", a, n)

    def _up(self, op, a, n):
        self._chk(a)
        if n < 1:
            raise ContractError("range", f"{op} n >= 1", _where())
        if a.rate is None:
            raise ContractError("rate_mismatch", f"cannot {op} a constant", _where())
        return self._new(op, (a,), {"n": int(n)}, a.fmt, a.rate * n)

    def reframe(self, a: Sig, n_in: int, picks) -> Sig:
        """帧重排：每 n_in 个输入样点为一帧，输出帧依次取 picks 中的位置（可重复、可省略、可重排）。

        覆盖去/加循环前缀、位反序、串并转换。y[m] = a[n_in·(m // P) + picks[m % P]]，P = len(picks)。"""
        self._chk(a)
        picks = [int(p) for p in picks]
        if n_in < 1 or not picks or any(not 0 <= p < n_in for p in picks):
            raise ContractError("range", "reframe needs n_in >= 1 and 0 <= picks[j] < n_in", _where())
        if a.rate is None:
            raise ContractError("rate_mismatch", "cannot reframe a constant", _where())
        return self._new("reframe", (a,), {"n_in": int(n_in), "picks": picks}, a.fmt,
                         a.rate * Fraction(len(picks), n_in))

    def interleave(self, sigs) -> Sig:
        """并串转换：k 个同速率信号交织成一个 k 倍速率的流，y[k·m + j] = sigs[j][m]（同一信号可重复出现）。

        与 reframe（串并、帧内重排）配合即可表达块处理：例如 IDFT 先得到 N 个帧速率的输出，再按输出顺序交织。"""
        sigs = list(sigs)
        self._chk(*sigs)
        if not sigs:
            raise ContractError("range", "interleave needs at least one signal", _where())
        r = self._rate(*sigs)
        if r is None:
            raise ContractError("rate_mismatch", "cannot interleave constants only", _where())
        fx = sigs[0].fmt
        for x in sigs[1:]:
            fx = _union(fx, x.fmt)
        return self._new("interleave", tuple(sigs), {"k": len(sigs)}, fx, r * len(sigs))

    def state(self, w: int, f: int, init: float = 0.0, like: Sig | None = None, signed: bool = True) -> Sig:
        """反馈状态 s：s[0] = init，s[m+1] = next[m]（由 close 给出 next）。速率取 like 的速率（缺省为输入速率）。"""
        fx = Fx(int(w), int(f), signed)
        c = int(round(float(init) * 2.0 ** fx.F))
        if not fx.lo <= c <= fx.hi:
            raise ContractError("range", f"state init {init} does not fit {fx}", _where())
        if like is not None:
            self._chk(like)
        rate = Fraction(1) if like is None else like.rate
        if rate is None:
            raise ContractError("rate_mismatch", "state cannot run in the rate of a constant", _where())
        s = self._new("state", (), {"init": float(init), "code": c, "next": None,
                                    "like": None if like is None else like.i}, fx, rate)
        self._open_states.add(s.i)
        return s

    def close(self, s: Sig, nxt: Sig) -> None:
        self._chk(s, nxt)
        if s.node.op != "state" or s.node.params["next"] is not None:
            raise ContractError("structure", "close() needs a state that is not yet closed", _where())
        if nxt.fmt != s.fmt:
            raise ContractError("type", f"next value must have the state format {s.fmt} (got {nxt.fmt}); "
                                        f"use g.q(...) first", _where())
        if nxt.rate != s.rate:
            raise ContractError("rate_mismatch", f"next value rate {nxt.rate} differs from state rate {s.rate}",
                                _where())
        s.node.params["next"] = nxt.i
        self._open_states.discard(s.i)

    # ------------------------------------------------------------------ 语法糖（展开后仍是原语）
    def integrate(self, a: Sig, w: int) -> Sig:
        """累加器（模 2^w 回绕）：y[m] = Σ_{k≤m} a[k]，等价于 state + add + q(wrap)。"""
        s = self.state(w, a.fmt.F, 0.0, like=a)
        y = self.q(self.add(s, a), w, a.fmt.F, "trunc", "wrap")
        self.close(s, y)
        return y

    def counter(self, step: int, bits: int, like: Sig | None = None) -> Sig:
        """无符号计数器：第 m 个样点的值为 (m·step) mod 2^bits。"""
        s = self.state(bits, 0, 0.0, like=like, signed=False)
        nxt = self.q(self.add(s, self.const(int(step) % (1 << bits), bits, 0, signed=False)), bits, 0, "trunc",
                     "wrap", signed=False)
        self.close(s, nxt)
        return s

    # ------------------------------------------------------------------ B 层：微结构承诺
    def commit(self, scope: str | None = None, **kw) -> None:
        """在分段上登记承诺（不改变任何数值）：

        fold=k：时分复用因子；mul_max / add_max：运算单元上限；latency_max：该段延迟上限（时钟）；
        storage='reg'|'srl'|'ram'；reset='none'|'sync'；warmup=n：数据寄存器不复位时的暖机样点数。"""
        bad = set(kw) - set(COMMIT_KEYS)
        if bad:
            raise ContractError("commit", f"unknown commitment(s) {sorted(bad)}; allowed {COMMIT_KEYS}", _where())
        sc = self._scope[-1] if scope is None else scope
        if not sc:
            raise ContractError("commit", "commit() needs a named scope (use g.scope(...) or scope=...)", _where())
        if "storage" in kw and kw["storage"] not in ("reg", "srl", "ram"):
            raise ContractError("commit", "storage in {reg, srl, ram}", _where())
        if "reset" in kw and kw["reset"] not in ("none", "sync"):
            raise ContractError("commit", "reset in {none, sync}", _where())
        for k in ("fold", "mul_max", "add_max", "latency_max", "warmup"):
            if k in kw and (not isinstance(kw[k], int) or kw[k] < 0):
                raise ContractError("commit", f"{k} must be a non-negative integer", _where())
        self.commits.setdefault(sc, {}).update(kw)

    def interface(self, ii: int | None = None, latency_max: int | None = None) -> None:
        """顶层时序：ii = 每个输入样点占用的时钟数（缺省为接口的 in_period）；latency_max = 总延迟上限（时钟）。"""
        if ii is not None:
            self.iface["ii"] = int(ii)
        if latency_max is not None:
            self.iface["latency_max"] = int(latency_max)

    # ------------------------------------------------------------------ 规范化与哈希
    def a_layer(self) -> list:
        """A 层的规范表示：只含数值语义（不含分段名、承诺、源码位置）。"""
        out = []
        for n in self.nodes:
            p = {k: v for k, v in n.params.items() if k != "fn"}
            if n.op == "lut":
                p["codes"] = n.params["codes"]
            out.append([n.op, list(n.args), p, str(n.fmt), None if n.rate is None else str(n.rate)])
        return [out, self.outputs]

    def a_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.a_layer(), sort_keys=True).encode()).hexdigest()[:16]

    def b_hash(self) -> str:
        b = {"commits": self.commits, "iface": self.iface,
             "scopes": [n.scope for n in self.nodes]}
        return hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest()[:16]
