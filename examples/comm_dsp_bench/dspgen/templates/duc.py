"""链 B 专家模板：教科书 DUC。
补偿 FIR 内插 ×2（预补偿 CIC 下垂）→ (k−1) 级半带内插 ×2 → N 阶 CIC 内插 ×R1 → 四分之一波 NCO 上变频取实部。
L = 2^k · R1。只用现有原语；内插 FIR 用“零值内插 + 对称预加乘加”，可分时复用乘法器。
"""
from __future__ import annotations

import math
import random

WIDE = {"P": 16, "A": 20, "Wf": 24, "Wh": 24, "Wc": 24, "Wm": 24, "Cf": 22, "Ch": 22}
MICRO_DEFAULT = {"sh_f": 1, "sh_h": 1}


def space(task):
    L = task.params["L"]
    ks = [k for k in (1, 2, 3, 4) if L % (2 ** k) == 0]       # R1 = L/2^k；R1 = 1 时不用 CIC
    return [
        ("k", "structure", ks),
        ("N", "structure", [2, 3, 4, 5, 6]),
        ("M", "structure", [1, 2]),
        ("fir_taps", "structure", list(range(11, 96, 4))),
        ("hb_taps", "structure", [7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47]),
        ("sw", "structure", [1.0, 3.0, 10.0, 30.0, 100.0]),
        ("P", "precision", list(range(8, 17))),
        ("A", "precision", list(range(10, 21))),
        ("Wf", "precision", list(range(14, 25))),
        ("Wh", "precision", list(range(14, 25))),
        ("Wc", "precision", list(range(14, 25))),
        ("Wm", "precision", list(range(14, 25))),
        ("Cf", "precision", list(range(8, 23))),
        ("Ch", "precision", list(range(8, 23))),
        ("G", "precision", list(range(-3, 4))),
        ("sh_f", "micro", [1, 2, 4, 8]),
        ("sh_h", "micro", [1, 2, 4]),
    ]


def random_params(task, rng: random.Random):
    return {n: rng.choice(v) for n, _, v in space(task)}


def baseline_params(task):
    p = {n: v[len(v) // 2] for n, _, v in space(task)}
    p.update(WIDE)
    p.update(MICRO_DEFAULT)
    p["G"] = 0
    return p


def code(p: dict) -> str:
    return f'''# 专家模板实例（DUC）：{p}
P_ = {p!r}

def build(g, spec):
    p = P_
    L, b, fp = spec.L, spec.output_bits, spec.passband
    k, N, M = p["k"], p["N"], p["M"]
    R1 = L // 2 ** k
    xi, xq = g.input()

    def interp_fir(v, h, cb, share, w_out):
        # 零值内插 ×2 后用对称预加乘加滤波（系数已含 ×2 增益）
        u = g.interpolate(v, 2)
        nt = len(h)
        c = nt // 2
        taps = g.delay_line(u, nt)
        terms = [(g.add(taps[j], taps[nt - 1 - j]), h[j]) for j in range(c) if h[j] != 0]
        terms.append((taps[c], h[c]))
        y = g.mac(terms, coef_bits=cb, share=share)
        return g.q(y, w_out, w_out - 2)      # 中间字长留 1 位整数余量（补偿与过冲）

    # 1) 补偿 FIR ×2：通带内预补偿后级 CIC 的下垂
    with g.scope("cfir"):
        fs = 2.0
        nt = p["fir_taps"]
        ed = np.linspace(0, fp, 9)
        with np.errstate(invalid="ignore", divide="ignore"):
            d = np.where(ed == 0, 1.0, np.abs(np.sin(np.pi * ed * R1 * M / L) / (R1 * M * np.sin(np.pi * ed / L))) ** N)
        gain = 1.0 / d
        bands, des = [], []
        for a0, a1, g0, g1 in zip(ed[:-1], ed[1:], gain[:-1], gain[1:]):
            bands += [a0, a1]; des += [g0, g1]
        h = scipy.signal.firls(nt, bands + [1.0 - fp, fs / 2], des + [0, 0], weight=[1] * 8 + [p["sw"]], fs=fs)
        h = h / h.sum() * 2.0
        h = 0.5 * (h + h[::-1])
        xi = interp_fir(xi, h, p["Cf"], p["sh_f"], p["Wf"])
        xq = interp_fir(xq, h, p["Cf"], p["sh_f"], p["Wf"])
    # 2) 半带 ×2
    for s in range(1, k):
        with g.scope(f"hb{{s}}"):
            fs = 2.0 ** (s + 1)
            fpk = fp / fs
            nt = p["hb_taps"]
            h = scipy.signal.firls(nt, [0, fpk, 0.5 - fpk, 0.5], [1, 1, 0, 0], fs=1.0)
            c = nt // 2
            h = np.array([0.0 if (j - c) % 2 == 0 and j != c else v for j, v in enumerate(h)])
            h[c] = 0.5
            h = 0.5 * (h + h[::-1]) * 2.0
            xi = interp_fir(xi, h, p["Ch"], p["sh_h"], p["Wh"])
            xq = interp_fir(xq, h, p["Ch"], p["sh_h"], p["Wh"])
    # 3) CIC 内插 ×R1：低速率梳状 → 零值内插 → 高速率积分（模回绕），增益 R1^(N-1)·M^N
    if R1 == 1:
        xi = g.q(xi, p["Wc"], p["Wc"] - 2)
        xq = g.q(xq, p["Wc"], p["Wc"] - 2)
    else:
     with g.scope("cic"):
         grow = math.ceil(N * math.log2(R1 * M) - 1e-9)
         W = p["Wh" if k > 1 else "Wf"] + grow + 1
         sh = math.log2(R1 ** (N - 1) * M ** N)
         def cic(v):
             v = g.q(v, W, v.f, ovf="wrap")
             for _ in range(N):
                 v = g.q(g.sub(v, g.delay(v, M)), W, v.f, ovf="wrap")
             v = g.interpolate(v, R1)
             for _ in range(N):
                 v = g.integrate(v, W)
             v = g.scale(v, 2.0 ** (-sh), 16) if abs(sh - round(sh)) > 1e-9 else g.shift(v, -int(round(sh)))
             return g.q(v, p["Wc"], p["Wc"] - 2)
         xi, xq = cic(xi), cic(xq)
    # 4) 四分之一波 NCO 上变频，取实部 I·cos − Q·sin
    with g.scope("nco"):
        P = p["P"]
        ph = g.counter(spec.fcw, 32, like=xi)
        quad = g.bits(ph, 31, 30)
        idx = g.bits(ph, 29, 32 - P)
        n = 1 << (P - 2)
        tab = [math.sin(math.pi / 2 * (j + 0.5) / n) for j in range(n)]
        mirror = g.bits(quad, 0, 0)
        top = g.const(n - 1, P + 1, 0)
        ia = g.bits(g.q(g.mux(mirror, g.sub(top, idx), idx), P + 1, 0, ovf="wrap"), P - 3, 0)
        ib = g.bits(g.q(g.mux(mirror, idx, g.sub(top, idx)), P + 1, 0, ovf="wrap"), P - 3, 0)
        s0 = g.lut(ia, tab, p["A"], p["A"] - 1)
        c0 = g.lut(ib, tab, p["A"], p["A"] - 1)
        sin = g.mux(g.bits(quad, 1, 1), g.neg(s0), s0)
        qc = g.bits(g.q(g.add(quad, g.const(1, 3, 0)), 3, 0, ovf="wrap"), 1, 1)
        cos = g.mux(qc, g.neg(c0), c0)
    with g.scope("mixer"):
        Wm = p["Wm"]
        y = g.q(g.sub(g.mul(xi, cos), g.mul(xq, sin)), Wm, Wm - 2)
    with g.scope("output"):
        y = g.q(g.shift(y, p["G"]), b, b - 1)
    g.output(y)
'''
