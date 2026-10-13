"""sdf：通用定点流式数据流构造接口。每个原语同时产生 Verilog、逐位整数值与代价。

这里没有任何算子（没有 FIR、CIC、NCO、CORDIC……），只有与算子无关的原语：
定点加减乘、常数缩放、移位、重量化（舍入/饱和/回绕）、查表、取位、选择、
流水寄存器、样点延迟线、积分器、抽取、计数器、常系数乘加（可分时复用乘法器）。
实现由调用方（LLM 写的 build 程序）用这些原语组合出来。

两种语义严格一致：
- 逐位整数语义（numpy）：构造的同时在给定输入上算出精确输出，用于快速打分；
- Verilog：最终设计用 iverilog 仿真，与整数语义逐位对拍。

时序（编译器自动处理，调用方只写样点级数学）：每个信号属于一个速率域（period =
每个样点的时钟周期数）并带有效周期 latency；组合时自动插入流水寄存器对齐；
不同速率域不能直接组合（需先 decimate）。

定点：信号 = 有符号/无符号整数码 × 2^-f；加法自动对齐小数点并扩 1 位，乘法位宽相加，
位宽只在 q() 处被裁剪；任何信号位宽不得超过 62。
"""

from __future__ import annotations

import math
from contextlib import contextmanager

import numpy as np

from .blocks import area
from .blocks.vlog import csd_digits, maxpat, minpat, sconst

MAX_WIDTH = 128
INT64_SAFE = 62      # 超过此宽度时数值改用 Python 任意精度整数（object 数组）
MAX_NODES = 60000


class BuildError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def _big(v, W):
    """结果宽度 W 超过 int64 安全范围时，把操作数转为任意精度整数数组。"""
    if isinstance(v, np.ndarray) and W > INT64_SAFE and v.dtype != object:
        return v.astype(object)
    return v


def _store(v, W):
    if isinstance(v, np.ndarray):
        if W > INT64_SAFE and v.dtype != object:
            return v.astype(object)
        if W <= INT64_SAFE and v.dtype == object:
            return v.astype(np.int64)
    return v


def _c(v, k):
    """与 v 的数组类型匹配的整数常数。"""
    return np.int64(k) if isinstance(v, np.ndarray) and v.dtype != object else int(k)


def _wrap(v, w):
    half = 1 << (w - 1)
    if isinstance(v, np.ndarray):
        if v.dtype == object or w > INT64_SAFE:
            v = v.astype(object)
            return ((v + half) & ((1 << w) - 1)) - half
        with np.errstate(over="ignore"):
            return ((v + np.int64(half)) & np.int64((1 << w) - 1)) - np.int64(half)
    return ((int(v) + half) & ((1 << w) - 1)) - half


class Sig:
    """W/F：实际位宽与小数位（生成硬件与数值）；w/f：名义值（调用方看到的）。

    正常运行时两者相同。诊断模式会把量化点加宽，实际值变大而名义值不变，
    因此同一份 build 程序无需修改即可在加宽条件下重跑。"""
    __slots__ = ("g", "name", "W", "F", "w", "f", "signed", "lin", "lat", "held", "v")

    def __init__(self, g, name, W, F, signed=True, lin=None, lat=0, held=False, v=None,
                 w=None, f=None):
        if W < 1 or W > MAX_WIDTH:
            raise BuildError("width", f"signal width {W} outside [1, {MAX_WIDTH}]; insert q() to "
                                      f"reduce width before this operation")
        self.g, self.name, self.W, self.F, self.signed = g, name, int(W), int(F), signed
        self.w = int(W if w is None else w)
        self.f = int(F if f is None else f)
        self.lin, self.lat, self.held, self.v = lin, lat, held, _store(v, self.W)

    @property
    def IB(self) -> int:
        return self.W - self.F

    @property
    def int_bits(self) -> int:
        return self.w - self.f

    @property
    def dF(self) -> int:
        return self.F - self.f

    @property
    def period(self):
        return None if self.lin is None else self.g._lin[self.lin]["period"]

    def __repr__(self):
        return f"Sig(w={self.w}, f={self.f}, {'signed' if self.signed else 'unsigned'}, period={self.period})"

    def __add__(self, o):
        return self.g.add(self, o)

    def __sub__(self, o):
        return self.g.sub(self, o)

    def __mul__(self, o):
        return self.g.mul(self, o) if isinstance(o, Sig) else self.g.scale(self, o)

    def __neg__(self):
        return self.g.neg(self)


class Graph:
    def __init__(self, spec, x_codes, extra_bits: int = 0, extra_scopes=None, top: str = "top",
                 auto_narrow: bool = False):
        """x_codes：int64 [场景, 样点] 的 ADC 码；extra_bits>0 用于诊断（加宽全部量化点）。

        auto_narrow=True：运算结果将超过 62 位时，自动截去输入的最低位（向下取整）并记录，
        而不是报错。"""
        self.auto_narrow = auto_narrow
        self.notes: list = []
        self.probes: list = []
        self.spec, self.top = spec, top
        self.x = np.atleast_2d(np.asarray(x_codes, dtype=np.int64))
        self.extra, self.extra_scopes = int(extra_bits), extra_scopes
        self.L: list[str] = []
        self._k = 0
        self._lin = {0: {"period": 1, "base_lat": 0}}
        self._valid = {(0, 0): "in_valid"}
        self._dec: dict = {}
        self._scope = ["top"]
        self.cost: dict = {}
        self.units: dict = {}      # 各类硬件资源的数量（位数等），用于校准单价
        self.sat: dict = {}
        self.stats = {"nodes": 0, "mults": 0, "rom_bits": 0, "primitives": {}}
        self._out = None
        self.y = None

    # ------------------------------------------------------------------ 基础设施
    def _n(self, p: str) -> str:
        self._k += 1
        if self._k > MAX_NODES:
            raise BuildError("size", f"design exceeds {MAX_NODES} nodes")
        return f"{p}{self._k}"

    def _use(self, prim: str, **costs):
        self.stats["nodes"] += 1
        self.stats["primitives"][prim] = self.stats["primitives"].get(prim, 0) + 1
        d = self.cost.setdefault(self._scope[-1], {})
        for k, units in costs.items():
            d[k] = d.get(k, 0.0) + units * area.C[k]
            self.units[k] = self.units.get(k, 0.0) + units

    @contextmanager
    def scope(self, name: str):
        """给一段电路命名：面积、饱和与诊断按此名称分组汇报。"""
        self._scope.append(str(name))
        try:
            yield
        finally:
            self._scope.pop()

    def _extra_here(self) -> int:
        if not self.extra:
            return 0
        return self.extra if (self.extra_scopes is None or self._scope[-1] in self.extra_scopes) else 0

    def _decl(self, s: Sig, expr: str | None = None, reg: bool = False) -> Sig:
        kind = "reg" if reg else "wire"
        sg = "signed " if s.signed else ""
        rng = f"[{s.W - 1}:0] " if (s.W > 1 or s.signed) else ""
        self.L.append(f"{kind} {sg}{rng}{s.name}" + (f" = {expr};" if expr is not None else ";"))
        return s

    def _chk(self, *sigs):
        for s in sigs:
            if not isinstance(s, Sig) or s.g is not self:
                raise BuildError("type", f"expected a signal from this graph, got {type(s).__name__}"
                                         f"; wrap numeric constants with g.const(value, w, f) or use g.scale")

    def _vld(self, lin: int, lat: int) -> str:
        if lat < self._lin[lin]["base_lat"]:
            raise BuildError("internal", "latency below rate-domain base")
        if (lin, lat) not in self._valid:
            prev = self._vld(lin, lat - 1)
            nm = self._n("v")
            self.L.append(f"reg {nm}; always @(posedge clk) if (rst) {nm} <= 1'b0; else {nm} <= {prev};")
            self._valid[(lin, lat)] = nm
            self._use("valid_pipe", reg_bit=1)
        return self._valid[(lin, lat)]

    def _s(self, x: Sig) -> Sig:
        if x.signed:
            return x
        y = Sig(self, self._n("s"), x.W + 1, x.F, True, x.lin, x.lat, x.held, x.v, x.w + 1, x.f)
        return self._decl(y, f"{{1'b0, {x.name}}}")

    def _ext(self, x: Sig, w: int, shl: int = 0) -> str:
        body = x.name if shl == 0 else f"{{{x.name}, {shl}'b0}}"
        cur = x.W + shl
        if w < cur:
            raise BuildError("internal", "extension narrower than source")
        if w == cur:
            return f"$signed({body})" if shl else x.name
        return f"$signed({{{{{w - cur}{{{x.name}[{x.W - 1}]}}}}, {body}}})"

    @staticmethod
    def _shl(v, k):
        return v << _c(v, k) if isinstance(v, np.ndarray) else int(v) << k

    def _narrow(self, x: Sig, k: int) -> Sig:
        """截去 k 个最低位（保持整数位，不会溢出）。"""
        if k <= 0 or x.lin is None and not isinstance(x.v, np.ndarray) and x.W - k < 2:
            return x
        if x.W - k < 2:
            raise BuildError("width", "cannot narrow signal further")
        self.notes.append(f"{self._scope[-1]}: 结果将超过 {MAX_WIDTH} 位，已自动截去输入最低 {k} 位")
        return self._q(x, x.W - k, x.F - k, "trunc", "wrap", x.w - k, x.f - k)

    def _fit(self, need: int, sigs):
        """若结果宽度 need 超过上限：auto_narrow 时把每个输入截去超出的位数，否则报错。"""
        if need <= MAX_WIDTH:
            return sigs
        if not self.auto_narrow:
            raise BuildError("width", f"result would be {need} bits (> {MAX_WIDTH}); insert g.q() "
                                      f"to reduce the inputs' width first")
        k = need - MAX_WIDTH
        return [self._narrow(x, k) if isinstance(x, Sig) and x.F >= k else x for x in sigs]

    # ------------------------------------------------------------------ 对齐
    def _pipe(self, x: Sig, n: int) -> Sig:
        for _ in range(n):
            y = Sig(self, self._n("p"), x.W, x.F, x.signed, x.lin, x.lat + 1, x.held, x.v, x.w, x.f)
            self._decl(y, reg=True)
            self.L.append(f"always @(posedge clk) {y.name} <= {x.name};")
            self._use("pipe_reg", reg_bit=x.W)
            x = y
        return x

    def _sync(self, sigs):
        timed = [s for s in sigs if s.lin is not None]
        if not timed:
            return sigs, None, 0, True
        lin = timed[0].lin
        for s in timed:
            if s.lin != lin:
                raise BuildError("rate_mismatch",
                                 f"cannot combine signals from different rate domains "
                                 f"(period {self._lin[lin]['period']} vs {self._lin[s.lin]['period']}); "
                                 f"bring a faster signal into a decimated domain with g.decimate(sig, r, phase) using the "
                                 f"same r (e.g. decimate a counter to get a phase at the slower rate)")
        P = self._lin[lin]["period"]
        tgt = max(s.lat for s in timed)
        out, held = [], True
        for s in sigs:
            if s.lin is None:
                out.append(s)
                continue
            d = tgt - s.lat
            if d == 0:
                held &= s.held
                out.append(s)
            elif s.held and d < P:
                held = False
                out.append(s)
            else:
                out.append(self._pipe(s, d))
                held &= s.held
        return out, lin, tgt, held

    def _hold(self, x: Sig) -> Sig:
        v = self._vld(x.lin, x.lat)
        y = Sig(self, self._n("h"), x.W, x.F, x.signed, x.lin, x.lat + 1, True, x.v, x.w, x.f)
        self._decl(y, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({v}) {y.name} <= {x.name};")
        self._use("hold_reg", reg_bit=x.W)
        return y

    # ------------------------------------------------------------------ 源
    def input(self) -> Sig:
        """实数 ADC 输入：有符号 input_bits 位、f = input_bits-1（数值范围 [-1, 1)）。"""
        b = self.spec.input_bits
        return Sig(self, "in_i", b, b - 1, True, 0, 0, False, self.x)

    def const(self, value: float, w: int, f: int) -> Sig:
        c = int(round(float(value) * 2.0**f))
        if not -(1 << (w - 1)) <= c < (1 << (w - 1)):
            raise BuildError("range", f"constant {value} does not fit w={w}, f={f}")
        y = Sig(self, self._n("c"), w, f, True, None, 0, True, c)
        return self._decl(y, sconst(c, w))

    def counter(self, step: int, bits: int) -> Sig:
        """无符号计数器（输入速率域）：第 n 个输入样点时值为 (n·step) mod 2^bits。"""
        if not 1 <= bits <= 48:
            raise BuildError("range", "counter bits in [1, 48]")
        step = int(step) % (1 << bits)
        n = self.x.shape[1]
        with np.errstate(over="ignore"):
            v = (np.arange(n, dtype=np.uint64) * np.uint64(step)) & np.uint64((1 << bits) - 1)
        v = np.broadcast_to(v.astype(np.int64), self.x.shape).copy()
        y = Sig(self, self._n("cnt"), bits, 0, False, 0, 0, False, v)
        self._decl(y, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if (in_valid) "
                      f"{y.name} <= {y.name} + {bits}'d{step};")
        self._use("counter", reg_bit=bits, adder_bit=bits)
        return y

    # ------------------------------------------------------------------ 组合运算
    def add(self, a: Sig, b: Sig) -> Sig:
        return self._addsub(a, b, "+")

    def sub(self, a: Sig, b: Sig) -> Sig:
        return self._addsub(a, b, "-")

    def _addsub(self, a, b, op):
        self._chk(a, b)
        a, b = self._s(a), self._s(b)
        a, b = self._fit(max(a.IB, b.IB) + 1 + max(a.F, b.F), [a, b])
        (a, b), lin, lat, held = self._sync([a, b])
        f = max(a.F, b.F)
        w = max(a.IB, b.IB) + 1 + f
        va, vb = self._shl(_big(a.v, w), f - a.F), self._shl(_big(b.v, w), f - b.F)
        fn = max(a.f, b.f)
        wn = max(a.int_bits, b.int_bits) + 1 + fn
        y = Sig(self, self._n("a"), w, f, True, lin, lat, held, va + vb if op == "+" else va - vb, wn, fn)
        self._decl(y, f"{self._ext(a, w, f - a.F)} {op} {self._ext(b, w, f - b.F)}")
        self._use("add", adder_bit=w)
        return y

    def neg(self, a: Sig) -> Sig:
        self._chk(a)
        a = self._s(a)
        y = Sig(self, self._n("n"), a.W + 1, a.F, True, a.lin, a.lat, a.held, -a.v, a.w + 1, a.f)
        self._decl(y, f"-{self._ext(a, a.W + 1)}")
        self._use("neg", adder_bit=a.W + 1)
        return y

    def mul(self, a: Sig, b: Sig) -> Sig:
        """通用乘法器（两个变量相乘）。"""
        self._chk(a, b)
        a, b = self._s(a), self._s(b)
        if a.W + b.W > MAX_WIDTH:
            if a.W >= b.W:
                a = self._fit(a.W + b.W, [a])[0]
            else:
                b = self._fit(a.W + b.W, [b])[0]
        (a, b), lin, lat, held = self._sync([a, b])
        y = Sig(self, self._n("m"), a.W + b.W, a.F + b.F, True, lin, lat, held,
                _big(a.v, a.W + b.W) * _big(b.v, a.W + b.W), a.w + b.w, a.f + b.f)
        self._decl(y, f"{a.name} * {b.name}")
        self._use("mul", mult_bit2=a.W * b.W)
        self.stats["mults"] += 1
        return y

    @staticmethod
    def _qconst(c: float, bits: int) -> tuple[int, int]:
        if c == 0:
            return 0, 0
        fc = bits - 1 - math.ceil(math.log2(abs(c)) + 1e-12)
        lim = (1 << (bits - 1)) - 1
        while True:
            ci = int(round(c * 2.0**fc))
            if abs(ci) <= lim:
                return ci, fc
            fc -= 1

    def scale(self, a: Sig, c: float, bits: int = 16) -> Sig:
        """乘以实常数 c：c 量化为 bits 位有效位，用移位加（CSD）实现，不占用乘法器。"""
        self._chk(a)
        if not 2 <= bits <= 32:
            raise BuildError("range", "scale bits in [2, 32]")
        ci, fc = self._qconst(float(c), bits + self._extra_here())
        return self._cmul(self._s(a), ci, fc, self._qconst(float(c), bits))

    @staticmethod
    def _strip(ci: int, fc: int) -> tuple[int, int]:
        if ci == 0:
            return 1, fc
        tz = (ci & -ci).bit_length() - 1
        return ci >> tz, fc - tz

    def _cmul(self, a: Sig, ci: int, fc: int, nominal=None) -> Sig:
        if ci == 0:
            return self.const(0.0, 2, 0)
        cin, fcn = self._strip(*(nominal or (ci, fc)))
        ci, fc = self._strip(ci, fc)
        a = self._fit(a.W + abs(ci).bit_length() + 1, [a])[0]
        w = a.W + abs(ci).bit_length() + 1
        dg = csd_digits(ci)
        y = Sig(self, self._n("k"), w, a.F + fc, True, a.lin, a.lat, a.held, _big(a.v, w) * ci,
                a.w + abs(cin).bit_length() + 1, a.f + fcn)
        ext = self._ext(a, w)
        terms = [("+ " if d > 0 else "- ") + (f"({ext} <<< {k})" if k else ext) for k, d in dg]
        expr = " ".join(terms)
        expr = expr[2:] if expr.startswith("+ ") else f"{w}'sd0 " + expr
        self._decl(y, expr)
        self._use("scale", const_add_bit=max(len(dg) - 1, 0) * w)
        return y

    def shift(self, a: Sig, k: int) -> Sig:
        """乘以 2^k（k 可正可负）：只移动小数点，不产生硬件。"""
        self._chk(a)
        return Sig(self, a.name, a.W, a.F - int(k), a.signed, a.lin, a.lat, a.held, a.v, a.w, a.f - int(k))

    def q(self, a: Sig, w: int, f: int, rnd: str = "round", ovf: str = "sat") -> Sig:
        """重量化到 w 位（含符号）、f 位小数。rnd: 'round'|'trunc'；ovf: 'sat'|'wrap'。

        ovf='wrap' 表示模运算语义（地址、相位、CIC 寄存器），诊断加宽时不改变它。"""
        self._chk(a)
        e = self._extra_here() if ovf == "sat" else a.F - a.f
        return self._q(a, int(w) + e, int(f) + e, rnd, ovf, int(w), int(f))

    def _q(self, a, w, f, rnd, ovf, wn=None, fn=None):
        wn, fn = (w if wn is None else wn), (f if fn is None else fn)
        self._chk(a)
        if rnd not in ("round", "trunc") or ovf not in ("sat", "wrap"):
            raise BuildError("choice", "rnd in {'round','trunc'}, ovf in {'sat','wrap'}")
        if not 2 <= w <= MAX_WIDTH:
            raise BuildError("width", f"q width {w} outside [2, {MAX_WIDTH}]")
        a = self._s(a)
        s = a.F - f
        tag = self._n("q")
        cur, cw, v = a.name, a.W, a.v
        n_add = 0
        if s > 0:
            if s >= cw:
                self.L.append(f"wire signed [{s}:0] {tag}_x = {self._ext(a, s + 1)};")
                cur, cw = f"{tag}_x", s + 1
            if rnd == "round":
                self.L.append(f"wire signed [{cw}:0] {tag}_r = $signed({{{cur}[{cw - 1}], {cur}}}) + "
                              f"{sconst(1 << (s - 1), cw + 1)};")
                self.L.append(f"wire signed [{cw - s}:0] {tag}_s = {tag}_r[{cw}:{s}];")
                cur, cw, n_add = f"{tag}_s", cw + 1 - s, cw
                v = (v + _c(v, 1 << (s - 1))) >> _c(v, s)
            else:
                self.L.append(f"wire signed [{cw - s - 1}:0] {tag}_s = {cur}[{cw - 1}:{s}];")
                cur, cw = f"{tag}_s", cw - s
                v = v >> _c(v, s)
        elif s < 0:
            if cw - s > MAX_WIDTH:
                raise BuildError("width", f"q would create a {cw - s}-bit intermediate")
            self.L.append(f"wire signed [{cw - s - 1}:0] {tag}_s = {{{cur}, {-s}'b0}};")
            cur, cw = f"{tag}_s", cw - s
            v = self._shl(_big(v, cw), -s)
        n_mux = 0
        if cw <= w:
            y = Sig(self, self._n("y"), w, f, True, a.lin, a.lat, a.held, v, wn, fn)
            self._decl(y, self._ext(Sig(self, cur, cw, f, True), w))
        elif ovf == "wrap":
            y = Sig(self, self._n("y"), w, f, True, a.lin, a.lat, a.held, _wrap(v, w), wn, fn)
            self._decl(y, f"{cur}[{w - 1}:0]")
        else:
            mx = (1 << (w - 1)) - 1
            if isinstance(v, np.ndarray):
                n_sat = int(np.count_nonzero((v > mx) | (v < -mx - 1)))
                vs = np.clip(v, -mx - 1, mx)
            else:
                n_sat, vs = int(v > mx or v < -mx - 1), min(max(v, -mx - 1), mx)
            if n_sat:
                sc = self._scope[-1]
                self.sat[sc] = self.sat.get(sc, 0) + n_sat
            y = Sig(self, self._n("y"), w, f, True, a.lin, a.lat, a.held, vs, wn, fn)
            self._decl(y, f"({cur} > {sconst(mx, cw)}) ? {maxpat(w)} : "
                          f"({cur} < {sconst(-mx - 1, cw)}) ? {minpat(w)} : {cur}[{w - 1}:0]")
            n_mux = w
        self._use("q", adder_bit=n_add, mux_bit=n_mux)
        return y

    def bits(self, a: Sig, hi: int, lo: int) -> Sig:
        """取位 a[hi:lo]（二进制补码位），结果为无符号整数。"""
        self._chk(a)
        if not 0 <= lo <= hi < a.w:
            raise BuildError("range", f"bits [{hi}:{lo}] outside signal width {a.w}")
        hi, lo = hi + a.dF, lo + a.dF
        m = (1 << (hi - lo + 1)) - 1
        v = (a.v >> _c(a.v, lo)) & _c(a.v, m)
        y = Sig(self, self._n("b"), hi - lo + 1, 0, False, a.lin, a.lat, a.held, v)
        return self._decl(y, f"{a.name}[{hi}:{lo}]")

    def mux(self, sel: Sig, a: Sig, b: Sig) -> Sig:
        """sel（1 位无符号，例如 bits(x, k, k)）为 1 选 a，否则选 b。"""
        self._chk(sel, a, b)
        if sel.W != 1 or sel.signed:
            raise BuildError("type", "mux select must be a 1-bit unsigned signal (use bits)")
        a, b = self._s(a), self._s(b)
        (sel, a, b), lin, lat, held = self._sync([sel, a, b])
        f = max(a.F, b.F)
        w = max(a.IB, b.IB) + f
        v = np.where(np.asarray(sel.v) != 0, self._shl(a.v, f - a.F), self._shl(b.v, f - b.F))
        v = int(v) if v.ndim == 0 else v
        fn = max(a.f, b.f)
        y = Sig(self, self._n("x"), w, f, True, lin, lat, held, v, max(a.int_bits, b.int_bits) + fn, fn)
        self._decl(y, f"{sel.name} ? {self._ext(a, w, f - a.F)} : {self._ext(b, w, f - b.F)}")
        self._use("mux", mux_bit=w)
        return y

    def lut(self, addr: Sig, values, w: int, f: int) -> Sig:
        """只读查找表：addr 为无符号信号，values 为实数列表（量化到 w 位、f 位小数）。"""
        self._chk(addr)
        if addr.signed:
            raise BuildError("type", "lut address must be unsigned (use bits or counter)")
        values = [float(x) for x in values]
        if not values or len(values) > (1 << addr.W) or len(values) > (1 << 16):
            raise BuildError("range", f"lut has {len(values)} entries for a {addr.W}-bit address "
                                      f"(at most 2^addr_bits and 65536)")
        e = self._extra_here()
        wn, fn = int(w), int(f)
        w, f = wn + e, fn + e
        if not 2 <= w <= 44:
            raise BuildError("width", "lut width in [2, 40]")
        lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
        codes = np.array([min(max(int(round(x * 2.0**f)), lo), hi) for x in values], dtype=np.int64)
        av = np.asarray(addr.v)
        v = np.where(av < len(codes), codes[np.minimum(av, len(codes) - 1)], 0)
        v = int(v) if v.ndim == 0 else v.astype(np.int64)
        y = Sig(self, self._n("t"), w, f, True, addr.lin, addr.lat, addr.held, v, wn, fn)
        self._decl(y, reg=True)
        body = " ".join(f"{addr.W}'d{i}: {y.name} = {sconst(int(c), w)};" for i, c in enumerate(codes))
        self.L.append(f"always @(*) begin case ({addr.name}) {body} default: {y.name} = 0; endcase end")
        self._use("lut", rom_bit=len(codes) * w)
        self.stats["rom_bits"] += len(codes) * w
        return y

    # ------------------------------------------------------------------ 时序原语
    def reg(self, a: Sig) -> Sig:
        """流水寄存器（多一个时钟周期，不改变样点序列）。"""
        self._chk(a)
        return a if a.lin is None else self._pipe(a, 1)

    def delay_line(self, a: Sig, n: int) -> list[Sig]:
        """返回 [x[k], x[k-1], ..., x[k-n+1]]：n 个对齐的抽头（共 n 个样点寄存器）。"""
        self._chk(a)
        if a.lin is None:
            raise BuildError("type", "cannot delay a constant")
        if not 1 <= n <= 8192:
            raise BuildError("range", "delay_line length in [1, 8192]")
        v = self._vld(a.lin, a.lat)
        names = [self._n("d") for _ in range(n)]
        sg = "signed " if a.signed else ""
        self.L.append(f"reg {sg}[{a.W - 1}:0] " + ", ".join(names) + ";")
        upd, prev, out = [], a.name, []
        z = np.zeros_like(a.v)
        for j, nm in enumerate(names):
            upd.append(f"{nm} <= {prev};")
            prev = nm
            vj = a.v if j == 0 else np.concatenate([z[:, :j], a.v[:, :-j]], axis=1)
            out.append(Sig(self, nm, a.W, a.F, a.signed, a.lin, a.lat + 1, True, vj, a.w, a.f))
        self.L.append("always @(posedge clk) if (rst) begin " + " ".join(f"{nm} <= 0;" for nm in names)
                      + f" end else if ({v}) begin " + " ".join(upd) + " end")
        self.stats["nodes"] += n
        self._use("delay_line", reg_bit=n * a.W)
        return out

    def delay(self, a: Sig, k: int) -> Sig:
        """x[n-k]（k ≥ 1）。与当前样点组合时直接组合即可，编译器会自动对齐。"""
        if k < 1:
            return a
        return self.delay_line(a, k + 1)[-1]

    def integrate(self, a: Sig, w: int) -> Sig:
        """累加器 y[n] = y[n-1] + x[n]，在 w 位上模 2^w 回绕。"""
        self._chk(a)
        a = self._s(a)
        if a.lin is None:
            raise BuildError("type", "cannot integrate a constant")
        if not a.w <= w <= MAX_WIDTH:
            raise BuildError("width", f"integrator width must be in [{a.w}, {MAX_WIDTH}]")
        wn, w = w, w + a.dF
        v = self._vld(a.lin, a.lat)
        with np.errstate(over="ignore"):
            val = _wrap(np.cumsum(_big(a.v, w), axis=1), w)
        y = Sig(self, self._n("i"), w, a.F, True, a.lin, a.lat + 1, True, val, wn, a.f)
        self._decl(y, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({v}) "
                      f"{y.name} <= {y.name} + {self._ext(a, w)};")
        self._use("integrate", reg_bit=w, adder_bit=w)
        return y

    def decimate(self, a: Sig, r: int, phase: int = 0) -> Sig:
        """每 r 个样点保留 1 个（第 m 个输出 = 输入下标 m·r + phase），进入 period×r 的速率域。

        同一来源、同一 r 的抽取（任意 phase）属于同一速率域，可以直接相加——这正是多相分解：
        Σ_p decimate(滤波分支_p(delay(x, p)), r, ...) 等。编译器把不同 phase 当作额外延迟自动对齐。
        要求输入每个时钟一个样点（in_valid 恒为 1）。
        """
        self._chk(a)
        if a.lin is None:
            raise BuildError("type", "cannot decimate a constant")
        r, phase = int(r), int(phase)
        if not 2 <= r <= 4096 or not 0 <= phase < r:
            raise BuildError("range", "decimate factor in [2, 4096], phase in [0, r)")
        key = (a.lin, r)
        cb = max(1, (r - 1).bit_length())
        p_src = self._lin[a.lin]["period"]
        if key not in self._dec:
            L0 = a.lat
            v0 = self._vld(a.lin, L0)
            cn, vn = self._n("dc"), self._n("dv")
            self.L.append(f"reg [{cb - 1}:0] {cn}; reg {vn};")
            self.L.append(f"always @(posedge clk) if (rst) begin {cn} <= 0; {vn} <= 1'b0; end else begin "
                          f"{vn} <= {v0} && ({cn} == {cb}'d0); if ({v0}) "
                          f"{cn} <= ({cn} == {cb}'d{r - 1}) ? {cb}'d0 : {cn} + {cb}'d1; end")
            lin = len(self._lin)
            self._lin[lin] = {"period": p_src * r, "base_lat": L0 + 1}
            self._valid[(lin, L0 + 1)] = vn
            self._dec[key] = {"lin": lin, "L0": L0, "cn": cn, "take": {}}
            self._use("decimate_ctl", reg_bit=cb + 1, adder_bit=cb)
        d = self._dec[key]
        if a.lat < d["L0"]:
            a = self._pipe(a, d["L0"] - a.lat)
        tk = d["take"]
        if (phase, d["L0"]) not in tk:
            nm = self._n("tk")
            self.L.append(f"wire {nm} = {self._vld(a.lin, d['L0'])} && ({d['cn']} == {cb}'d{phase});")
            tk[(phase, d["L0"])] = nm
        L = d["L0"]
        while (phase, a.lat) not in tk:
            L = max(l for (p, l) in tk if p == phase)
            nm = self._n("tk")
            self.L.append(f"reg {nm}; always @(posedge clk) if (rst) {nm} <= 1'b0; else {nm} <= {tk[(phase, L)]};")
            tk[(phase, L + 1)] = nm
        n_out = a.v.shape[1] // r
        y = Sig(self, self._n("z"), a.W, a.F, a.signed, d["lin"], a.lat + 1 + phase * p_src, True,
                a.v[:, phase::r][:, :n_out], a.w, a.f)
        self._decl(y, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({tk[(phase, a.lat)]}) "
                      f"{y.name} <= {a.name};")
        self._use("decimate", reg_bit=a.W)
        return y

    def mac(self, terms, coef_bits: int = 16, share: int = 1) -> Sig:
        """常系数乘加 Σ c_i·x_i。terms = [(信号, 实系数), ...]；系数共用一个缩放，量化到 coef_bits 位。

        share=1：每个乘积用移位加（CSD）实现，零系数不产生硬件。
        share=F>1：每个物理乘法器分时服务 F 个乘积，共 ceil(K/F) 个通用乘法器；
                   要求该速率域每个样点至少有 F 个时钟周期（F ≤ period）。
        """
        terms = list(terms)
        if not terms:
            raise BuildError("range", "mac needs at least one term")
        if not 2 <= int(coef_bits) <= 32:
            raise BuildError("range", "coef_bits in [2, 32]")
        sigs = [s for s, _ in terms]
        self._chk(*sigs)
        sigs = [self._s(s) for s in sigs]
        coefs = [float(c) for _, c in terms]
        cmax = max(abs(c) for c in coefs)
        if cmax == 0:
            return self.const(0.0, 2, 0)
        _, fc = self._qconst(cmax, int(coef_bits) + self._extra_here())
        _, fcn = self._qconst(cmax, int(coef_bits))
        ints = [int(round(c * 2.0**fc)) for c in coefs]
        ints_n = [int(round(c * 2.0**fcn)) for c in coefs]
        keep = [(s, ci, cn) for s, ci, cn in zip(sigs, ints, ints_n) if ci != 0]
        if not keep:
            return self.const(0.0, 2, 0)
        sigs, ints, ints_n = [k[0] for k in keep], [k[1] for k in keep], [k[2] for k in keep]
        if self.auto_narrow and len(sigs) > 1:
            fps, ibs = [], []
            for s_, ci in zip(sigs, ints):
                c2, f2 = self._strip(ci, fc)
                fps.append(s_.F + f2)
                ibs.append(s_.W + abs(c2).bit_length() + 1 - s_.F - f2)
            if int(share) > 1:
                cbw = max(abs(c) for c in ints).bit_length() + 1
                need = max(s_.IB for s_ in sigs) + max(s_.F for s_ in sigs) + cbw + \
                    math.ceil(math.log2(len(sigs))) + 1
            else:
                need = max(ibs) + math.ceil(math.log2(len(sigs))) + 1 + max(fps)
            sigs = self._fit(need, sigs)
        if int(share) > 1 and len(sigs) > 1:
            return self._mac_shared(sigs, ints, fc, int(share), ints_n, fcn)
        sigs, lin, lat, held = self._sync(sigs)
        prods = [self._cmul(s, ci, fc, (cn, fcn)) for s, ci, cn in zip(sigs, ints, ints_n)]
        if len(prods) == 1:
            return prods[0]
        f = max(p.F for p in prods)
        w = max(p.IB for p in prods) + math.ceil(math.log2(len(prods))) + 1 + f
        if w > MAX_WIDTH:
            raise BuildError("width", f"mac sum would be {w} bits; quantize inputs or use fewer coef_bits")
        acc = 0
        for p in prods:
            acc = acc + self._shl(_big(p.v, w), f - p.F)
        fn = max(p.f for p in prods)
        wn = max(p.int_bits for p in prods) + math.ceil(math.log2(len(prods))) + 1 + fn
        y = Sig(self, self._n("s"), w, f, True, lin, lat, held, acc, wn, fn)
        terms = [self._ext(p, w, f - p.F) for p in prods]
        if len(terms) > 1024:
            # 超长加法拆成每组 64 项的部分和，避免综合工具解析单条表达式时递归过深（数值不变）
            parts = []
            for k in range(0, len(terms), 64):
                nm = self._n("ps")
                self.L.append(f"wire signed [{w - 1}:0] {nm} = " + " + ".join(terms[k:k + 64]) + ";")
                parts.append(nm)
            terms = parts
        self._decl(y, " + ".join(terms))
        self._use("mac_sum", adder_bit=(len(prods) - 1) * w)
        return y

    def _mac_shared(self, sigs, ints, fc, F, ints_n, fcn):
        timed = [s for s in sigs if s.lin is not None]
        if not timed:
            raise BuildError("type", "shared mac needs at least one non-constant operand")
        lin = timed[0].lin
        P = self._lin[lin]["period"]
        K = len(sigs)
        F = min(F, K)
        if F > P:
            raise BuildError("timing", f"share={F} needs {F} clock cycles per sample but this rate "
                                       f"domain has period {P}; decimate earlier or reduce share")
        for _ in range(6):
            sigs, lin, T, _ = self._sync(sigs)
            bad = [i for i, s in enumerate(sigs) if s.lin is not None and
                   not (s.held and s.lat + P - 1 >= T + F - 1)]
            if not bad:
                break
            for i in bad:
                x = self._pipe(sigs[i], T - sigs[i].lat)
                sigs[i] = x if x.held else self._hold(x)
        else:
            raise BuildError("timing", f"cannot keep operands stable for share={F}; reduce share")
        f_in = max(s.F for s in sigs)
        w_in = max(s.IB for s in sigs) + f_in
        cbw = max(abs(c) for c in ints).bit_length() + 1
        wp = w_in + cbw
        nm = math.ceil(K / F)
        accw = wp + math.ceil(math.log2(K)) + 1
        if accw > MAX_WIDTH:
            raise BuildError("width", f"shared mac accumulator would be {accw} bits")
        tw = max(1, (F - 1).bit_length())
        t = self._n("mc")
        go = self._vld(lin, T)
        self.L.append(f"reg [{tw - 1}:0] {t}_tc; reg {t}_busy;")
        self.L.append(f"wire [{tw - 1}:0] {t}_ct = {go} ? {tw}'d0 : {t}_tc; wire {t}_act = {go} | {t}_busy;")
        self.L.append(f"always @(posedge clk) if (rst) begin {t}_tc <= 0; {t}_busy <= 1'b0; end else begin "
                      f"if ({t}_act && {t}_ct != {tw}'d{F - 1}) begin {t}_busy <= 1'b1; {t}_tc <= {t}_ct + {tw}'d1; end "
                      f"else begin {t}_busy <= 1'b0; {t}_tc <= 0; end end")
        accs, acc = [], 0
        for s, ci in zip(sigs, ints):
            acc = acc + self._shl(_big(s.v, accw), f_in - s.F) * ci
        for k in range(nm):
            self.L.append(f"reg signed [{w_in - 1}:0] {t}_s{k}; reg signed [{cbw - 1}:0] {t}_c{k};")
            rows = []
            for j in range(F):
                i = k * F + j
                if i < K:
                    rows.append(f"{tw}'d{j}: begin {t}_s{k} = {self._ext(sigs[i], w_in, f_in - sigs[i].F)}; "
                                f"{t}_c{k} = {sconst(ints[i], cbw)}; end")
            self.L.append(f"always @(*) begin case ({t}_ct) " + " ".join(rows)
                          + f" default: begin {t}_s{k} = 0; {t}_c{k} = 0; end endcase end")
            self.L.append(f"wire signed [{wp - 1}:0] {t}_p{k} = {t}_s{k} * {t}_c{k};")
            self.L.append(f"reg signed [{accw - 1}:0] {t}_a{k};")
            self.L.append(f"always @(posedge clk) if (rst) {t}_a{k} <= 0; else if ({t}_act) "
                          f"{t}_a{k} <= ({t}_ct == 0) ? $signed({t}_p{k}) : {t}_a{k} + $signed({t}_p{k});")
            accs.append(f"{t}_a{k}")
        fin_n = max(s.f for s in sigs)
        win_n = max(s.int_bits for s in sigs) + fin_n
        cb_n = max(max(abs(c) for c in ints_n).bit_length(), 1) + 1
        y = Sig(self, self._n("s"), accw, f_in + fc, True, lin, T + F, False, acc,
                win_n + cb_n + math.ceil(math.log2(K)) + 1, fin_n + fcn)
        self._decl(y, " + ".join(accs))
        self._vld(lin, T + F)
        self.stats["nodes"] += K
        self.stats["mults"] += nm
        self._use("mac_shared", mult_bit2=nm * w_in * cbw, mux_bit=nm * w_in * (F - 1),
                  rom_bit=K * cbw, reg_bit=nm * accw + tw + 1, adder_bit=nm * accw + (nm - 1) * accw)
        return y

    # ------------------------------------------------------------------ 观测
    def probe(self, name: str, i: Sig, q: Sig | None = None) -> None:
        """观测点（不产生硬件）：裁判报告该中间信号相对理想期望信号的带内 SNR、残留带外功率、
        增益与群时延。i/q 为复信号两路（实信号只给 i）。最多 8 个。"""
        self._chk(i, *([q] if q is not None else []))
        if len(self.probes) >= 8:
            raise BuildError("range", "at most 8 probes")
        if i.lin is None:
            raise BuildError("type", "cannot probe a constant")
        v = np.asarray(i.v).astype(np.float64) / 2.0 ** i.F
        if q is not None:
            if q.lin is None or self._lin[q.lin]["period"] != self._lin[i.lin]["period"]:
                raise BuildError("rate_mismatch", "probe i and q must have the same rate")
            vq = np.asarray(q.v).astype(np.float64) / 2.0 ** q.F
            n = min(v.shape[1], vq.shape[1])
            v = v[:, :n] + 1j * vq[:, :n]
        self.probes.append((str(name), v, self._lin[i.lin]["period"]))

    # ------------------------------------------------------------------ 输出与生成
    def output(self, i: Sig, q: Sig) -> None:
        """复基带输出：两路都必须是有符号 output_bits 位、f = output_bits-1。"""
        self._chk(i, q)
        if self._out is not None:
            raise BuildError("structure", "output() called twice")
        b = self.spec.output_bits
        for s, nm in ((i, "I"), (q, "Q")):
            if not s.signed or s.w != b or s.f != b - 1:
                raise BuildError("interface", f"output {nm} must be signed w={b}, f={b - 1} "
                                              f"(got w={s.W}, f={s.F}); finish with g.q(x, {b}, {b - 1})")
        if i.W != b or i.F != b - 1:     # 诊断模式：内部已加宽，回到接口格式
            i = self._q(i, b, b - 1, "round", "sat")
        if q.W != b or q.F != b - 1:
            q = self._q(q, b, b - 1, "round", "sat")
        (i, q), lin, lat, _ = self._sync([i, q])
        if lin is None:
            raise BuildError("structure", "output is constant")
        period = self._lin[lin]["period"]
        if period != self.spec.r_total:
            raise BuildError("decimation", f"output rate is input_rate/{period}, required "
                                           f"input_rate/{self.spec.r_total}")
        self._out = (i, q, self._vld(lin, lat))
        self.y = (np.asarray(i.v) + 1j * np.asarray(q.v)) / float(1 << (b - 1))

    def verilog(self) -> str:
        if self._out is None:
            raise BuildError("structure", "build() never called g.output(i, q)")
        i, q, v = self._out
        b, bo = self.spec.input_bits, self.spec.output_bits
        head = [f"module {self.top} (input wire clk, input wire rst, input wire in_valid, "
                f"input wire signed [{b - 1}:0] in_i, output wire out_valid, "
                f"output wire signed [{bo - 1}:0] out_i, output wire signed [{bo - 1}:0] out_q);"]
        tail = [f"assign out_valid = {v}; assign out_i = {i.name}; assign out_q = {q.name};", "endmodule"]
        return "\n".join(head + self.L + tail) + "\n"

    def area(self) -> dict:
        per = {k: float(sum(v.values())) for k, v in self.cost.items()}
        return {"total": float(sum(per.values())), "per_scope": per, "units": dict(self.units)}
