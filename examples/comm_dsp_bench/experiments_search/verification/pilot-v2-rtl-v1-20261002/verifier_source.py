#!/usr/bin/env python3
"""验证完整pilot的所有有效候选；不生成新候选、不评价held-out。"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np

BENCH = Path(__file__).resolve().parents[1] / "examples/comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.ddc import spec
from search_ir.canonicalize import candidate_hash
from search_ir.lower_bittrue import emulate_ddc_candidate, emulate_nco_accumulators
from search_ir.lower_rtl import lower_ddc_rtl, lower_nco_map_rtl


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_new(path, data):
    with path.open("x") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)


def hex_file(path, values, width):
    mask = (1 << width) - 1
    path.write_text("\n".join(f"{int(v) & mask:0{(width + 3) // 4}x}" for v in values) + "\n")


def simulate(directory, rtl, tb, tools):
    (directory / "design.v").write_text(rtl)
    (directory / "tb.v").write_text(tb)
    for label, command in (
        ("compile", [tools["iverilog"]["path"], "-g2012", "-o", "sim", "design.v", "tb.v"]),
        ("simulate", [tools["vvp"]["path"], "sim"]),
    ):
        p = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=120)
        (directory / f"{label}.stdout").write_text(p.stdout)
        (directory / f"{label}.stderr").write_text(p.stderr)
        if p.returncode:
            raise RuntimeError(f"{label} failed: {(p.stdout + p.stderr)[-1000:]}")
    return {"rtl_sha256": sha(rtl.encode()), "tb_sha256": sha(tb.encode())}


def check_nco(directory, node, tools, acc):
    directory.mkdir()
    hex_file(directory / "phase.hex", acc, 32)
    s, c = emulate_nco_accumulators(node, acc)
    expected = np.column_stack((s, c))
    # 当前叶子B<=16、split<=14，低16位不影响叶子取位或coarse进位边界。
    clean = emulate_nco_accumulators(node, (acc >> 16) << 16)
    np.testing.assert_array_equal(s, clean[0])
    np.testing.assert_array_equal(c, clean[1])
    n = len(acc)
    tb = f"""`timescale 1ns/1ps
module tb;
reg [31:0] acc;
wire signed [15:0] s, c;
reg [31:0] values [0:{n-1}];
integer i, fh;
nco_map dut(.phase_acc(acc), .sin_o(s), .cos_o(c));
initial begin
  $readmemh("phase.hex", values);
  fh = $fopen("outputs.txt", "w");
  for (i=0; i<{n}; i=i+1) begin
    acc = values[i]; #1;
    $fwrite(fh, "%0d %0d\\n", s, c);
  end
  $fclose(fh); $finish;
end
endmodule
"""
    artifacts = simulate(directory, lower_nco_map_rtl(node), tb, tools)
    actual = np.loadtxt(directory / "outputs.txt", dtype=np.int64).reshape(-1, 2)
    np.testing.assert_array_equal(actual, expected)
    return {"status": "pass", "states": n, "node_hash": candidate_hash(node),
            "output_sha256": sha(expected.astype("<i4").tobytes()), **artifacts}


def check_ddc(directory, candidate, tools, i12, q12, fcw):
    directory.mkdir()
    result = emulate_ddc_candidate(candidate, i12, q12, fcw)
    np.testing.assert_array_equal(result["output_indices"], np.arange(32, len(i12), 2))
    for name, values, width in (("i.hex", i12, 12), ("q.hex", q12, 12),
                                ("re.hex", result["y_re"], 16), ("im.hex", result["y_im"], 16)):
        hex_file(directory / name, values, width)
    n, m = len(i12), len(result["y_re"])
    tb = f"""`timescale 1ns/1ps
module tb;
reg clk=0; always #5 clk=~clk;
reg rst_n=0, in_valid=0, out_ready=1;
wire in_ready, out_valid;
reg signed [11:0] i_in=0, q_in=0;
wire signed [15:0] y_re, y_im;
reg signed [11:0] iv[0:{n-1}], qv[0:{n-1}];
reg signed [15:0] re[0:{m-1}], im[0:{m-1}], held_re, held_im;
integer i, k;
top dut(.clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_ready(in_ready),
 .fcw(32'd{fcw}),.i_in(i_in),.q_in(q_in),.y_re(y_re),.y_im(y_im),
 .out_valid(out_valid),.out_ready(out_ready));
initial begin
 $readmemh("i.hex",iv); $readmemh("q.hex",qv);
 $readmemh("re.hex",re); $readmemh("im.hex",im);
 repeat(2) @(posedge clk);
 @(negedge clk); rst_n=1; k=0;
 for(i=0;i<{n};i=i+1) begin
   if(i==20 || i==70 || i==100) begin
     @(negedge clk); in_valid=0; out_ready=1;
     repeat(2) begin @(posedge clk); #1;
       if(out_valid !== 0) $fatal(1,"unexpected valid during input bubble");
     end
   end
   @(negedge clk); in_valid=1; i_in=iv[i]; q_in=qv[i]; out_ready=1;
   if(i==33 || i==65 || i==97) begin
     held_re=y_re; held_im=y_im; out_ready=0;
     repeat(3) begin @(posedge clk); #1;
       if(in_ready !== 0 || out_valid !== 1 || y_re !== held_re || y_im !== held_im)
         $fatal(1,"backpressure violated at %0d",i);
     end
     @(negedge clk); out_ready=1;
   end
   @(posedge clk); #1;
   if(i>=32 && (i%2)==0) begin
     if(out_valid !== 1 || $signed(y_re) !== $signed(re[k]) || $signed(y_im) !== $signed(im[k]))
       $fatal(1,"output mismatch input=%0d output=%0d",i,k);
     k=k+1;
   end else if(out_valid !== 0) $fatal(1,"unexpected valid at %0d",i);
 end
 if(k != {m}) $fatal(1,"missing output");
 $display("PASS"); $finish;
end
endmodule
"""
    artifacts = simulate(directory, lower_ddc_rtl(candidate), tb, tools)
    assert "PASS" in (directory / "simulate.stdout").read_text()
    return {"status": "pass", "candidate_hash": candidate_hash(candidate),
            "accepted_inputs": n, "outputs": m, "input_bubbles": [20, 70, 100],
            "output_stalls": [33, 65, 97], **artifacts}


def verify(run, output):
    result = json.loads((run / "results.json").read_text())
    assert result["status"] == "pilot_completed"
    configs = {}
    area_rtl = {}
    for state in result["arms"].values():
        for row in state["history"]:
            configs[row["candidate_hash"]] = row["candidate"]
    for trial in result["trials"]:
        if trial["status"] == "ok":
            area = json.loads(Path(trial["area"]["source_result"]).read_text())
            area_rtl[trial["candidate_hash"]] = area["binding"]["rtl_sha256"]
    if not configs or set(configs) != set(area_rtl):
        raise ValueError("候选集合与成功面积集合不一致或为空")
    tools = {}
    for name in ("iverilog", "vvp"):
        path = shutil.which(name)
        if path is None:
            raise RuntimeError(f"missing {name}")
        path = Path(path).resolve()
        p = subprocess.run([str(path), "-V"], capture_output=True, text=True, timeout=30)
        tools[name] = {"path": str(path), "sha256": sha(path.read_bytes()),
                       "version": (p.stdout + p.stderr).splitlines()[0]}
    rng = np.random.Generator(np.random.PCG64(20261002))
    acc = (np.arange(65536, dtype=np.int64) << 16) | rng.integers(0, 65536, size=65536)
    i12 = rng.integers(-2048, 2048, size=128, dtype=np.int64)
    q12 = rng.integers(-2048, 2048, size=128, dtype=np.int64)
    i12[:8] = [0, 2047, -2048, 2047, -2048, 1, -1, 0]
    q12[:8] = [0, 2047, -2048, -2048, 2047, -1, 1, 2047]
    fcw = spec.fcw_of(0.39)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"source_result_sha256": sha((run / "results.json").read_bytes()),
                "script_sha256": sha(Path(__file__).read_bytes()), "tools": tools,
                "candidates": configs, "area_rtl_sha256": area_rtl,
                "phase_states": 65536, "phase_input_sha256": sha(acc.astype("<u4").tobytes()),
                "i12": i12.tolist(), "q12": q12.tolist(), "fcw": fcw,
                "purpose": "post-pilot model/RTL verification, not new fitness or held-out"}
    write_new(output / "manifest.json", manifest)
    nco_reports, ddc_reports = {}, []
    error = None
    started = time.monotonic()
    try:
        for identity, config in sorted(configs.items()):
            assert identity == candidate_hash(config)
            assert sha(lower_ddc_rtl(config).encode()) == area_rtl[identity]
            node_id = candidate_hash(config["nco"])
            if node_id not in nco_reports:
                nco_reports[node_id] = check_nco(output / f"nco-{node_id[:16]}", config["nco"], tools, acc)
            row = check_ddc(output / f"ddc-{identity[:16]}", config, tools, i12, q12, fcw)
            row["nco_proof"] = node_id
            ddc_reports.append(row)
            print(f"[PASS {len(ddc_reports)}/{len(configs)}] {identity[:12]}", flush=True)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc), "candidate_hash": identity}
    report = {"status": "pass" if error is None and len(ddc_reports) == len(configs) else "failed",
              "candidate_count": len(configs), "nco_proofs": nco_reports, "ddc_proofs": ddc_reports,
              "error": error, "wall_seconds": time.monotonic() - started,
              "manifest_sha256": sha((output / "manifest.json").read_bytes())}
    write_new(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = verify(args.run, args.output)
    print(json.dumps({"status": report["status"], "error": report["error"]}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "pass" else 1)
