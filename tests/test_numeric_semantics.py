from pathlib import Path
import shutil
import subprocess
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from numeric_semantics import (
    FLOOR,
    NEAREST_TIES_TO_POS_INF,
    normalize_rounding_mode,
    numeric_semantics_manifest,
    round_shift,
    saturate_signed,
    signed_round_shift_expression,
    sign_extend_code,
    wrap_signed,
)


def _independent_round_shift(value: int, shift: int, mode: str) -> int:
    """Pure quotient/remainder reference; does not use implementation shifts."""
    if shift < 0:
        return value * (1 << (-shift))
    if shift == 0:
        return value
    denominator = 1 << shift
    quotient, remainder = divmod(value, denominator)
    if mode == FLOOR:
        return quotient
    assert mode == NEAREST_TIES_TO_POS_INF
    return quotient + int(2 * remainder >= denominator)


def _literal(width: int, value: int) -> str:
    return f"-{width}'sd{-value}" if value < 0 else f"{width}'sd{value}"


@pytest.mark.parametrize("mode", [NEAREST_TIES_TO_POS_INF, FLOOR])
def test_round_shift_matches_independent_reference_over_signed_boundaries(mode):
    for shift in range(0, 8):
        for value in range(-513, 514):
            assert round_shift(value, shift, mode) == _independent_round_shift(
                value, shift, mode
            )


def test_positive_and_negative_half_ties_are_explicit():
    values = (-7, -5, -3, -1, 1, 3, 5, 7)
    assert [round_shift(value, 1, NEAREST_TIES_TO_POS_INF) for value in values] == [
        -3,
        -2,
        -1,
        0,
        1,
        2,
        3,
        4,
    ]
    assert [round_shift(value, 1, FLOOR) for value in values] == [
        -4,
        -3,
        -2,
        -1,
        0,
        1,
        2,
        3,
    ]


def test_historical_aliases_preserve_values_but_are_not_public_modes():
    assert normalize_rounding_mode("rne") == NEAREST_TIES_TO_POS_INF
    assert normalize_rounding_mode("trunc") == FLOOR
    manifest = numeric_semantics_manifest()
    assert set(manifest["rounding_modes"]) == {NEAREST_TIES_TO_POS_INF, FLOOR}
    assert "rne" not in manifest["rounding_modes"]
    assert "trunc" not in manifest["rounding_modes"]


def test_sign_extension_wrap_and_saturation_cover_exact_boundaries():
    for width in range(1, 9):
        modulus = 1 << width
        midpoint = 1 << (width - 1)
        for code in range(modulus):
            expected = code - modulus if code >= midpoint else code
            assert sign_extend_code(code, width) == expected
        low, high = -midpoint, midpoint - 1
        for value in range(-2 * modulus, 2 * modulus + 1):
            code = value % modulus
            expected_wrap = code - modulus if code >= midpoint else code
            assert wrap_signed(value, width) == expected_wrap
            assert saturate_signed(value, width) == min(max(value, low), high)


@pytest.mark.parametrize("mode", [NEAREST_TIES_TO_POS_INF, FLOOR])
@pytest.mark.parametrize("shift", [1, 2, 3])
def test_generated_signed_rtl_shift_matches_independent_reference(
    tmp_path, mode, shift
):
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not installed")
    expression = signed_round_shift_expression("x", 8, shift, mode)
    checks = []
    for value in range(-128, 128):
        expected = _independent_round_shift(value, shift, mode)
        checks.append(
            f"x = {_literal(8, value)}; #1; "
            f"if ($signed(y) !== {_literal(8, expected)}) "
            f'$fatal(1, "mismatch value={value}");'
        )
    source = f"""module tb;
reg signed [7:0] x;
wire signed [7:0] y = {expression};
initial begin
{chr(10).join(checks)}
$display("PASS"); $finish;
end
endmodule
"""
    source_path = tmp_path / "round_shift.v"
    executable = tmp_path / "round_shift.out"
    source_path.write_text(source, encoding="utf-8")
    compile_result = subprocess.run(
        ["iverilog", "-g2012", "-o", str(executable), str(source_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(
        ["vvp", str(executable)], capture_output=True, text=True, check=False
    )
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert "PASS" in run_result.stdout
