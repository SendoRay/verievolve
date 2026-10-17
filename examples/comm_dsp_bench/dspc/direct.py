"""语义直写：把任务的理想程序（公式）逐运算展开成足够宽的原语程序，作为搜索的根节点。

与 dspgen/direct.py 的展开规则相同，改用 dspc 原语：
  mix      → 相位累加器（模 2^32）→ 移成 [0, 1) 的相位 → 两张整周期正余弦查表（2^16 项，20 位）→ 全精度乘 → 量化到 22 位
  lowpass  → 100 dB Kaiser 窗直接型 FIR（22 位系数）
  decimate → g.decimate；upsample → g.interpolate
  输出     → 乘 2^G 后量化到接口位宽
理想解释下，相位不截断、表值与系数取精确值，因此直写起点的理想解释就是公式本身（滤波器为所选的 Kaiser FIR）。
"""
from __future__ import annotations

from dataclasses import dataclass

LUT_ADDR, LUT_W, LUT_F = 16, 20, 18
MIX_W, MIX_F = 22, 20
FIR_ATT_DB, COEF_BITS = 100.0, 22


@dataclass
class DSig:
    names: tuple
    rate: float = 1
    gain: float = 1.0


class DirectC:
    def __init__(self, in_kind="real"):
        self.lines: list[str] = []
        self._k = 0
        self.in_kind = in_kind

    def _n(self, p):
        self._k += 1
        return f"{p}{self._k}"

    def input(self) -> DSig:
        if self.in_kind == "complex":
            self.lines.append("xi, xq = g.input()")
            return DSig(("xi", "xq"))
        self.lines.append("x = g.input()")
        return DSig(("x",))

    def _nco(self, freq_word, acc_bits, like):
        self.lines += [
            f"ph = g.shift(g.counter({freq_word}, {acc_bits}, like={like}), -{acc_bits})   # 相位，单位为周",
            f"cos = g.lut(ph, lambda v: np.cos(2 * np.pi * v), {LUT_ADDR}, {LUT_W}, {LUT_F})",
            f"sin = g.lut(ph, lambda v: np.sin(2 * np.pi * v), {LUT_ADDR}, {LUT_W}, {LUT_F})",
        ]

    def mix(self, s: DSig, freq_word: int, acc_bits: int = 32) -> DSig:
        assert len(s.names) == 1 and s.rate == 1, "direct expansion of mix supports a real input at the input rate"
        i, q = self._n("i"), self._n("q")
        self.lines.append(f"# 频谱搬移 x·exp(-j2π·f0·n)，f0 = {freq_word}/2^{acc_bits}")
        self.lines.append('with g.scope("nco"):')
        start = len(self.lines)
        self._nco(freq_word, acc_bits, s.names[0])
        self.lines[start:] = ["    " + l for l in self.lines[start:]]
        self.lines += [
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
            self.lines.append(f"    {b} = lib.fir(g, {a}, {h}, coef_bits={COEF_BITS})")
        self._pending = (out, h)
        return DSig(out, s.rate, 1.0)

    def upsample(self, s: DSig, L: int) -> DSig:
        out = tuple(self._n("u") for _ in s.names)
        self.lines.append(f"# 零值内插 {L} 倍（幅度由后级低通乘 {L} 恢复）")
        for a, b in zip(s.names, out):
            self.lines.append(f"{b} = g.interpolate({a}, {L})")
        return DSig(out, s.rate / L, gain=L)

    def upconvert(self, s: DSig, freq_word: int, acc_bits: int = 32) -> DSig:
        assert len(s.names) == 2, "upconvert expects a complex signal"
        y = self._n("y")
        self.lines.append(f"# 上变频取实部 Re{{z·exp(j2π·f0·n)}} = I·cos − Q·sin，f0 = {freq_word}/2^{acc_bits}")
        self.lines.append('with g.scope("nco"):')
        start = len(self.lines)
        self._nco(freq_word, acc_bits, s.names[0])
        self.lines[start:] = ["    " + l for l in self.lines[start:]]
        self.lines += [
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


OFDM_TX = '''# 直写起点（自动生成）：任务 {name}
# 公式直译：52 个单槽 reframe 做串并转换（帧速率）→ 每个输出点用常系数复乘求和（64 点 IDFT）
# → interleave 按 b[48..63] ‖ b[0..63] 顺序并串输出。语义正确但不考虑 PPA。
def build(g, spec):
    N, CP, SLOTS = spec.N, spec.CP, spec.SLOTS
    xi, xq = g.input()
    with g.scope("s2p"):
        ui = [g.reframe(xi, SLOTS, [s]) for s in range(len(spec.used_bins))]
        uq = [g.reframe(xq, SLOTS, [s]) for s in range(len(spec.used_bins))]
    b = spec.output_bits
    bi, bq = [], []
    with g.scope("idft"):
        for m in range(N):
            re_t, im_t = [], []
            for s, k in enumerate(spec.used_bins):
                c = np.exp(2j * np.pi * k * m / N) * spec.out_scale    # b[m] = out_scale · Σ X_k·e^{+j2πkm/N}
                cr, ci = lib.coef(g, c.real, 18), lib.coef(g, c.imag, 18)
                if cr is not None:
                    re_t.append(g.mul(ui[s], cr))
                    im_t.append(g.mul(uq[s], cr))
                if ci is not None:
                    re_t.append(g.neg(g.mul(uq[s], ci)))
                    im_t.append(g.mul(ui[s], ci))
            bi.append(g.q(lib.add_tree(g, re_t), b, b - 1))
            bq.append(g.q(lib.add_tree(g, im_t), b, b - 1))
    order = list(range(N - CP, N)) + list(range(N))
    with g.scope("p2s"):
        oi = g.interleave([bi[m] for m in order])
        oq = g.interleave([bq[m] for m in order])
    g.output(oi, oq)
'''


def direct_start(task) -> str:
    """任务的直写起点（dspc 原语程序文本）。输出增益规则与 dspgen.Task.direct_start 相同。"""
    import math
    if getattr(task, "frame_outputs", None) and task.name.startswith("ofdm_tx"):
        return OFDM_TX.replace("{name}", task.name)

    import numpy as np
    pk = 0.0
    for i in task.search_scenarios:
        ref = task.scene(i)["reference"]
        n_out = int(task.n_in() / task.rate())
        v = ref.at(np.arange(n_out) * task.rate())
        pk = max(pk, float(np.max(np.abs(v.real))),
                 0.0 if task.iface("out_kind") == "real" else float(np.max(np.abs(v.imag))))
    gain_shift = int(math.floor(math.log2(0.8 / pk)))
    d = DirectC(task.iface("in_kind"))
    out = task.ideal(d, task.params)
    header = (f"# 直写起点（自动生成）：任务 {task.name}\n# {task.description}\n"
              f"# 由理想版程序逐运算展开；语义正确但不考虑 PPA。理想解释即公式本身。\n")
    return d.program(out, gain_shift, header)
