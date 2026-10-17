"""TaskGraph：在 sdf.Graph 上补充与链路无关的通用能力（不修改 sdf.py）。

- 接口由 Task 声明：输入/输出为实数或复数；输入每 in_period 个时钟一个样点，输出每 out_period 个时钟一个样点。
- interpolate：零值内插（速率提高 L 倍）。
- counter(like=sig)：在任意速率域运行的计数器（例如输出速率上的相位累加器）；modulus 给出非 2 的幂的模。
- gather：帧处理。按帧切分一个或多个同域信号，按给定顺序取出样点（去循环前缀、重排、并串转换）。
  其输出进入“不规则速率域”：每帧固定个数的样点，但相邻样点间隔不一定相等（只保证至少为原域的样点周期）。
  不规则域内可以照常组合、延迟、计数、分时复用乘法器，但不能再 decimate / interpolate。
- clock / state / close / sample：时钟域与反馈。clock 把样点流带进每个时钟都有效的自由运行域；state/close 是反馈寄存器；
  sample 按选通把时钟域的值取回成样点流。含时钟域的设计，其逐位语义由生成的 RTL 仿真给出（rtlsim.py）。
"""
from __future__ import annotations

import numpy as np

from dspgraph.sdf import BuildError, Graph, Sig, _big
from dspgraph.blocks.vlog import sconst


class TaskGraph(Graph):
    def __init__(self, spec, x_i, x_q=None, *, in_kind="real", out_kind="complex", in_period=1, out_period=1,
                 extra_bits=0, extra_scopes=None):
        super().__init__(spec, x_i, extra_bits, extra_scopes)
        self.xq = None if x_q is None else np.atleast_2d(np.asarray(x_q, dtype=np.int64))
        self.in_kind, self.out_kind, self.in_period, self.out_period = in_kind, out_kind, in_period, out_period
        self._lin[0]["period"] = in_period

    # ---- 接口
    def input(self):
        """输入信号：实数接口返回一个信号；复数接口返回 (i, q)。有符号 input_bits 位、f = input_bits-1。"""
        b = self.spec.input_bits
        held = self.in_period > 1          # 输入样点在下一个样点到来前保持（由测试平台保证）
        i = Sig(self, "in_i", b, b - 1, True, 0, 0, held, self.x)
        if self.in_kind == "real":
            return i
        return i, Sig(self, "in_q", b, b - 1, True, 0, 0, held, self.xq)

    def output(self, *sigs) -> None:
        """输出：实数接口给一个信号，复数接口给 (i, q)；都必须是有符号 output_bits 位、f = output_bits-1。"""
        n = 1 if self.out_kind == "real" else 2
        if len(sigs) != n:
            raise BuildError("interface", f"output() expects {n} signal(s) for a {self.out_kind} output")
        self._chk(*sigs)
        if self._out is not None:
            raise BuildError("structure", "output() called twice")
        b = self.spec.output_bits
        outs = []
        for s in sigs:
            if not s.signed or s.w != b or s.f != b - 1:
                raise BuildError("interface", f"output must be signed w={b}, f={b - 1} (got w={s.w}, f={s.f}); "
                                              f"finish with g.q(x, {b}, {b - 1})")
            outs.append(self._q(s, b, b - 1, "round", "sat") if (s.W != b or s.F != b - 1) else s)
        outs, lin, lat, _ = self._sync(outs)
        if lin is None:
            raise BuildError("structure", "output is constant")
        period = self._lin[lin]["period"]
        if self.out_period is not None and (period != self.out_period or self._lin[lin].get("irregular")):
            raise BuildError("rate", f"output has one sample per {period} clock(s); the interface requires one per "
                                     f"{self.out_period} (input: one per {self.in_period})")
        self._out = (outs, self._vld(lin, lat))
        sc = float(1 << (b - 1))
        self.y = np.asarray(outs[0].v) / sc if n == 1 else (np.asarray(outs[0].v) + 1j * np.asarray(outs[1].v)) / sc

    def verilog(self) -> str:
        if self._out is None:
            raise BuildError("structure", "build() never called g.output(...)")
        outs, v = self._out
        b, bo = self.spec.input_bits, self.spec.output_bits
        ports = ["input wire clk", "input wire rst", "input wire in_valid", f"input wire signed [{b - 1}:0] in_i"]
        if self.in_kind == "complex":
            ports.append(f"input wire signed [{b - 1}:0] in_q")
        ports += ["output wire out_valid", f"output wire signed [{bo - 1}:0] out_i"]
        tail = f"assign out_valid = {v}; assign out_i = {outs[0].name};"
        if self.out_kind == "complex":
            ports.append(f"output wire signed [{bo - 1}:0] out_q")
            tail += f" assign out_q = {outs[1].name};"
        return "\n".join([f"module {self.top} (" + ", ".join(ports) + ");"] + self.L + [tail, "endmodule"]) + "\n"

    # ---- 通用原语
    def counter(self, step: int, bits: int, like: Sig | None = None, modulus: int | None = None) -> Sig:
        """无符号计数器：第 n 个样点时值为 (n·step) mod 2^bits。默认在输入速率上计数；
        给出 like=sig 时在 sig 所在的速率域上计数（例如内插后的输出速率、gather 后的帧内序号）。
        modulus=M（M ≤ 2^bits）时改为 (n·step) mod M，用于长度不是 2 的幂的帧（例如 80 点 OFDM 符号）。"""
        if not 1 <= bits <= 48:
            raise BuildError("range", "counter bits in [1, 48]")
        mod = (1 << bits) if modulus is None else int(modulus)
        if not 2 <= mod <= (1 << bits):
            raise BuildError("range", f"counter modulus must be in [2, 2^bits] (bits={bits})")
        step = int(step) % mod
        if like is None:
            lin, lat, shape = 0, 0, self.x.shape
        else:
            self._chk(like)
            if like.lin is None:
                raise BuildError("type", "counter(like=...) needs a non-constant signal")
            lin, lat, shape = like.lin, like.lat, np.asarray(like.v).shape
        if modulus is None:
            with np.errstate(over="ignore"):
                v = (np.arange(shape[1], dtype=np.uint64) * np.uint64(step)) & np.uint64(mod - 1)
        else:
            v = (np.arange(shape[1], dtype=object) * step) % mod
        v = np.broadcast_to(v.astype(np.int64), shape).copy()
        y = Sig(self, self._n("cnt"), bits, 0, False, lin, lat, False, v)
        self._decl(y, reg=True)
        if modulus is None:
            nxt = f"{y.name} + {bits}'d{step}"
        else:
            nxt = (f"({{1'b0, {y.name}}} + {bits + 1}'d{step} >= {bits + 1}'d{mod}) ? "
                   f"{y.name} + {bits}'d{step} - {bits}'d{mod % (1 << bits)} : {y.name} + {bits}'d{step}")
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({self._vld(lin, lat)}) "
                      f"{y.name} <= {nxt};")
        self._use("counter", reg_bit=bits, adder_bit=bits * (1 if modulus is None else 2), mux_bit=0 if modulus is None else bits)
        return y

    def decimate(self, a: Sig, r: int, phase: int = 0) -> Sig:
        self._chk(a)
        if a.lin is not None and self._lin[a.lin].get("irregular"):
            raise BuildError("rate", "decimate is not defined on an irregular (gathered) rate domain; "
                                     "use g.gather to pick the samples you need instead")
        return super().decimate(a, r, phase)

    decimate.__doc__ = Graph.decimate.__doc__

    def interpolate(self, a: Sig, L: int) -> Sig:
        """零值内插：速率提高 L 倍，输出 y[kL] = x[k]，其余为 0（通常后接低通滤波并乘以 L 恢复幅度）。
        要求该信号每个样点占用的时钟周期数能被 L 整除。"""
        self._chk(a)
        if a.lin is None:
            raise BuildError("type", "cannot interpolate a constant")
        if self._lin[a.lin].get("irregular"):
            raise BuildError("rate", "interpolate is not defined on an irregular (gathered) rate domain")
        L = int(L)
        P = self._lin[a.lin]["period"]
        if L < 2 or P % L:
            raise BuildError("rate", f"interpolate by {L} needs a signal with a multiple of {L} clocks per sample "
                                     f"(this one has {P})")
        a = self._s(a)
        step = P // L
        cw = max(1, (P - 1).bit_length())
        src = self._vld(a.lin, a.lat)
        if not hasattr(self, "_interp"):
            self._interp = {}
        key = (a.lin, L, a.lat)          # 同源、同倍率、同时刻的内插共用计数器与速率域（I/Q 可直接组合）
        if key not in self._interp:
            c, vn = self._n("ic"), self._n("iv")
            ticks = " | ".join(f"({c} == {cw}'d{k * step})" for k in range(1, L))
            self.L.append(f"reg [{cw - 1}:0] {c}; reg {vn}; wire {c}_t = {src} | ({ticks});")
            self.L.append(f"always @(posedge clk) if (rst) begin {c} <= 0; {vn} <= 1'b0; end else begin "
                          f"{vn} <= {c}_t; if ({src}) {c} <= {cw}'d1; else if ({c} != 0) "
                          f"{c} <= ({c} == {cw}'d{P - 1}) ? {cw}'d0 : {c} + {cw}'d1; end")
            lin = len(self._lin)
            self._lin[lin] = {"period": step, "base_lat": a.lat + 1}
            self._valid[(lin, a.lat + 1)] = vn
            self._interp[key] = (lin, c)
            self._use("interpolate_ctl", reg_bit=cw + 1, adder_bit=cw)
        lin, c = self._interp[key]
        v = np.zeros((a.v.shape[0], a.v.shape[1] * L), dtype=np.asarray(a.v).dtype)
        v[:, ::L] = a.v
        y = Sig(self, self._n("u"), a.W, a.F, True, lin, a.lat + 1, True, v, a.w, a.f)
        self._decl(y, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({c}_t) "
                      f"{y.name} <= {src} ? {a.name} : {a.W}'sd0;")
        self._use("interpolate", reg_bit=a.W, mux_bit=a.W)
        return y

    # ---- 帧处理
    def gather(self, sigs, frame: int, picks, offset: int = 0) -> Sig:
        """帧重排：把 sigs（一个信号或同一速率域的信号列表）按帧切分，每帧 frame 个样点，按 picks 的顺序输出。
        picks 为 [n, ...] 或 [(n, s), ...]：第 f 帧的第 i 个输出 = sigs[s_i] 在样点 offset + f·frame + n_i 上的值
        （s 缺省为 0）。前 offset 个样点被丢弃（用于对齐前级的样点延迟）。要求 len(picks) ≤ frame。
        输出进入新的不规则速率域：每帧 len(picks) 个样点，相邻样点间隔至少为原域一个样点周期。
        帧内序号与 picks 的 n 相同、offset 相同的多次调用（例如 I 和 Q 两路）共用控制逻辑并处于同一速率域，可以直接组合。
        硬件：只取一个信号且 n 严格递增时为门控（无缓存，例如去循环前缀）；否则为双缓冲寄存器堆
        （每个 bank 存放不同 (n, s) 个字），在该帧最后一个被取的样点到达后，按 picks 顺序每个样点周期读出一个。"""
        sigs = [sigs] if isinstance(sigs, Sig) else list(sigs)
        if not sigs:
            raise BuildError("range", "gather needs at least one signal")
        self._chk(*sigs)
        frame, offset = int(frame), int(offset)
        pk = [(int(p), 0) if not isinstance(p, (tuple, list)) else (int(p[0]), int(p[1])) for p in picks]
        K = len(pk)
        if not 2 <= frame <= 4096 or not 1 <= K <= frame or offset < 0:
            raise BuildError("range", "gather: frame in [2, 4096], 1 ≤ len(picks) ≤ frame, offset ≥ 0")
        for n, s in pk:
            if not (0 <= n < frame and 0 <= s < len(sigs)):
                raise BuildError("range", f"gather pick {(n, s)} outside frame {frame} / {len(sigs)} signal(s)")
        if any(s.lin is None for s in sigs):
            raise BuildError("type", "gather needs non-constant signals")
        sigs = [self._s(s) if not s.signed else s for s in sigs]
        sigs, lin, lat, _ = self._sync(sigs)
        P = self._lin[lin]["period"]
        ns = tuple(n for n, _ in pk)
        gate = len(sigs) == 1 and all(a < b for a, b in zip(ns, ns[1:]))
        key = (lin, frame, ns, offset, "gate" if gate else "buf")
        if not hasattr(self, "_gather"):
            self._gather = {}
        if key in self._gather and lat != self._gather[key]["lat"]:
            L0 = self._gather[key]["lat"]
            if lat < L0:
                sigs = [self._pipe(s, L0 - lat) for s in sigs]
                lat = L0
            else:
                raise BuildError("timing", "gather calls that share a frame structure must see their inputs at the "
                                           "same time; call gather for the earlier-computed signal later in the "
                                           "program, or g.reg() the other inputs")
        pb = max(1, (frame - 1).bit_length())
        v = self._vld(lin, lat)
        if key not in self._gather:
            t = self._n("gf")
            en = "1'b1"
            if offset:
                ob = offset.bit_length()
                self.L.append(f"reg [{ob - 1}:0] {t}_sk; always @(posedge clk) if (rst) {t}_sk <= {ob}'d{offset}; "
                              f"else if ({v} && {t}_sk != 0) {t}_sk <= {t}_sk - 1'b1;")
                en = f"({t}_sk == 0)"
                self._use("gather_ctl", reg_bit=ob, adder_bit=ob)
            self.L.append(f"reg [{pb - 1}:0] {t}_pc; wire {t}_go = {v} && {en};")
            self.L.append(f"always @(posedge clk) if (rst) {t}_pc <= 0; else if ({t}_go) "
                          f"{t}_pc <= ({t}_pc == {pb}'d{frame - 1}) ? {pb}'d0 : {t}_pc + 1'b1;")
            self._use("gather_ctl", reg_bit=pb, adder_bit=pb)
            ctl = {"t": t, "lat": lat, "go": f"{t}_go", "pc": f"{t}_pc"}
            lin2 = len(self._lin)
            self._lin[lin2] = {"period": P, "base_lat": lat + 1, "irregular": True}
            ctl["lin"] = lin2
            if gate:
                hits = " | ".join(f"({t}_pc == {pb}'d{n})" for n in ns)
                self.L.append(f"wire {t}_hit = {t}_go && ({hits}); reg {t}_vo; "
                              f"always @(posedge clk) if (rst) {t}_vo <= 1'b0; else {t}_vo <= {t}_hit;")
                self._use("gather_ctl", reg_bit=1, adder_bit=pb * len(set(ns)) // 2)
                ctl["we"] = f"{t}_hit"
            else:
                nmax = max(ns)
                kb = max(1, (K - 1).bit_length())
                tb = max(1, (P - 1).bit_length())
                self.L.append(f"reg {t}_wb, {t}_rb, {t}_act, {t}_vo; reg [{kb - 1}:0] {t}_ri; reg [{tb - 1}:0] {t}_tm;")
                self.L.append(f"wire {t}_trig = {t}_go && ({t}_pc == {pb}'d{nmax}); "
                              f"wire {t}_tick = {t}_act && ({t}_tm == 0);")
                self.L.append(
                    f"always @(posedge clk) if (rst) begin {t}_wb <= 1'b0; {t}_rb <= 1'b0; {t}_act <= 1'b0; "
                    f"{t}_vo <= 1'b0; {t}_ri <= 0; {t}_tm <= 0; end else begin "
                    f"{t}_vo <= {t}_tick; "
                    f"if ({t}_go && {t}_pc == {pb}'d{frame - 1}) {t}_wb <= ~{t}_wb; "
                    f"if ({t}_act) {t}_tm <= ({t}_tm == {tb}'d{P - 1}) ? {tb}'d0 : {t}_tm + 1'b1; "
                    f"if ({t}_tick) begin {t}_ri <= {t}_ri + 1'b1; if ({t}_ri == {kb}'d{K - 1}) {t}_act <= 1'b0; end "
                    f"if ({t}_trig) begin {t}_act <= 1'b1; {t}_ri <= 0; {t}_tm <= 0; {t}_rb <= {t}_wb; end end")
                self._use("gather_ctl", reg_bit=4 + kb + tb, adder_bit=kb + tb + pb * (len(set(ns)) + 2) // 2)
                ctl["we"] = f"{t}_tick"
            self._valid[(lin2, lat + 1)] = f"{t}_vo"
            self._gather[key] = ctl
        ctl = self._gather[key]
        t, lin2 = ctl["t"], ctl["lin"]
        W = max(s.IB for s in sigs) + max(s.F for s in sigs)
        F = max(s.F for s in sigs)
        wn = max(s.int_bits for s in sigs) + max(s.f for s in sigs)
        fn = max(s.f for s in sigs)
        # 逐位整数语义
        n_tot = sigs[0].v.shape[1]
        nF = max(0, (n_tot - offset) // frame)
        vals = [self._shl(_big(s.v, W), F - s.F) for s in sigs]
        out = np.zeros((sigs[0].v.shape[0], nF * K), dtype=object if W > 62 else np.int64)
        for i, (n, s) in enumerate(pk):
            out[:, i::K] = vals[s][:, offset + n: offset + n + nF * frame: frame][:, :nF]
        y = Sig(self, self._n("gy"), W, F, True, lin2, ctl["lat"] + 1, True, out, wn, fn)
        self._decl(y, reg=True)
        ext = [self._ext(s, W, F - s.F) for s in sigs]
        if gate:
            self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({ctl['we']}) {y.name} <= {ext[0]};")
            self._use("gather", reg_bit=W)
        else:
            slots = list(dict.fromkeys(pk))
            sid = {p: j for j, p in enumerate(slots)}
            m = self._n("gm")
            self.L.append(f"reg signed [{W - 1}:0] {m}_a [0:{len(slots) - 1}]; reg signed [{W - 1}:0] {m}_b [0:{len(slots) - 1}];")
            byn = {}
            for j, (n, s) in enumerate(slots):
                byn.setdefault(n, []).append((j, s))
            wr = []
            for n, lst in byn.items():
                body = " ".join(f"if ({t}_wb) {m}_b[{j}] <= {ext[s]}; else {m}_a[{j}] <= {ext[s]};" for j, s in lst)
                wr.append(f"if ({ctl['go']} && {ctl['pc']} == {pb}'d{n}) begin {body} end")
            self.L.append("always @(posedge clk) begin " + " ".join(wr) + " end")
            kb = max(1, (K - 1).bit_length())
            self.L.append(f"reg [{max(1, (len(slots) - 1).bit_length()) - 1}:0] {m}_s;")
            cases = " ".join(f"{kb}'d{i}: {m}_s = {sid[p]};" for i, p in enumerate(pk))
            self.L.append(f"always @(*) begin case ({t}_ri) {cases} default: {m}_s = 0; endcase end")
            self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({t}_tick) "
                          f"{y.name} <= {t}_rb ? {m}_b[{m}_s] : {m}_a[{m}_s];")
            S = len(slots)
            self._use("gather", reg_bit=2 * S * W + W, mux_bit=(2 * S - 1) * W, rom_bit=K * kb)
        return y

    # ---- 时钟域与反馈
    # 时钟域：每个时钟都有效的自由运行速率域（样点 = 时钟周期）。含时钟域的设计的逐位语义由生成的 RTL 仿真给出
    # （见 dspgen/rtlsim.py），构造时的数值只是占位，因此这类设计不报告饱和计数。
    def _clock_domain(self) -> int:
        if getattr(self, "_clk", None) is None:
            lin = len(self._lin)
            self._lin[lin] = {"period": 1, "base_lat": 0, "free": True}
            self._valid[(lin, 0)] = "1'b1"
            self._clk = lin
            self._states = {}
            self.rtl_numerics = True
        return self._clk

    def _clk_zeros(self):
        return np.zeros((self.x.shape[0], self.x.shape[1] * max(1, self.in_period)), dtype=np.int64)

    def clock(self, *sigs):
        """把样点流带进时钟域（每个时钟都有效的自由运行速率域，样点 = 时钟周期，复位后立即开始）。
        参数为同一速率域的一个或多个信号；返回 ([h_1, ...], strobe)：h_k 在每个时钟给出 sig_k 最近一个已到达样点的值，
        strobe（1 位无符号）只在 h 刚更新的那个时钟为 1。时钟域内可以用全部原语（counter(like=h)、delay_line、lut、mux、
        add、mul……）以及 g.state / g.close 反馈寄存器。
        结果用 g.sample 送回样点流。"""
        sigs = list(sigs)
        if not sigs:
            raise BuildError("range", "clock needs at least one signal")
        self._chk(*sigs)
        if any(s.lin is None for s in sigs):
            raise BuildError("type", "clock needs non-constant signals")
        lc = self._clock_domain()
        if any(s.lin == lc for s in sigs):
            raise BuildError("type", "signal is already in the clock domain")
        sigs = [self._s(s) for s in sigs]
        sigs, lin, lat, _ = self._sync(sigs)
        v = self._vld(lin, lat)
        outs = []
        for s in sigs:
            h = Sig(self, self._n("ck"), s.W, s.F, True, lc, 0, False, self._clk_zeros(), s.w, s.f)
            self._decl(h, reg=True)
            self.L.append(f"always @(posedge clk) if (rst) {h.name} <= 0; else if ({v}) {h.name} <= {s.name};")
            self._use("clock", reg_bit=s.W)
            outs.append(h)
        st = Sig(self, self._n("cs"), 1, 0, False, lc, 0, False, self._clk_zeros())
        self._decl(st, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {st.name} <= 1'b0; else {st.name} <= {v};")
        self._use("clock", reg_bit=1)
        return outs, st

    def state(self, w: int, f: int, init: float = 0.0) -> Sig:
        """反馈寄存器（时钟域）：返回有符号 w 位、f 位小数的信号 r。必须随后调用 g.close(r, nxt) 指定它的下一个值：
        每个时钟 r ← nxt，复位后 r = init。用它可以写任意反馈（累加器、IIR、计数器、存储单元等）。"""
        lc = self._clock_domain()
        e = self._extra_here()
        wn, fn = int(w), int(f)
        W, F = wn + e, fn + e
        if not 1 <= W <= 62:
            raise BuildError("width", "state width in [1, 62]")
        c = int(round(float(init) * 2.0 ** F))
        if not -(1 << (W - 1)) <= c < (1 << (W - 1)):
            raise BuildError("range", f"init {init} does not fit w={wn}, f={fn}")
        r = Sig(self, self._n("st"), W, F, True, lc, 0, False, self._clk_zeros(), wn, fn)
        self._decl(r, reg=True)
        self._states[r.name] = {"sig": r, "init": c, "closed": False}
        self._use("state", reg_bit=W)
        return r

    def close(self, r: Sig, nxt: Sig) -> None:
        """闭合反馈寄存器：每个时钟 r ← nxt。nxt 必须是时钟域信号，名义位宽与小数位和 r 相同（先用 g.q(…, ovf='wrap'
        或 'sat') 裁成 r 的格式）。环路延迟 = 1 + d 个时钟，d 是 nxt 相对 r 多出的流水级数（经过 g.reg、delay_line、
        mac(share>1) 等会增加 d；只用组合运算时 d = 0，即 r[t+1] = nxt[t]）。"""
        self._chk(r, nxt)
        st = getattr(self, "_states", {}).get(r.name)
        if st is None or st["sig"] is not r:
            raise BuildError("type", "close() needs a signal returned by g.state()")
        if st["closed"]:
            raise BuildError("structure", "state closed twice")
        if nxt.lin != self._clk:
            raise BuildError("rate_mismatch", "close(): next value must be a clock-domain signal "
                                              "(derived from g.state / g.clock outputs)")
        nxt = self._s(nxt)
        if nxt.w != r.w or nxt.f != r.f:
            raise BuildError("width", f"close(): next value must have w={r.w}, f={r.f} like the state "
                                      f"(got w={nxt.w}, f={nxt.f}); use g.q(x, {r.w}, {r.f}, ovf=...) first")
        if nxt.W != r.W or nxt.F != r.F:
            nxt = self._q(nxt, r.W, r.F, "round", "wrap", r.w, r.f)
        if nxt.lat < r.lat:
            nxt = self._pipe(nxt, r.lat - nxt.lat)
        self.L.append(f"always @(posedge clk) if (rst) {r.name} <= {sconst(st['init'], r.W)}; "
                      f"else {r.name} <= {nxt.name};")
        st["closed"] = True
        st["loop_delay"] = 1 + nxt.lat - r.lat

    def sample(self, sig: Sig, strobe: Sig) -> Sig:
        """从时钟域取样点：在 strobe（1 位无符号时钟域信号）为 1 的时钟取 sig 的值，组成新的不规则样点流
        （相邻样点至少隔 1 个时钟）。同一个 strobe 取出的多个信号（例如 I、Q）处于同一速率域，可以直接组合；
        结果可接 gather、output 等。"""
        self._chk(sig, strobe)
        if sig.lin != getattr(self, "_clk", None) or strobe.lin != self._clk:
            raise BuildError("rate_mismatch", "sample() needs clock-domain signals")
        if strobe.W != 1 or strobe.signed:
            raise BuildError("type", "sample strobe must be a 1-bit unsigned signal (use bits)")
        sig = self._s(sig)
        (sig, strobe), lin, lat, _ = self._sync([sig, strobe])
        if not hasattr(self, "_samplers"):
            self._samplers = {}
        key = (strobe.name, lat)
        if key not in self._samplers:
            vo = self._n("sv")
            self.L.append(f"reg {vo}; always @(posedge clk) if (rst) {vo} <= 1'b0; else {vo} <= {strobe.name};")
            lin2 = len(self._lin)
            self._lin[lin2] = {"period": 1, "base_lat": lat + 1, "irregular": True}
            self._valid[(lin2, lat + 1)] = vo
            self._samplers[key] = lin2
            self._use("sample_ctl", reg_bit=1)
        lin2 = self._samplers[key]
        sv = np.asarray(strobe.v) != 0
        n = int(sv.sum(axis=1).min()) if sv.size else 0
        v = np.stack([np.asarray(sig.v)[k][sv[k]][:n] for k in range(sv.shape[0])])
        y = Sig(self, self._n("sy"), sig.W, sig.F, True, lin2, lat + 1, True, v, sig.w, sig.f)
        self._decl(y, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({strobe.name}) {y.name} <= {sig.name};")
        self._use("sample", reg_bit=sig.W)
        return y

    # ---- 存储
    def ram(self, data: Sig, waddr: Sig, we: Sig, raddr: Sig, depth: int) -> Sig:
        """可寻址存储（单写口、单读口，寄存器堆实现，复位清零）：在每个样点，先按 raddr 读出（读出的是此前写入的值），
        再在 we=1 时把 data 写入 waddr。data、waddr、we、raddr 必须处于同一速率域（常数可直接使用，例如 we 恒为 1）；
        waddr/raddr 为无符号信号，we 为 1 位无符号信号。读出值与输入同一样点、同一速率域。
        用途：重排（例如 FFT 倒位序、行列转置）、按地址存取的缓存（例如回溯、按子载波存放的估计值）。"""
        self._chk(data, waddr, we, raddr)
        depth = int(depth)
        if not 2 <= depth <= 4096:
            raise BuildError("range", "ram depth in [2, 4096]")
        for s, nm in ((waddr, "waddr"), (raddr, "raddr")):
            if s.signed:
                raise BuildError("type", f"ram {nm} must be unsigned (use bits or counter)")
            if (1 << s.W) < depth and s.lin is not None:
                pass
        if we.W != 1 or we.signed:
            raise BuildError("type", "ram we must be a 1-bit unsigned signal (use bits, or a const via bits)")
        data = self._s(data)
        (data, waddr, we, raddr), lin, lat, _ = self._sync([data, waddr, we, raddr])
        if lin is None:
            raise BuildError("type", "ram needs at least one non-constant input")
        shape = next(np.asarray(s.v).shape for s in (data, waddr, we, raddr) if s.lin is not None)
        B = lambda s: np.broadcast_to(np.asarray(s.v, dtype=object if data.W > 62 else np.int64), shape)
        dv, wa, wv, ra = B(data), B(waddr), B(we), B(raddr)
        rows, n = shape
        mem = np.zeros((rows, depth), dtype=dv.dtype)
        y = np.zeros(shape, dtype=dv.dtype)
        r_ix = np.arange(rows)
        for i in range(n):
            a = ra[:, i]
            ok = a < depth
            y[:, i] = np.where(ok, mem[r_ix, np.minimum(a, depth - 1)], 0)
            m = (wv[:, i] != 0) & (wa[:, i] < depth)
            if m.any():
                mem[r_ix[m], wa[m, i]] = dv[m, i]
        out = Sig(self, self._n("rm"), data.W, data.F, True, lin, lat, False, y, data.w, data.f)
        m = self._n("mem")
        v = self._vld(lin, lat)
        self.L.append(f"reg signed [{data.W - 1}:0] {m} [0:{depth - 1}];")
        self.L.append(f"integer {m}_k;")
        self.L.append(f"always @(posedge clk) if (rst) begin for ({m}_k = 0; {m}_k < {depth}; {m}_k = {m}_k + 1) "
                      f"{m}[{m}_k] <= 0; end else if ({v} && {we.name}[0] && {waddr.name} < {depth}) "
                      f"{m}[{waddr.name}] <= {data.name};")
        self._decl(out, f"({raddr.name} < {depth}) ? {m}[{raddr.name}] : {data.W}'sd0")
        self._use("ram", reg_bit=depth * data.W, mux_bit=depth * data.W, adder_bit=2 * max(1, (depth - 1).bit_length()))
        return out

    def probe(self, name: str, i: Sig, q: Sig | None = None) -> None:
        super().probe(name, i, q)
        if not hasattr(self, "rtl_probes"):
            self.rtl_probes = []
        self.rtl_probes.append((str(name), i, q))
