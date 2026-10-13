"""CIC 抽取积木（Hogenauer 结构，可选逐级剪枝近似）。

位语义：第 j 级输入先 floor 到 2^Bj 网格，整级在 Bmax 位上模回绕；
phase-0 抽取；输出 = rnd(comb >> (Bmax-Wout-g))，饱和到 Wout。
Bj 由 Hogenauer 噪声预算公式给出，prune_margin 平移它（正=保守，负=激进近似）。
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy import signal as sps

from ..core import Block, PlanError, Param, register
from . import area
from .fixed import ROUNDING, floor_grid, from_codes, per_component, sat, shift_round, to_codes, wrap


def cic_response(f, order, decim, m):
    rm = decim * m
    f = np.asarray(f, dtype=np.float64)
    num = np.sin(np.pi * f * rm)
    den = rm * np.sin(np.pi * f)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(np.abs(den) < 1e-15, 1.0, num / np.where(den == 0, 1, den))
    return r**order


def full_width(b_in, order, decim, m):
    return b_in + math.ceil(order * math.log2(decim * m) - 1e-12)


@lru_cache(maxsize=8192)
def discards(order, decim, m, b_in, b_out, margin):
    n = order
    if margin is None:
        return tuple([0] * (2 * n))
    b_final = full_width(b_in, order, decim, m) - b_out
    rm = decim * m
    out = []
    for j in range(1, 2 * n + 1):
        if j <= n:
            hk = []
            for k in range((rm - 1) * n + j):
                acc = 0
                for l in range(k // rm + 1):
                    a, b = n - j + k - rm * l, k - rm * l
                    if a >= b >= 0:
                        acc += (-1) ** l * math.comb(n, l) * math.comb(a, b)
                hk.append(acc)
        else:
            hk = [(-1) ** k * math.comb(2 * n + 1 - j, k) for k in range(2 * n + 2 - j)]
        f2 = float(sum(v * v for v in hk))
        bj = math.floor(b_final - 0.5 * math.log2(f2) - 0.5 * math.log2(2 * n))
        out.append(max(0, min(b_final, bj - margin)))
    return tuple(out)


@register
class CicDecim(Block):
    type = "cic_decim"
    doc = ("Cascaded integrator-comb decimator (multiplier-free). Response is sinc^order with "
           "droop in the passband and limited rejection near multiples of the output rate; "
           "registers grow by order*log2(decim*diff_delay) bits. Hogenauer pruning discards "
           "low bits per stage (prune_margin_bits: null = no pruning, 0 = textbook, negative = "
           "more aggressive approximation). gain_shift applies a 2^g digital gain before the "
           "output word (risk of saturation).")
    params = (
        Param("decim", "int", "structure", "decimation factor", lo=2, hi=64, default=8, rate=True),
        Param("order", "int", "structure", "number of integrator/comb stages", lo=1, hi=6, default=4),
        Param("diff_delay", "int", "structure", "comb differential delay", lo=1, hi=2, default=1),
        Param("prune_margin_bits", "int", "precision", "Hogenauer pruning margin (null = no pruning)",
              lo=-4, hi=8, default=0, wide=None, nullable=True),
        Param("out_bits", "int", "precision", "output width", lo=8, hi=40, default=20, wide=40),
        Param("rounding", "choice", "precision", "output rounding", choices=ROUNDING, default="trunc",
              wide="round"),
        Param("gain_shift", "int", "precision", "digital gain 2^g before output truncation",
              lo=0, hi=16, default=0, wide=0, scaling=True),
    )

    def check(self, p, ctx):
        b_max = full_width(ctx["width_in"], p["order"], p["decim"], p["diff_delay"])
        if b_max > 62:
            raise PlanError("width_overflow", ctx["path"], f"CIC register width {b_max} > 62")
        p = dict(p, out_bits=min(p["out_bits"], b_max))
        fp = ctx["spec"].passband
        if fp * ctx["rate_in"] * p["decim"] >= 0.5:
            raise PlanError("infeasible", ctx["path"], "passband exceeds output Nyquist of this block")
        return p, {"width_out": p["out_bits"], "decim": p["decim"]}

    def run(self, x, p, ctx, aux, *, exact, ideal_coef, stats):
        n_ord, r, m = p["order"], p["decim"], p["diff_delay"]
        b_in, w_out = ctx["width_in"], p["out_bits"]
        b_max = full_width(b_in, n_ord, r, m)
        if not exact:
            h = np.ones(r * m)
            for _ in range(n_ord - 1):
                h = np.convolve(h, np.ones(r * m))
            g = (r * m) ** n_ord / 2.0 ** (b_max - b_in) * 2.0 ** p["gain_shift"]
            h = h / h.sum() * g
            return sps.oaconvolve(x, h)[: len(x)][::r]
        disc = discards(n_ord, r, m, b_in, w_out, p["prune_margin_bits"])

        def one(v, st):
            c = to_codes(v, b_in)
            for j in range(n_ord):
                c = wrap(np.cumsum(floor_grid(c, disc[j])), b_max)
            c = c[::r]
            for j in range(n_ord):
                cin = floor_grid(c, disc[n_ord + j])
                d = np.concatenate([np.zeros(m, dtype=np.int64), cin[:-m]])
                c = wrap(cin - d, b_max)
            y, ns = sat(shift_round(c, b_max - w_out - p["gain_shift"], p["rounding"]), w_out)
            st["sat"] = ns
            return from_codes(y, w_out)
        return per_component(one, x, stats, "cic")

    def response(self, f, p, ctx, aux, quantized=True):
        return cic_response(np.asarray(f) * ctx["rate_in"], p["order"], p["decim"],
                            p["diff_delay"]).astype(np.complex128)

    def delay(self, p, ctx, aux):
        return p["order"] * (p["decim"] * p["diff_delay"] - 1) / 2.0 * ctx["rate_in"]

    def cost(self, p, ctx, aux):
        C = area.C
        n, r, m = p["order"], p["decim"], p["diff_delay"]
        b_max = full_width(ctx["width_in"], n, r, m)
        disc = discards(n, r, m, ctx["width_in"], p["out_bits"], p["prune_margin_bits"])
        integ = sum(b_max - disc[j] for j in range(n))
        comb = sum(b_max - disc[n + j] for j in range(n))
        per = (integ * (C["adder_bit"] + C["reg_bit"])
               + comb * (C["adder_bit"] + (m + 1) * C["reg_bit"])
               + p["out_bits"] * C["reg_bit"])
        return {"integrators_combs": 2 * per,
                "control": math.ceil(math.log2(r)) * (C["adder_bit"] + C["reg_bit"])}


def _rtl(self, p, ctx, aux, module):
    from .vlog import header, rnd_sat, sv
    n, r, m = p["order"], p["decim"], p["diff_delay"]
    b_in, w_out, g = ctx["width_in"], p["out_bits"], p["gain_shift"]
    b_max = full_width(b_in, n, r, m)
    disc = discards(n, r, m, b_in, w_out, p["prune_margin_bits"])
    L = header(module, b_in, w_out, complex_in=True)

    def rescale(src, w_src, b_src, b_dst, dst):
        w_dst = b_max - b_dst
        if b_dst >= b_src:
            k = b_dst - b_src
            ext = f"$signed({{{{{max(w_dst + k - w_src, 0)}{{{src}[{w_src - 1}]}}}}, {src}}})" \
                if w_dst + k > w_src else src
            return f"wire {sv(w_dst)} {dst} = {ext} >>> {k};" if k else \
                f"wire {sv(w_dst)} {dst} = {ext};"
        k = b_src - b_dst
        return f"wire {sv(w_dst)} {dst} = {{{src}, {k}'b0}};"

    # 相位/暖机计数：pipelined 积分器使 acc_N 晚 N-1 个样点
    pw = max(1, (r - 1).bit_length())
    init = (-(n - 1)) % r
    ww = max(1, n.bit_length())
    L.append(f"reg [{pw - 1}:0] ph; reg [{ww - 1}:0] warm; reg take;")
    L.append("always @(posedge clk) begin")
    L.append(f"  if (rst) begin ph <= {pw}'d{init}; warm <= 0; take <= 1'b0; end")
    L.append("  else begin take <= in_valid && (ph == 0) && (warm >= " + str(n - 1) + ");")
    L.append(f"    if (in_valid) begin ph <= (ph == {pw}'d{r - 1}) ? {pw}'d0 : ph + {pw}'d1;"
             f" if (warm < {n - 1}) warm <= warm + 1; end end")
    L.append("end")
    for ch in ("i", "q"):
        src, w_src, b_src = f"in_{ch}", b_in, 0
        for j in range(n):
            bj = disc[j]
            L.append(rescale(src, w_src, b_src, bj, f"{ch}_ii{j}"))
            wj = b_max - bj
            L.append(f"reg {sv(wj)} {ch}_acc{j};")
            L.append(f"always @(posedge clk) if (rst) {ch}_acc{j} <= 0; "
                     f"else if (in_valid) {ch}_acc{j} <= {ch}_acc{j} + {ch}_ii{j};")
            src, w_src, b_src = f"{ch}_acc{j}", wj, bj
        for j in range(n):
            bj = disc[n + j]
            wj = b_max - bj
            L.append(rescale(src, w_src, b_src, bj, f"{ch}_ci{j}"))
            for t in range(m):
                L.append(f"reg {sv(wj)} {ch}_dl{j}_{t};")
            prev = f"{ch}_ci{j}"
            upd = []
            for t in range(m):
                upd.append(f"{ch}_dl{j}_{t} <= {prev};")
                prev = f"{ch}_dl{j}_{t}"
            L.append(f"always @(posedge clk) if (rst) begin "
                     + " ".join(f"{ch}_dl{j}_{t} <= 0;" for t in range(m))
                     + " end else if (take) begin " + " ".join(upd) + " end")
            L.append(f"wire {sv(wj)} {ch}_co{j} = {ch}_ci{j} - {ch}_dl{j}_{m - 1};")
            src, w_src, b_src = f"{ch}_co{j}", wj, bj
        s_rel = b_max - w_out - g - b_src
        L += rnd_sat(src, w_src, s_rel, p["rounding"], w_out, f"{ch}_res", f"{ch}_rs")
    L.append("always @(posedge clk) begin")
    L.append("  if (rst) begin out_valid <= 1'b0; out_i <= 0; out_q <= 0; end")
    L.append("  else begin out_valid <= take; if (take) begin out_i <= i_res; out_q <= q_res; end end")
    L.append("end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


CicDecim.rtl = _rtl
