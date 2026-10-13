"""TaskGraph：在 sdf.Graph 上补充与链路无关的通用能力（不修改 sdf.py）。

- 接口由 Task 声明：输入/输出为实数或复数；输入每 in_period 个时钟一个样点，输出每 out_period 个时钟一个样点。
- interpolate：零值内插（速率提高 L 倍）。
- counter(like=sig)：在任意速率域运行的计数器（例如输出速率上的相位累加器）。
"""
from __future__ import annotations

import numpy as np

from dspgraph.sdf import BuildError, Graph, Sig


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
        if period != self.out_period:
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
    def counter(self, step: int, bits: int, like: Sig | None = None) -> Sig:
        """无符号计数器：第 n 个样点时值为 (n·step) mod 2^bits。默认在输入速率上计数；
        给出 like=sig 时在 sig 所在的速率域上计数（例如内插后的输出速率）。"""
        if not 1 <= bits <= 48:
            raise BuildError("range", "counter bits in [1, 48]")
        step = int(step) % (1 << bits)
        if like is None:
            lin, lat, shape = 0, 0, self.x.shape
        else:
            self._chk(like)
            if like.lin is None:
                raise BuildError("type", "counter(like=...) needs a non-constant signal")
            lin, lat, shape = like.lin, like.lat, np.asarray(like.v).shape
        with np.errstate(over="ignore"):
            v = (np.arange(shape[1], dtype=np.uint64) * np.uint64(step)) & np.uint64((1 << bits) - 1)
        v = np.broadcast_to(v.astype(np.int64), shape).copy()
        y = Sig(self, self._n("cnt"), bits, 0, False, lin, lat, False, v)
        self._decl(y, reg=True)
        self.L.append(f"always @(posedge clk) if (rst) {y.name} <= 0; else if ({self._vld(lin, lat)}) "
                      f"{y.name} <= {y.name} + {bits}'d{step};")
        self._use("counter", reg_bit=bits, adder_bit=bits)
        return y

    def interpolate(self, a: Sig, L: int) -> Sig:
        """零值内插：速率提高 L 倍，输出 y[kL] = x[k]，其余为 0（通常后接低通滤波并乘以 L 恢复幅度）。
        要求该信号每个样点占用的时钟周期数能被 L 整除。"""
        self._chk(a)
        if a.lin is None:
            raise BuildError("type", "cannot interpolate a constant")
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
