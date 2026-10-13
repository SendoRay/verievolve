"""线性相位 FIR 抽取积木（通用低通 / 半带，可选补偿上游下垂，可折叠）。

滤波器由积木内部从规格与上下文确定性设计：通带 = 规格通带，阻带边缘 = 本级
输出率 − 通带（防止折入通带的混叠）。compensate_upstream 让通带目标等于上游
LTI 积木（如 CIC）频响的倒数。

位语义：acc = Σ q_i·x[mD-i]（精确）；out = rnd(acc >> (frac+Win-Wout-g))，饱和。
fold 只改变硬件（每个乘法器服务 fold 个对称乘积），不改变数值。
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy import signal as sps

from ..core import Block, PlanError, Param, register, upstream_response
from . import area
from .fixed import ROUNDING, from_codes, per_component, sat, shift_round, to_codes


def unique_mults(kind: str, taps: int) -> int:
    return (taps + 1) // 4 if kind == "halfband" else (taps + 1) // 2


def _robust_lowpass(taps, fp_k, fs_k, stop_weight):
    """等波纹设计；不收敛时依次退回最小二乘与 Kaiser 窗设计（均为确定性）。"""
    try:
        h = sps.remez(taps, [0, fp_k, fs_k, 0.5], [1, 0], weight=[1, stop_weight], fs=1.0,
                      maxiter=200)
        if np.all(np.isfinite(h)):
            return h
    except Exception:
        pass
    try:
        h = sps.firls(taps, [0, fp_k, fs_k, 0.5], [1, 1, 0, 0], weight=[1, stop_weight], fs=1.0)
        if np.all(np.isfinite(h)):
            return h
    except Exception:
        pass
    return sps.firwin(taps, 0.5 * (fp_k + fs_k), window=("kaiser", 8.0), fs=1.0)


@lru_cache(maxsize=8192)
def _design(kind, taps, fp_k, fs_k, stop_weight, comp_key, comp_gains):
    if kind == "halfband":
        h = _robust_lowpass(taps, fp_k, 0.5 - fp_k, 1.0)
        c = taps // 2
        idx = np.arange(taps) - c
        h = np.where((idx % 2 == 0) & (idx != 0), 0.0, h)
        h[c] = 0.5
        odd = idx % 2 != 0
        s = h[odd].sum()
        if abs(s) > 1e-12:
            h[odd] *= 0.5 / s
        return tuple(h)
    if comp_gains is None:
        h = _robust_lowpass(taps, fp_k, fs_k, stop_weight)
    else:
        edges = np.linspace(0, fp_k, len(comp_gains))
        bands, desired = [], []
        for a, b, ga, gb in zip(edges[:-1], edges[1:], comp_gains[:-1], comp_gains[1:]):
            bands += [a, b]
            desired += [ga, gb]
        bands += [fs_k, 0.5]
        desired += [0, 0]
        try:
            h = sps.firls(taps, bands, desired, weight=[1] * (len(edges) - 1) + [stop_weight], fs=1.0)
        except Exception:
            h = None
        if h is None or not np.all(np.isfinite(h)):
            h = _robust_lowpass(taps, fp_k, fs_k, stop_weight)
    h = np.asarray(h)
    if abs(h.sum()) > 1e-12:
        h = h / h.sum()
    return tuple(h)


def quantize(h: np.ndarray, bits: int):
    mx = float(np.max(np.abs(h)))
    frac = bits - 1 - (math.ceil(math.log2(mx)) if mx > 0 else 0)
    lim = (1 << (bits - 1)) - 1
    while True:
        q = np.round(h * 2.0**frac).astype(np.int64)
        if np.max(np.abs(q)) <= lim:
            return q, frac
        frac -= 1


def _resp(h, nu):
    return sps.freqz(h, worN=2 * np.pi * np.asarray(nu))[1]


@register
class FirDecim(Block):
    type = "fir_decim"
    doc = ("Linear-phase FIR decimator designed automatically from the spec passband and this "
           "block's output rate (stopband edge = output rate - passband). 'lowpass' is a "
           "general equiripple filter; 'halfband' (decim 2, taps 4m+3) has every other "
           "coefficient zero, so it needs about half the multipliers but requires passband < "
           "input_rate/4. compensate_upstream flattens the droop of upstream blocks such as "
           "CIC. coef_bits quantizes coefficients (fewer bits = fewer CSD adders but worse "
           "stopband). fold > 1 time-shares each multiplier over fold products using the "
           "spare clock cycles available after decimation (requires fold <= clock cycles between "
           "input samples of this block); fold = 1 uses fixed constant multipliers.")
    params = (
        Param("filter_kind", "choice", "structure", "lowpass or halfband",
              choices=("lowpass", "halfband"), default="lowpass"),
        Param("decim", "int", "structure", "decimation factor", lo=2, hi=8, default=2, rate=True),
        Param("taps", "int", "structure", "odd number of taps", lo=3, hi=255, default=31, step=2),
        Param("compensate_upstream", "bool", "structure", "equalize upstream passband droop",
              default=False, when=lambda p: p.get("filter_kind", "lowpass") == "lowpass"),
        Param("stop_weight", "float", "structure", "stopband/passband error weight in design",
              lo=0.1, hi=1000.0, default=10.0),
        Param("coef_bits", "int", "precision", "coefficient width", lo=4, hi=26, default=16, wide=22),
        Param("out_bits", "int", "precision", "output width", lo=8, hi=32, default=18, wide=24),
        Param("rounding", "choice", "precision", "output rounding", choices=ROUNDING,
              default="round", wide="round"),
        Param("gain_shift", "int", "precision", "digital gain 2^g before output truncation",
              lo=0, hi=16, default=0, wide=0, scaling=True),
        Param("fold", "int", "micro", "multiplier time-sharing factor", lo=1, hi=4096, default=1,
              numeric=False),
    )

    def repair(self, p):
        p = dict(p)
        if "taps" in p and p["taps"] % 2 == 0:
            p["taps"] += 1
        if p.get("filter_kind") == "halfband":
            p["decim"] = 2
            p["compensate_upstream"] = False
            if p.get("taps", 3) % 4 != 3:
                p["taps"] = 4 * max(0, (p["taps"] - 3 + 2) // 4) + 3
        return p

    def locked(self, p):
        return {"decim"} if p.get("filter_kind") == "halfband" else set()

    def check(self, p, ctx):
        path, spec = ctx["path"], ctx["spec"]
        kind, d, taps = p["filter_kind"], p["decim"], p["taps"]
        if taps % 2 == 0:
            raise PlanError("structure", f"{path}.taps", "odd taps required (type-I linear phase)")
        fs_in_k = 1.0 / ctx["rate_in"]
        fp = spec.passband
        if kind == "halfband":
            if d != 2:
                raise PlanError("structure", f"{path}.decim", "halfband must decimate by 2")
            if taps % 4 != 3:
                raise PlanError("structure", f"{path}.taps", "halfband taps must be 4m+3")
            if fp >= fs_in_k / 4:
                raise PlanError("infeasible", path, "passband exceeds halfband limit input_rate/4")
        if fp >= fs_in_k / d / 2:
            raise PlanError("infeasible", path, "passband exceeds output Nyquist of this block")
        # 折叠在两个输入样点之间完成，因此 fold 不超过输入间隔周期数（无需窗口快照）
        n_terms = unique_mults(kind, taps) + (1 if kind == "halfband" else 0)
        p = dict(p, fold=max(1, min(p["fold"], ctx["rate_in"], n_terms)))
        return p, {"width_out": p["out_bits"], "decim": d}

    def prepare(self, p, ctx):
        spec = ctx["spec"]
        r_in = ctx["rate_in"]
        fp_k = spec.passband * r_in
        fs_k = 1.0 / p["decim"] - fp_k
        gains = None
        if p.get("compensate_upstream"):
            f_abs = np.linspace(0, spec.passband, 9)
            up = np.abs(upstream_response(ctx["upstream"], f_abs, spec))
            gains = tuple(float(v) for v in 1.0 / np.maximum(up, 1e-6) * up[0])
        h = np.array(_design(p["filter_kind"], p["taps"], round(fp_k, 12), round(fs_k, 12),
                             p["stop_weight"], None, gains))
        h = 0.5 * (h + h[::-1])  # 严格对称，保证对称对共享乘法与模型逐位一致
        q, frac = quantize(h, p["coef_bits"])
        return {"h": h, "q": q, "frac": frac}

    def run(self, x, p, ctx, aux, *, exact, ideal_coef, stats):
        d, w_in, w_out = p["decim"], ctx["width_in"], p["out_bits"]
        if not exact:
            h = aux["h"] if ideal_coef else aux["q"] / 2.0 ** aux["frac"]
            return np.convolve(x, h * 2.0 ** p["gain_shift"])[: len(x)][::d]

        def one(v, st):
            c = to_codes(v, w_in)
            acc = np.convolve(c, aux["q"])[: len(c)][::d]
            y, ns = sat(shift_round(acc, aux["frac"] + w_in - w_out - p["gain_shift"],
                                    p["rounding"]), w_out)
            st["sat"] = ns
            return from_codes(y, w_out)
        return per_component(one, x, stats, "fir")

    def response(self, f, p, ctx, aux, quantized=True):
        if aux is None:
            return None
        h = aux["q"] / 2.0 ** aux["frac"] if quantized else aux["h"]
        return _resp(h, (np.asarray(f) * ctx["rate_in"]) % 1.0)

    def delay(self, p, ctx, aux):
        return (p["taps"] - 1) / 2.0 * ctx["rate_in"]

    def cost(self, p, ctx, aux):
        C = area.C
        taps, kind, f = p["taps"], p["filter_kind"], p["fold"]
        u = unique_mults(kind, taps)
        q = aux["q"]
        c_ = taps // 2
        coefs = ([int(q[c_ - i]) for i in range(1, c_ + 1, 2)] if kind == "halfband"
                 else [int(q[c_ - i]) for i in range(c_ + 1)])
        nz = [v for v in coefs if v != 0]
        w_in, cb = ctx["width_in"], p["coef_bits"]
        acc_w = w_in + cb + math.ceil(math.log2(max(taps, 2)))
        per = {"delay_line": taps * w_in * C["reg_bit"], "out_reg": p["out_bits"] * C["reg_bit"]}
        if f == 1:
            per["preadd"] = len(nz) * (w_in + 1) * C["adder_bit"]
            per["const_mult"] = sum(max(area.csd_nonzeros(v) - 1, 0) *
                                    (w_in + 1 + abs(v).bit_length()) for v in nz) * C["const_add_bit"]
            per["adder_tree"] = max(len(nz), 1) * acc_w * C["adder_bit"]
        else:
            nm = math.ceil(u / f)
            per["sample_mux"] = nm * 2 * w_in * (f - 1) * C["mux_bit"]
            per["coef_rom"] = u * cb * C["rom_bit"] * 2
            per["preadd"] = nm * (w_in + 1) * C["adder_bit"]
            per["mult"] = nm * (w_in + 1) * cb * C["mult_bit2"]
            per["accum"] = nm * acc_w * (C["adder_bit"] + C["reg_bit"])
            per["adder_tree"] = max(nm - 1, 0) * acc_w * C["adder_bit"]
            per["control"] = math.ceil(math.log2(f + 1)) * (C["adder_bit"] + C["reg_bit"]) * 2
        return {k: 2 * v for k, v in per.items()}


def fir_terms(kind: str, q) -> list[tuple[int, list[int]]]:
    """(系数, 参与的延迟线下标) 列表；对称对共享一次乘法，零系数省略。"""
    taps = len(q)
    c = taps // 2
    terms = []
    for i in range(c):
        if kind == "halfband" and (c - i) % 2 == 0:
            continue
        if int(q[i]) != 0:
            terms.append((int(q[i]), [i, taps - 1 - i]))
    if int(q[c]) != 0:
        terms.append((int(q[c]), [c]))
    return terms


def _rtl(self, p, ctx, aux, module):
    from .vlog import const_mult, header, rnd_sat, sv
    w_in, w_out, g = ctx["width_in"], p["out_bits"], p["gain_shift"]
    d, f = p["decim"], p["fold"]
    q, frac = aux["q"], aux["frac"]
    taps = len(q)
    terms = fir_terms(p["filter_kind"], q)
    cb = max(abs(v) for v, _ in terms).bit_length() + 1
    wp = w_in + 1 + cb                                   # 单个乘积位宽
    acc_w = wp + max(1, math.ceil(math.log2(max(len(terms), 2)))) + 1
    s = frac + w_in - w_out - g
    L = header(module, w_in, w_out, complex_in=True)
    pw = max(1, (d - 1).bit_length())
    L.append(f"reg [{pw - 1}:0] ph; reg go;")
    L.append("always @(posedge clk) begin")
    L.append(f"  if (rst) begin ph <= 0; go <= 1'b0; end")
    L.append(f"  else begin go <= in_valid && (ph == 0); if (in_valid) "
             f"ph <= (ph == {pw}'d{d - 1}) ? {pw}'d0 : ph + {pw}'d1; end")
    L.append("end")
    for ch in ("i", "q"):
        for k in range(taps):
            L.append(f"reg {sv(w_in)} {ch}_x{k};")
        sh = " ".join(f"{ch}_x{k} <= {ch}_x{k - 1};" for k in range(1, taps))
        L.append(f"always @(posedge clk) if (rst) begin "
                 + " ".join(f"{ch}_x{k} <= 0;" for k in range(taps))
                 + f" end else if (in_valid) begin {ch}_x0 <= in_{ch}; {sh} end")

    def pre(ch, idx):
        a = f"$signed({{{ch}_x{idx[0]}[{w_in - 1}], {ch}_x{idx[0]}}})"
        if len(idx) == 1:
            return a
        return f"({a} + $signed({{{ch}_x{idx[1]}[{w_in - 1}], {ch}_x{idx[1]}}}))"

    if f == 1:
        for ch in ("i", "q"):
            prods = []
            for t, (v, idx) in enumerate(terms):
                L.append(f"wire {sv(w_in + 1)} {ch}_pa{t} = {pre(ch, idx)};")
                L += const_mult(f"{ch}_pa{t}", w_in + 1, v, wp, f"{ch}_pm{t}")
                prods.append(f"$signed({ch}_pm{t})")
            L.append(f"wire {sv(acc_w)} {ch}_acc = " + " + ".join(prods) + ";")
            L += rnd_sat(f"{ch}_acc", acc_w, s, p["rounding"], w_out, f"{ch}_res", f"{ch}_rs")
        L.append("always @(posedge clk) begin")
        L.append("  if (rst) begin out_valid <= 1'b0; out_i <= 0; out_q <= 0; end")
        L.append("  else begin out_valid <= go; if (go) begin out_i <= i_res; out_q <= q_res; end end")
        L.append("end")
    else:
        nm = math.ceil(len(terms) / f)
        tw = max(1, (f - 1).bit_length())
        L.append(f"reg [{tw - 1}:0] tc; reg busy; reg fin;")
        L.append(f"wire [{tw - 1}:0] cur_t = go ? {tw}'d0 : tc;")
        L.append(f"wire active = go | busy;")
        L.append("always @(posedge clk) begin")
        L.append("  if (rst) begin tc <= 0; busy <= 1'b0; fin <= 1'b0; end")
        L.append(f"  else begin fin <= active && (cur_t == {tw}'d{f - 1});")
        L.append(f"    if (active && cur_t != {tw}'d{f - 1}) begin busy <= 1'b1; tc <= cur_t + 1; end")
        L.append("    else begin busy <= 1'b0; tc <= 0; end end")
        L.append("end")
        for ch in ("i", "q"):
            for k in range(nm):
                L.append(f"reg {sv(w_in + 1)} {ch}_s{k}; reg {sv(cb)} {ch}_c{k};")
                L.append(f"always @(*) begin case (cur_t)")
                for t in range(f):
                    ti = k * f + t
                    if ti < len(terms):
                        v, idx = terms[ti]
                        L.append(f"  {tw}'d{t}: begin {ch}_s{k} = {pre(ch, idx)}; "
                                 f"{ch}_c{k} = {v & ((1 << cb) - 1)}; end")
                L.append(f"  default: begin {ch}_s{k} = 0; {ch}_c{k} = 0; end endcase end")
                L.append(f"wire {sv(wp)} {ch}_p{k} = {ch}_s{k} * {ch}_c{k};")
                L.append(f"reg {sv(acc_w)} {ch}_a{k};")
                L.append(f"always @(posedge clk) if (rst) {ch}_a{k} <= 0; else if (active) "
                         f"{ch}_a{k} <= (cur_t == 0) ? $signed({ch}_p{k}) : {ch}_a{k} + $signed({ch}_p{k});")
            L.append(f"wire {sv(acc_w)} {ch}_acc = " + " + ".join(f"{ch}_a{k}" for k in range(nm)) + ";")
            L += rnd_sat(f"{ch}_acc", acc_w, s, p["rounding"], w_out, f"{ch}_res", f"{ch}_rs")
        L.append("always @(posedge clk) begin")
        L.append("  if (rst) begin out_valid <= 1'b0; out_i <= 0; out_q <= 0; end")
        L.append("  else begin out_valid <= fin; if (fin) begin out_i <= i_res; out_q <= q_res; end end")
        L.append("end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


FirDecim.rtl = _rtl
