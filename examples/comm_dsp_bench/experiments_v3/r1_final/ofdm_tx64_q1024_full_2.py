# OFDM 发射 IDFT64+CP：8x8 分解，输入期把 T[k1,m2]=Σ X_k·W^{k·m2} 累加进两条 32 级循环移位寄存器
# （A 环放偶 k1，B 环放奇 k1），空闲期每时钟出一个样点：b = Σ_l ω^{l·m1}·T[l,m2]。
# - 输入按 1024QAM 电平解码为 5 位 i'（L=2i'+1），乘法器为 6 位×10 位。
# - 输出网络用蝶形；取反用按位取反（-x-1），偏移与乘积截断偏差合并成每槽一个常数 K（查表）在末端加上。
import numpy as np

U_OUT = 5.0 / 16          # T 的单位：输出 LSB 的 5/16
TW = 11                   # T 位宽（模 2^11 回绕；超界概率 < 1e-9/项）
L2U = 1.0 / (64 * np.sqrt(682)) * 2048 / U_OUT   # 1 个电平单位 = 多少 u
LUTW, LUTF = 9, 6
C_TERMS = [(2, 1), (5, -1), (9, 1)]          # (5/16)/√2 ≈ 0.2209473
PRF = 6                                                # 乘积小数位（截断前）
USED = list(range(38, 64)) + list(range(1, 27))


def m1_of(s):
    return ((s + 4) >> 1) % 8


def valid(v):
    return 0 <= v <= 52 and v != 26


def vA(s):
    return s & ~1


def vB(s):
    return s if s & 1 else s - 1


def lane_count():
    n = [0] * 8
    for v in range(53):
        if valid(v):
            n[(6 + v) % 8] += 1
    return n


class Num:
    def __init__(self, v, f):
        self.v, self.f = v, f


def build(g, spec):
    xi, xq = g.input()

    def dec(x):                          # i' = floor(x·26)，误差容限 ±0.5
        x7 = g.q(x, 8, 7, rnd='trunc', ovf='wrap')
        y = g.add(g.add(g.shift(x7, 4), g.shift(x7, 3)), g.shift(x7, 1))
        return g.q(y, 5, 0, rnd='trunc', ovf='wrap')

    ii, iq = dec(xi), dec(xq)
    slot = g.counter(1, 7, like=xi, modulus=80)
    (hi, hq, hs0), stb = g.clock(ii, iq, slot)

    def b1(sig):
        return g.bits(sig, 0, 0)

    def dly(x):
        r = g.state(x.w, x.f)
        g.close(r, x)
        return r

    hs_s = [g.q(hs0, 8, 0)]              # 槽号的延迟版本（有符号承载）
    hsd = [g.bits(h, 6, 0) for h in hs_s]

    def lut_s(vals, w, f=0, d=0):
        vals = list(vals) + [0] * (128 - len(vals))
        return g.lut(hsd[d], vals, w, f)

    def flag_s(fn, d=0):
        return b1(lut_s([1 if fn(s) else 0 for s in range(80)], 2, 0, d))

    def inv(x):                          # 按位取反 = -x - 2^-f
        return g.q(g.sub(g.const(-2.0 ** -x.f, x.w, x.f), x), x.w, x.f, ovf='wrap')

    ph = g.state(2, 0)
    ph_e = g.mux(stb, g.const(0, 2, 0), ph)
    g.close(ph, g.q(g.add(ph_e, g.const(1, 2, 0)), 2, 0, ovf='wrap'))
    ph_u = g.bits(ph_e, 1, 0)
    ph3 = b1(g.lut(ph_u, [0, 0, 0, 1], 2, 0))

    def hold(x, en):
        r = g.state(x.w, x.f)
        g.close(r, g.mux(en, x, r))
        return r
    di, dq = hold(hi, ph3), hold(hq, ph3)
    d2i, d2q = hold(di, ph3), hold(dq, ph3)

    spar = lut_s([s & 1 for s in range(80)], 2)
    m2 = g.bits(g.add(g.shift(spar, 2), g.q(ph_u, 3, 0)), 2, 0)
    # B 侧 k_B = k_A ± 1（偶槽 −1、奇槽 +1）→ n_B = n_A ± m2 (mod 64)
    pm_addr = g.bits(g.add(g.shift(spar, 3), g.q(m2, 4, 0)), 3, 0)
    pm = g.lut(pm_addr, [(-m) % 64 for m in range(8)] + [m for m in range(8)], 8, 0)

    # 先把 c、s 量化到 LUT 网格，再由量化值精确算 s−c、c+s（三乘法的等效系数与四乘法一致）
    cw = [round(L2U * np.cos(2 * np.pi * r / 64) * 2 ** LUTF) / 2 ** LUTF for r in range(16)]
    sw = [round(L2U * np.sin(2 * np.pi * r / 64) * 2 ** LUTF) / 2 ** LUTF for r in range(16)]

    def lane_side(vfun, n_in=None):
        src = []
        for s in range(80):
            v = vfun(s)
            first = (s == v)
            src.append((0 if first else 1) if v <= 25 else (1 if first else 2))
        sel1 = flag_s(lambda s: src[s] >= 1)
        sel2 = flag_s(lambda s: src[s] == 2)
        ar = g.mux(sel2, d2i, g.mux(sel1, di, hi))
        am = g.mux(sel2, d2q, g.mux(sel1, dq, hq))
        nvld = flag_s(lambda s: not valid(vfun(s)))
        if n_in is None:
            k = g.bits(lut_s([(38 + vfun(s)) % 64 for s in range(80)], 8), 5, 0)
            n = g.mul(k, m2)
        else:
            n = g.bits(g.add(n_in, pm), 5, 0)
        lane_side.n = n
        # 无效槽：旋转因子地址指向全零表项，乘积自然为 0（省去乘积后的选择器）
        r = g.bits(g.add(g.shift(g.q(nvld, 2, 0), 4), g.q(g.bits(n, 3, 0), 5, 0)), 4, 0)
        qsw = g.bits(n, 4, 4)
        neg_r = b1(g.lut(g.bits(n, 5, 4), [0, 1, 1, 0], 2, 0))
        neg_i = g.bits(n, 5, 5)
        sa = g.mux(qsw, am, ar)          # X·j^q：交换 + 对 i' 按位取反（奇电平取负精确）
        sb = g.mux(qsw, ar, am)
        ra = g.mux(neg_r, inv(sa), sa)
        rb = g.mux(neg_i, inv(sb), sb)
        one = g.const(1, 2, 0)
        Xr = g.q(g.add(g.shift(ra, 1), one), 6, 0, ovf='wrap')
        Xi = g.q(g.add(g.shift(rb, 1), one), 6, 0, ovf='wrap')
        hsum = g.q(g.add(g.add(ra, rb), one), 6, 0, ovf='wrap')   # (Xr+Xi)/2
        # 3 乘法复乘：k1 = c(Xr+Xi), k2 = Xr(s-c), k3 = Xi(c+s)；re = k1-k3, im = k1+k2
        Z16 = [0.0] * 16
        c = g.lut(r, cw + Z16, LUTW, LUTF)
        smc = g.lut(r, [b - a for a, b in zip(cw, sw)] + Z16, LUTW, LUTF)
        cps = g.lut(r, [a + b for a, b in zip(cw, sw)] + Z16, LUTW + 1, LUTF)
        k1 = g.shift(g.mul(hsum, c), 1)
        k2 = g.mul(Xr, smc)
        k3 = g.mul(Xi, cps)
        pr = g.q(g.sub(k1, k3), 9, 0, rnd='trunc', ovf='wrap')
        pi_ = g.q(g.add(k1, k2), 9, 0, rnd='trunc', ovf='wrap')
        z = g.const(0, 2, 0)
        init = flag_s(lambda s: 0 <= vfun(s) <= 7)
        loops = []
        for p in (pr, pi_):
            S = [g.state(TW, 0) for _ in range(32)]
            nxt = g.add(g.mux(init, z, S[-1]), p)
            g.close(S[0], g.q(nxt, TW, 0, ovf='wrap'))
            for j in range(1, 32):
                g.close(S[j], S[j - 1])
            loops.append(S)
        return [(loops[0][7 + 8 * i], loops[1][7 + 8 * i]) for i in range(4)]

    with g.scope("accA"):
        tA = lane_side(vA)
    with g.scope("accB"):
        tB = lane_side(vB, lane_side.n)

    # ---------------- 输出网络 ----------------
    # b = j^a·(F_A + ω^γ F_B)，F = (V0 + σV2) + (-j)^{m1}(V1 + σV3)，σ=(-1)^{m1}
    def cA(s):
        return (s % 8) >> 1

    def cB(s):
        return ((s - 1) % 8) >> 1

    def a_of(s):
        return ((2 + cA(s)) * m1_of(s)) % 4

    def gam_of(s):
        return ((5 + 2 * cB(s)) * m1_of(s) - 2 * a_of(s)) % 8

    def laneA(s, i):
        return (4 + 2 * cA(s) - 2 * i) % 8

    def laneB(s, i):
        return (5 + 2 * cB(s) - 2 * i) % 8

    OUT_S = list(range(56, 76))

    class HW:
        def add(self, a, b):
            return g.add(a, b)

        def sub(self, a, b):
            return g.sub(a, b)

        def negsel(self, fl, x):
            return g.mux(fl[0], inv(x), x)

        def swap(self, fl, x, y):
            return g.mux(fl[0], y, x), g.mux(fl[0], x, y)

        def shift(self, x, k):
            return g.shift(x, k)

        def q(self, x, w, f):           # w=0：保持整数位数不变，只截小数位
            if w == 0:
                w = x.w - x.f + f
            return g.q(x, w, f, rnd='trunc', ovf='wrap')

        def mux(self, fl, a, b):
            return g.mux(fl[0], a, b)

        def reg(self, x):
            return dly(x)

    class PY:                            # 均值模型：信号取值 = 误差均值（取反偏移、截断均值）
        def __init__(self, s):
            self.s = s

        def add(self, a, b):
            return Num(a.v + b.v, max(a.f, b.f))

        def sub(self, a, b):
            return Num(a.v - b.v, max(a.f, b.f))

        def negsel(self, fl, x):
            return Num(-x.v - 2.0 ** -x.f, x.f) if fl[1](self.s) else x

        def swap(self, fl, x, y):
            return (y, x) if fl[1](self.s) else (x, y)

        def shift(self, x, k):
            return Num(x.v * 2.0 ** k, x.f - k)

        def q(self, x, w, f):
            if x.f > f:                  # 截断：低位均匀分布时均值 -(2^-f - 2^-x.f)/2
                return Num(x.v - (2.0 ** -f - 2.0 ** -x.f) / 2, f)
            return Num(x.v, x.f)

        def mux(self, fl, a, b):
            return a if fl[1](self.s) else b

    def mk(fn, d):
        return (flag_s(fn, d), fn)

    def rot_flags(qfn, d):
        return (mk(lambda s: qfn(s) & 1, d), mk(lambda s: qfn(s) % 4 in (1, 2), d),
                mk(lambda s: qfn(s) % 4 in (2, 3), d))

    odd0 = mk(lambda s: m1_of(s) & 1, 0)
    odd1 = mk(lambda s: m1_of(s) & 1, 0)
    rotR = rot_flags(lambda s: (-m1_of(s)) % 4, 0)
    rotQ = rot_flags(lambda s: ((gam_of(s) + 2 * a_of(s)) % 8) >> 1, 0)
    rotH = rot_flags(a_of, 0)

    def rot(o, flags, x):
        sw_, nr, ni = flags
        a, b = o.swap(sw_, x[0], x[1])
        return o.negsel(nr, a), o.negsel(ni, b)

    YF = 2                               # 输出网络小数位（输出 LSB 单位）

    def net(o, VA, VB, K=None):
        # Y = j^a·F_A·(5/16) + K  +  ω^q'·F_B·(5/16)，q' = γ + 2a（把末端旋转并进 F_B 支路）
        def Fpart(V):
            P = (o.add(V[0][0], o.negsel(odd0, V[2][0])), o.add(V[0][1], o.negsel(odd0, V[2][1])))
            R = (o.add(V[1][0], o.negsel(odd0, V[3][0])), o.add(V[1][1], o.negsel(odd0, V[3][1])))
            R = rot(o, rotR, R)
            return (o.add(P[0], R[0]), o.add(P[1], R[1]))

        def x516(x):                     # ×5/16 = 2^-2 + 2^-4
            return o.q(o.add(o.shift(x, -2), o.q(o.shift(x, -4), 0, YF)), 0, YF)

        FA = rot(o, rotH, Fpart(VA))
        YA = [x516(x) for x in FA]
        if K is not None:
            YA = [o.q(o.add(y, k), 0, YF) for y, k in zip(YA, K)]
        G = rot(o, rotQ, Fpart(VB))
        D = o.sub(G[0], G[1])
        S = o.add(G[0], G[1])

        # 先按奇偶选 Z = D/S（奇）或 G'（偶），再 Y_B = Z/4 + W：
        # 偶 W = Z/16（×5/16）；奇 W = −Z/32 + Z/512（×(5/16)/√2 ≈ 2^-2 − 2^-5 + 2^-9）
        def t(x, e):
            return o.q(o.shift(x, -e), 0, YF)
        YB = []
        for z0, g0 in ((D, G[0]), (S, G[1])):
            Z = o.mux(odd1, z0, g0)
            W = o.mux(odd1, o.sub(t(Z, 9), t(Z, 5)), t(Z, 4))
            YB.append(o.add(t(Z, 2), W))
        return [o.add(ya, yb) for ya, yb in zip(YA, YB)]

    with g.scope("out"):
        # 常数校正 K：按位取反偏移 + 乘积截断均值 + 网络截断均值 + 末端截断均值（查表，加在 F_A 支路，不在关键路径上）
        nl = lane_count()
        pb = -0.5 * (1 - 2.0 ** -PRF)
        Kr, Ki = [0.0] * 80, [0.0] * 80
        for s in OUT_S:
            o = PY(s)
            VA = [(Num(pb * nl[laneA(s, i)], 0),) * 2 for i in range(4)]
            VB = [(Num(pb * nl[laneB(s, i)], 0),) * 2 for i in range(4)]
            y = net(o, VA, VB)
            Kr[s] = -y[0].v + 0.5 * (1 - 2.0 ** -YF)
            Ki[s] = -y[1].v + 0.5 * (1 - 2.0 ** -YF)
        kr = lut_s([round(v * 2 ** YF) / 2 ** YF for v in Kr], 5 + YF, YF, 0)
        ki = lut_s([round(v * 2 ** YF) / 2 ** YF for v in Ki], 5 + YF, YF, 0)
        Y = net(HW(), tA, tB, (kr, ki))
        yr = g.q(g.shift(Y[0], -11), 12, 11, rnd='trunc', ovf='wrap')
        yi = g.q(g.shift(Y[1], -11), 12, 11, rnd='trunc', ovf='wrap')
        ov = flag_s(lambda s: 56 <= s < 76, 0)
        g.output(g.sample(yr, ov), g.sample(yi, ov))
