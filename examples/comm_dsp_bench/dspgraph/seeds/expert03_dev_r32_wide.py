# 专家模板实例：{'k': 3, 'N': 4, 'M': 1, 'hb_taps': 27, 'fir_taps': 113, 'comp': 1, 'sw': 10.0, 'se': 1.0, 'P': 15, 'A': 14, 'Wm': 17, 'Wc': 22, 'Ch': 16, 'Wh': 18, 'Cf': 15, 'G': 4, 'sh_h': 1, 'sh_f': 16}
P_ = {'k': 3, 'N': 4, 'M': 1, 'hb_taps': 27, 'fir_taps': 113, 'comp': 1, 'sw': 10.0, 'se': 1.0, 'P': 15, 'A': 14, 'Wm': 17, 'Wc': 22, 'Ch': 16, 'Wh': 18, 'Cf': 15, 'G': 4, 'sh_h': 1, 'sh_f': 16}

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
        with g.scope(f"hb{s}"):
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
