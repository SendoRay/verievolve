# 照公式直写：y[m] = (h * (x·e^{-j2π f_if n}))[m·R]
# 一张整周期正余弦表做混频，一个长的单级低通 h，最后抽取 R 倍。正确但不考虑面积。
def build(g, spec):
    x = g.input()
    # 相位 n·f_if：32 位累加器，取高 16 位查整周期正余弦表
    ph = g.counter(spec.fcw, 32)
    addr = g.bits(ph, 31, 16)
    cos = g.lut(addr, [math.cos(2 * math.pi * k / 65536) for k in range(65536)], 20, 18)
    sin = g.lut(addr, [math.sin(2 * math.pi * k / 65536) for k in range(65536)], 20, 18)
    with g.scope("mixer"):
        i = g.q(g.mul(x, cos), 22, 20)
        q = g.q(g.neg(g.mul(x, sin)), 22, 20)
    # 低通 h：通带到 passband，阻带从 fs_out - passband 开始（防止混叠进通带）
    fp, fstop = spec.passband, spec.fs_out - spec.passband
    ntaps, beta = scipy.signal.kaiserord(100.0, (fstop - fp) / 0.5)
    ntaps |= 1
    h = scipy.signal.firwin(ntaps, 0.5 * (fp + fstop), window=("kaiser", beta), fs=1.0)
    with g.scope("lowpass"):
        i = g.mac(list(zip(g.delay_line(i, ntaps), h)), coef_bits=22)
        q = g.mac(list(zip(g.delay_line(q, ntaps), h)), coef_bits=22)
    # 抽取 R 倍；乘 2^3 后量化到输出字长
    b = spec.output_bits
    with g.scope("output"):
        i = g.q(g.shift(g.decimate(i, spec.r_total), 3), b, b - 1)
        q = g.q(g.shift(g.decimate(q, spec.r_total), 3), b, b - 1)
    g.output(i, q)
