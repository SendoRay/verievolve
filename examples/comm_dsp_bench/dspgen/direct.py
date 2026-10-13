"""理想版程序的第三种解释：直写定点起点。把每个数学级运算展开成“足够宽”的原语实现，生成可读的 build 程序文本，
作为 LLM 进化的起点。展开规则与具体链路无关：

  mix      → 相位累加器 + 整周期正余弦表（2^16 项，20 位）+ 通用乘法器，结果量化到 22 位（20 位小数）
  lowpass  → 100 dB Kaiser 窗 FIR（直接型，22 位系数），抽头数由过渡带宽度决定
  decimate → g.decimate
  输出     → 乘 2^G 后量化到接口位宽；G 由干净参考信号的峰值决定（留 6 dB 余量）
"""
from __future__ import annotations

from dataclasses import dataclass

LUT_ADDR, LUT_W, LUT_F = 16, 20, 18
MIX_W, MIX_F = 22, 20
FIR_ATT_DB, COEF_BITS = 100.0, 22


@dataclass
class DSig:
    names: tuple          # 实信号 (x,)；复信号 (i, q)
    rate: float = 1
    gain: float = 1.0     # 待由后级低通补偿的增益（内插后为 L）


class Direct:
    def _n(self, p):
        self._k += 1
        return f"{p}{self._k}"

    def __init__(self, in_kind="real"):
        self.lines: list[str] = []
        self._k = 0
        self.in_kind = in_kind

    def input(self) -> DSig:
        if self.in_kind == "complex":
            self.lines.append("xi, xq = g.input()")
            return DSig(("xi", "xq"))
        self.lines.append("x = g.input()")
        return DSig(("x",))

    def mix(self, s: DSig, freq_word: int, acc_bits: int = 32) -> DSig:
        assert len(s.names) == 1 and s.rate == 1, "direct expansion of mix supports a real input at the input rate"
        n = 1 << LUT_ADDR
        i, q = self._n("i"), self._n("q")
        self.lines += [
            f"# 频谱搬移 x·exp(-j2π·f0·n)，f0 = {freq_word}/2^{acc_bits}：相位累加器取高 {LUT_ADDR} 位查整周期正余弦表",
            f"ph = g.counter({freq_word}, {acc_bits})",
            f"addr = g.bits(ph, {acc_bits - 1}, {acc_bits - LUT_ADDR})",
            f"cos = g.lut(addr, [math.cos(2 * math.pi * k / {n}) for k in range({n})], {LUT_W}, {LUT_F})",
            f"sin = g.lut(addr, [math.sin(2 * math.pi * k / {n}) for k in range({n})], {LUT_W}, {LUT_F})",
            'with g.scope("mixer"):',
            f"    {i} = g.q(g.mul({s.names[0]}, cos), {MIX_W}, {MIX_F})",
            f"    {q} = g.q(g.neg(g.mul({s.names[0]}, sin)), {MIX_W}, {MIX_F})",
        ]
        return DSig((i, q), s.rate)

    def lowpass(self, s: DSig, passband: float, stopband: float, cutoff=None) -> DSig:
        fs = 1.0 / s.rate
        h, nt = self._n("h"), self._n("ntaps")
        out = tuple(self._n(c) for c in ("i", "q")[: len(s.names)])
        self.lines += [
            f"# 理想低通的直写实现：通带到 {passband!r}，阻带从 {stopband!r} 起（频率以输入采样率为单位）",
            f"fp, fstop = {passband!r}, {stopband!r}",
            f"{nt}, beta = scipy.signal.kaiserord({FIR_ATT_DB}, (fstop - fp) / (0.5 * {fs!r}))",
            f"{nt} |= 1",
            f'{h} = scipy.signal.firwin({nt}, 0.5 * (fp + fstop), window=("kaiser", beta), fs={fs!r})'
            + (f" * {s.gain!r}" if s.gain != 1 else ""),
            'with g.scope("lowpass"):',
        ]
        for a, b in zip(s.names, out):
            self.lines.append(f"    {b} = g.mac(list(zip(g.delay_line({a}, {nt}), {h})), coef_bits={COEF_BITS})")
        return DSig(out, s.rate, 1.0)

    def upsample(self, s: DSig, L: int) -> DSig:
        out = tuple(self._n("u") for _ in s.names)
        self.lines.append(f"# 零值内插 {L} 倍（幅度由后级低通乘 {L} 恢复）")
        for a, b in zip(s.names, out):
            self.lines.append(f"{b} = g.interpolate({a}, {L})")
        return DSig(out, s.rate / L, gain=L)

    def upconvert(self, s: DSig, freq_word: int, acc_bits: int = 32) -> DSig:
        assert len(s.names) == 2, "upconvert expects a complex signal"
        n = 1 << LUT_ADDR
        y = self._n("y")
        self.lines += [
            f"# 上变频取实部 Re{{z·exp(j2π·f0·n)}} = I·cos − Q·sin，f0 = {freq_word}/2^{acc_bits}（按本级采样率）",
            f"ph = g.counter({freq_word}, {acc_bits}, like={s.names[0]})",
            f"addr = g.bits(ph, {acc_bits - 1}, {acc_bits - LUT_ADDR})",
            f"cos = g.lut(addr, [math.cos(2 * math.pi * k / {n}) for k in range({n})], {LUT_W}, {LUT_F})",
            f"sin = g.lut(addr, [math.sin(2 * math.pi * k / {n}) for k in range({n})], {LUT_W}, {LUT_F})",
            'with g.scope("mixer"):',
            f"    {y} = g.q(g.sub(g.mul({s.names[0]}, cos), g.mul({s.names[1]}, sin)), {MIX_W}, {MIX_F})",
        ]
        return DSig((y,), s.rate)

    def decimate(self, s: DSig, r: int) -> DSig:
        out = tuple(self._n("d") for _ in s.names)
        for a, b in zip(s.names, out):
            self.lines.append(f"{b} = g.decimate({a}, {r})")
        return DSig(out, s.rate * r)

    def program(self, s: DSig, gain_shift: int, header: str) -> str:
        outs = [f"o{k}" for k in range(len(s.names))]
        body = self.lines + [f"# 乘 2^{gain_shift} 后量化到输出字长", "b = spec.output_bits", 'with g.scope("output"):']
        body += [f"    {o} = g.q(g.shift({n}, {gain_shift}), b, b - 1)" for o, n in zip(outs, s.names)]
        body.append(f"g.output({', '.join(outs)})")
        return header + "def build(g, spec):\n" + "\n".join("    " + l for l in body) + "\n"
