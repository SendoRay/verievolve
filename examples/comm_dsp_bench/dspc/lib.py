"""构造函数库：用原语组合出的常用结构。编译器与判定都不认识这些函数，它们展开后仍是原语，结构决策保持可见。

复数用 (re, im) 二元组表示。
"""
from __future__ import annotations

import math


def coef(g, c: float, bits: int = 16):
    """常数 c 量化为 bits 位有效位（近似点在这里）。返回 const 信号；c = 0 返回 None。"""
    if c == 0:
        return None
    f = bits - 1 - math.ceil(math.log2(abs(c)) + 1e-12)
    while abs(round(c * 2.0 ** f)) > (1 << (bits - 1)) - 1:
        f -= 1
    return g.const(c, bits, f)


def add_tree(g, terms):
    """平衡加法树（全精度，不丢位）。"""
    terms = [t for t in terms if t is not None]
    if not terms:
        return g.const(0.0, 2, 0)
    while len(terms) > 1:
        nxt = [g.add(terms[k], terms[k + 1]) for k in range(0, len(terms) - 1, 2)]
        if len(terms) % 2:
            nxt.append(terms[-1])
        terms = nxt
    return terms[0]


def fir(g, x, h, coef_bits: int = 16):
    """直接型 FIR：Σ_k h[k]·x[m-k]，全精度累加（不丢位）。"""
    terms = []
    for k, c in enumerate(h):
        cs = coef(g, float(c), coef_bits)
        if cs is not None:
            terms.append(g.mul(g.delay(x, k), cs))
    return add_tree(g, terms)


def fir_decimate(g, x, h, r: int, phase: int = 0, coef_bits: int = 16):
    """多相抽取 FIR：等价于 decimate(fir(x, h), r, phase)，但每一相只在低速率上运算。

    y[m] = Σ_k h[k]·x[m·r + phase - k]。全精度整数运算下与直接型逐位相同（加法交换律、结合律成立）。"""
    terms = []
    for p in range(r):
        hp = list(h[p::r])
        if not any(hp):
            continue
        d = p - phase
        u = g.decimate(g.delay(x, d), r, 0) if d >= 0 else g.decimate(x, r, -d)
        terms.append(fir(g, u, hp, coef_bits))
    return add_tree(g, terms)


def cadd(g, a, b):
    return g.add(a[0], b[0]), g.add(a[1], b[1])


def csub(g, a, b):
    return g.sub(a[0], b[0]), g.sub(a[1], b[1])


def cmul(g, a, b):
    """4 乘法复乘（也可以改写成 3 乘法形式）。"""
    return (g.sub(g.mul(a[0], b[0]), g.mul(a[1], b[1])),
            g.add(g.mul(a[0], b[1]), g.mul(a[1], b[0])))


def cmul_const(g, a, c: complex, bits: int = 16):
    cr, ci = coef(g, c.real, bits), coef(g, c.imag, bits)
    def m(x, k):
        return None if k is None else g.mul(x, k)
    re = [m(a[0], cr), None if ci is None else g.neg(g.mul(a[1], ci))]
    im = [m(a[1], cr), m(a[0], ci)]
    return add_tree(g, re), add_tree(g, im)


def mul_j(g, a, sign: int = +1):
    """乘 ±j：只交换实虚部并取负，不产生乘法器。"""
    return (g.neg(a[1]), a[0]) if sign > 0 else (a[1], g.neg(a[0]))


def bfly2(g, a, b):
    """基 2 蝶形：(a + b, a − b)。"""
    return cadd(g, a, b), csub(g, a, b)


def q2(g, a, w, f, rnd="round", ovf="sat"):
    """复数重量化。"""
    return g.q(a[0], w, f, rnd, ovf), g.q(a[1], w, f, rnd, ovf)
