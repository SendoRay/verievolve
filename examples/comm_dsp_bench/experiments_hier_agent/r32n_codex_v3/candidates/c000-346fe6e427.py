# dev_r32_narrow 最终设计（来自 candidates/c32.py）
# 结构：Taylor 一阶插值 NCO（128 点表 + 6 位低位相位）全速实混频
#   → 5 级全速积分器（Hogenauer 剪枝，模运算）
#   → 盒长 [41,32,32,32,32] 的 CIC：首个 41 长梳状用 1/16 速率两相位抽取 + I/Q 交织实现
#   → 其余 4 个 32 长梳状合成非递归 FIR (1-z^-2)^4（I/Q 交织流复用）
#   → 输出速率 7 抽头 CSD 补偿器（I/Q 交织复用，系数 [2,-0.640625,0.138672,-1/64]）
#   → 所有截断偏置合并为一个常数补偿 → 16 位输出
P = dict(P=7, D=6, wl=12, cw=7, mix_w=15, Ls=[41, 32, 32, 32, 32], R=32, prune_db=-110.0, out_ib=-3, comp_in_w=16,
         comp_c=[2.0, -0.640625, 142/1024, -1/64], comp_f=21, out_sh=4)
FCW = 1061286419
def cic_prune(Ls, R, f_in, target_db, wfun=None):
    """Hogenauer 剪枝（任意盒长 Ls，第一个梳状在抽取处实现，其余为 R 长）：输出速率全带总噪声准则。"""
    N = len(Ls); G = float(np.prod(Ls))
    f = np.linspace(-0.5, 0.5, 400001)[1:-1]; df = f[1]-f[0]
    nu = (f*R + 0.5) % 1 - 0.5
    w2 = np.ones_like(f) if wfun is None else wfun(nu)
    s1 = 2*np.abs(np.sin(np.pi*f))
    combs = np.ones_like(f)
    for L in Ls:
        combs = combs*2*np.abs(np.sin(np.pi*f*L))
    seq = []
    for j in range(1, N+1):
        # 积分器 j 之后：剩余 N-j 个积分器 + 全部梳状
        H2 = np.zeros_like(f)
        nz = s1 > 1e-9
        H2[nz] = (combs[nz]/s1[nz]**(N-j))**2/G**2
        gain = np.sum(H2*w2)*df
        seq.append(min(math.floor(0.5*math.log2(gain/12/10**(target_db/10))+1), f_in))
    nu2 = np.linspace(-0.5, 0.5, 20001)[1:-1]; d2 = nu2[1]-nu2[0]
    w22 = np.ones_like(nu2) if wfun is None else wfun(nu2)
    for j in range(1, N+1):
        gain = np.sum(((2*np.abs(np.sin(np.pi*nu2)))**(2*(N-j))/G**2)*w22)*d2
        seq.append(math.floor(0.5*math.log2(gain/12/10**(target_db/10))+1))
    for k in range(1, len(seq)):
        seq[k] = min(seq[k], seq[k-1])
    return seq[:N], seq[N:]
def nco(g):
    Pb, Db, wl, cw = P["P"], P["D"], P["wl"], P["cw"]
    ph = g.counter(FCW, 32)
    a = g.bits(ph, 31, 32-Pb)
    lo = g.bits(ph, 31-Pb, 32-Pb-Db)
    step = 2*math.pi/2**Pb
    thm = [step*(k+0.5) for k in range(1 << Pb)]
    dm = 0.5*step*(1-1/2**Db)
    half = 2.0**-(wl)
    amp = 1 - 2.0**-(wl-3)
    C = g.lut(a, [amp*(math.cos(t)+dm*math.sin(t))+half for t in thm], wl+1, wl)
    S = g.lut(a, [-amp*(math.sin(t)-dm*math.cos(t))+half for t in thm], wl+1, wl)
    sc = 2*math.pi/8
    Ss = g.lut(a, [sc*math.sin(t) for t in thm], cw, cw-1)
    Cs = g.lut(a, [-sc*math.cos(t) for t in thm], cw, cw-1)
    sh = 3 - Pb - Db
    with g.scope("nco_corr"):
        mc = g.shift(g.mul(lo, Ss), sh)
        ms = g.shift(g.mul(lo, Cs), sh)
        cf = g.q(g.sub(C, mc), wl, wl-1, rnd='trunc', ovf='wrap')
        sf = g.q(g.add(S, ms), wl, wl-1, rnd='trunc', ovf='wrap')
    return cf, sf
def build(g, spec):
    x = g.input()
    with g.scope("nco"):
        cos, sin = nco(g)
    mw = P["mix_w"]
    with g.scope("mixer"):
        i1 = g.q(g.mul(x, cos), mw, mw-1, rnd='trunc', ovf='wrap')
        q1 = g.q(g.mul(x, sin), mw, mw-1, rnd='trunc', ovf='wrap')   # sin 表已取负
    Ls, R = P["Ls"], P["R"]
    N = len(Ls)
    fin = mw-1
    gl = int(math.ceil(math.log2(np.prod(Ls))))
    ibits = P["out_ib"] + gl
    c = P["comp_c"]
    def wfun(nu):
        return (c[0] + sum(2*c[k]*np.cos(2*np.pi*k*nu) for k in range(1, len(c))))**2
    fi, fc = cic_prune(Ls, R, fin, P["prune_db"], wfun)
    L1 = Ls[0]; ph = L1 - R
    def integ(s):
        s = g.q(s, ibits+s.f, s.f, ovf='wrap')
        for j in range(N):
            s = g.integrate(s, ibits+s.f)
            if fi[j] < s.f:
                s = g.q(s, ibits+fi[j], fi[j], rnd='trunc', ovf='wrap')
        return s
    assert L1 - R <= ph < R//2
    with g.scope("cic_int"):
        yI = integ(i1); yQ = integ(q1)
    with g.scope("comb1_ilv"):
        # 先交织再做首梳状：w 交织 1/16 相位 ph 的样点，v 交织相位 ph-9 的样点；c1 = w - v[k-2]
        uI9 = g.decimate(yI, R//2, ph); uI0 = g.decimate(yI, R//2, ph-(L1-R))
        uQ9 = g.decimate(yQ, R//2, ph); uQ0 = g.decimate(yQ, R//2, ph-(L1-R))
        sel = g.bits(g.counter(1, 1, like=uI9), 0, 0)
        w = g.mux(sel, g.delay_line(uQ9, 2)[1], uI9)
        v = g.mux(sel, g.delay_line(uQ0, 2)[1], uI0)
        z = g.q(g.sub(w, g.delay_line(v, 3)[2]), ibits+fc[0], fc[0], rnd='trunc', ovf='wrap')
    with g.scope("cic_comb"):
        # 其余 4 个 R 长梳状合成一个非递归 FIR：(1 - z^-2)^4（交织流上）
        dl = g.delay_line(z, 9)
        W0, F0 = z.w, z.f
        mw_ = lambda sg: g.q(sg, W0, F0, ovf='wrap')     # 模运算：中间和只需保留输入字宽
        a = mw_(g.add(dl[0], dl[8])); bq = mw_(g.add(dl[2], dl[6]))
        z = mw_(g.add(mw_(g.sub(a, g.shift(bq, 2))), mw_(g.add(g.shift(dl[4], 2), g.shift(dl[4], 1)))))
        z = g.q(z, ibits+fc[-1], fc[-1], rnd='trunc', ovf='wrap')
        cw_ = P["comp_in_w"]
        z = g.q(g.shift(z, -gl), cw_, cw_-1-P["out_ib"], rnd='trunc', ovf='wrap')
    with g.scope("comp"):
        # 手写 CSD 补偿器：c = [2, -(1/2+1/8+1/64), 1/8+1/64-1/512, -1/64]，按移位分组共用加法器
        assert c == [2.0, -0.640625, 142/1024, -1/64]
        FT = P["comp_f"]
        tbias = [0.0]
        def tq(sg, f):
            if sg.f > f:
                tbias[0] += 0.5*(2.0**-f - 2.0**-sg.f)
                return g.q(sg, f+2, f, rnd='trunc', ovf='wrap')
            return sg
        dl = g.delay_line(z, 13)
        x0 = dl[6]
        p1 = g.add(dl[4], dl[8]); p2 = g.add(dl[2], dl[10]); p3 = g.add(dl[0], dl[12])
        d = g.sub(p2, p1)
        t64 = g.sub(d, p3)
        y = g.sub(g.shift(x0, 1), g.shift(p1, -1))
        y = g.add(y, tq(g.shift(d, -3), FT))
        y = g.add(y, tq(g.shift(t64, -6), FT))
        y = g.sub(y, tq(g.shift(p2, -9), FT))
        o = g.q(y, FT-1, FT, rnd='trunc', ovf='wrap')   # 归一输出范围 ±0.25
    b = spec.output_bits
    with g.scope("output"):
        # 截断偏置（混频截断 + 末级梳状截断 + 输出截断）合并为一个常数补偿
        G1 = float(np.prod(Ls))/2.0**gl
        gc = c[0] + 2*sum(c[1:])
        tb = lambda fa, fb: 0.5*(2.0**-fb - 2.0**-fa)       # 从 fa 位截到 fb 位的平均偏置
        bias_mix = tb(x.f + cos.f, mw-1)*G1                    # 混频截断（经 CIC 归一增益）
        bias_cmb = tb(-fc[0], -fc[-1])*2.0**-gl               # 梳状 FIR 输出截断（原始单位→归一）
        bias_cin = tb(-fc[-1]+gl, cw_-1-P["out_ib"])           # 补偿器输入截断
        bias = ((bias_mix + bias_cmb + bias_cin)*gc + tbias[0])*2.0**P["out_sh"] + tb(40, b-1)
        o = g.shift(o, P["out_sh"])
        o = g.add(o, g.const(bias, 10, b+3))
        o = g.q(o, b, b-1, rnd='trunc', ovf='wrap')   # 前级模运算已限幅，输出不可能溢出
        oI = g.decimate(o, 2, 0); oQ = g.decimate(o, 2, 1)
    g.output(oI, oQ)
