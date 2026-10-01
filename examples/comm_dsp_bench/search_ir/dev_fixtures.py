"""阶段 B/C 共用的固定开发候选；不是正式搜索候选池。"""

from .schema import (
    cordic_sincos,
    ddc_candidate,
    direct_symmetric_fir,
    lut_sincos,
    phasor_compose,
    polyphase_decimator,
)


def make_candidate(kind="lut", coefficient_bits=16):
    """保持最初开发 fixture 的结构与参数，不按结果挑选候选。"""
    if kind == "lut":
        return ddc_candidate(
            lut_sincos(256, "linear", 12),
            direct_symmetric_fir(coefficient_bits),
        )
    if kind == "cordic":
        return ddc_candidate(
            cordic_sincos(12, 16), polyphase_decimator(coefficient_bits)
        )
    if kind == "compose":
        return ddc_candidate(
            phasor_compose(
                lut_sincos(128, "nearest", 10),
                cordic_sincos(7, 16),
                split_bits=8,
            ),
            polyphase_decimator(coefficient_bits),
        )
    raise ValueError(kind)


def development_candidates():
    """按固定顺序返回三份独立 IR：LUT、CORDIC、单层 compose。"""
    return [make_candidate(kind) for kind in ("lut", "cordic", "compose")]
