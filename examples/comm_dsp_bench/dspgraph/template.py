"""专家模板：教科书多级 DDC 的参数化 build 程序（命题 1 的设计空间，也是命题 2 的专家对照）。

结构：四分之一波 NCO → 实复混频 → N 阶 CIC(÷R1) → (k-1) 个半带(÷2) → 末级 FIR(÷2，可补偿 CIC 下垂)。
参数按角色分为 structure / precision / micro。模板本身只是普通 build 程序，经同一编译器与裁判评价。
"""

from __future__ import annotations

import math
import random

# (名称, 角色, 取值)
def space(spec) -> list[tuple]:
    R = spec.r_total
    ks = [k for k in (1, 2, 3, 4) if R % (2 ** k) == 0 and R // 2 ** k >= 2]
    return [
        ("k", "structure", ks),                       # CIC 之后的 ÷2 级数
        ("N", "structure", [2, 3, 4, 5, 6]),          # CIC 阶数
        ("M", "structure", [1, 2]),                   # 差分延迟
        ("hb_taps", "structure", [7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47, 51, 55, 59, 63]),
        ("fir_taps", "structure", list(range(9, 128, 2))),
        ("comp", "structure", [0, 1]),                # 末级是否补偿 CIC 下垂
        ("sw", "structure", [1.0, 3.0, 10.0, 30.0, 100.0]),   # 末级阻带权重
        ("se", "structure", [0.55, 0.65, 0.75, 0.85, 1.0]),   # 末级阻带起点 / 输出奈奎斯特
        ("P", "precision", list(range(8, 17))),      # NCO 相位地址位（含象限 2 位）
        ("A", "precision", list(range(10, 21))),     # NCO 幅度位
        ("Wm", "precision", list(range(12, 25))),    # 混频输出位
        ("Wc", "precision", list(range(14, 29))),    # CIC 输出位
        ("Ch", "precision", list(range(8, 23))),     # 半带系数位
        ("Wh", "precision", list(range(14, 29))),    # 半带输出位
        ("Cf", "precision", list(range(8, 23))),     # 末级系数位
        ("G", "precision", list(range(0, 9))),       # 输出增益移位
        ("sh_h", "micro", [1, 2, 4, 8, 16]),         # 半带乘法器分时复用
        ("sh_f", "micro", [1, 2, 4, 8, 16, 32, 64]), # 末级乘法器分时复用
    ]


WIDE = {"P": 16, "A": 20, "Wm": 24, "Wc": 28, "Ch": 22, "Wh": 28, "Cf": 22}
MICRO_DEFAULT = {"sh_h": 1, "sh_f": 1}


def code(p: dict) -> str:
    return f'''# 专家模板实例：{p}
P_ = {p!r}

def build(g, spec):
    p = P_
    R, b = spec.r_total, spec.output_bits
    k, N, M = p["k"], p["N"], p["M"]
    R1 = R // 2 ** k
    x = g.input()
    with g.scope("nco"):
        P = p["P"]
        ph = g.counter(spec.fcw, 32)
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
        i = g.q(g.mul(x, cos), Wm, Wm - 1)
        q = g.q(g.neg(g.mul(x, sin)), Wm, Wm - 1)
    with g.scope("cic"):
        grow = math.ceil(N * math.log2(R1 * M) - 1e-9)
        W = Wm + grow
        def cic(v):
            for _ in range(N):
                v = g.integrate(v, W)
            v = g.decimate(v, R1)
            for _ in range(N):
                v = g.q(g.sub(v, g.delay(v, M)), W, v.f, ovf="wrap")
            return g.q(g.shift(v, -grow), p["Wc"], p["Wc"] - 1)
        i, q = cic(i), cic(q)
    fp = spec.passband
    rate = R1
    for s in range(k - 1):
        with g.scope(f"hb{{s}}"):
            fpk = fp * rate
            nt = p["hb_taps"]
            h = scipy.signal.firls(nt, [0, fpk, 0.5 - fpk, 0.5], [1, 1, 0, 0], fs=1.0)
            c = nt // 2
            h = np.array([0.0 if (j - c) % 2 == 0 and j != c else v for j, v in enumerate(h)])
            h[c] = 0.5
            h = 0.5 * (h + h[::-1])
            def hb(v):
                taps = g.delay_line(v, nt)
                terms = [(g.add(taps[j], taps[nt - 1 - j]), h[j]) for j in range(c) if h[j] != 0]
                terms.append((taps[c], h[c]))
                y = g.mac(terms, coef_bits=p["Ch"], share=p["sh_h"])
                return g.q(g.decimate(y, 2), p["Wh"], p["Wh"] - 1)
            i, q = hb(i), hb(q)
            rate *= 2
    with g.scope("fir"):
        fpk = fp * rate
        fsk = max(fpk + 0.01, 0.25 * p["se"])
        nt = p["fir_taps"]
        if p["comp"]:
            ed = np.linspace(0, fpk, 9)
            fr = ed / rate
            with np.errstate(invalid="ignore", divide="ignore"):
                d = np.where(fr == 0, 1.0, np.sin(np.pi * fr * R1 * M) / (R1 * M * np.sin(np.pi * fr)))
            gain = 1.0 / np.abs(d) ** N
            bands, des = [], []
            for a0, a1, g0, g1 in zip(ed[:-1], ed[1:], gain[:-1], gain[1:]):
                bands += [a0, a1]; des += [g0, g1]
            h = scipy.signal.firls(nt, bands + [fsk, 0.5], des + [0, 0], weight=[1] * 8 + [p["sw"]], fs=1.0)
        else:
            h = scipy.signal.firls(nt, [0, fpk, fsk, 0.5], [1, 1, 0, 0], weight=[1, p["sw"]], fs=1.0)
        h = h / h.sum()
        h = 0.5 * (h + h[::-1])
        c = nt // 2
        def fir(v):
            taps = g.delay_line(v, nt)
            terms = [(g.add(taps[j], taps[nt - 1 - j]), h[j]) for j in range(c)] + [(taps[c], h[c])]
            y = g.mac(terms, coef_bits=p["Cf"], share=p["sh_f"])
            return g.q(g.shift(g.decimate(y, 2), p["G"]), b, b - 1)
        i, q = fir(i), fir(q)
    g.output(i, q)
'''


def random_params(spec, rng: random.Random) -> dict:
    return {n: rng.choice(v) for n, _, v in space(spec)}


def baseline_params(spec) -> dict:
    """一组合理的起点（宽精度、中等结构）。"""
    p = {n: v[len(v) // 2] for n, _, v in space(spec)}
    p.update(WIDE)
    p.update(MICRO_DEFAULT)
    p["G"] = 2
    return p
