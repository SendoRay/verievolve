"""评价一份 build 程序：编译 + 逐位输出 + 裁判打分 + 确定性诊断；最终设计用 iverilog 对拍。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from . import judge
from .rx_spec import SPECS

BENCH = Path(__file__).resolve().parent.parent
BUILD_TIMEOUT = 180
SIM_TIMEOUT = 3600


HARNESS = {"auto_narrow": False, "probes": False}


def run_program(code: str, spec_name: str, scenarios, extra_bits=0, extra_scopes=None,
                want_verilog=False) -> dict:
    req = {"code": code, "spec": spec_name, "scenarios": list(scenarios), "extra_bits": extra_bits,
           "extra_scopes": extra_scopes, "want_verilog": want_verilog} | HARNESS
    try:
        pr = subprocess.run([sys.executable, "-W", "ignore", "-m", "dspgraph.sdf_worker"],
                            input=json.dumps(req), capture_output=True, text=True, cwd=BENCH,
                            timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "build_timeout",
                                       "message": f"build() did not finish in {BUILD_TIMEOUT} s"}}
    try:
        return json.loads(pr.stdout)
    except Exception:
        return {"ok": False, "error": {"code": "worker_crash", "message": pr.stderr[-600:]}}


def evaluate_program(code: str, spec_name: str, scenarios=judge.SEARCH_SCENARIOS,
                     diagnose: bool = False) -> dict:
    spec = SPECS[spec_name]
    t0 = time.time()
    r = run_program(code, spec_name, scenarios)
    if not r.get("ok"):
        return {"valid": False, "error": r["error"], "seconds": time.time() - t0}
    q = judge.combine(spec, r["scores"])
    q["saturation"] = r["saturation"]
    out = {"valid": True, "quality": q, "area": r["area"]["total"],
           "area_per_scope": r["area"]["per_scope"], "stats": r["stats"],
           "notes": r.get("notes", []), "probes": r.get("probes", {})}
    if diagnose and not q["passed"]:
        out["diagnosis"] = diagnose_failure(code, spec_name, q, r["area"]["per_scope"])
    out["seconds"] = time.time() - t0
    return out


def diagnose_failure(code, spec_name, q, scopes, extra=4, max_scopes=8) -> dict:
    """把全部量化点（q、lut、scale、mac 系数）加宽 extra 位重跑：
    仍不达标且改善 < 3 dB → 结构限制；否则逐个命名段单独加宽，找出主导段。"""
    worst = min(q["scenarios"], key=lambda s: s["snr_db"] - s["snr_min_db"])
    idx = worst["scenario"]
    out = {"worst_scenario": idx, "snr_db": worst["snr_db"], "snr_min_db": worst["snr_min_db"],
           "ripple_db": worst["ripple_db"], "saturation": q.get("saturation", {})}
    if not worst.get("valid_output", True):
        out["kind"] = "too_few_outputs"
        return out
    w = run_program(code, spec_name, [idx], extra, None)
    if not w.get("ok"):
        out["kind"] = "undetermined"
        return out
    ws = w["scores"][0]
    out[f"snr_if_all_quantizers_plus_{extra}_bits_db"] = ws["snr_db"]
    out["ripple_if_widened_db"] = ws["ripple_db"]
    if ws["snr_db"] < worst["snr_min_db"] and ws["snr_db"] - worst["snr_db"] < 3.0:
        out["kind"] = "structure_limited"
    else:
        out["kind"] = "precision_limited" if ws["snr_db"] >= worst["snr_min_db"] else "both"
        per = {}
        for s in [s for s in scopes if s != "top"][:max_scopes]:
            r = run_program(code, spec_name, [idx], extra, [s])
            if r.get("ok"):
                per[s] = r["scores"][0]["snr_db"] - worst["snr_db"]
        if per:
            out["snr_gain_db_if_only_this_scope_widened"] = per
            out["dominant_scope"] = max(per, key=per.get)
    return out


def _tb(w_in: int, w_out: int, n: int) -> str:
    return f"""`timescale 1ns/1ps
module tb;
reg clk = 0; reg rst = 1; reg in_valid = 0; reg signed [{w_in - 1}:0] in_i = 0;
wire out_valid; wire signed [{w_out - 1}:0] out_i, out_q;
reg [{w_in - 1}:0] mem [0:{n - 1}];
integer fo, k;
top dut (.clk(clk), .rst(rst), .in_valid(in_valid), .in_i(in_i),
         .out_valid(out_valid), .out_i(out_i), .out_q(out_q));
always #5 clk = ~clk;
always @(posedge clk) if (!rst && out_valid) $fwrite(fo, "%0d %0d\\n", out_i, out_q);
initial begin
  $readmemh("in.hex", mem); fo = $fopen("out.txt", "w");
  @(posedge clk); @(posedge clk); #1 rst = 0;
  for (k = 0; k < {n}; k = k + 1) begin in_i = mem[k]; in_valid = 1; @(posedge clk); #1; end
  in_valid = 0; repeat (256) @(posedge clk);
  $fclose(fo); $finish;
end
endmodule
"""


def rtl_crosscheck(code: str, spec_name: str, scenario: int = 0, n_in: int | None = None) -> dict:
    """生成 Verilog，用 iverilog 仿真，与逐位整数语义比较。"""
    spec = SPECS[spec_name]
    r = run_program(code, spec_name, [scenario], want_verilog=True)
    if not r.get("ok"):
        return {"passed": False, "error": r["error"]}
    sc = judge.scene(spec, scenario)
    n = n_in or sc.n_in
    b = spec.output_bits
    exp_re = np.round(np.array(r["outputs"][str(scenario)][0]) * (1 << (b - 1))).astype(np.int64)
    exp_im = np.round(np.array(r["outputs"][str(scenario)][1]) * (1 << (b - 1))).astype(np.int64)
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="dspg_x_") as d:
        d = Path(d)
        (d / "dut.v").write_text(r["verilog"])
        (d / "tb.v").write_text(_tb(spec.input_bits, b, n))
        mask = (1 << spec.input_bits) - 1
        (d / "in.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc.x_codes[:n]) + "\n")
        pr = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"], cwd=d,
                            capture_output=True, text=True)
        if pr.returncode:
            return {"passed": False, "error": {"code": "verilog_compile", "message": pr.stderr[-800:]}}
        subprocess.run(["vvp", "-n", "sim"], cwd=d, capture_output=True, text=True, timeout=SIM_TIMEOUT)
        rows = np.array([l.split() for l in (d / "out.txt").read_text().splitlines() if l],
                        dtype=np.int64).reshape(-1, 2)
    m = min(len(rows), len(exp_re))
    exp_n = len(range(0, n, spec.r_total))
    mism = int(np.count_nonzero((rows[:m, 0] != exp_re[:m]) | (rows[:m, 1] != exp_im[:m])))
    return {"passed": mism == 0 and len(rows) == exp_n, "rtl_outputs": int(len(rows)),
            "expected_outputs": exp_n, "compared": m, "mismatches": mism,
            "sim_seconds": time.time() - t0}
