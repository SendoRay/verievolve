# 串行复数（实部、虚部相邻两个时钟）R2^2 SDF (DIF) + 分时复用旋转乘法器 + 位反转交换 + CP
# 长延迟用自由运行（无使能）的 4 相位交织移位链：一条链同时承载两个延迟相近的复数通道
# （A: S1/SW1；B: S2/CP 循环；D: S3+S4+S5 中段注入/SW2），去掉每位寄存器的使能 mux。
# 数值均为“未缩放”部分和（最终 /32 只是移位）；蝶形内部精确，只在输入、旋转、输出处舍入。
P = dict(
    win=(9, 8),
    wd=[10, 11, 11, 12, 12, 13],
    tw=(11, 9),                      # 旋转因子 LUT 格式
    tacc=3,                          # 旋转累加器额外小数位
    tm=[(11, 8), (12, 8, 'sat')],
    out=(10, 10),
    dcoff=2.0 ** -6,                 # 未缩放单位：32 * 2^-(out_f+1)
    sat=[False, False, True, True, True, False],
    r12=3, r34=3,                    # 相位对齐寄存器个数
)


def build(g, spec):
    W = lambda e: np.exp(2j * np.pi * e / 64)
    xi, xq = g.input()
    (hi, hq), st = g.clock(g.q(xi, *P['win'], 'round', 'wrap'), g.q(xq, *P['win'], 'round', 'wrap'))   # 先舍入再进时钟域：保持寄存器只存 9 位
    c = g.counter(1, 9, like=hi, modulus=320)
    ph = g.bits(c, 1, 0)
    zero1 = g.bits(g.const(0, 2, 0), 0, 0)

    def bit(t, k):
        return (t >> k) & 1

    def lut1(addr, vals):
        return g.bits(g.lut(addr, [float(v) for v in vals], 2, 0), 0, 0)

    def phs(*phis):
        return lut1(ph, [1 if i in [p % 4 for p in phis] else 0 for i in range(4)])

    def ctl(O, fn):
        """按元素位置的控制位：时钟 O+4τ（实部）与 O+4τ+1（虚部）都给出 fn(τ)。"""
        vals = []
        for cc in range(512):
            if cc >= 320:
                vals.append(0)
                continue
            tau = ((cc - O) % 320) // 4
            vals.append(1 if fn(tau) else 0)
        return lut1(c, vals)

    def AND(a, b):
        return g.bits(g.mux(a, b, zero1), 0, 0)

    def q(x, w, f, rnd='round', ovf='wrap'):
        return g.q(x, w, f, rnd, ovf)

    def reg(v, en=None):
        r = g.state(v.w, v.f)
        g.close(r, v if en is None else g.mux(en, v, r))
        return r

    def shreg_en(din, n, en):
        regs = [g.state(din.w, din.f) for _ in range(n)]
        prev = din
        for r in regs:
            g.close(r, g.mux(en, prev, r))
            prev = r
        return regs[-1]

    class Chain:
        """自由运行移位链：tap(k) = 输入延迟 k 个时钟。"""
        def __init__(self, n, w, f):
            self.regs = [g.state(w, f) for _ in range(n)]
            self.w, self.f = w, f

        def tap(self, k):
            return self.regs[k - 1]

        def close(self, din, entries=None):
            # entries: {位置 p: (相位选择, 值)}：在 regs[p] 的输入处按相位注入（p 须为 4 的倍数）
            entries = entries or {}
            prev = din
            for i, r in enumerate(self.regs):
                if i in entries:
                    assert i % 4 == 0
                    sel_, v_ = entries[i]
                    prev = g.mux(sel_, to_fmt(v_, self.w, self.f), prev)
                g.close(r, prev)
                prev = r

    def to_fmt(x, w, f):
        # 把 x 平移到小数位 f（只移小数点）再扩到 w 位
        return q(g.shift(x, x.f - f), w, f)

    def from_fmt(x, f, w=None):
        return q(g.shift(x, x.f - f), P['out'][0] if w is None else w, f)

    def sdf(x, D, O, rot, wd, dl, sat=False):
        """串行 SDF 级。x：输入（实部在 O_x、虚部在 O_x+1）。rot 时本级在 O_x+1 处理。
        O：本级处理实部的时钟（位置 0）。dl(din) -> do：延迟 D 个 tick 的存储。返回 (out, din)。"""
        j = D.bit_length() - 1
        f = x.f
        sel = ctl(O, lambda t: bit(t, j))
        if rot is not None:
            rj = ctl(O, lambda t: bit(t, j) and rot(t))
            isre = phs(O)
            xd = reg(x)
            xdd = reg(xd)
            a = g.mux(rj, g.mux(isre, x, xdd), xd)
            swp = AND(rj, isre)
        else:
            a = x
        do = dl
        Pp, Mm = g.add(do, a), g.sub(do, a)
        if rot is not None:
            sm, df = g.mux(swp, Mm, Pp), g.mux(swp, Pp, Mm)
        else:
            sm, df = Pp, Mm
        out = g.mux(sel, sm, do)
        if sat:
            out = q(out, wd, f, 'round', 'sat')
            df = q(df, wd, f, 'round', 'sat')
        din = g.mux(sel, q(df, wd, f), q(a, wd, f))
        return out, din

    def offcnt(base):
        # u = (C - base) mod 320（无符号位直接给出 τ=u>>2, k=u&3）
        u = g.state(10, 0, float((-base) % 320))
        wrapc = lut1(c, [1 if cc == (base - 1) % 320 else 0 for cc in range(512)])
        g.close(u, q(g.mux(wrapc, g.const(0, 10, 0), g.add(u, g.const(1, 2, 0))), 10, 0))
        return u

    def twiddle(y, e, tfn, fmt, abits):
        """y：串行输入（实部在 e，虚部在 e+1）。1 个实乘法器分时：
        e+1: Hr*tr, e+2: Hi*(-ti) → pr；e+3: Hr*ti, e+4: Hi*tr → pi。
        输出串行：实部在 e+4，虚部在 e+5（两级自由运行寄存器取出）。"""
        Hr = reg(y, phs(e))
        Hi = reg(y, phs(e + 1))
        base = e + 1
        u = offcnt(base)
        vals = []
        for a_ in range(1 << abits):
            tau, k = a_ // 4, a_ % 4
            v = tfn(tau)
            vals.append([v.real, -v.imag, v.imag, v.real][k])
        B = g.lut(g.bits(u, abits - 1, 0), vals, *P['tw'])
        A = g.mux(phs(e + 2, e + 4), Hi, Hr)
        prod = g.mul(A, B)
        fa = fmt[1] + P['tacc']
        wa = fmt[0] + P['tacc'] + 1
        prod = q(prod, wa, fa, 'trunc')
        acc = g.state(wa, fa)
        s = q(g.add(prod, g.mux(phs(e + 1, e + 3), g.const(2.0 ** -(fmt[1] + 1), wa, fa), acc)), wa, fa, 'trunc')
        g.close(acc, s)
        sq = q(s, fmt[0], fmt[1], 'trunc', fmt[2] if len(fmt) > 2 else 'wrap')
        d1 = reg(sq)                  # e+3: pr, e+5: pi
        d2 = reg(d1)                  # e+4: pr
        return g.mux(phs(e + 4), d2, d1)

    def swap_ctl(O, i, j):
        return ctl(O, lambda t: bit(t, j) == 1 and bit(t, i) == 0 and t < 64)

    # ---- 输入：舍入 + 前一槽寄存器 + DC 修正 + 串行化 ----
    h = (hi, hq)
    pv = (reg(h[0], phs(0)), reg(h[1], phs(0)))
    O = -22                           # S1 实部处理时钟（位置 0），相位 2
    s_h = ctl(O, lambda t: t < 32 or t >= 64)
    s_p = ctl(O, lambda t: 32 < t < 64)
    zc = g.const(P['dcoff'], *P['win'])     # DC 槽注入常数 = 输出 1/2 LSB 的舍入偏置
    isre1 = phs(O)
    xs = [g.mux(s_h, h[k], g.mux(s_p, pv[k], zc)) for k in range(2)]
    x = g.mux(isre1, xs[0], xs[1])

    def T1(t):   # W64^{p_lo*i_lo} (-j)^{p_lo} (-1)^{m0}
        p_lo = t & 15
        i_lo = bit(t, 5) + 2 * bit(t, 4)
        return complex(W(p_lo * i_lo) * (-1j) ** p_lo * (-1) ** bit(t, 5))

    def T2(t):
        return complex(W(4 * (t & 3) * (bit(t, 3) + 2 * bit(t, 2))))

    wd = P['wd']
    of = P['out']
    # 相位安排：S1..S5 处理相位 2/3，输出侧（SW1/SW2/CP）相位 0/1；
    # 共享链：A = S1(32 tick) + SW1(31)；B = S2(16) + CP(16，循环 4 次 = 64 tick)；
    #         D = SW2(14) + S3(8, 位置 0..31) + S4(4, 位置 32..47 注入) + S5(2, 位置 48..55 注入)。
    #         S6、SW3 用使能移位寄存器。
    def delay_n(v, n):
        for _ in range(n):
            v = reg(v)
        return v

    def en_shift(din, n, O):
        en = phs(O, O + 1)
        regs = [g.state(din.w, din.f) for _ in range(n)]
        return regs, en

    chA = Chain(128, wd[0], x.f)
    with g.scope("s1"):
        O1 = O
        out1, din1 = sdf(x, 32, O1, None, wd[0], chA.tap(128))
        O = O1 + 128
    with g.scope("s2"):
        x2 = delay_n(out1, P['r12']); O += P['r12']
        O2 = O + 1
        chB = Chain(64, wd[1], out1.f)
        out2, din2 = sdf(x2, 16, O2, lambda t: bit(t, 5), wd[1], chB.tap(64))
        O = O2 + 64
    with g.scope("t1"):
        x3 = twiddle(q(out2, wd[1], out1.f), O, T1, P['tm'][0], 8)
        O += 4
    with g.scope("s3"):
        O3 = O
        chD = Chain(56, max(wd[2], wd[3], wd[4]), x3.f)
        out3, din3 = sdf(x3, 8, O3, None, wd[2], from_fmt(chD.tap(32), x3.f, wd[2]), P['sat'][2])
        O = O3 + 32
    with g.scope("s4"):
        x4 = delay_n(out3, P['r34']); O += P['r34']
        O4 = O + 1
        out4, din4 = sdf(x4, 4, O4, lambda t: bit(t, 3), wd[3], from_fmt(chD.tap(48), x4.f, wd[3]), P['sat'][3])
        O = O4 + 16
    with g.scope("t2"):
        x5 = twiddle(q(out4, wd[3], out3.f), O, T2, P['tm'][1], 6)
        O += 4
    with g.scope("s5"):
        O5 = O
        out5, din5 = sdf(x5, 2, O5, None, wd[4], from_fmt(chD.tap(56), x5.f, wd[4]), P['sat'][4])
        O = O5 + 8
    with g.scope("s6"):
        O6 = O + 1
        en6 = phs(O6, O6 + 1)
        r6 = [g.state(wd[5], out5.f) for _ in range(2)]
        out6, din6 = sdf(q(out5, wd[4], out5.f), 1, O6, lambda t: bit(t, 1), wd[5], r6[-1])
        prev = din6
        for r in r6:
            g.close(r, g.mux(en6, prev, r))
            prev = r
        O = O6 + 4
    # 输出舍入（/32）+ 饱和
    y = reg(q(g.shift(out6, -5), of[0], of[1], 'trunc', 'sat')); O += 1
    with g.scope("rev"):
        Osw1 = O
        s1c = swap_ctl(Osw1, 0, 5)
        do1 = from_fmt(chA.tap(124), of[1])
        y1 = g.mux(s1c, y, do1)
        dsw1 = g.mux(s1c, do1, y)
        chA.close(g.mux(phs(O1, O1 + 1), din1, to_fmt(dsw1, wd[0], chA.f)))
        O = Osw1 + 124
        Osw2 = O
        s2c = swap_ctl(Osw2, 1, 4)
        do2 = from_fmt(chD.tap(56), of[1])
        y2 = g.mux(s2c, y1, do2)
        dsw2 = g.mux(s2c, do2, y1)
        chD.close(g.mux(phs(O3, O3 + 1), to_fmt(din3, chD.w, chD.f), to_fmt(dsw2, chD.w, chD.f)),
                  {32: (phs(O4, O4 + 1), din4), 48: (phs(O5, O5 + 1), din5)})
        O = Osw2 + 56
        Osw3 = O
        s3c = swap_ctl(Osw3, 2, 3)
        e3 = phs(Osw3, Osw3 + 1)
        r3s = [g.state(y2.w, y2.f) for _ in range(8)]
        do3 = r3s[-1]
        y3 = g.mux(s3c, y2, do3)
        dsw3 = g.mux(s3c, do3, y2)
        prev = dsw3
        for r in r3s:
            g.close(r, g.mux(e3, prev, r))
            prev = r
        O = Osw3 + 16
    # ---- CP：位置 0..15 存入，16..63 在链 B 中循环，64..79 重放 ----
    with g.scope("cp"):
        Ocp = O
        first = ctl(Ocp, lambda t: t < 16)
        lt64 = ctl(Ocp, lambda t: t < 64)
        docp = from_fmt(chB.tap(64), of[1])
        outs = g.mux(lt64, y3, docp)
        dcp = g.mux(first, y3, docp)
        chB.close(g.mux(phs(O2, O2 + 1), din2, to_fmt(dcp, wd[1], chB.f)))
        oI = reg(outs)                # 实部延迟一拍，与虚部在 Ocp+1 一起取样
    assert O3 % 4 == O4 % 4 == O5 % 4
    for a_, b_ in ((O1, Osw1), (O2, Ocp), (O3, Osw2)):
        assert len({a_ % 4, (a_ + 1) % 4, b_ % 4, (b_ + 1) % 4}) == 4, (a_, b_)

    # ---- 输出：实部寄存、虚部直通，在 Ocp+1 相位取样；起始标志 ----
    Os = Ocp + 1
    wr = g.state(2, 0)
    at319 = lut1(c, [1 if cc == 319 else 0 for cc in range(512)])
    g.close(wr, q(g.mux(at319, g.const(1, 2, 0), wr), 2, 0))
    stv = g.state(2, 0)
    cpre = (Os - 1) % 320
    atp = lut1(c, [1 if cc == cpre else 0 for cc in range(512)])
    trig = AND(atp, g.bits(wr, 0, 0)) if (Os - 1) >= 320 else atp
    g.close(stv, q(g.mux(trig, g.const(1, 2, 0), stv), 2, 0))
    so_ = AND(phs(Os), g.bits(stv, 0, 0))
    ob = spec.output_bits
    g.output(g.sample(q(oI, ob, ob - 1), so_), g.sample(q(outs, ob, ob - 1), so_))
