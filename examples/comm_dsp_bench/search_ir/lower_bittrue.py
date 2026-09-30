"""Deterministic search-IR lowering to existing integer reference models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from certfit import tpl_cordic
from chains.ddc import fixed_chain, ref_chain

from .canonicalize import candidate_hash
from .validate import validate_fir_node, validate_nco_node


def leaf_nco_config(node: Mapping[str, Any]) -> dict[str, Any]:
    """Translate an IR leaf to the legacy, already-verified NCO configuration.

    This bridge exists only while the old bit-true model and RTL generator are
    reused.  It dispatches on node kind, never on a registered candidate name.
    """
    validate_nco_node(node)
    kind = node["kind"]
    name = f"ir_{candidate_hash(node)[:12]}"
    if kind == "lut_sincos":
        return {
            "name": name,
            "algo": "lut",
            "order": node["interpolation"],
            "depth": int(node["depth"]),
            "phase_bits": int(node["phase_bits"]),
        }
    if kind == "cordic_sincos":
        return {
            "name": name,
            "algo": "cordic",
            "stages": int(node["stages"]),
            "phase_bits": int(node["phase_bits"]),
        }
    raise NotImplementedError(
        "phasor_compose is not a leaf; use emulate_nco_accumulators or RTL tree lowering"
    )


def split_phase_accumulators(
    phase_acc: np.ndarray, split_bits: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split phase into the nearest coarse grid point and a signed residual.

    Returns ``(coarse_unsigned, residual_unsigned, residual_signed)``.  The
    first two arrays are 32-bit modulo-domain states suitable for child NCOs.
    """
    acc = np.asarray(phase_acc, dtype=np.int64)
    if np.any(acc < 0) or np.any(acc > 0xFFFFFFFF):
        raise ValueError("phase_acc must contain unsigned 32-bit states")
    if not 2 <= split_bits <= 14:
        raise ValueError("split_bits must be in [2, 14]")
    step = 1 << (32 - split_bits)
    half = step >> 1
    coarse_index = ((acc + half) // step) & ((1 << split_bits) - 1)
    coarse = (coarse_index * step) & 0xFFFFFFFF
    delta = acc - coarse
    residual_signed = ((delta + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)
    residual = residual_signed & 0xFFFFFFFF
    return (
        coarse.astype(np.int64),
        residual.astype(np.int64),
        residual_signed.astype(np.int64),
    )


def _round_shift_15(value: np.ndarray, mode: str) -> np.ndarray:
    if mode == "rne":
        return (value + (1 << 14)) >> 15
    if mode == "trunc":
        return value >> 15
    raise ValueError(f"unsupported product rounding {mode!r}")


def emulate_nco_accumulators(
    node: Mapping[str, Any], phase_acc: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate an NCO tree on explicit unsigned 32-bit accumulator states."""
    validate_nco_node(node)
    if node["kind"] == "phasor_compose":
        coarse_acc, residual_acc, _ = split_phase_accumulators(
            phase_acc, int(node["split_bits"])
        )
        coarse_sin, coarse_cos = emulate_nco_accumulators(node["coarse"], coarse_acc)
        residual_sin, residual_cos = emulate_nco_accumulators(
            node["residual"], residual_acc
        )
        real_product = coarse_cos * residual_cos - coarse_sin * residual_sin
        imag_product = coarse_sin * residual_cos + coarse_cos * residual_sin
        cos_code = _round_shift_15(real_product, node["product_rounding"])
        sin_code = _round_shift_15(imag_product, node["product_rounding"])
        return (
            np.clip(sin_code, -(1 << 15), (1 << 15) - 1).astype(np.int64),
            np.clip(cos_code, -(1 << 15), (1 << 15) - 1).astype(np.int64),
        )

    cfg = leaf_nco_config(node)
    acc = np.asarray(phase_acc, dtype=np.int64)
    if np.any(acc < 0) or np.any(acc > 0xFFFFFFFF):
        raise ValueError("phase_acc must contain unsigned 32-bit states")
    phase_bits = int(cfg["phase_bits"])
    phase_word = acc >> (32 - phase_bits)
    z = phase_word << (16 - phase_bits)
    z_signed = np.where(z >= (1 << 15), z - (1 << 16), z).astype(np.int64)
    params = (
        {"algo": "lut", "order": cfg["order"], "depth": cfg["depth"]}
        if cfg["algo"] == "lut"
        else {"algo": "cordic", "stages": cfg["stages"]}
    )
    sin_code, cos_code = tpl_cordic.emulate(params, z_signed)
    return sin_code.astype(np.int64), cos_code.astype(np.int64)


def fir_node_config(node: Mapping[str, Any]) -> dict[str, Any]:
    """Return the explicit numeric choices shared by both FIR structures."""
    validate_fir_node(node)
    return {
        "name": f"ir_{candidate_hash(node)[:12]}",
        "wc": int(node["coefficient_bits"]),
        "prod_drop": int(node["product_drop"]),
        "wacc": int(node["accumulator_bits"]),
        "mode": node["rounding"],
    }


def resolve_fir_coefficients(node: Mapping[str, Any]) -> np.ndarray:
    """Resolve the frozen DDC coefficient family and quantize it per candidate."""
    cfg = fir_node_config(node)
    taps = ref_chain.prototype_taps()
    return fixed_chain.quantize_coeffs(taps, cfg["wc"], cfg["mode"])


def _finish_fir_accumulator(acc: np.ndarray, cfg: Mapping[str, Any]) -> tuple[np.ndarray, int]:
    value = np.asarray(acc, dtype=np.int64)
    n_sat = 0
    accumulator_bits = int(cfg["wacc"])
    if accumulator_bits:
        lo = -(1 << (accumulator_bits - 1))
        hi = (1 << (accumulator_bits - 1)) - 1
        n_sat += int(np.sum((value < lo) | (value > hi)))
        value = np.clip(value, lo, hi)
    value = fixed_chain.shr_round(value, int(cfg["wc"]) - 2, cfg["mode"])
    value, output_saturation = fixed_chain.sat16(value)
    return value.astype(np.int64), n_sat + output_saturation


def _direct_symmetric_channel(
    signal: np.ndarray, hq: np.ndarray, output_indices: np.ndarray, cfg: Mapping[str, Any]
) -> tuple[np.ndarray, int]:
    """Symmetric pre-add implementation; quantization occurs after each pre-add product."""
    terms = []
    taps = len(hq)
    for tap in range(taps // 2):
        paired = signal[output_indices - tap] + signal[output_indices - (taps - 1 - tap)]
        terms.append(
            fixed_chain.drop_low(paired * int(hq[tap]), int(cfg["prod_drop"]), cfg["mode"])
        )
    center = signal[output_indices - taps // 2] * int(hq[taps // 2])
    terms.append(fixed_chain.drop_low(center, int(cfg["prod_drop"]), cfg["mode"]))
    acc = np.stack(terms, axis=1).sum(axis=1, dtype=np.int64)
    return _finish_fir_accumulator(acc, cfg)


def _polyphase_channel(
    signal: np.ndarray, hq: np.ndarray, output_indices: np.ndarray, cfg: Mapping[str, Any]
) -> tuple[np.ndarray, int]:
    """R=2 polyphase form with per-tap product quantization before branch sums."""
    tap_indices = np.arange(len(hq), dtype=np.int64)
    samples = signal[output_indices[:, None] - tap_indices[None, :]]
    products = samples * hq[None, :]
    products = fixed_chain.drop_low(products, int(cfg["prod_drop"]), cfg["mode"])
    even_branch = products[:, 0::2].sum(axis=1, dtype=np.int64)
    odd_branch = products[:, 1::2].sum(axis=1, dtype=np.int64)
    return _finish_fir_accumulator(even_branch + odd_branch, cfg)


def emulate_fir_decimator(
    node: Mapping[str, Any], x_re: np.ndarray, x_im: np.ndarray
) -> dict[str, Any]:
    """Evaluate a FIR / R=2 decimator node on signed Q1.15 input samples."""
    validate_fir_node(node)
    re = np.asarray(x_re, dtype=np.int64)
    im = np.asarray(x_im, dtype=np.int64)
    if re.ndim != 1 or im.ndim != 1 or len(re) != len(im):
        raise ValueError("x_re and x_im must be one-dimensional arrays of equal length")
    if np.any(re < -(1 << 15)) or np.any(re > (1 << 15) - 1):
        raise ValueError("x_re contains values outside signed Q1.15")
    if np.any(im < -(1 << 15)) or np.any(im > (1 << 15) - 1):
        raise ValueError("x_im contains values outside signed Q1.15")

    cfg = fir_node_config(node)
    hq = resolve_fir_coefficients(node)
    output_indices = np.arange(len(hq) - 1, len(re), 2, dtype=np.int64)
    channel = (
        _direct_symmetric_channel
        if node["kind"] == "direct_symmetric_fir_decimator"
        else _polyphase_channel
    )
    y_re, sat_re = channel(re, hq, output_indices, cfg)
    y_im, sat_im = channel(im, hq, output_indices, cfg)
    return {
        "re": y_re,
        "im": y_im,
        "n_sat": sat_re + sat_im,
        "output_indices": output_indices,
        "hq": hq,
    }
