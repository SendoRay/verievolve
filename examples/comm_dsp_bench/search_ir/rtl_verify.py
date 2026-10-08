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


def verify_candidate_rtl(
    candidate: Mapping[str, Any], workdir: Path, *, seed: int = 53, samples: int = 97,
) -> dict[str, Any]:
    """Compile and simulate one deterministic stream against its bit-true model."""
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
    output = {
        int(index): (int(re), int(im))
        for index, re, im in zip(
            expected["output_indices"], expected["y_re"], expected["y_im"]
        )
    }
    stimulus: list[str] = []
    for index, (re, im) in enumerate(zip(i12, q12)):
        stimulus.extend([
            "@(negedge clk);",
            f"i_in = {_literal(12, re)}; q_in = {_literal(12, im)}; in_valid = 1'b1;",
            "@(posedge clk); #1;",
        ])
        if index in output:
            out_re, out_im = output[index]
            stimulus.extend([
                f"if (out_valid !== 1'b1) $fatal(1, \"missing valid {index}\");",
                f"if ($signed(y_re) !== {_literal(32, out_re)}) "
                f"$fatal(1, \"re mismatch {index}\");",
                f"if ($signed(y_im) !== {_literal(32, out_im)}) "
                f"$fatal(1, \"im mismatch {index}\");",
            ])
        else:
            stimulus.append(
                f"if (out_valid !== 1'b0) $fatal(1, \"unexpected valid {index}\");"
            )
    testbench = f"""module tb;
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
{chr(10).join(stimulus)}
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
        "checked_output_samples": len(output),
        "fcw": fcw,
        "rtl_sha256": hashlib.sha256(rtl.encode()).hexdigest(),
        "iverilog": subprocess.run(
            [iverilog, "-V"], capture_output=True, text=True, check=False
        ).stdout.splitlines()[0],
    }
