import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir import (
    cordic_sincos,
    ddc_candidate,
    direct_symmetric_fir,
    emulate_ddc_candidate,
    lower_ddc_rtl,
    lut_sincos,
    phasor_compose,
    polyphase_decimator,
)


def _literal(width, value):
    value = int(value)
    return f"-{width}'sd{-value}" if value < 0 else f"{width}'sd{value}"


def _candidates():
    return [
        ddc_candidate(
            lut_sincos(256, "linear", 12), direct_symmetric_fir(12)
        ),
        ddc_candidate(
            phasor_compose(
                lut_sincos(128, "nearest", 10),
                cordic_sincos(7, 16),
                split_bits=8,
            ),
            polyphase_decimator(12, product_drop=2, accumulator_bits=24),
        ),
    ]


@pytest.mark.parametrize("candidate", _candidates())
def test_complete_ddc_rtl_matches_bittrue_model(tmp_path, candidate):
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not installed")
    rng = np.random.default_rng(53)
    i12 = rng.integers(-(1 << 10), 1 << 10, size=97, dtype=np.int64)
    q12 = rng.integers(-(1 << 10), 1 << 10, size=97, dtype=np.int64)
    fcw = int(round(0.39e6 / 2e6 * (1 << 32)))
    expected = emulate_ddc_candidate(candidate, i12, q12, fcw)
    output_by_index = {
        int(sample_index): (int(re), int(im))
        for sample_index, re, im in zip(
            expected["output_indices"], expected["y_re"], expected["y_im"]
        )
    }
    stimulus = []
    for sample_index, (re, im) in enumerate(zip(i12, q12)):
        stimulus.extend(
            [
                "@(negedge clk);",
                f"i_in = {_literal(12, re)}; q_in = {_literal(12, im)}; in_valid = 1'b1;",
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
    tb = f"""module tb;
reg clk = 1'b0;
always #5 clk = ~clk;
reg rst_n = 1'b0;
reg in_valid = 1'b0;
wire in_ready;
reg [31:0] fcw = 32'h{fcw:08x};
reg signed [11:0] i_in = 12'sd0;
reg signed [11:0] q_in = 12'sd0;
wire signed [15:0] y_re, y_im;
wire out_valid;
reg out_ready = 1'b1;
top dut(
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready), .fcw(fcw),
    .i_in(i_in), .q_in(q_in), .y_re(y_re), .y_im(y_im),
    .out_valid(out_valid), .out_ready(out_ready)
);
initial begin
    repeat (2) @(posedge clk);
    @(negedge clk); rst_n = 1'b1;
""" + "\n".join(stimulus) + "\n$display(\"PASS\"); $finish;\nend\nendmodule\n"
    rtl_path = tmp_path / "ddc.v"
    tb_path = tmp_path / "tb.v"
    sim_path = tmp_path / "sim.out"
    rtl_path.write_text(lower_ddc_rtl(candidate), encoding="utf-8")
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


@pytest.mark.parametrize("candidate", _candidates())
def test_complete_ddc_rtl_holds_state_under_output_backpressure(tmp_path, candidate):
    """A stalled output must freeze the accepted-input and phase sequence."""
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not installed")
    rng = np.random.default_rng(71)
    i12 = rng.integers(-(1 << 10), 1 << 10, size=48, dtype=np.int64)
    q12 = rng.integers(-(1 << 10), 1 << 10, size=48, dtype=np.int64)
    fcw = int(round(0.51e6 / 2e6 * (1 << 32)))
    expected = emulate_ddc_candidate(candidate, i12, q12, fcw)
    output_by_index = {
        int(sample_index): (int(re), int(im))
        for sample_index, re, im in zip(
            expected["output_indices"], expected["y_re"], expected["y_im"]
        )
    }

    def drive_sample(sample_index):
        re = _literal(12, i12[sample_index])
        im = _literal(12, q12[sample_index])
        lines = [
            "@(negedge clk);",
            f"i_in = {re}; q_in = {im}; in_valid = 1'b1;",
            "@(posedge clk); #1;",
        ]
        if sample_index in output_by_index:
            out_re, out_im = output_by_index[sample_index]
            lines.extend(
                [
                    f"if (out_valid !== 1'b1) $fatal(1, \"missing valid {sample_index}\");",
                    f"if ($signed(y_re) !== {_literal(32, out_re)}) "
                    f'$fatal(1, "re mismatch {sample_index}");',
                    f"if ($signed(y_im) !== {_literal(32, out_im)}) "
                    f'$fatal(1, "im mismatch {sample_index}");',
                ]
            )
        else:
            lines.append(
                f"if (out_valid !== 1'b0) $fatal(1, \"unexpected valid {sample_index}\");"
            )
        return lines

    stimulus = []
    for sample_index in range(33):
        stimulus.extend(drive_sample(sample_index))
    first_re, first_im = output_by_index[32]
    stimulus.extend(
        [
            "@(negedge clk);",
            f"i_in = {_literal(12, i12[33])}; q_in = {_literal(12, q12[33])}; "
            "in_valid = 1'b1; out_ready = 1'b0;",
            "repeat (3) begin",
            "    @(posedge clk); #1;",
            "    if (in_ready !== 1'b0) $fatal(1, \"accepted data while stalled\");",
            "    if (out_valid !== 1'b1) $fatal(1, \"lost held output\");",
            f"    if ($signed(y_re) !== {_literal(32, first_re)}) "
            '$fatal(1, "held real output changed");',
            f"    if ($signed(y_im) !== {_literal(32, first_im)}) "
            '$fatal(1, "held imag output changed");',
            "end",
            "@(negedge clk); out_ready = 1'b1;",
            "@(posedge clk); #1;",
            "if (out_valid !== 1'b0) $fatal(1, \"unexpected output after odd sample\");",
        ]
    )
    for sample_index in range(34, len(i12)):
        stimulus.extend(drive_sample(sample_index))

    tb = f"""module tb;
reg clk = 1'b0;
always #5 clk = ~clk;
reg rst_n = 1'b0;
reg in_valid = 1'b0;
wire in_ready;
reg [31:0] fcw = 32'h{fcw:08x};
reg signed [11:0] i_in = 12'sd0;
reg signed [11:0] q_in = 12'sd0;
wire signed [15:0] y_re, y_im;
wire out_valid;
reg out_ready = 1'b1;
top dut(
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready), .fcw(fcw),
    .i_in(i_in), .q_in(q_in), .y_re(y_re), .y_im(y_im),
    .out_valid(out_valid), .out_ready(out_ready)
);
initial begin
    repeat (2) @(posedge clk);
    @(negedge clk); rst_n = 1'b1;
""" + "\n".join(stimulus) + "\n$display(\"PASS\"); $finish;\nend\nendmodule\n"
    rtl_path = tmp_path / "ddc_backpressure.v"
    tb_path = tmp_path / "tb_backpressure.v"
    sim_path = tmp_path / "sim_backpressure.out"
    rtl_path.write_text(lower_ddc_rtl(candidate), encoding="utf-8")
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


@pytest.mark.parametrize("candidate", _candidates())
def test_complete_ddc_rtl_passes_yosys_structural_check(tmp_path, candidate):
    if shutil.which("yosys") is None:
        pytest.skip("yosys not installed")
    rtl_path = tmp_path / "ddc.v"
    rtl_path.write_text(lower_ddc_rtl(candidate), encoding="utf-8")
    result = subprocess.run(
        [
            "yosys",
            "-q",
            "-p",
            f"read_verilog -sv {rtl_path}; hierarchy -check -top top; proc; opt; check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
