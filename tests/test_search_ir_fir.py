import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.ddc import fixed_chain
from search_ir import (
    direct_symmetric_fir,
    emulate_fir_decimator,
    lower_fir_decimator_rtl,
    polyphase_decimator,
    resolve_fir_coefficients,
)


@pytest.mark.parametrize("coefficient_bits", [11, 12, 16])
@pytest.mark.parametrize("rounding", ["rne", "trunc"])
def test_direct_and_polyphase_are_bit_identical_without_product_drop(
    coefficient_bits, rounding
):
    rng = np.random.default_rng(20260930 + coefficient_bits)
    x_re = rng.integers(-(1 << 14), 1 << 14, size=257, dtype=np.int64)
    x_im = rng.integers(-(1 << 14), 1 << 14, size=257, dtype=np.int64)
    direct = direct_symmetric_fir(coefficient_bits, rounding=rounding)
    polyphase = polyphase_decimator(coefficient_bits, rounding=rounding)
    got_direct = emulate_fir_decimator(direct, x_re, x_im)
    got_polyphase = emulate_fir_decimator(polyphase, x_re, x_im)
    np.testing.assert_array_equal(got_direct["re"], got_polyphase["re"])
    np.testing.assert_array_equal(got_direct["im"], got_polyphase["im"])
    np.testing.assert_array_equal(
        got_direct["output_indices"], np.arange(32, len(x_re), 2)
    )


def test_polyphase_matches_legacy_direct_per_tap_semantics():
    rng = np.random.default_rng(41)
    x_re = rng.integers(-(1 << 14), 1 << 14, size=193, dtype=np.int64)
    x_im = rng.integers(-(1 << 14), 1 << 14, size=193, dtype=np.int64)
    node = polyphase_decimator(
        coefficient_bits=12, product_drop=2, accumulator_bits=24, rounding="rne"
    )
    got = emulate_fir_decimator(node, x_re, x_im)
    hq = resolve_fir_coefficients(node)
    legacy = fixed_chain.fir_fixed(
        x_re,
        x_im,
        hq,
        {"wc": 12, "prod_drop": 2, "wacc": 24, "mode": "rne"},
    )
    np.testing.assert_array_equal(got["re"], legacy["re"][32::2])
    np.testing.assert_array_equal(got["im"], legacy["im"][32::2])


def test_direct_preadd_and_polyphase_have_distinct_quantization_semantics():
    rng = np.random.default_rng(43)
    x_re = rng.integers(-(1 << 15), 1 << 15, size=193, dtype=np.int64)
    x_im = rng.integers(-(1 << 15), 1 << 15, size=193, dtype=np.int64)
    direct = emulate_fir_decimator(
        direct_symmetric_fir(12, product_drop=4, rounding="trunc"), x_re, x_im
    )
    polyphase = emulate_fir_decimator(
        polyphase_decimator(12, product_drop=4, rounding="trunc"), x_re, x_im
    )
    assert np.any(direct["re"] != polyphase["re"]) or np.any(
        direct["im"] != polyphase["im"]
    )


def test_fir_input_range_is_checked():
    node = direct_symmetric_fir(12)
    with pytest.raises(ValueError, match="outside signed Q1.15"):
        emulate_fir_decimator(node, np.array([40000] * 40), np.zeros(40, dtype=np.int64))


def _literal(width, value):
    value = int(value)
    return f"-{width}'sd{-value}" if value < 0 else f"{width}'sd{value}"


@pytest.mark.parametrize(
    "node",
    [
        direct_symmetric_fir(12),
        direct_symmetric_fir(12, product_drop=4, accumulator_bits=24, rounding="trunc"),
        polyphase_decimator(12),
        polyphase_decimator(12, product_drop=2, accumulator_bits=24, rounding="rne"),
    ],
)
def test_fir_streaming_rtl_matches_bittrue_model(tmp_path, node):
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not installed")
    rng = np.random.default_rng(47)
    x_re = rng.integers(-(1 << 14), 1 << 14, size=97, dtype=np.int64)
    x_im = rng.integers(-(1 << 14), 1 << 14, size=97, dtype=np.int64)
    expected = emulate_fir_decimator(node, x_re, x_im)
    output_by_index = {
        int(sample_index): (int(re), int(im))
        for sample_index, re, im in zip(
            expected["output_indices"], expected["re"], expected["im"]
        )
    }
    stimulus = []
    for sample_index, (re, im) in enumerate(zip(x_re, x_im)):
        stimulus.extend(
            [
                "@(negedge clk);",
                f"x_re = {_literal(16, re)}; x_im = {_literal(16, im)}; in_valid = 1'b1;",
                "@(posedge clk); #1;",
            ]
        )
        if sample_index in output_by_index:
            out_re, out_im = output_by_index[sample_index]
            stimulus.extend(
                [
                    f"if (out_valid !== 1'b1) $fatal(1, \"missing valid {sample_index}\");",
                    f"if ($signed(y_re) !== {_literal(32, out_re)}) "
                    f'$fatal(1, "re mismatch {sample_index}");',
                    f"if ($signed(y_im) !== {_literal(32, out_im)}) "
                    f'$fatal(1, "im mismatch {sample_index}");',
                ]
            )
        else:
            stimulus.append(
                f"if (out_valid !== 1'b0) $fatal(1, \"unexpected valid {sample_index}\");"
            )
    tb = """module tb;
reg clk = 1'b0;
always #5 clk = ~clk;
reg rst_n = 1'b0;
reg in_valid = 1'b0;
wire in_ready;
reg signed [15:0] x_re = 16'sd0;
reg signed [15:0] x_im = 16'sd0;
wire signed [15:0] y_re, y_im;
wire out_valid;
reg out_ready = 1'b1;
fir_decimator dut(
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready),
    .x_re(x_re), .x_im(x_im), .y_re(y_re), .y_im(y_im),
    .out_valid(out_valid), .out_ready(out_ready)
);
initial begin
    repeat (2) @(posedge clk);
    @(negedge clk); rst_n = 1'b1;
""" + "\n".join(stimulus) + "\n$display(\"PASS\"); $finish;\nend\nendmodule\n"
    rtl_path = tmp_path / "fir.v"
    tb_path = tmp_path / "tb.v"
    sim_path = tmp_path / "sim.out"
    rtl_path.write_text(lower_fir_decimator_rtl(node), encoding="utf-8")
    tb_path.write_text(tb, encoding="utf-8")
    compile_result = subprocess.run(
        ["iverilog", "-g2012", "-o", str(sim_path), str(rtl_path), str(tb_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(
        ["vvp", str(sim_path)], capture_output=True, text=True, check=False
    )
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert "PASS" in run_result.stdout


@pytest.mark.parametrize(
    "node", [direct_symmetric_fir(12), polyphase_decimator(12)]
)
def test_fir_streaming_rtl_passes_yosys_structural_check(tmp_path, node):
    if shutil.which("yosys") is None:
        pytest.skip("yosys not installed")
    rtl_path = tmp_path / "fir.v"
    rtl_path.write_text(lower_fir_decimator_rtl(node), encoding="utf-8")
    result = subprocess.run(
        [
            "yosys",
            "-q",
            "-p",
            f"read_verilog -sv {rtl_path}; hierarchy -check -top fir_decimator; "
            "proc; opt; check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
