"""积木共用的定点整数原语（向量化，int64）。

rnd 语义：trunc = floor；round = floor(v + 2^(s-1))（半值向正无穷）。
"""

from __future__ import annotations

import numpy as np

ROUNDING = ("trunc", "round")


def to_codes(x: np.ndarray, width: int) -> np.ndarray:
    return np.round(x * float(1 << (width - 1))).astype(np.int64)


def from_codes(c: np.ndarray, width: int) -> np.ndarray:
    return c / float(1 << (width - 1))


def shift_round(v: np.ndarray, s: int, mode: str) -> np.ndarray:
    if s <= 0:
        return v << np.int64(-s)
    if mode == "round":
        return (v + (np.int64(1) << np.int64(s - 1))) >> np.int64(s)
    return v >> np.int64(s)


def sat(v: np.ndarray, bits: int) -> tuple[np.ndarray, int]:
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    n = int(np.count_nonzero((v < lo) | (v > hi)))
    return np.clip(v, lo, hi), n


def wrap(v: np.ndarray, bits: int) -> np.ndarray:
    half = np.int64(1) << np.int64(bits - 1)
    mask = (np.int64(1) << np.int64(bits)) - np.int64(1)
    with np.errstate(over="ignore"):
        return ((v + half) & mask) - half


def floor_grid(v: np.ndarray, b: int) -> np.ndarray:
    if b <= 0:
        return v
    return (v >> np.int64(b)) << np.int64(b)


def per_component(fn, x: np.ndarray, stats: dict, tag: str):
    """对复信号的实部、虚部分别执行同一实数处理，并累加统计。"""
    s1: dict = {}
    s2: dict = {}
    yr = fn(x.real, s1)
    yi = fn(x.imag, s2)
    for k in set(s1) | set(s2):
        stats[k] = s1.get(k, 0) + s2.get(k, 0)
    return yr + 1j * yi
