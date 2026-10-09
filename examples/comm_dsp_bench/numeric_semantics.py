"""Versioned fixed-point rounding and signed-boundary semantics.

Historical artifacts use ``rne`` and ``trunc``.  Their implemented meanings
are preserved exactly, but the names are aliases rather than mathematical
definitions: ``rne`` rounds to nearest with ties toward positive infinity;
``trunc`` is an arithmetic right shift, hence floor division for negatives.
New external plans use the explicit names below.
"""

from __future__ import annotations

from typing import Any


NUMERIC_SEMANTICS_VERSION = "verievolve-numeric-semantics-v1"
NEAREST_TIES_TO_POS_INF = "nearest_ties_to_pos_inf"
FLOOR = "floor"
EXPLICIT_ROUNDING_MODES = (NEAREST_TIES_TO_POS_INF, FLOOR)
LEGACY_ROUNDING_ALIASES = {
    "rne": NEAREST_TIES_TO_POS_INF,
    "trunc": FLOOR,
}


def normalize_rounding_mode(mode: str) -> str:
    """Return the explicit mode for an explicit name or historical alias."""
    if mode in EXPLICIT_ROUNDING_MODES:
        return mode
    try:
        return LEGACY_ROUNDING_ALIASES[mode]
    except (KeyError, TypeError) as exc:
        choices = sorted((*EXPLICIT_ROUNDING_MODES, *LEGACY_ROUNDING_ALIASES))
        raise ValueError(f"unsupported rounding mode {mode!r}; expected {choices}") from exc


def legacy_rounding_alias(mode: str) -> str:
    """Map an explicit mode to the token used by frozen historical artifacts."""
    explicit = normalize_rounding_mode(mode)
    return "rne" if explicit == NEAREST_TIES_TO_POS_INF else "trunc"


def round_shift(value: Any, bits: int, mode: str) -> Any:
    """Scale by ``2**-bits`` using the declared signed-integer semantics.

    Operators intentionally work for Python integers and NumPy integer arrays.
    No fixed-width overflow is introduced by this function.
    """
    if isinstance(bits, bool) or not isinstance(bits, int):
        raise TypeError("bits must be an integer")
    if bits < 0:
        return value << (-bits)
    if bits == 0:
        return value
    explicit = normalize_rounding_mode(mode)
    if explicit == FLOOR:
        return value >> bits
    return (value + (1 << (bits - 1))) >> bits


def _signed_decimal(width: int, value: int) -> str:
    return f"-{width}'sd{-value}" if value < 0 else f"{width}'sd{value}"


def signed_round_shift_expression(
    signal: str, width: int, shift: int, mode: str
) -> str:
    """Return a widened signed-Verilog expression matching :func:`round_shift`."""
    if not isinstance(signal, str) or not signal:
        raise ValueError("signal must be a nonempty Verilog expression")
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive integer")
    if isinstance(shift, bool) or not isinstance(shift, int) or shift < 0:
        raise ValueError("shift must be a nonnegative integer")
    if shift == 0:
        return f"$signed({signal})"
    explicit = normalize_rounding_mode(mode)
    bias = 1 << (shift - 1) if explicit == NEAREST_TIES_TO_POS_INF else 0
    return (
        f"($signed({{{signal}[{width - 1}], {signal}}}) + "
        f"{_signed_decimal(width + 1, bias)}) >>> {shift}"
    )


def sign_extend_code(code: int, width: int) -> int:
    """Interpret an unsigned ``width``-bit code as a signed two's-complement value."""
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive integer")
    if isinstance(code, bool) or not isinstance(code, int):
        raise TypeError("code must be an integer")
    if not 0 <= code < (1 << width):
        raise ValueError(f"code must be in [0, 2**{width})")
    return code - (1 << width) if code >= (1 << (width - 1)) else code


def wrap_signed(value: int, width: int) -> int:
    """Return the signed representative of ``value modulo 2**width``."""
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive integer")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("value must be an integer")
    return sign_extend_code(value & ((1 << width) - 1), width)


def saturate_signed(value: int, width: int) -> int:
    """Clamp an integer to the representable signed ``width``-bit interval."""
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive integer")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("value must be an integer")
    low = -(1 << (width - 1))
    high = (1 << (width - 1)) - 1
    return min(max(value, low), high)


def numeric_semantics_manifest() -> dict[str, Any]:
    """Describe the semantics exposed to planners and persisted run manifests."""
    return {
        "version": NUMERIC_SEMANTICS_VERSION,
        "rounding_modes": {
            NEAREST_TIES_TO_POS_INF: {
                "definition": "floor((value + 2^(shift-1)) / 2^shift)",
                "tie_direction": "positive_infinity",
            },
            FLOOR: {
                "definition": "floor(value / 2^shift)",
                "hardware_operation": "signed_arithmetic_right_shift",
            },
        },
        "legacy_aliases": dict(LEGACY_ROUNDING_ALIASES),
        "overflow_modes": {
            "sat": "clamp to the signed destination interval",
            "wrap": "signed representative modulo 2^width",
        },
    }
