"""Development-only bit-true versus generated-RTL verification."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .canonicalize import candidate_hash
from .lower_bittrue import emulate_ddc_candidate
from .lower_rtl import lower_ddc_rtl
from .validate import validate_candidate


class RTLVerificationError(RuntimeError):
    pass


def _literal(width: int, value: int) -> str:
    value = int(value)
    return f"-{width}'sd{-value}" if value < 0 else f"{width}'sd{value}"


def _array_assignments(name: str, width: int, values: list[int]) -> str:
    return "\n".join(
        f"    {name}[{index}] = {_literal(width, value)};"
        for index, value in enumerate(values)
    )


def verify_candidate_rtl(
    candidate: Mapping[str, Any], workdir: Path, *, seed: int = 53, samples: int = 97,
) -> dict[str, Any]:
    """Compare accepted input/output transactions without assuming a fixed latency."""
    validate_candidate(candidate)
    if samples <= 33:
        raise ValueError("samples must exceed the 33-tap FIR warmup")
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iverilog or not vvp:
        raise RTLVerificationError("iverilog and vvp are required")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=False)

    rng = np.random.default_rng(seed)
    i12 = rng.integers(-(1 << 10), 1 << 10, size=samples, dtype=np.int64)
    q12 = rng.integers(-(1 << 10), 1 << 10, size=samples, dtype=np.int64)
    fcw = int(round(0.39e6 / 2e6 * (1 << 32)))
    expected = emulate_ddc_candidate(candidate, i12, q12, fcw)
    expected_re = [int(value) for value in expected["y_re"]]
    expected_im = [int(value) for value in expected["y_im"]]
    output_count = len(expected_re)
    max_cycles = (samples + output_count) * 20 + 100
    testbench = f"""module tb;
localparam integer INPUT_COUNT = {samples};
localparam integer OUTPUT_COUNT = {output_count};
localparam integer MAX_CYCLES = {max_cycles};
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
reg signed [11:0] stimulus_i [0:INPUT_COUNT-1];
reg signed [11:0] stimulus_q [0:INPUT_COUNT-1];
reg signed [15:0] expected_re [0:OUTPUT_COUNT-1];
reg signed [15:0] expected_im [0:OUTPUT_COUNT-1];
integer accepted_count = 0;
integer received_count = 0;
integer cycle_count = 0;
reg input_was_accepted = 1'b0;
reg stall_active = 1'b0;
reg signed [15:0] held_re;
reg signed [15:0] held_im;
top dut(
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready), .fcw(fcw),
    .i_in(i_in), .q_in(q_in), .y_re(y_re), .y_im(y_im),
    .out_valid(out_valid), .out_ready(out_ready)
);
initial begin
{_array_assignments("stimulus_i", 12, i12.tolist())}
{_array_assignments("stimulus_q", 12, q12.tolist())}
{_array_assignments("expected_re", 16, expected_re)}
{_array_assignments("expected_im", 16, expected_im)}
    repeat (2) @(posedge clk);
    @(negedge clk); rst_n = 1'b1;
    while ((accepted_count < INPUT_COUNT || received_count < OUTPUT_COUNT) &&
           cycle_count < MAX_CYCLES) begin
        @(negedge clk);
        if (in_valid && !input_was_accepted) begin
            in_valid = 1'b1;
        end else if ((accepted_count < INPUT_COUNT) &&
                     ((cycle_count % 5) != 1)) begin
            in_valid = 1'b1;
            i_in = stimulus_i[accepted_count];
            q_in = stimulus_q[accepted_count];
        end else begin
            in_valid = 1'b0;
        end
        out_ready = ((cycle_count % 7) != 3) && ((cycle_count % 11) != 5);
        @(posedge clk);
        if (stall_active) begin
            if (out_valid !== 1'b1) $fatal(1, "lost valid while stalled");
            if ($signed(y_re) !== held_re) $fatal(1, "real output changed while stalled");
            if ($signed(y_im) !== held_im) $fatal(1, "imag output changed while stalled");
        end
        if (out_valid && out_ready) begin
            if (received_count >= OUTPUT_COUNT) $fatal(1, "unexpected extra output");
            if ($signed(y_re) !== expected_re[received_count])
                $fatal(1, "real output mismatch at transaction %0d", received_count);
            if ($signed(y_im) !== expected_im[received_count])
                $fatal(1, "imag output mismatch at transaction %0d", received_count);
            received_count = received_count + 1;
        end
        input_was_accepted = in_valid && in_ready;
        if (input_was_accepted)
            accepted_count = accepted_count + 1;
        if (out_valid && !out_ready) begin
            stall_active = 1'b1;
            held_re = y_re;
            held_im = y_im;
        end else begin
            stall_active = 1'b0;
        end
        cycle_count = cycle_count + 1;
    end
    @(negedge clk); in_valid = 1'b0; out_ready = 1'b1;
    if (accepted_count != INPUT_COUNT)
        $fatal(1, "accepted %0d of %0d inputs", accepted_count, INPUT_COUNT);
    if (received_count != OUTPUT_COUNT)
        $fatal(1, "received %0d of %0d outputs", received_count, OUTPUT_COUNT);
    repeat (8) begin
        @(posedge clk);
        if (out_valid) $fatal(1, "unexpected trailing output");
    end
    $display("PASS"); $finish;
end
endmodule
"""
    rtl = lower_ddc_rtl(candidate)
    rtl_path = workdir / "design.v"
    tb_path = workdir / "tb.v"
    executable = workdir / "sim.out"
    rtl_path.write_text(rtl, encoding="utf-8")
    tb_path.write_text(testbench, encoding="utf-8")
    compile_result = subprocess.run(
        [iverilog, "-g2012", "-o", str(executable), str(rtl_path), str(tb_path)],
        capture_output=True, text=True, check=False,
    )
    if compile_result.returncode != 0:
        raise RTLVerificationError(compile_result.stderr)
    run_result = subprocess.run(
        [vvp, str(executable)], capture_output=True, text=True, check=False,
    )
    if run_result.returncode != 0 or "PASS" not in run_result.stdout:
        raise RTLVerificationError(run_result.stdout + run_result.stderr)
    return {
        "status": "ok",
        "candidate_sha256": candidate_hash(candidate),
        "seed": seed,
        "input_samples": samples,
        "accepted_input_samples": samples,
        "checked_output_samples": output_count,
        "transaction_check": "valid-ready scoreboard",
        "input_gaps_exercised": True,
        "output_backpressure_exercised": True,
        "max_simulation_cycles": max_cycles,
        "fcw": fcw,
        "rtl_sha256": hashlib.sha256(rtl.encode()).hexdigest(),
        "iverilog": subprocess.run(
            [iverilog, "-V"], capture_output=True, text=True, check=False
        ).stdout.splitlines()[0],
    }
