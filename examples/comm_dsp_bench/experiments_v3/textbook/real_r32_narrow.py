
P = {"cordic_stages": 16, "cordic_w": 24, "cordic_zw": 16, "mix_w": 18, "cic_w": 20, "hb_coef": 17, "hb_w": 24, "fir_coef": 18, "fir_w": 22, "out_shift": 7, "R1": 8, "N": 5, "A_target_db": 104.23370558170004, "h_hb": [7.607826770759159e-06, -9.754142041116129e-20, -0.0011580499412840054, 1.553719636919376e-18, 0.011874712687107237, -6.886539864363136e-18, -0.05989290089788645, 1.5175758019713706e-17, 0.29917103475947127, 0.49999519113164226, 0.29917103475947127, 1.5175758019713706e-17, -0.05989290089788645, -6.886539864363136e-18, 0.011874712687107237, 1.553719636919376e-18, -0.0011580499412840054, -9.754142041116129e-20, 7.607826770759159e-06], "h_fir": [-9.447193599528357e-05, -0.00018617594282711015, 0.0007673824053800762, 0.0017730494911981723, -0.0030774918421362096, -0.008714272577818037, 0.00792744292399067, 0.029996890011127417, -0.013983261339891761, -0.08710209236300373, 0.011623298293606794, 0.31423260351965404, 0.49367419871342993, 0.31423260351965404, 0.011623298293606794, -0.08710209236300373, -0.013983261339891761, 0.029996890011127417, 0.00792744292399067, -0.008714272577818037, -0.0030774918421362096, 0.0017730494911981723, 0.0007673824053800762, -0.00018617594282711015, -9.447193599528357e-05]}


def build(g, spec):
    R, fp = spec.r_total, spec.passband
    R1, N = P["R1"], P["N"]
    x = g.input()
    ph = g.counter(spec.fcw, 32)
    K, cw, zw = P["cordic_stages"], P["cordic_w"], P["cordic_zw"]
    with g.scope("cordic"):                     # 下变频：把 (x, 0) 旋转 −θ，θ = 相位（单位：周）
        quad = g.bits(ph, 31, 30)               # 象限：先按 −90° 的整数倍精确旋转（交换与取负）
        b1, b0 = g.bits(quad, 1, 1), g.bits(quad, 0, 0)
        zero = g.const(0.0, 2, 1)
        xa = g.q(x, cw, cw - 2)
        nx = g.neg(xa)
        # 象限 0:(x,0) 1:(0,−x) 2:(−x,0) 3:(0,x)
        xi = g.mux(b0, zero, g.mux(b1, nx, xa))
        yi = g.mux(b0, g.mux(b1, xa, nx), zero)
        xi, yi = g.q(xi, cw, cw - 2), g.q(yi, cw, cw - 2)
        r = g.bits(ph, 29, 30 - zw)            # 余下角度 ∈ [0, 1/4) 周，无符号
        z = g.q(g.neg(g.shift(r, -(zw + 2))), zw + 3, zw + 2)   # z0 = −r（单位：周），有符号，范围 ±1/2 周
        for k in range(K):
            neg = g.bits(z, z.w - 1, z.w - 1)  # z < 0 → 向负方向旋转
            xs, ys = g.shift(xi, -k), g.shift(yi, -k)
            ang = math.atan(2.0 ** -k) / (2 * math.pi)
            xn = g.mux(neg, g.add(xi, ys), g.sub(xi, ys))
            yn = g.mux(neg, g.sub(yi, xs), g.add(yi, xs))
            zn = g.mux(neg, g.add(z, g.const(ang, zw + 3, zw + 2)), g.sub(z, g.const(ang, zw + 3, zw + 2)))
            xi, yi = g.reg(g.q(xn, cw, cw - 2, "trunc")), g.reg(g.q(yn, cw, cw - 2, "trunc"))
            z = g.reg(g.q(zn, zw + 3, zw + 2))
        Kc = 1.0
        for k in range(K):
            Kc *= math.sqrt(1 + 2.0 ** (-2 * k))
    mw = P["mix_w"]
    with g.scope("mixer"):                       # CORDIC 增益补偿（常数乘）
        br = [g.q(g.scale(xi, 1.0 / Kc, 16), mw, mw - 2), g.q(g.scale(yi, 1.0 / Kc, 16), mw, mw - 2)]
    out = []
    for k, y in enumerate(br):
        with g.scope("cic"):
            Wc = y.w + N * int(round(math.log2(R1)))              # Hogenauer 满量程界
            for _ in range(N):
                y = g.integrate(y, Wc)
            y = g.decimate(y, R1)
            for _ in range(N):
                y = g.q(g.sub(y, g.delay(y, 1)), Wc, y.f, ovf="wrap")
            y = g.q(g.shift(y, -N * int(round(math.log2(R1)))), P["cic_w"], P["cic_w"] - 2)
        with g.scope("halfband"):
            y = g.mac(list(zip(g.delay_line(y, len(P["h_hb"])), P["h_hb"])), coef_bits=P["hb_coef"])
            y = g.decimate(g.q(y, P["hb_w"], P["hb_w"] - 2), 2)
        with g.scope("comp_fir"):
            y = g.mac(list(zip(g.delay_line(y, len(P["h_fir"])), P["h_fir"])), coef_bits=P["fir_coef"])
            y = g.decimate(g.q(y, P["fir_w"], P["fir_w"] - 2), 2)
        with g.scope("output"):
            b = spec.output_bits
            out.append(g.q(g.shift(y, P["out_shift"]), b, b - 1))
    g.output(out[0], out[1])
