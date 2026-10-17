"""链 C：OFDM 接收内环（802.11a/g 20 MHz 参数）。公式：对每个 80 点符号去掉 16 点循环前缀，
Y_k = (1/32)·Σ_n x[n+16]·e^{-j2πkn/64}，按 k = −26..−1, 1..26 输出 52 个有用子载波。

这是帧处理任务（FrameTask）：输入每 in_period 个时钟一个复样点，输出每个符号 52 个样点（不规则间隔，
由 out_valid 标记）。1/32 = 酉 FFT 的 1/8 再乘 1/4，使输出码与 Verilog 契约（16 位、13 位小数的 Y_k/8·FFT）完全相同。
场景与 /Users/chengzhy/verievolve_tools/ofdm_tool.py 逐码一致，末尾另加 2 个全零符号以排空流水线（不计分）。
"""
from __future__ import annotations

import math

import numpy as np

from ..frame_task import FrameTask
from ..task import register

N, CP, NUSED = 64, 16, 52
SYM = N + CP
N_SYMBOLS, PAD_SYMBOLS = 12, 2
USED_BINS = [k % N for k in list(range(-26, 0)) + list(range(1, 27))]
SCENES = {
    0: dict(qam=16, rms=0.08, taps=4, seed=101),
    1: dict(qam=64, rms=0.11, taps=10, seed=202),
    10: dict(qam=64, rms=0.125, taps=12, seed=1010),
    11: dict(qam=16, rms=0.05, taps=1, seed=1111),
    12: dict(qam=256, rms=0.10, taps=8, seed=1212),
}


def _qam(rng, m, n):
    k = int(round(math.sqrt(m)))
    lv = np.arange(-(k - 1), k, 2, dtype=float)
    s = rng.choice(lv, n) + 1j * rng.choice(lv, n)
    return s / math.sqrt(2 * (m - 1) / 3)


def stimulus(idx: int, in_bits: int = 12):
    """返回 (x_i, x_q, ref)：x 为输入整数码（含末尾全零符号），ref 为每个符号 52 个子载波的浮点参考（Y_k/4 量纲）。"""
    p = SCENES[idx]
    rng = np.random.default_rng(p["seed"])
    pdp = np.exp(-np.arange(p["taps"]) / 3.0)
    h = (rng.normal(size=p["taps"]) + 1j * rng.normal(size=p["taps"])) * np.sqrt(pdp / pdp.sum() / 2)
    tx = []
    for _ in range(N_SYMBOLS):
        X = np.zeros(N, complex)
        X[USED_BINS] = _qam(rng, p["qam"], NUSED)
        x = np.fft.ifft(X) * math.sqrt(N)
        tx.append(np.concatenate([x[-CP:], x]))
    tx = np.concatenate(tx)
    rx = np.convolve(tx, h)[: len(tx)]
    rx = rx + (rng.normal(size=len(rx)) + 1j * rng.normal(size=len(rx))) * math.sqrt(10 ** (-3.0) / 2)
    rx = rx / np.sqrt(np.mean(np.abs(rx) ** 2)) * p["rms"]
    frac = in_bits - 1
    lim = (1 << frac) - 1
    re = np.clip(np.round(rx.real * (1 << frac)), -lim - 1, lim).astype(np.int64)
    im = np.clip(np.round(rx.imag * (1 << frac)), -lim - 1, lim).astype(np.int64)
    xq = (re + 1j * im) / (1 << frac)
    ref = np.concatenate([np.fft.fft(xq[s * SYM + CP:(s + 1) * SYM])[USED_BINS] / 32.0 for s in range(N_SYMBOLS)])
    pad = np.zeros(PAD_SYMBOLS * SYM, dtype=np.int64)
    return np.concatenate([re, pad]), np.concatenate([im, pad]), ref


DIRECT = '''# 直写起点（约定示例，自动可得的“照公式写”）：任务 ofdm_rx64
# 去 CP（gather 门控）→ 64 抽头延迟线做串并转换 → 在每帧最后一个样点上用常系数乘加直接算 52 个 DFT 输出
# → gather 并串转换按子载波顺序输出。正确但不考虑面积。
def build(g, spec):
    N, CP, SYM = spec.N, spec.CP, spec.SYM
    xi, xq = g.input()
    body = list(range(CP, SYM))
    bi = g.gather(xi, SYM, body)          # 去循环前缀：每 80 个样点取后 64 个
    bq = g.gather(xq, SYM, body)
    ti = g.delay_line(bi, N)              # ti[j] = x[k-j]；帧内第 63 个样点时 ti[63-n] = x[n]
    tq = g.delay_line(bq, N)
    yi, yq = [], []
    for k in spec.used_bins:
        re_terms, im_terms = [], []
        for n in range(N):
            c = np.exp(-2j * np.pi * k * n / N) * spec.out_scale      # 输出 = out_scale · Σ x[n]·e^{-j2πkn/N}
            xr, xm = ti[N - 1 - n], tq[N - 1 - n]
            re_terms += [(xr, c.real), (xm, -c.imag)]
            im_terms += [(xr, c.imag), (xm, c.real)]
        yi.append(g.q(g.mac(re_terms, 18), spec.output_bits, spec.output_bits - 1))
        yq.append(g.q(g.mac(im_terms, 18), spec.output_bits, spec.output_bits - 1))
    last = [(N - 1, j) for j in range(len(spec.used_bins))]   # 都在帧内最后一个样点上取
    g.output(g.gather(yi, N, last), g.gather(yq, N, last))
'''

register(FrameTask(
    name="ofdm_rx64",
    params=dict(N=N, CP=CP, SYM=SYM, used_bins=USED_BINS, out_scale=1.0 / 32, n_symbols=N_SYMBOLS),
    interface=dict(in_bits=12, out_bits=16, in_kind="complex", out_kind="complex", in_period=4, out_period=None),
    ideal=None,
    stimulus="ofdm_rx64",
    tolerance=dict(sqnr_min_db=45.0),
    search_scenarios=(0, 1),
    holdout_scenarios=(10, 11, 12),
    description=("复基带 OFDM 符号流（每符号 80 点，前 16 点为循环前缀；每 4 个时钟一个样点）去循环前缀、64 点 DFT，"
                 "按 k=−26..−1, 1..26 输出 52 个有用子载波 Y_k = (1/32)·Σ_n x[n+16]·e^{-j2πkn/64}。"),
    frame_stimulus=stimulus,
    frame_outputs=NUSED,
    frame_inputs=SYM,
    n_frames=N_SYMBOLS,
    direct_code=DIRECT,
))
