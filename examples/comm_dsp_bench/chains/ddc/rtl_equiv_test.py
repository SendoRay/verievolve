#!/usr/bin/env python3
"""RTL vs Python 整数模型位精确对拍（rtl_gen 生成设计的验收）。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import spec, scenarios, ref_chain, fixed_chain, candidates, rtl_gen

TB = """`timescale 1ns/1ps
module tb;
    reg clk = 0, rst_n = 0;
    reg signed [11:0] i_in = 0, q_in = 0;
    wire signed [15:0] y_re, y_im;
    wire out_valid;
    integer n_in = {n_in};
    integer idx = 0;
    reg [11:0] mem_i [0:{n_in_m1}];
    reg [11:0] mem_q [0:{n_in_m1}];
    integer fh;
    top dut(.clk(clk), .rst_n(rst_n), .in_valid(1'b1),
            .i_in(i_in), .q_in(q_in), .y_re(y_re), .y_im(y_im), .out_valid(out_valid));
    always #5 clk = ~clk;
    initial begin
        $readmemh("{stim}", mem_i);
        $readmemh("{stim_q}", mem_q);
        i_in <= mem_i[0]; q_in <= mem_q[0];   // t=0 即驱动首样本
        fh = $fopen("{dump}", "w");
        repeat (4) @(posedge clk);
        rst_n = 1;
        idx = 1;
        repeat ({n_in} - 1) begin
            @(posedge clk);
            #1;
            if (idx < n_in) begin
                i_in <= mem_i[idx]; q_in <= mem_q[idx];
                idx = idx + 1;
            end
        end
        repeat (16) @(posedge clk);
        $fclose(fh);
        $finish;
    end
    always @(posedge clk) begin
        if (rst_n && out_valid) $fwrite(fh, "%0d %0d\\n", $signed(y_re), $signed(y_im));
    end
endmodule
"""


def run_case(name: str, nco: dict, fir: dict, cmul: dict, hq: np.ndarray,
             sd, n_samples: int = 2048) -> tuple:
    """跑一个设计的 iverilog 仿真并与 Python 模型对拍。返回 (mismatch, n_out)。"""
    from chains.ddc.spec import R, N_TAPS
    i12, q12 = fixed_chain.adc_quantize(sd.x_adc)
    i12 = i12[:n_samples]
    q12 = q12[:n_samples]
    cand = fixed_chain.run_candidate(nco, fir, cmul, sd, hq)
    n_out = (n_samples - (spec.N_TAPS - 1)) // spec.R
    y_ref_py_re = cand["y_re"][:n_out]
    y_ref_py_im = cand["y_im"][:n_out]

    with tempfile.TemporaryDirectory() as td:
        fcw = int(round(sd.scen.f_off_mhz * 1e6 / spec.FS_IN * (1 << 32)))
        v = rtl_gen.gen_ddc_verilog(nco, fir, cmul, fcw=fcw)
        vp = Path(td) / "top.v"
        vp.write_text(v)
        stim = str(Path(td) / "stim.hex")
        with open(stim, "w") as fh:
            fh.write("@0\n")
            fh.write(" ".join(f"{int(x) & 0xFFF:x}" for x in i12) + "\n")
        with open(stim, "a") as fh:  # mem_q 下一文件？readmemh 双文件调用
            pass
        stim_q = str(Path(td) / "stim_q.hex")
        with open(stim_q, "w") as fh:
            fh.write("@0\n")
            fh.write(" ".join(f"{int(x) & 0xFFF:x}" for x in q12) + "\n")
        dump = str(Path(td) / "out.txt")
        tb = TB.format(n_in=n_samples, n_in_m1=n_samples - 1,
                       stim=stim, stim_q=stim_q, dump=dump)
        tbp = Path(td) / "tb.v"
        tbp.write_text(tb)
        p = subprocess.run(["iverilog", "-g2012", "-o", str(Path(td) / "sim"),
                            str(vp), str(tbp)], capture_output=True, text=True)
        if p.returncode != 0:
            print(f"[{name}] iverilog compile FAIL:\n{p.stderr[:500]}")
            return None, None
        p = subprocess.run([str(Path(td) / "sim")], capture_output=True, text=True,
                           cwd=td, timeout=120)
        if not Path(dump).exists():
            print(f"[{name}] no output: {p.stderr[:300]}")
            return None, None
        rows = [ln.split() for ln in Path(dump).read_text().splitlines() if ln.strip()]
        rtl_re = np.array([int(r[0]) for r in rows], dtype=np.int64)
        rtl_im = np.array([int(r[1]) for r in rows], dtype=np.int64)
        n = min(len(rtl_re), len(y_ref_py_re))
        mis_re = int(np.sum(rtl_re[:n] != y_ref_py_re[:n]))
        mis_im = int(np.sum(rtl_im[:n] != y_ref_py_im[:n]))
        return mis_re + mis_im, n


def main() -> int:
    h = ref_chain.prototype_taps()
    pool = candidates.build_all(h)
    scen = spec.build_scenarios()[0]
    sd = scenarios.generate_scenario(scen)
    cases = [
        (pool["nco"][1], pool["fir"][0], pool["cmul"][0], "lut256near_b16 f1 c1"),
        (pool["nco"][0], pool["fir"][0], pool["cmul"][0], "lut256near_b12 f1 c1"),
        (pool["nco"][3], pool["fir"][1], pool["cmul"][0], "lut1024lin_b16 f2 c1"),
        (pool["nco"][5], pool["fir"][6], pool["cmul"][1], "cordic16_b16 f7pd2 c2"),
        (pool["nco"][0], pool["fir"][7], pool["cmul"][1], "lut256near_b12 f8 c2"),
        (pool["nco"][4], pool["fir"][4], pool["cmul"][0], "cordic12_b12 f5acc24 c1"),
    ]
    ok = True
    for nc, fc, cm, name in cases:
        mis, n = run_case(name, nc, fc, cm, fc["hq"], sd)
        status = "PASS" if mis == 0 else "FAIL"
        if mis != 0:
            ok = False
        print(f"[{status}] {name}: mismatch={mis}/{2*n} 样点")
    print("RTL_EQUIV:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
