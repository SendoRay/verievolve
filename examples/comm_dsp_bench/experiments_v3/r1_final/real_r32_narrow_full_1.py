# v17: v16 + NCO 真取负；去掉乘法器数据输入与输出量化后的流水寄存器（数据来自延迟线寄存器）
# v16: v14 + 乘积截到 2^-22（输出 LSB）；HB4 差分基多一级减法，流水切点提前到第 3 层
# v14: v13 + HB3/HB4 改差分基（h0 隐含，重新量化：HB3 6 位、HB4 9 位）
# v13: v12 + 虚部改为相位减 1/4 周（省系数选择）、八分圆/象限交换合并
# v12: v11 + 混频在交错流上分时（2 个乘法器，系数/数据按奇偶选择）
# v11: v10 + 各级半带改交错多相（偶相交错流长延迟线、奇相交错流只延迟中心抽头；输出天然是交错流）
#      HB1 直接在全速率上拼出 HB2 的偶/奇相流
# v10: v7 + 全链在 I/Q 交错流上运行（每级半带一棵树分时服务两路；末级同相位抽取拆回 I、Q）
# v7: v6 + HB2/HB3/HB4 输出量程收窄到 ±0.5（HB2 之后干扰镜像 ≤0.031×0.45，信号峰值 ≤0.47）
# v6: v5 + 更少位数系数（随机序 LP 量化）+ 中心/常数先合并 + HB4 树中流水 + 八分圆正余弦表 + 乘积截位后寄存
# v5: 直接型多相半带（延迟线 + 对称预加）+ 单棵混合符号加法树（常数作叶子）+ 树中段流水寄存器
#     fs/4 免费粗混频；HB1 精确无舍入；输出速率 NCO（12 位相位、四分之一波表）+ 4 乘法器
import math

# h: 半带系数 h_0..h_{K-1}（奇偏移 ±1,±3,...）；diff=True 时 h_0 = 0.25-Σg 隐含（H(0.5)=0 精确）
# cut: 加法树第几层之后插流水寄存器（None 不插）
HB = [
    dict(h=[0.2815093994140625, -0.0315093994140625], diff=True, cut=None),
    dict(h=[0.292999267578125, -0.048858642578125, 0.005859375], diff=True, cut=None),
    dict(h=[0.3014564514160156, -0.06427383422851562, 0.0146484375, -0.0018310546875],
         diff=True, cut=3),
    dict(h=[0.31261253356933594, -0.090087890625, 0.040157318115234375, -0.018068313598632812,
            0.00732421875, -0.002471923828125, 0.0006237030029296875, -9.1552734375e-05],
         diff=False, cut=4),
]
CFG = dict(F=[18, 18, 19, 19], W=[18, 18, 19, 13], OVF=['wrap', 'wrap', 'sat', 'sat'], GUARD=3, A=12, LW=12, LF=11, PF=22)


def csd(c, B=30):
    n = int(round(c * 2 ** B)); d = []; k = 0
    while n:
        if n & 1:
            r = 2 - (n & 3); d.append((r, k - B)); n -= r
        n >>= 1; k += 1
    return d


def sgn_tree(g, v, cut=None):
    """v = [(sig, ±1)]，两两合并成一棵树；cut 层之后对所有部分和插 g.reg。返回 (sig, sign)。"""
    lvl = 0
    while len(v) > 1:
        nv = []
        for i in range(0, len(v), 2):
            if i + 1 == len(v):
                nv.append(v[i]); continue
            (a, sa), (b, sb) = v[i], v[i + 1]
            if sa == sb:
                nv.append((g.add(a, b), sa))
            elif sa > 0:
                nv.append((g.sub(a, b), 1))
            else:
                nv.append((g.sub(b, a), 1))
        v = nv; lvl += 1
        if cut is not None and lvl == cut:
            v = [(g.reg(s), sg) for s, sg in v]
    return v[0]


def lin(g, terms, F, W, guard, ovf='wrap', cut=None, early=None):
    """Σ c·x：CSD 移位加；各移位项截到 F+guard 位小数，截位均值偏差与 0.5LSB 舍入并入一个常数叶子。"""
    v = []; bias = 0.0; fg = F + guard
    for x, c in terms:
        for s, k in csd(c):
            t = g.shift(x, k)
            if t.f > fg:
                if t.w - t.f + fg < 2:
                    continue
                bias -= s * 0.5 * (2.0 ** -fg - 2.0 ** -t.f)
                t = g.q(t, t.w - t.f + fg, fg, 'trunc', 'wrap')
            v.append((t, s))
    cst = g.const(0.5 * 2.0 ** -F - bias, fg + 3, fg + 1)
    if early is not None:                      # 早到达的项（中心抽头）先与常数相加，作为一片叶子
        x0, c0 = early
        t0 = g.shift(x0, int(round(math.log2(abs(c0)))))
        v.insert(0, ((g.add(cst, t0) if c0 > 0 else g.sub(cst, t0)), 1))
    else:
        v.append((cst, 1))
    acc, sg = sgn_tree(g, v, cut)
    assert sg > 0
    return g.q(acc, W, F, 'trunc', ovf)


def hb_dec(g, x, hb, csign, F, W, guard, ovf='wrap'):
    """多相抽 2 半带：y = csign·0.5·x[2m-2K+1] + Σ h_i (x[2m-2K+2+2i] + x[2m-2K-2i])。"""
    h = hb['h']; K = len(h)
    e = g.decimate(x, 2, 0); o = g.decimate(x, 2, 1)
    t = g.delay_line(e, 2 * K)
    s = [g.add(t[K - 1 - i], t[K + i]) for i in range(K)]
    c = g.delay(o, K)
    if hb['diff']:
        terms = [(s[0], 0.25)] + [(g.sub(s[i], s[0]), h[i]) for i in range(1, K)]
    else:
        terms = [(s[i], h[i]) for i in range(K)]
    return lin(g, terms, F, W, guard, ovf, hb['cut'], early=(c, 0.5 * csign))


def hb_core(g, E, O, cdel, hb, csign, F, W, guard, ovf):
    """交错多相半带核心：E 为偶相交错流（e_I,e_Q,...），O 为奇相交错流；
    w[p] = Σ h_i (E[p-2(K-1-i)] + E[p-2(K+i)]) + csign·0.5·O[p-cdel]，w 的偶/奇样点即 I/Q 输出（交错流）。"""
    h = hb['h']; K = len(h)
    t = g.delay_line(E, 4 * K - 1)
    s = [g.add(t[2 * (K - 1 - i)], t[2 * (K + i)]) for i in range(K)]
    c = g.delay(O, cdel)
    if hb['diff']:
        terms = [(s[0], 0.25)] + [(g.sub(s[i], s[0]), h[i]) for i in range(1, K)]
    else:
        terms = [(s[i], h[i]) for i in range(K)]
    return lin(g, terms, F, W, guard, ovf, hb['cut'], early=(c, 0.5 * csign))


def hb_il(g, y, hb, csign, F, W, guard, ovf='wrap'):
    """交错流 y（y[2k]=I[k]、y[2k+1]=Q[k]，周期 P）上的抽 2 半带：拆成偶相流 E 与奇相流 O（晚一组），
    长延迟线只存偶相样点，一棵树分时服务 I/Q；输出 w（周期 2P）仍是交错流。"""
    K = len(hb['h'])
    sel = g.bits(g.counter(1, 2, like=y), 1, 1)
    d = g.delay_line(y, 4)
    E = g.decimate(g.mux(sel, d[1], d[0]), 2, 0)       # E[2m]=y[4m], E[2m+1]=y[4m+1]
    O = g.decimate(g.mux(sel, d[3], d[2]), 2, 0)       # O[2m]=y[4m-2], O[2m+1]=y[4m-1]
    return hb_core(g, E, O, 2 * K - 2, hb, csign, F, W, guard, ovf)


def build(g, spec):
    F, W, GD = CFG['F'], CFG['W'], CFG['GUARD']
    x = g.input()
    # fs/4 粗混频 + HB1（9/32、-1/32，精确）：I = (9(e2-e1) - (e0-e3))/32，Q = 中心抽头 0.5·o
    # 交替符号 (-1)^m 吸收进 HB2 中心抽头符号；Q 路整体取反，在混频器里补回
    # 输入本身就是 I/Q 交错流：I 来自偶样点（HB1 插值对齐到奇样点时刻）、Q 来自奇样点（0.5·x[n-5]）。
    # 在全速率上直接拼出 HB2 的偶相流 E（n≡0 取 I、n≡2 取 Q）与奇相流 O（相反），O 比 E 超前一个样点。
    with g.scope("hb1"):
        t = g.delay_line(x, 7)
        da = g.sub(t[4], t[2]); db = g.sub(t[0], t[6])
        wI = g.q(g.shift(g.add(g.shift(da, 3), g.sub(da, db)), -5), 19, 18, 'trunc', 'wrap')
        x5 = g.shift(t[5], -1)
        sel = g.bits(g.counter(1, 2), 1, 1)
        E = g.decimate(g.mux(sel, x5, wI), 2, 0)
        O = g.decimate(g.mux(sel, wI, x5), 2, 0)
    with g.scope("hb2"):
        y = hb_core(g, E, O, 2 * len(HB[0]['h']) - 1, HB[0], -1, F[0], W[0], GD, CFG['OVF'][0])
    for k in (1, 2):
        with g.scope("hb%d" % (k + 2)):
            y = hb_il(g, y, HB[k], 1, F[k], W[k], GD, CFG['OVF'][k])
    with g.scope("hb5"):
        w = hb_il(g, y, HB[3], 1, F[3], W[3], GD, 'sat')     # 交错流：w[2m]=a=I，w[2m+1]=b=-Q（周期 16）
    # 输出速率 NCO：乘 e^{+j2π·12455405·m/2^27}；八分圆表 + 象限
    # 混频在交错流上分时：p=2m+1 算实部 a·cosφ + b·sinφ，p=2m+2 算虚部 a·sinφ − b·cosφ
    # = a·cos(φ−90°) + b·sin(φ−90°)，即虚部只是相位减 1/4 周：两拍共用同一套 (cos, sin) 与 2 个乘法器
    with g.scope("nco"):
        A, LW, LF = CFG['A'], CFG['LW'], CFG['LF']
        STEP = 12455405
        par = g.bits(g.counter(1, 1, like=w), 0, 0)    # p 为奇数时 1
        ctr = g.counter(STEP, 28, like=w)              # p·STEP（28 位，满周 = 2^28）
        ph = g.add(ctr, g.mux(par, g.const(STEP, 28, 0), g.const(-2 ** 26, 28, 0)))  # 奇：2(m+1)·STEP；偶：再减 1/4 周
        idx = g.bits(ph, 27 - 3, 28 - A)               # 八分圆内地址
        oc = g.bits(ph, 25, 25); b0 = g.bits(ph, 26, 26); b1 = g.bits(ph, 27, 27)
        N = 2 ** (A - 3); mx = 1 - 2.0 ** -LF
        nidx = g.bits(g.sub(g.const(N - 1, A, 0), idx), A - 4, 0)   # N-1-idx（按位取反）
        ad = g.bits(g.mux(oc, nidx, idx), A - 4, 0)
        th = [math.pi / 2 * (k + 0.5) / (2 * N) for k in range(N)]
        C = g.lut(ad, [min(mx, math.cos(t)) for t in th], LW, LF)
        S = g.lut(ad, [min(mx, math.sin(t)) for t in th], LW, LF)
        # 象限 q=b1b0：(c,s) = (ct,st)、(−st,ct)、(−ct,−st)、(st,−ct)；八分圆镜像与象限交换合成一次交换
        xr = lambda u, v: g.bits(g.add(u, v), 0, 0)
        sw = xr(oc, b0)
        u = g.mux(sw, S, C); v = g.mux(sw, C, S)
        z0 = g.const(0, LW, LF)
        kA = g.reg(g.mux(xr(b0, b1), g.sub(z0, u), u))     # 真取负（反码的 1 LSB 偏差会进带内）
        kB = g.reg(g.mux(b1, g.sub(z0, v), v))
        d = g.delay_line(w, 3)
        xa = g.mux(par, d[1], d[2]); xb = g.mux(par, d[0], d[1])
    with g.scope("mixer"):
        PF = CFG['PF']
        def pm(u, v):
            p = g.mul(u, v)
            return g.reg(g.q(p, p.w - p.f + PF, PF, 'trunc', 'wrap'))
        r = g.add(pm(xa, kA), pm(xb, kB))
        ob = spec.output_bits
        rq = g.q(g.shift(r, 7), ob, ob - 1)
        oI = g.decimate(g.delay(rq, 1), 2, 0); oQ = g.decimate(rq, 2, 0)
    g.output(oI, oQ)
