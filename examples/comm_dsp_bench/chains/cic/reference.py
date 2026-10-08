"""CIC witness 的三路独立参考实现。

正式参考采用有限 FIR 与 Python 无界整数递归的共同结果。第三路保留递归 float64
拓扑，但把内部整数状态按 2^40 精确取模，避免高阶积分器状态增长吞掉低位；二进制
模数内的加减在 float64 精确整数区间完成。
"""

from __future__ import annotations

import numpy as np


MODULUS_BITS = 40


def fir_coefficients(R: int, N: int) -> np.ndarray:
    h = np.ones(R, dtype=np.int64)
    for _ in range(N - 1):
        h = np.convolve(h, np.ones(R, dtype=np.int64))
    return h


def fir_integer(codes: np.ndarray, R: int, N: int) -> np.ndarray:
    x = np.asarray(codes, dtype=np.int64)
    return np.convolve(x, fir_coefficients(R, N))[: len(x)][::R].astype(np.int64)


def recursive_unbounded(codes: np.ndarray, R: int, N: int) -> np.ndarray:
    integrators = [0] * N
    delays = [0] * N
    out: list[int] = []
    for index, sample in enumerate(np.asarray(codes, dtype=np.int64)):
        current = int(sample)
        for k in range(N):
            integrators[k] += current
            current = integrators[k]
        if index % R:
            continue
        for k in range(N):
            previous = delays[k]
            delays[k] = current
            current -= previous
        out.append(current)
    return np.asarray(out, dtype=np.int64)


def _float_mod_signed(value: np.float64) -> np.float64:
    modulus = np.float64(1 << MODULUS_BITS)
    half = np.float64(1 << (MODULUS_BITS - 1))
    wrapped = np.remainder(value, modulus)
    return wrapped - modulus if wrapped >= half else wrapped


def recursive_float64(codes: np.ndarray, R: int, N: int) -> np.ndarray:
    """递归 float64 拓扑；2^40 模稳定化保持所有整数操作精确。"""
    integrators = [np.float64(0)] * N
    delays = [np.float64(0)] * N
    out: list[np.float64] = []
    for index, sample in enumerate(np.asarray(codes, dtype=np.int64)):
        current = np.float64(sample)
        for k in range(N):
            integrators[k] = _float_mod_signed(integrators[k] + current)
            current = integrators[k]
        if index % R:
            continue
        for k in range(N):
            previous = delays[k]
            delays[k] = current
            current = _float_mod_signed(current - previous)
        out.append(current)
    return np.asarray(out, dtype=np.float64)


def cross_validate(codes: np.ndarray, R: int, N: int) -> dict:
    fir = fir_integer(codes, R, N)
    integer = recursive_unbounded(codes, R, N)
    floating = recursive_float64(codes, R, N)
    if not np.array_equal(fir, integer):
        mismatch = int(np.flatnonzero(fir != integer)[0])
        raise RuntimeError(f"FIR/unbounded mismatch at output {mismatch}")
    if not np.array_equal(fir, floating):
        mismatch = int(np.flatnonzero(fir != floating)[0])
        raise RuntimeError(f"FIR/float64 mismatch at output {mismatch}")
    return {
        "output": fir,
        "n_output": len(fir),
        "fir_equals_unbounded": True,
        "fir_equals_float64": True,
        "float64_modulus_bits": MODULUS_BITS,
    }


def normalized_iq(i_codes: np.ndarray, q_codes: np.ndarray,
                  R: int, N: int) -> tuple[np.ndarray, dict]:
    i = cross_validate(i_codes, R, N)
    q = cross_validate(q_codes, R, N)
    scale = float((1 << 11) * (R ** N))
    y = (i["output"].astype(np.float64)
         + 1j * q["output"].astype(np.float64)) / scale
    return y, {
        "i": {k: v for k, v in i.items() if k != "output"},
        "q": {k: v for k, v in q.items() if k != "output"},
        "normalization": f"1/(2^11 * {R}^{N})",
    }
