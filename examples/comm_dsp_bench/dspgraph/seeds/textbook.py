# 教科书多级结构：四分之一波 NCO → 4 阶 CIC(÷R/4) → 补偿 FIR(÷2, 分时复用) → 半带(÷2)
def build(g, spec):
    R, b = spec.r_total, spec.output_bits
    x = g.input()
    with g.scope("nco"):
        P = 12
        ph = g.counter(spec.fcw, 32)
        quad = g.bits(ph, 31, 30)
        idx = g.bits(ph, 29, 32 - P)
        n = 1 << (P - 2)
        tab = [math.sin(math.pi / 2 * k / n) for k in range(n)]
        # 四分之一波：象限 1、3 镜像地址；象限 2、3 取负
        mirror = g.bits(quad, 0, 0)
        idx_m = g.mux(mirror, g.sub(g.const(n - 1, P, 0), idx), idx)
        a = g.bits(g.q(idx_m, P, 0, ovf="wrap"), P - 3, 0)
        s0 = g.lut(a, tab, 16, 14)
        c0 = g.lut(g.bits(g.q(g.sub(g.const(n - 1, P, 0), idx_m), P, 0, ovf="wrap"), P - 3, 0), tab, 16, 14)
        neg_s = g.bits(quad, 1, 1)
        neg_c = g.bits(g.q(g.add(quad, g.const(1, 3, 0)), 3, 0, ovf="wrap"), 1, 1)
        sin = g.mux(neg_s, g.neg(s0), s0)
        cos = g.mux(neg_c, g.neg(c0), c0)
    with g.scope("mixer"):
        i = g.q(g.mul(x, cos), 18, 17)
        q = g.q(g.neg(g.mul(x, sin)), 18, 17)
    with g.scope("cic"):
        N, R1 = 4, R // 4
        W = 18 + N * int(math.log2(R1))
        def cic(v):
            for _ in range(N):
                v = g.integrate(v, W)
            v = g.decimate(v, R1)
            for _ in range(N):
                v = g.q(g.sub(v, g.delay(v, 1)), W, v.f, ovf="wrap")
            return g.q(g.shift(v, -N * int(math.log2(R1))), 20, 19)
        i, q = cic(i), cic(q)
    with g.scope("cfir"):
        fp, fo = spec.passband * R1, 1.0 / 2
        ntap = 23
        f = np.linspace(0, fp, 16)
        droop = np.abs(np.sinc(f) / np.sinc(f / R1) / R1) ** N if False else None
        h = scipy.signal.remez(ntap, [0, fp, fo - fp, 0.5], [1, 0], weight=[1, 20], fs=1.0)
        i = g.q(g.mac(list(zip(g.delay_line(i, ntap), h)), coef_bits=16, share=2), 20, 19)
        q = g.q(g.mac(list(zip(g.delay_line(q, ntap), h)), coef_bits=16, share=2), 20, 19)
        i, q = g.decimate(i, 2), g.decimate(q, 2)
    with g.scope("hb"):
        fp2 = spec.passband * R1 * 2
        nt = 31
        h = scipy.signal.remez(nt, [0, fp2, 0.5 - fp2, 0.5], [1, 0], fs=1.0)
        i = g.mac(list(zip(g.delay_line(i, nt), h)), coef_bits=16)
        q = g.mac(list(zip(g.delay_line(q, nt), h)), coef_bits=16)
        i = g.q(g.shift(g.decimate(i, 2), 3), b, b - 1)
        q = g.q(g.shift(g.decimate(q, 2), 3), b, b - 1)
    g.output(i, q)
