"""NCO + 实数输入到复基带的混频积木。

位语义：32 位相位累加 acc[n] = n·FCW mod 2^32；四分之一波表 Q+1 项
t[i] = round(sin(2πi/2^P)·(2^(W-1)-1))；lut_interp 用其后 I 位做
s + floor((s_next - s)·frac / 2^I)；混频 I = rnd(x·cos >> s)，
Q = -rnd(x·sin >> s)，s = Bx+W-1-Wm，饱和到 Wm。
"""

from __future__ import annotations

import numpy as np

from ..core import Block, Param, register
from . import area
from .fixed import ROUNDING, from_codes, sat, shift_round, to_codes

ACC_BITS = 32
MASK32 = (1 << ACC_BITS) - 1


def quarter_table(phase_bits: int, amp_bits: int) -> np.ndarray:
    q = 1 << (phase_bits - 2)
    a = (1 << (amp_bits - 1)) - 1
    return np.round(np.sin(2 * np.pi * np.arange(q + 1) / (1 << phase_bits)) * a).astype(np.int64)


def _lookup(idx, table, p):
    q = 1 << (p - 2)
    quad = (idx >> (p - 2)) & 3
    r = idx & (q - 1)
    v = table[np.where((quad == 1) | (quad == 3), q - r, r)]
    return np.where(quad >= 2, -v, v)


def nco_codes(p: dict, fcw: int, n: int):
    acc = (np.arange(n, dtype=np.int64) * np.int64(fcw)) & np.int64(MASK32)
    pb, w = p["phase_bits"], p["amp_bits"]
    table = quarter_table(pb, w)
    q, full = 1 << (pb - 2), (1 << pb) - 1
    idx = acc >> np.int64(ACC_BITS - pb)
    s0, c0 = _lookup(idx, table, pb), _lookup((idx + q) & full, table, pb)
    if p["nco_kind"] == "lut":
        return c0, s0
    ib = p["interp_bits"]
    sh = ACC_BITS - pb - ib
    frac = (acc >> np.int64(sh)) & np.int64((1 << ib) - 1)
    s1 = _lookup((idx + 1) & full, table, pb)
    c1 = _lookup((idx + q + 1) & full, table, pb)
    return c0 + (((c1 - c0) * frac) >> np.int64(ib)), s0 + (((s1 - s0) * frac) >> np.int64(ib))


@register
class NcoMixer(Block):
    type = "nco_mixer"
    doc = ("Numerically controlled oscillator (32-bit phase accumulator, quarter-wave sine "
           "table, optional linear interpolation) multiplying a real ADC input to produce "
           "complex baseband I/Q at the input rate. Phase truncation and table amplitude "
           "quantization create spurs; out_bits sets the mixer output word.")
    in_kind, out_kind = "real", "complex"
    params = (
        Param("nco_kind", "choice", "structure", "lut: table only; lut_interp: table + linear interpolation",
              choices=("lut", "lut_interp"), default="lut"),
        Param("phase_bits", "int", "precision", "phase bits addressing the full-wave table (table has 2^(P-2)+1 entries)",
              lo=6, hi=16, default=12, wide=16),
        Param("amp_bits", "int", "precision", "sine/cosine amplitude width",
              lo=8, hi=22, default=16, wide=20),
        Param("interp_bits", "int", "precision", "fractional phase bits used for interpolation",
              lo=1, hi=10, default=5, wide=8, when=lambda p: p.get("nco_kind") == "lut_interp"),
        Param("out_bits", "int", "precision", "mixer output width", lo=8, hi=26, default=18, wide=24),
        Param("rounding", "choice", "precision", "mixer output rounding", choices=ROUNDING,
              default="round", wide="round"),
    )

    def check(self, p, ctx):
        return p, {"width_out": p["out_bits"], "decim": 1}

    def run(self, x, p, ctx, aux, *, exact, ideal_coef, stats):
        spec = ctx["spec"]
        bx = ctx["width_in"]
        n = len(x)
        wn, wm = p["amp_bits"], p["out_bits"]
        if not exact:
            ph = 2 * np.pi * ((np.arange(n, dtype=np.float64) * spec.fcw) % 2**32) / 2**32
            return x * np.cos(ph) - 1j * x * np.sin(ph)
        xc = to_codes(x, bx)
        c, s = nco_codes(p, spec.fcw, n)
        sh = bx + wn - 1 - wm
        i_c, n1 = sat(shift_round(xc * c, sh, p["rounding"]), wm)
        q_c, n2 = sat(-shift_round(xc * s, sh, p["rounding"]), wm)
        stats["sat"] = n1 + n2
        return from_codes(i_c, wm) + 1j * from_codes(q_c, wm)

    def cost(self, p, ctx, aux):
        C = area.C
        pb, w = p["phase_bits"], p["amp_bits"]
        rom_bits = ((1 << (pb - 2)) + 1) * (w - 1)
        n_lookup = 4 if p["nco_kind"] == "lut_interp" else 2
        c = {"phase_acc": ACC_BITS * (C["adder_bit"] + C["reg_bit"]),
             "rom": n_lookup * rom_bits * C["rom_bit"],
             "multipliers": 2 * ctx["width_in"] * w * C["mult_bit2"],
             "out_reg": 2 * p["out_bits"] * (C["adder_bit"] + C["reg_bit"])}
        if p["nco_kind"] == "lut_interp":
            ib = p["interp_bits"]
            c["interp"] = 2 * ((w + 1) * ib * C["mult_bit2"] + 2 * (w + 1) * C["adder_bit"])
        return c


def _rtl(self, p, ctx, aux, module):
    from .vlog import header, neg_sat, rnd_sat, sv
    spec = ctx["spec"]
    bx, pb, w, wm = ctx["width_in"], p["phase_bits"], p["amp_bits"], p["out_bits"]
    table = quarter_table(pb, w)
    q = 1 << (pb - 2)
    L = header(module, bx, wm, complex_in=False)
    L.append("reg [31:0] acc;")
    L.append(f"always @(posedge clk) if (rst) acc <= 32'd0; else if (in_valid) acc <= acc + 32'd{spec.fcw};")
    L.append(f"function {sv(w)} tab; input [{pb - 2}:0] a; begin case (a)")
    for i, v in enumerate(table):
        L.append(f"  {pb - 1}'d{i}: tab = {v};")
    L.append(f"  default: tab = 0; endcase end endfunction")
    L.append(f"function {sv(w)} sinl; input [{pb - 1}:0] i; reg [{pb - 3}:0] r; reg [{pb - 2}:0] a; "
             f"reg {sv(w)} v; begin r = i[{pb - 3}:0]; "
             f"a = (i[{pb - 2}]) ? ({pb - 1}'d{q} - {{1'b0, r}}) : {{1'b0, r}}; v = tab(a); "
             f"sinl = (i[{pb - 1}]) ? -v : v; end endfunction")
    L.append(f"wire [{pb - 1}:0] idx = acc[31:{32 - pb}];")
    L.append(f"wire {sv(w)} s0 = sinl(idx);")
    L.append(f"wire {sv(w)} c0 = sinl(idx + {pb}'d{q});")
    if p["nco_kind"] == "lut":
        L += [f"wire {sv(w)} sv_ = s0;", f"wire {sv(w)} cv_ = c0;"]
    else:
        ib = p["interp_bits"]
        L.append(f"wire [{ib - 1}:0] frac = acc[{31 - pb}:{32 - pb - ib}];")
        L.append(f"wire {sv(w)} s1 = sinl(idx + {pb}'d1);")
        L.append(f"wire {sv(w)} c1 = sinl(idx + {pb}'d{q + 1});")
        for n_, a0, a1 in (("sv_", "s0", "s1"), ("cv_", "c0", "c1")):
            L.append(f"wire {sv(w + 1)} {n_}d = $signed({{{a1}[{w - 1}], {a1}}}) - $signed({{{a0}[{w - 1}], {a0}}});")
            L.append(f"wire {sv(w + 2 + ib)} {n_}p = {n_}d * $signed({{1'b0, frac}});")
            L.append(f"wire {sv(w + 2)} {n_}t = {n_}p >>> {ib};")
            L.append(f"wire {sv(w + 2)} {n_}w = $signed({{{{2{{{a0}[{w - 1}]}}}}, {a0}}}) + {n_}t;")
            L.append(f"wire {sv(w)} {n_} = {n_}w[{w - 1}:0];")
    sh = bx + w - 1 - wm
    L.append(f"wire {sv(bx + w)} pc = in_i * cv_;")
    L.append(f"wire {sv(bx + w)} ps = in_i * sv_;")
    L += rnd_sat("pc", bx + w, sh, p["rounding"], wm, "ri", "ri")
    L += rnd_sat("ps", bx + w, sh, p["rounding"], wm, "rs", "rs")
    L += neg_sat("rs", wm, "rq")
    L.append("always @(posedge clk) begin")
    L.append("  if (rst) begin out_valid <= 1'b0; out_i <= 0; out_q <= 0; end")
    L.append("  else begin out_valid <= in_valid; if (in_valid) begin out_i <= ri; out_q <= rq; end end")
    L.append("end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


NcoMixer.rtl = _rtl
