"""通用 RTL 对拍：按 Task 接口生成测试平台（实/复输入、每 in_period 个时钟一个样点、实/复输出），
用 iverilog 仿真生成的 Verilog，与逐位整数语义比较。"""
import subprocess, tempfile, time
from pathlib import Path
import numpy as np
from .task import get, run_program


def _tb(task, n):
    b, bo = task.interface["in_bits"], task.interface["out_bits"]
    cx_in, cx_out = task.iface("in_kind") == "complex", task.iface("out_kind") == "complex"
    P = task.iface("in_period")
    qd = f"reg signed [{b - 1}:0] in_q = 0; reg [{b - 1}:0] memq [0:{n - 1}];" if cx_in else ""
    qc = ".in_q(in_q)," if cx_in else ""
    qr = "in_q = memq[k];" if cx_in else ""
    qm = '$readmemh("inq.hex", memq);' if cx_in else ""
    od = f"wire signed [{bo - 1}:0] out_q;" if cx_out else ""
    oc = ", .out_q(out_q)" if cx_out else ""
    ow = '$fwrite(fo, "%0d %0d\\n", out_i, out_q);' if cx_out else '$fwrite(fo, "%0d\\n", out_i);'
    return f"""`timescale 1ns/1ps
module tb;
reg clk = 0; reg rst = 1; reg in_valid = 0; reg signed [{b - 1}:0] in_i = 0; {qd}
wire out_valid; wire signed [{bo - 1}:0] out_i; {od}
reg [{b - 1}:0] mem [0:{n - 1}];
integer fo, k, j;
top dut (.clk(clk), .rst(rst), .in_valid(in_valid), .in_i(in_i), {qc} .out_valid(out_valid), .out_i(out_i){oc});
always #5 clk = ~clk;
always @(posedge clk) if (!rst && out_valid) {ow}
initial begin
  $readmemh("in.hex", mem); {qm} fo = $fopen("out.txt", "w");
  @(posedge clk); @(posedge clk); #1 rst = 0;
  for (k = 0; k < {n}; k = k + 1) begin
    in_i = mem[k]; {qr} in_valid = 1; @(posedge clk); #1 in_valid = 0;
    for (j = 1; j < {P}; j = j + 1) begin @(posedge clk); #1; end
  end
  repeat (512) @(posedge clk);
  $fclose(fo); $finish;
end
endmodule
"""


def crosscheck(code, task_name, scenario=0, n_in=2000):
    task = get(task_name)
    r = run_program(code, task_name, [scenario], want_verilog=True)
    if not r.get("ok"):
        return {"passed": False, "error": r["error"]}
    sc = task.scene(scenario)
    bo = task.interface["out_bits"]
    exp_i = np.round(np.array(r["outputs"][str(scenario)][0]) * (1 << (bo - 1))).astype(np.int64)
    exp_q = np.round(np.array(r["outputs"][str(scenario)][1]) * (1 << (bo - 1))).astype(np.int64)
    mask = (1 << task.interface["in_bits"]) - 1
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="dspgen_x_") as d:
        d = Path(d)
        (d / "dut.v").write_text(r["verilog"])
        (d / "tb.v").write_text(_tb(task, n_in))
        (d / "in.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc["x_codes"][:n_in]) + "\n")
        if "xq_codes" in sc:
            (d / "inq.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc["xq_codes"][:n_in]) + "\n")
        pr = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"], cwd=d, capture_output=True, text=True)
        if pr.returncode:
            return {"passed": False, "error": {"code": "verilog_compile", "message": pr.stderr[-800:]}}
        subprocess.run(["vvp", "-n", "sim"], cwd=d, capture_output=True, text=True, timeout=3600)
        rows = [list(map(int, l.split())) for l in (d / "out.txt").read_text().splitlines() if l.strip()]
    got = np.array(rows, dtype=np.int64).reshape(len(rows), -1)
    exp_n = int(round(n_in / task.rate()))
    m = min(len(got), exp_n, len(exp_i))
    bad = int(np.count_nonzero(got[:m, 0] != exp_i[:m]))
    if got.shape[1] > 1:
        bad += int(np.count_nonzero(got[:m, 1] != exp_q[:m]))
    return {"passed": bad == 0 and len(got) >= exp_n - 1, "rtl_outputs": len(got), "expected_outputs": exp_n,
            "compared": m, "mismatches": bad, "sim_seconds": time.time() - t0}
