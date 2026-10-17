# v26: v23 + 各级交织输出去掉 1 个整数位（干扰复包络 ≤ 0.9/(2·cos(π/16)) ≈ 0.46 < 0.5；k=8/16 带的干扰在 s1/s2 内已滤除，
#      半带 H(f)+H(0.5−f)=1 保证镜像对之和不超）。s5 输出与混频字长保持 2^-7（期望信号载波近 fs/4 时，
#      实峰值可低至复包络的 2·cos(π/4) 倍：复包络最大 0.0067/1.414 = 0.0047 > 2^-8，c012 的 2^-8 在统计复核中回绕）
# v23: v20 + 去掉输出寄存器；交织流分路不再显式延迟：用 decimate 的两个相位（编译器对齐，比显式延迟省寄存器），
# 各级在“正常/交换”两种 A/B 取法间选择，使 I/Q 偏斜各级相消（s2 交换、s3/s4 正常、s5 交换：净偏斜 +1，
# 由 s1 的 Q 延迟吸收，QD 仍为 3）；混频输出也改用相位对齐；s5 部分积保护位回到 2
import math
import numpy as np

# 各级半带偶相位系数 a_j = n_j / 2^B（中心抽头 0.5）
C2 = (12, [1153, -129])
C3 = (12, [1202, -203, 25])
C4 = (15, [9873, -2096, 473, -58])
C5 = (18, [81951, -23618, 10527, -4732, 1912, -640, 158, -22])
P = dict(F2=18, F3=19, F4=19, F5=20, R5=-6, G=3, KH=6, LB=14, TB=8, PIPE=3, MW=18, MF=22, MREG=1, PG=2, DG=99, BMERGE=1)
P.update(dict(KH=7, TB=6, PG=1, PIPE=0, F3=18, GS=(4, 3, 3, 3), OOVF='wrap', R5=-7, MW=16, LB=11))
P.update(dict(F4=18))
P.update(dict(MW=15, TB=5, GS=(4, 3, 3, 2), PG=0))
P.update(dict(CSE=1, CSEIN=2))
P.update(dict(GS=(4, 3, 3, 1)))
P.update(dict(MREG=0, MREGA=1, OREG=0))
P.update(dict(ZDEC=1, QD=3, NAT=(1, 1, 2), NAT2=2, CS2=-1, GS=(4, 3, 3, 2)))
P.update(dict(WX=(0, 0, 0), R5=-7, MW=16))


def csd(n):
    out, k = [], 0
    while n:
        if n & 1:
            r = 2 - (n & 3)
            out.append((r, k))
            n -= r
        n >>= 1
        k += 1
    return out


def tree(g, terms, pipe):
    """terms: [(sig, sign)]；平衡加法树，每 pipe 层插一级寄存器。"""
    lvl = 0
    while len(terms) > 1:
        nxt = []
        for i in range(0, len(terms) - 1, 2):
            (a, sa), (b, sb) = terms[i], terms[i + 1]
            if sa == sb:
                nxt.append((g.add(a, b), sa))
            elif sa > 0:
                nxt.append((g.sub(a, b), 1))
            else:
                nxt.append((g.sub(b, a), 1))
        if len(terms) % 2:
            nxt.append(terms[-1])
        terms = nxt
        lvl += 1
        if pipe and lvl % pipe == 0 and len(terms) > 1:
            terms = [(g.reg(s), sg) for s, sg in terms]
    s, sg = terms[0]
    return s if sg > 0 else g.neg(s)


def csd_digits(n):
    return len(csd(abs(n)))


def odd(m):
    z = 0
    while m % 2 == 0:
        m //= 2
        z += 1
    return m, z


_DEC = {}


def dec(n):
    """奇数 n>0 的常数乘法分解，返回 (加法器数, 表达式)。
    ('csd', n)；('fac', a, s, z, e) = e·(2^a+s)·2^z；('fr', a, s, z, e, b, t) = e·(2^a+s)·2^z + t·2^b·x。"""
    if n in _DEC:
        return _DEC[n]
    best = (csd_digits(n) - 1, ('csd', n))
    if n > 1:
        for a in range(1, 20):
            for s in (-1, 1):
                f = 2 ** a + s
                if f <= 1:
                    continue
                if n % f == 0:
                    m, z = odd(n // f)
                    c, e = dec(m)
                    if 1 + c < best[0]:
                        best = (1 + c, ('fac', a, s, z, e))
                for b in range(0, 22):
                    for t in (1, -1):
                        r = n - t * 2 ** b
                        if r > 1 and r % f == 0 and r // f < n:
                            m, z = odd(r // f)
                            c, e = dec(m)
                            if 2 + c < best[0]:
                                best = (2 + c, ('fr', a, s, z, e, b, t))
    _DEC[n] = best
    return best


def val_inner(e):
    """表达式内层（精确实现部分）的常数值。"""
    e = e[4]
    if e[0] == 'csd':
        return e[1]
    v = val_inner(e) * (2 ** e[1] + e[2]) * 2 ** e[3]
    return v + (e[6] * 2 ** e[5] if e[0] == 'fr' else 0)


def mat(g, e, x):
    """精确实现表达式 e·x（不截位）。"""
    if e[0] == 'csd':
        ts = [(g.shift(x, k), sg) for sg, k in csd(e[1])]
        return tree(g, ts, 0)
    terms = [(g.shift(x, 0), 1)] if False else []
    return sum_terms(g, top_terms(g, e, x))


def top_terms(g, e, x):
    """表达式最外层的项 [(信号, 符号, 移位)]；内层精确实现。"""
    if e[0] == 'csd':
        return [(x, sg, k) for sg, k in csd(e[1])]
    m = mat(g, e[4], x)
    out = [(m, 1, e[1] + e[3]), (m, e[2], e[3])]
    if e[0] == 'fr':
        out.append((x, e[6], e[5]))
    return out


def sum_terms(g, ts):
    return tree(g, [(g.shift(sig, k), sg) for sig, sg, k in ts], 0)


BIAS = [0.0]


def hb_ilv(g, A, B, coef, csign, w, f, last=False, G=None):
    """I/Q 交织半带 ÷2（见 v4b）；乘法用手写 CSD，部分积截到 f+G 位小数。
    偶相位延迟线后半段（只服务小系数）逐级截掉低位。各级截位偏置累加到 BIAS，
    在最后一级用一个常数统一补偿（各级直流增益≈1）。"""
    Bc, ns = coef
    M = len(ns)
    fk = f + (P['G'] if G is None else G)
    ev = g.bits(g.counter(1, 1, like=A), 0, 0)
    ve = g.mux(ev, B, A)
    vo = g.mux(ev, A, B)
    # 每个抽头所需小数位：后半段抽头 2(M+j-1) 只乘 a_j
    L = 4 * M - 1
    need = [ve.f] * L
    for j in range(1, M + 1):
        aj = abs(ns[j - 1]) / 2.0 ** Bc
        need[2 * (M + j - 1)] = min(ve.f, int(math.ceil(fk + math.log2(aj))) + P['DG'])
    for k in range(L - 2, -1, -1):
        need[k] = max(need[k], need[k + 1]) if k >= 2 * M else ve.f
    # 按所需精度分段，每段一个 delay_line（段间截位）
    t, bt, cb = [], [], 0.0
    k = 0
    cur = ve
    while k < L:
        e = k
        while e + 1 < L and need[e + 1] == need[k]:
            e += 1
        if need[k] < cur.f:
            d = cur.f - need[k]
            cur = g.q(cur, cur.w - d, need[k], rnd='trunc', ovf='wrap')
            cb += -(1 - 2.0 ** -d) / 2 * 2.0 ** -need[k]
        n = e - k + 1
        seg = g.delay_line(cur, n + (1 if k > 0 else 0))
        seg = seg[1:] if k > 0 else seg
        t += seg
        bt += [cb] * n
        cur = seg[-1]
        k = e + 1
    terms, bias = [], 0.0
    for j in range(1, M + 1):
        t2 = 2 * (M + j - 1)
        pj = g.add(t[2 * (M - j)], t[t2])
        bias += ns[j - 1] / 2.0 ** Bc * bt[t2]
        nn = ns[j - 1]
        mo, z0 = odd(abs(nn))
        sgn = 1 if nn > 0 else -1
        dm = dec(mo)
        if P['CSE'] and dm[0] < csd_digits(mo) - 1 and dm[1][0] != 'csd' and dec(odd(abs(int(val_inner(dm[1]))))[0])[0] <= P['CSEIN']:
            tts = [(sig, sg * sgn, k + z0) for sig, sg, k in top_terms(g, dec(mo)[1], pj)]
        else:
            tts = [(pj, sg, k) for sg, k in csd(nn)]
        for sig, sg, k in tts:
            tm = g.shift(sig, k - Bc)
            d = tm.f - fk
            if d > 0:
                tm = g.q(tm, tm.w - d, fk, rnd='trunc', ovf='wrap')
                bias += sg * (-(1 - 2.0 ** -d) / 2) * 2.0 ** -fk
            terms.append((tm, sg))
    c = g.shift(g.delay_line(vo, 2 * M)[2 * M - 1], -1)
    terms.append((c, csign))
    bias += -(1 - 2.0 ** -(fk - f)) / 2 * 2.0 ** -f        # 本级末端截断
    BIAS[0] += bias
    if last or not P['BMERGE']:
        kq = round(-BIAS[0] * 2 ** fk)
        BIAS[0] = 0.0
        if kq:
            terms.append((g.const(abs(kq) * 2.0 ** -fk, 12, fk), 1 if kq > 0 else -1))
    y = tree(g, terms, P['PIPE'])
    return g.q(y, w, f, rnd='trunc', ovf='wrap')


def ilv_mix(g, v):
    """交织流上的精细混频。v[2k]=I_k, v[2k+1]=Q_k（速率 1/16）。
    粗旋转（2 个乘法器）：w[n] = v[n-1]·cos + X[n]·(∓sin)，X = 奇? v[n] : v[n-2]
      → w[2k+1] = I_k c − Q_k s,  w[2k+2] = Q_k c + I_k s
    细旋转（1 个乘法器）：z[n] = Y[n] + (±φ)·w[n-1]，Y = 偶? w[n] : w[n-2]
      → z[2k+2] = Qc + φ·Ic,  z[2k+3] = Ic − φ·Qc
    相位：每对样点共用一个相位（奇样点的相位地址在偶样点保持）；±号并入查表地址最高位。"""
    kh, lb, tb, F, PG = P['KH'], P['LB'], P['TB'], P['MF'], P['PG']
    R = g.reg if P['MREG'] else (lambda t: t)
    RA = g.reg if P.get('MREGA', P['MREG']) else (lambda t: t)
    od = g.bits(g.counter(1, 1, like=v), 0, 0)          # 1 = 奇样点
    ph = g.counter(12455405, 28, like=v)                # θ = 2π·ph/2^28
    a0 = g.bits(ph, 27, 28 - kh - tb)
    adr = RA(g.mux(od, a0, g.delay(a0, 1)))             # 偶样点沿用上一个奇样点的地址
    hi = g.bits(adr, kh + tb - 1, tb)
    lo = g.bits(adr, tb - 1, 0)
    n = 1 << kh
    m = 1 << tb
    cos = g.lut(hi, [math.cos(2 * math.pi * (k + 0.5) / n) for k in range(n)], lb, lb - 1)
    sa = g.bits(g.add(g.shift(od, kh), hi), kh, 0)      # 奇: −sin（地址高位=1）
    ssn = g.lut(sa, [math.sin(2 * math.pi * (k % n + 0.5) / n) * (1 if k < n else -1)
                     for k in range(2 * n)], lb, lb - 1)
    vt = g.delay_line(v, 3)
    vd = vt[1]
    X = g.mux(od, v, vt[2])

    def pq(t):
        return R(g.q(t, t.w - (t.f - F - PG), F + PG, rnd='trunc'))
    w = g.q(g.add(pq(g.mul(vd, cos)), pq(g.mul(X, ssn))), P['MW'], F, rnd='trunc', ovf='wrap')
    # 细角 φ（对应上一样点的地址），奇样点取负
    pa = g.bits(g.add(g.shift(od, tb), g.delay(lo, 1)), tb, 0)
    phi = g.lut(pa, [2 * math.pi * ((k % m + 0.5) / m - 0.5) / n * (1 if k < m else -1)
                     for k in range(2 * m)], tb + 2, tb + kh - 1)
    wt = g.delay_line(w, 3)
    Y = g.mux(od, wt[2], w)
    z = g.q(g.add(Y, pq(g.mul(wt[1], phi))), P['MW'], F, rnd='trunc', ovf='wrap')
    if P.get('ZDEC', 0):                                 # z[2m+1]=I_{m-1}, z[2m]=Q_{m-1}：由编译器按相位对齐
        return g.decimate(z, 2, 1), g.decimate(z, 2, 0)
    zt = g.delay_line(z, 3)                              # z[2m-1]=I_{m-2}, z[2m-2]=Q_{m-2}
    return g.decimate(zt[1], 2, 0), g.decimate(zt[2], 2, 0)


def split(g, F, nat=0):
    if nat == 1:                                         # (F[2m], F[2m+1])：不显式延迟，由编译器按相位对齐
        return g.decimate(F, 2, 0), g.decimate(F, 2, 1)
    if nat == 2:                                         # 交换：A 取奇相位、B 取偶相位
        return g.decimate(F, 2, 1), g.decimate(F, 2, 0)
    return g.decimate(F, 2, 0), g.decimate(g.delay(F, 1), 2, 0)


def build(g, spec):
    BIAS[0] = 0.0
    x = g.input()
    with g.scope("s1"):
        xe = g.decimate(x, 2, 0)
        xo = g.decimate(x, 2, 1)
        d = g.delay_line(xe, 4)
        i1 = g.shift(g.add(g.sub(d[3], d[0]), g.scale(g.sub(d[2], d[1]), 9)), -5)
        i1 = g.q(i1, 19, 18, ovf='wrap')                 # |I1| ≤ 20/32，19 位足够（精确）
        q1d = g.neg(g.shift(g.delay(xo, P['QD']), -1))        # Q1 延迟一个样点（交织所需）
    with g.scope("s2"):
        a2, b2 = (q1d, i1) if P['NAT2'] == 2 else (i1, q1d)
        y2 = hb_ilv(g, a2, b2, C2, P['CS2'], P['F2'] + P['WX'][0], P['F2'], G=P['GS'][0])
    with g.scope("s3"):
        y3 = hb_ilv(g, *split(g, y2, P['NAT'][0]), C3, 1, P['F3'] + P['WX'][1], P['F3'], G=P['GS'][1])
    with g.scope("s4"):
        y4 = hb_ilv(g, *split(g, y3, P['NAT'][1]), C4, 1, P['F4'] + P['WX'][2], P['F4'], G=P['GS'][2])
    with g.scope("s5"):
        w5 = P['F5'] + P['R5'] + 1
        y5 = hb_ilv(g, *split(g, y4, P['NAT'][2]), C5, 1, w5, P['F5'], last=True, G=P['GS'][3])
    with g.scope("mix"):
        zi, zq = ilv_mix(g, y5)
    b = spec.output_bits
    with g.scope("output"):
        o0 = g.q(g.shift(zi, 7), b, b - 1, ovf=P['OOVF'])
        o1 = g.q(g.shift(zq, 7), b, b - 1, ovf=P['OOVF'])
    if P.get('OREG', 1):
        o0, o1 = g.reg(o0), g.reg(o1)
    g.output(o0, o1)
