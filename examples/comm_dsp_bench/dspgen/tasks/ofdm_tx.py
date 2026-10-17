"""链 C：OFDM 发射（802.11a/g 20 MHz 参数）。公式：每个符号输入 52 个子载波上的 QAM 符号 X_k
（k = −26..−1, 1..26），计算 64 点 IDFT 并加 16 点循环前缀：

    b[m] = (1/32)·Σ_k X_k·e^{+j2πkm/64}，m = 0..63；输出 y = b[48..63] ‖ b[0..63]（每符号 80 点）

这是帧处理任务（FrameTask）：时钟为样点率的 4 倍（每 4 个时钟一个样点槽），每帧 80 个槽，前 52 个槽依次送入
X_k（顺序同上），后 28 个槽空闲（输入为 0）。输出每符号 80 个复样点，不规则间隔，由 out_valid 标记。

指标：发射 EVM，按全部 80 个输出样点（含循环前缀）与理想浮点 IDFT 的时域误差计算（框架中记为 SQNR = −EVM）。
门槛按“数字部分 EVM 比对应标准门限低 10 dB（只占总 EVM 预算约 10% 功率）”设定：
64QAM 802.11a −25 dB → −35 dB；256QAM 802.11ac −32 dB → −42 dB；1024QAM 802.11ax −35 dB → −45 dB；
4096QAM 802.11be −38 dB → −48 dB。
"""
from __future__ import annotations

import math

import numpy as np

from ..frame_task import FrameTask
from ..task import register

N, CP, NUSED = 64, 16, 52
SLOTS = N + CP                      # 每帧 80 个样点槽：前 52 个为数据，其余空闲
N_SYMBOLS, PAD_SYMBOLS = 12, 2
USED_BINS = [k % N for k in list(range(-26, 0)) + list(range(1, 27))]
IN_SCALE = 0.5                      # 单位平均功率的 QAM 乘 0.5 后送入（4096QAM 的角点约 0.6，留出余量）
OUT_SCALE = 1.0 / 32
SEEDS = {0: 301, 1: 302, 10: 1310, 11: 1311, 12: 1312}


def _qam(rng, m, n):
    if m == 0:          # 通用输入：每个分量在 ±A 上均匀分布，A 取使平均功率为 1（与 QAM 相同），峰值约等于 1024QAM 角点
        A = math.sqrt(3 / 2)
        return rng.uniform(-A, A, n) + 1j * rng.uniform(-A, A, n)
    k = int(round(math.sqrt(m)))
    lv = np.arange(-(k - 1), k, 2, dtype=float)
    s = rng.choice(lv, n) + 1j * rng.choice(lv, n)
    return s / math.sqrt(2 * (m - 1) / 3)


def make_stimulus(qam: int):
    def stimulus(idx: int, in_bits: int = 12):
        """返回 (x_i, x_q, ref)：x 为输入整数码（含末尾全零符号），ref 为每符号 80 个输出样点的浮点参考。
        参考由量化后的输入码计算，因此输入量化不计入实现误差。"""
        rng = np.random.default_rng(SEEDS.get(idx, 7000 + idx) * 7 + qam)
        frac = in_bits - 1
        lim = (1 << frac) - 1
        xi, xq, ref = [], [], []
        for _ in range(N_SYMBOLS):
            X = _qam(rng, qam, NUSED) * IN_SCALE
            re = np.clip(np.round(X.real * (1 << frac)), -lim - 1, lim).astype(np.int64)
            im = np.clip(np.round(X.imag * (1 << frac)), -lim - 1, lim).astype(np.int64)
            Xq = (re + 1j * im) / (1 << frac)
            full = np.zeros(N, complex)
            full[USED_BINS] = Xq
            b = np.fft.ifft(full) * N * OUT_SCALE
            ref.append(np.concatenate([b[N - CP:], b]))
            xi.append(np.concatenate([re, np.zeros(SLOTS - NUSED, np.int64)]))
            xq.append(np.concatenate([im, np.zeros(SLOTS - NUSED, np.int64)]))
        pad = np.zeros(PAD_SYMBOLS * SLOTS, dtype=np.int64)
        return (np.concatenate(xi + [pad]), np.concatenate(xq + [pad]), np.concatenate(ref))
    return stimulus


DIRECT = '''# 直写起点（约定示例，自动可得的“照公式写”）：任务 {name}
# 80 槽延迟线做串并转换 → 在每帧最后一个槽上用常系数乘加直接算 64 个 IDFT 输出
# → gather 并串转换，先输出循环前缀 b[48..63]，再输出 b[0..63]。正确但不考虑面积。
def build(g, spec):
    N, CP, SLOTS = spec.N, spec.CP, spec.SLOTS
    xi, xq = g.input()
    ti = g.delay_line(xi, SLOTS)          # 帧内最后一个槽（第 79 个）时 ti[79 - s] = 第 s 个槽的输入
    tq = g.delay_line(xq, SLOTS)
    bi, bq = [], []
    for m in range(N):
        re_terms, im_terms = [], []
        for s, k in enumerate(spec.used_bins):
            c = np.exp(2j * np.pi * k * m / N) * spec.out_scale      # b[m] = out_scale · Σ X_k·e^{+j2πkm/N}
            xr, xm = ti[SLOTS - 1 - s], tq[SLOTS - 1 - s]
            re_terms += [(xr, c.real), (xm, -c.imag)]
            im_terms += [(xr, c.imag), (xm, c.real)]
        bi.append(g.q(g.mac(re_terms, 18), spec.output_bits, spec.output_bits - 1))
        bq.append(g.q(g.mac(im_terms, 18), spec.output_bits, spec.output_bits - 1))
    order = list(range(N - CP, N)) + list(range(N))
    picks = [(SLOTS - 1, m) for m in order]   # 都在帧内最后一个槽上取
    g.output(g.gather(bi, SLOTS, picks), g.gather(bq, SLOTS, picks))
'''

# (名字, QAM 阶数, 数字部分 EVM 目标 dB, 依据)
SPECS = [
    ("ofdm_tx64_q64", 64, 35.0, "802.11a/g 64QAM 发射 EVM 门限 −25 dB，数字部分取 −35 dB"),
    ("ofdm_tx64_q256", 256, 42.0, "802.11ac 256QAM 发射 EVM 门限 −32 dB，数字部分取 −42 dB"),
    ("ofdm_tx64_q1024", 1024, 45.0, "802.11ax 1024QAM 发射 EVM 门限 −35 dB，数字部分取 −45 dB"),
    ("ofdm_tx64_q4096", 4096, 48.0, "802.11be 4096QAM 发射 EVM 门限 −38 dB，数字部分取 −48 dB"),
    ("ofdm_tx64_gen", 0, 45.0, "输入为任意 12 位复数（不限于星座点），与通用 IFFT 核同口径；门槛同 1024QAM"),
]

for name, qam, evm_db, basis in SPECS:
    register(FrameTask(
        name=name,
        params=dict(N=N, CP=CP, SLOTS=SLOTS, used_bins=USED_BINS, out_scale=OUT_SCALE, in_scale=IN_SCALE,
                    qam=qam, n_symbols=N_SYMBOLS, evm_max_db=-evm_db),
        interface=dict(in_bits=12, out_bits=12, in_kind="complex", out_kind="complex", in_period=4, out_period=None),
        ideal=None,
        stimulus=name,
        tolerance=dict(sqnr_min_db=evm_db),
        search_scenarios=(0, 1),
        holdout_scenarios=(10, 11, 12),
        description=(f"OFDM 发射（802.11a/g 参数，{'任意复数输入' if qam == 0 else f'{qam}QAM'}）：每符号 52 个子载波符号 X_k（k=−26..−1, 1..26）"
                     f"依次占用 80 个样点槽中的前 52 个（每 4 个时钟一个槽），输出 64 点 IDFT 加 16 点循环前缀共 80 个复样点："
                     f"b[m]=(1/32)·Σ_k X_k·e^{{+j2πkm/64}}，y=b[48..63]‖b[0..63]。发射 EVM ≤ −{evm_db:g} dB（{basis}）。"),
        frame_stimulus=make_stimulus(qam),
        frame_outputs=SLOTS,
        frame_inputs=SLOTS,
        n_frames=N_SYMBOLS,
        direct_code=DIRECT.replace('{name}', name),
    ))
