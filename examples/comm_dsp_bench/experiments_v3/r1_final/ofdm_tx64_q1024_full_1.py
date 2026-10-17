# v17：v16 + PF=1（乘积与累加器小数位 2→1）
# v16：v15 + 系数象限并入累加级 j^r 旋转，系数表只存第一象限（系数非负、ci-cr 少 1 位）
# v15：v14 + 3 乘法复乘的 Q0+Q1 移到 Q 寄存器之后
# v14：v13 + 去掉 lane 0 空洞门控（k=0 槽恒为 L=1，贡献并入初值表）
# v13：v11 + AI=12（输出本身 ±2048 饱和不可达，模 2^12 累加即可）、PI=10（|P|>512 LSB 概率 <1e-10/样点）
# v11：v10 + lane 9 头部显式 2 级寄存器（编译器自动补齐放在更宽处）
# v10：v9 + 填充环/计算环拷贝结构（去掉 bank 读选择 mux）
# v5：v4 + lane 9 改为周期 2 的环（每 bank 省 2 字）+ 精度重新分配（PF=2, CF=7, CC 3 项, F3P/F4P=2）
# v4：在 v2/v3 基础上
#  - 树的输入直接取环内第 1 级寄存器（B 抽头），省掉一级专用流水寄存器
#  - 控制改为“lane 字段 + 4→16 译码”，累加初值按 (q, m') 6 位地址查表
#  - Q/P/累加器按统计范围收窄；3 乘法复乘
# b[m] = 1.2253 * sum_phi W64^{phi m} Q_phi(m mod 16),  Q_phi(m') = sum_a L_{4a+phi} W16^{a m'}
import numpy as np

F3, F3P = 2, 2      # 级 3 输出 / 常数乘积小数位
F4, F4P = 1, 2      # 级 4 输出 / 常数乘积小数位
CB, CF = 9, 7      # 复乘系数位宽 / 小数位
PF = 1              # 乘积、累加小数位
QI = 10             # Q 整数位（含符号）
PI = 10             # 乘积整数位
AI = 12             # 累加器整数位
TAP = 2             # 树从环的第几级寄存器读（0=状态寄存器本身）
CUTS = ('n3',)      # 树内流水切点；TAP + len(CUTS) 必须为 3（Q 之后是状态寄存器）
KAP = [(1, 0), (-1, 2), (-1, 4), (1, 6), (1, 8)]      # 0.70703
CC = [(1, 0), (-1, 4), (-1, 6)]                       # 0.92188
SS = [(1, 1), (-1, 3), (1, 7)]                        # 0.38281
NCFG = 64           # 配置 = m'*4 + phi
G3 = [(1, 0), (-1, 2)]        # 0.75
G3K = [(1, 1), (1, 5)]        # 0.53125 ≈ 0.75/√2
SHIFT3 = 1          # 类 3 整体移 1 个 lane（补偿 W16^{-m'} 并入系数表），使 lane 6 满、lane 9 只剩 k=38
RING1 = (9,)        # lane 9 只含 k=38（类 2）：单寄存器


class D:
    """硬件信号 + 全零数据（e=0，即 L=1）时在各配置下的期望值（用于离线算偏置）"""
    def __init__(self, s, v):
        self.s, self.v = s, np.asarray(v, dtype=float) * np.ones(NCFG)


def build(g, spec):
    assert TAP + len(CUTS) == 3
    assert TAP in (2, 3)

    def regn(x, n):
        for _ in range(n):
            x = g.reg(x)
        return x
    N, SLOTS = 64, 80
    used = list(spec.used_bins)
    SC = 0.5 / np.sqrt(682) * 2048 / 32          # 每电平单位对应的输出 LSB = 1.2253
    Wc = lambda p: np.exp(2j * np.pi * p / N)
    CFG_M = np.arange(NCFG) // 4
    CFG_P = np.arange(NCFG) % 4

    def C(v, w=2, f=0):
        return g.const(v, w, f)

    def bit(x, k):
        return g.bits(x, k, k)

    def AND(a, b):
        return g.bits(g.mux(a, b, C(0)), 0, 0)

    def NOT1(a):
        return g.bits(g.mux(a, C(0), C(1)), 0, 0)

    def xor(a, b):
        return g.bits(g.mux(a, NOT1(b), b), 0, 0)

    # ---- Dual 运算 ----
    def dadd(a, b):
        return D(g.add(a.s, b.s), a.v + b.v)

    def dsub(a, b):
        return D(g.sub(a.s, b.s), a.v - b.v)

    def dnot(x, s, sv):      # s=1 时按位取反 = -x - 2^-f
        f = x.s.f
        n = g.q(g.sub(g.const(-2.0 ** -f, x.s.w, f), x.s), x.s.w, f, rnd='trunc', ovf='wrap')
        return D(g.mux(s, n, x.s), np.where(sv, -x.v - 2.0 ** -f, x.v))

    def dsel(s, sv, a, b):   # s ? a : b
        return D(g.mux(s, a.s, b.s), np.where(sv, a.v, b.v))

    def dq(x, w, f):         # 截位（floor），模型里加均值偏置
        fin = x.s.f
        bias = -(2.0 ** -f - 2.0 ** -fin) / 2 if fin > f else 0.0
        return D(g.q(x.s, w, f, rnd='trunc', ovf='wrap'), x.v + bias)

    def dreg(x):
        return D(g.reg(x.s), x.v)

    def cut(name, x):
        return dreg(x) if name in CUTS else x

    def dcsd(x, terms, w, f):
        acc, val = None, 0.0
        for sg, k in terms:
            t = g.shift(x.s, -k)
            val += sg * 2.0 ** -k
            if acc is None:
                acc = t if sg > 0 else g.neg(t)
            else:
                acc = g.add(acc, t) if sg > 0 else g.sub(acc, t)
        return dq(D(acc, x.v * val), w, f)

    def dmul(a, b):
        return D(g.mul(a.s, b.s), a.v * b.v)

    def ctl(s, sv):
        return (s, np.asarray(sv, dtype=bool))

    def rot_add(n, y, q0, ngr, ngi):
        # n + j^q y ；q0 奇则交换实虚；ngr/ngi 为实/虚部取反控制
        yr = dsel(q0[0], q0[1], y[1], y[0])
        yi = dsel(q0[0], q0[1], y[0], y[1])
        yr = dnot(yr, ngr[0], ngr[1])
        yi = dnot(yi, ngi[0], ngi[1])
        return dadd(n[0], yr), dadd(n[1], yi)

    xi, xq = g.input()
    with g.scope("conv"):
        def conv(h):            # 码字 → 电平索引 e=floor(code*26/2048)，在样点域做，时钟域只保持 10 位
            x = g.q(h, 8, 7, rnd='trunc', ovf='wrap')
            y = g.add(g.sub(g.shift(x, 5), g.shift(x, 3)), g.shift(x, 1))
            return g.q(y, 5, 0, rnd='trunc', ovf='wrap')
        exi, exq = conv(xi), conv(xq)
    c160 = g.counter(1, 8, modulus=2 * SLOTS)
    (ei, eq, hc), st = g.clock(exi, exq, c160)
    hi = ei
    ph = g.counter(1, 2, like=hi)          # 时钟 mod 4；strobe 在 ph==1；读出类 φ=(ph-1)%4
    hca = g.bits(hc, 7, 0)

    def win(j160):
        par = j160 // SLOTS
        j = j160 % SLOTS
        o = (j - 52) % SLOTS
        m = (o - 16) % N
        return par, j, o, m

    lanes = [a for a in range(16) if a not in (7, 8)]

    with g.scope("ctrl"):
        def cw(t):
            par, j, o, m = win(t)
            valid = j <= 52
            kk = used[j] if j < 52 else 0       # 槽 j=52 为空闲槽（输入恒 0 → e=0）：写进 k=0 空洞，使其恒为 L=1
            lane = (((kk >> 2) + (SHIFT3 if (kk & 3) == 3 else 0)) % 16) if valid else 0
            tg = ((kk & 3) + 1) % 4 if valid else 0
            qprev = win((t - 1) % (2 * SLOTS))[3] >> 4
            return lane | (tg << 4) | (int(valid) << 6) | (int(j == 52) << 7) | (qprev << 9)
        CW = g.lut(hca, [cw(t) for t in range(2 * SLOTS)], 12, 0)
        lane = g.bits(CW, 3, 0)
        TG = g.bits(CW, 5, 4)
        valid = bit(CW, 6)
        QV = g.bits(CW, 10, 9)
        onehot = g.lut(lane, [1 << a for a in range(16)], 18, 0)
        insph = g.bits(g.lut(g.bits(g.sub(ph, TG), 1, 0), [1, 0, 0, 0], 2, 0), 0, 0)
        ins = AND(insph, valid)
        m0 = g.bits(g.add(hca, C(12, 6, 0)), 3, 0)          # 本窗口 m' = (j+12) mod 16
        m0c = m0
        m0p = g.bits(g.add(hca, C(11, 6, 0)), 3, 0)         # 上一窗口 m'


    with g.scope("ring"):
        # 填充环 F（每符号都写入）+ 计算环 Cm（在切换前 4 个时钟从 F 的头部逐拍拷入），省掉 bank 读选择
        load = bit(CW, 7)       # 槽 j=52 的 4 个时钟
        load9 = load
        heads = {}
        for a in lanes:
            we = AND(bit(onehot, a), ins)
            comp = []
            for src in (ei, eq):
                Sf = g.state(5, 0)
                Af = g.mux(we, src, Sf)
                if a in RING1:          # 单项 lane：保持寄存器
                    g.close(Sf, Af)
                    Sc = g.state(5, 0)
                    g.close(Sc, g.mux(load9, Af, Sc))
                    comp.append(regn(Sc, TAP))
                    continue
                g.close(Sf, g.reg(g.reg(g.reg(Af))))
                Sc = g.state(5, 0)
                Ac = g.mux(load, Af, Sc)
                Bc = g.reg(Ac)
                Cc = g.reg(Bc)
                Dc = g.reg(Cc)
                g.close(Sc, Dc)
                comp.append([Sc, Bc, Cc, Dc][TAP])
            heads[a] = tuple(comp)

    mv, phv = CFG_M, CFG_P
    m0x = regn(m0, TAP)             # 与树数据（环抽头 TAP）对齐
    phx = regn(ph, TAP)
    m0 = m0x
    s1 = ctl(bit(m0, 0), mv & 1)
    q0 = ctl(bit(m0, 0), mv & 1)
    q1 = ctl(bit(m0, 1), (mv >> 1) & 1)
    ngr2 = ctl(xor(q0[0], q1[0]), q0[1] ^ q1[1])
    hole013 = ctl(g.bits(g.lut(phx, [1, 1, 1, 0], 2, 0), 0, 0), phv != 2)

    with g.scope("leaf_l12"):
        def leaf(a):
            out = []
            for e in heads[a]:
                if a >= 9:
                    ne = g.q(g.sub(C(-1, 5, 0), e), 5, 0, ovf='wrap')
                    e2 = g.mux(s1[0], ne, e)
                    vv = np.where(s1[1], -1.0, 1.0)
                else:
                    e2, vv = e, np.ones(NCFG)
                L = g.q(g.add(g.shift(e2, 1), C(1)), 6, 0, ovf='wrap')
                hole = {9: hole013}.get(a)      # lane 0 的 k=0 槽从不写入（恒为 e=0 即 L=1），其贡献由累加初值表扣除
                if hole is not None:
                    L = g.mux(hole[0], C(0), L)
                    vv = np.where(hole[1], 0.0, vv)
                out.append(D(L, vv))
            return out
        x = {a: leaf(a) for a in lanes}
        n1 = {0: x[0]}
        for a in range(1, 7):
            n1[a] = [dq(dadd(x[a][c], x[a + 8][c]), 7, 0) for c in range(2)]
        n1[7] = x[15]
        n2 = {}
        for a in range(4):
            v = rot_add(n1[a], n1[a + 4], q0, ngr2, q1)
            n2[a] = [cut('n2', dq(c, 8, 0)) for c in v]

    with g.scope("l3"):
        odd = ctl(bit(m0, 0), mv & 1)
        r0 = ctl(bit(m0, 1), (mv >> 1) & 1)
        r1 = ctl(bit(m0, 2), (mv >> 2) & 1)
        ngr3 = ctl(xor(r0[0], r1[0]), r0[1] ^ r1[1])
        n3 = {}
        for a in range(2):
            y = n2[a + 2]
            # 奇 m'：0.75*n2_a + j^r*0.53125*(1+j)*n2_b（公共增益 0.75 由系数表补偿）
            dd = dcsd(dsub(y[0], y[1]), G3K, 9 + F3P, F3P)
            ss = dcsd(dadd(y[0], y[1]), G3K, 9 + F3P, F3P)
            ur = dsel(odd[0], odd[1], dd, y[0])
            ui = dsel(odd[0], odd[1], ss, y[1])
            xa = [dsel(odd[0], odd[1], dcsd(c, G3, 8 + F3P, F3P), c) for c in n2[a]]
            v = rot_add(xa, (ur, ui), r0, ngr3, r1)
            n3[a] = [cut('n3', dq(c, 10 + F3, F3)) for c in v]

    with g.scope("l4"):
        m0 = regn(m0x, len(CUTS))
        t0 = ctl(bit(m0, 0), mv & 1)
        t1 = ctl(bit(m0, 1), (mv >> 1) & 1)
        u0 = ctl(bit(m0, 2), (mv >> 2) & 1)
        u1 = ctl(bit(m0, 3), (mv >> 3) & 1)
        yr, yi = n3[1]
        W4 = 10 + F4P

        def sel4(v0, v1, v2, v3):
            hi_ = dsel(t0[0], t0[1], v3, v2)
            lo_ = dsel(t0[0], t0[1], v1, v0)
            return dsel(t1[0], t1[1], hi_, lo_)
        zero = D(g.const(0, 2, 0), 0.0)
        cyr, syr = dcsd(yr, CC, W4, F4P), dcsd(yr, SS, W4, F4P)
        cyi, syi = dcsd(yi, CC, W4, F4P), dcsd(yi, SS, W4, F4P)
        # t=2（45°）：0.75*n3_0 + 0.53125*(1+j)*n3_1，增益 0.75 由系数表补偿
        dk = dcsd(dsub(yr, yi), G3K, W4, F4P)
        sk = dcsd(dadd(yr, yi), G3K, W4, F4P)
        A = sel4(yr, cyr, dk, syr)
        B = sel4(zero, syi, zero, cyi)
        Cc = sel4(zero, syr, zero, cyr)
        Dd = sel4(yi, cyi, sk, syi)
        rr, ri = dsub(A, B), dadd(Cc, Dd)
        is2 = ctl(AND(t1[0], NOT1(t0[0])), (t1[1] == 1) & (t0[1] == 0))
        x0 = [dsel(is2[0], is2[1], dcsd(c, G3, 10 + F4P, F4P), c) for c in n3[0]]
        ngr4 = ctl(xor(u0[0], u1[0]), u0[1] ^ u1[1])
        v = rot_add(x0, (rr, ri), u0, ngr4, u1)
        Q = [dq(c, QI + F4, F4) for c in v]
        Qst = []
        for c in Q:                  # 状态寄存器：语义延迟 4 拍（读出后第 4 拍到达累加级）
            st_ = g.state(c.s.w, c.s.f)
            g.close(st_, c.s)
            Qst.append(D(st_, c.v))
        Q = Qst
        Qs = dq(dadd(Q[0], Q[1]), QI + 1 + F4, F4)     # 和放在寄存器之后（省 12 位寄存器）

    with g.scope("cmul"):
        # 累加级时刻 t 的数据来自窗口 (hc-1)、类 φ=(ph-1)%4；地址提前一拍算好存入寄存器
        php0 = g.bits(g.lut(ph, [1, 0, 0, 0], 2, 0), 0, 0)
        mnext = g.mux(php0, m0c, m0p)
        cadn = g.bits(g.add(g.shift(mnext, 2), ph), 5, 0)
        cad3 = g.state(7, 0)
        g.close(cad3, g.q(cadn, 7, 0, ovf='wrap'))
        cad3 = g.bits(cad3, 5, 0)
        g3 = sum(sg * 2.0 ** -k for sg, k in G3)
        # 系数相位 n = φm' (类 3 再减 4m')；象限 n>>4 并入累加级的 j^r 旋转，表中只存第一象限 → 系数非负/更窄
        nph = [((t & 3) * (t >> 2) - (4 * SHIFT3 * (t >> 2) if (t & 3) == 3 else 0)) % N for t in range(64)]
        quad = [n_ >> 4 for n_ in nph]
        cv = np.array([SC * Wc(nph[t] & 15)
                       / (g3 if ((t >> 2) & 1 or (t >> 2) & 3 == 2) else 1.0) for t in range(64)])
        qr = np.round(cv.real * 2 ** CF) / 2 ** CF
        qi = np.round(cv.imag * 2 ** CF) / 2 ** CF
        dqv, sqv = qi - qr, qr + qi
        cr = D(g.lut(cad3, list(qr), CB, CF), qr)
        cd_ = D(g.lut(cad3, list(dqv), CB, CF), dqv)       # 第一象限：|ci-cr| ≤ 1.634
        QD = g.bits(g.lut(cad3, quad, 3, 0), 1, 0)
        cs_ = D(g.lut(cad3, list(sqv), CB + 1, CF), sqv)
        k1, k2, k3 = dmul(Qs, cr), dmul(Q[0], cd_), dmul(Q[1], cs_)
        PW = PI + PF
        P = [dq(dsub(k1, k3), PW, PF), dq(dadd(k1, k2), PW, PF)]

    # ---- 累加级偏置模型 ----
    lsb = 2.0 ** -PF
    model = np.zeros(N, dtype=complex)
    for m in range(N):
        mp, q = m & 15, m >> 4
        for phi in range(4):
            k = mp * 4 + phi
            a_, b_ = P[0].v[k], P[1].v[k]
            r = (phi * q + quad[k]) % 4
            yr_, yi_ = [(a_, b_), (-b_ - lsb, a_), (-a_ - lsb, -b_ - lsb), (b_, -a_ - lsb)][r]
            model[m] += yr_ + 1j * yi_
    Dm = np.array([sum(np.exp(2j * np.pi * k * m / N) for k in used) for m in range(N)])
    init = SC * (1 + 1j) * Dm - model + 0.5 * (1 + 1j)     # +0.5：输出截位变舍入

    with g.scope("acc"):
        AW = AI + PF
        iad = g.bits(g.add(g.shift(QV, 4), m0p), 5, 0)        # m = q*16 + m'（上一窗口）
        IR = g.lut(iad, [np.round(init[m].real * 2 ** PF) / 2 ** PF for m in range(N)], AW, PF)
        II = g.lut(iad, [np.round(init[m].imag * 2 ** PF) / 2 ** PF for m in range(N)], AW, PF)
        rad = g.bits(g.add(g.shift(QV, 2), ph), 3, 0)
        RV0 = g.lut(rad, [(((p_ - 1) % 4) * qq) % 4 for qq in range(4) for p_ in range(4)], 3, 0)
        RV = g.bits(g.add(RV0, QD), 1, 0)
        a0, a1 = bit(RV, 0), bit(RV, 1)
        dz = np.zeros(NCFG, dtype=bool)
        yr2 = dnot(dsel(a0, dz, P[1], P[0]), xor(a0, a1), dz)
        yi2 = dnot(dsel(a0, dz, P[0], P[1]), a1, dz)
        acc_r = g.state(AW, PF)
        acc_i = g.state(AW, PF)
        g.close(acc_r, g.q(g.add(g.mux(st, IR, acc_r), yr2.s), AW, PF, rnd='trunc', ovf='wrap'))
        g.close(acc_i, g.q(g.add(g.mux(st, II, acc_i), yi2.s), AW, PF, rnd='trunc', ovf='wrap'))

    with g.scope("out"):
        started = g.state(2, 0)
        d54 = g.bits(g.lut(hca, [1 if t % SLOTS == 54 else 0 for t in range(2 * SLOTS)], 2, 0), 0, 0)
        g.close(started, g.mux(d54, C(1), started))
        so = AND(st, g.bits(g.mux(d54, C(1), started), 0, 0))
        oi = g.q(g.shift(acc_r, -11), 12, 11, rnd='trunc', ovf='sat')
        oq = g.q(g.shift(acc_i, -11), 12, 11, rnd='trunc', ovf='sat')
        g.output(g.sample(oi, so), g.sample(oq, so))
