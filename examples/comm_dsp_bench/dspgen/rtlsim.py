"""含时钟域（反馈）的设计的逐位语义：用 iverilog 仿真生成的 RTL，读出输出流与观测点。

反馈环要逐个时钟推进，构造时的 numpy 向量化求值无法给出它的值；因此这类设计的数值直接取自 RTL 仿真，
RTL 与“数值语义”按定义一致。测试平台：每 in_period 个时钟送一个输入样点（in_valid 为单拍脉冲），
在 out_valid 上记录输出；观测点按其所在速率域的有效信号记录。"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np


def _tb(g, n_in, probes, drain):
    b, bo = g.spec.input_bits, g.spec.output_bits
    cx_in, cx_out = g.in_kind == "complex", g.out_kind == "complex"
    P = g.in_period
    qd = f"reg signed [{b - 1}:0] in_q = 0; reg [{b - 1}:0] memq [0:{n_in - 1}];" if cx_in else ""
    qc = ".in_q(in_q)," if cx_in else ""
    qr = "in_q = memq[k];" if cx_in else ""
    qm = '$readmemh("inq.hex", memq);' if cx_in else ""
    od = f"wire signed [{bo - 1}:0] out_q;" if cx_out else ""
    oc = ", .out_q(out_q)" if cx_out else ""
    ow = '$fwrite(fo, "%0d %0d\\n", out_i, out_q);' if cx_out else '$fwrite(fo, "%0d\\n", out_i);'
    pd, po, pc = [], [], []
    for k, (name, sig, valid) in enumerate(probes):
        pd.append(f"integer fp{k};")
        po.append(f'fp{k} = $fopen("probe{k}.txt", "w");')
        pc.append(f"$fclose(fp{k});")
        val = f"$signed(dut.{sig.name})" if sig.signed else f"dut.{sig.name}"
        pd.append(f'always @(posedge clk) if (!rst && dut.{valid}) $fwrite(fp{k}, "%0d\\n", {val});'
                  if not valid.startswith("1'b") else
                  f'always @(posedge clk) if (!rst) $fwrite(fp{k}, "%0d\\n", {val});')
    return f"""`timescale 1ns/1ps
module tb;
reg clk = 0; reg rst = 1; reg in_valid = 0; reg signed [{b - 1}:0] in_i = 0; {qd}
wire out_valid; wire signed [{bo - 1}:0] out_i; {od}
reg [{b - 1}:0] mem [0:{n_in - 1}];
integer fo, k, j;
{chr(10).join(pd)}
top dut (.clk(clk), .rst(rst), .in_valid(in_valid), .in_i(in_i), {qc} .out_valid(out_valid), .out_i(out_i){oc});
always #5 clk = ~clk;
always @(posedge clk) if (!rst && out_valid) {ow}
initial begin
  $readmemh("in.hex", mem); {qm} fo = $fopen("out.txt", "w"); {" ".join(po)}
  @(posedge clk); @(posedge clk); #1 rst = 0;
  for (k = 0; k < {n_in}; k = k + 1) begin
    in_i = mem[k]; {qr} in_valid = 1; @(posedge clk); #1 in_valid = 0;
    for (j = 1; j < {P}; j = j + 1) begin @(posedge clk); #1; end
  end
  repeat ({drain}) @(posedge clk);
  $fclose(fo); {" ".join(pc)} $finish;
end
endmodule
"""


def simulate(g, x_i, x_q=None, drain=None, timeout=600):
    """x_i/x_q：[场景, 样点] 输入码。返回 (ys, probes)：ys[k] 为场景 k 的输出（按接口缩放的浮点数，复数或实数），
    probes[k] 为 {名字: 浮点数组}（与 g.probe 的观测值同一量纲）。"""
    x_i = np.atleast_2d(x_i)
    x_q = None if x_q is None else np.atleast_2d(x_q)
    n_in = x_i.shape[1]
    plist = []
    for name, i, q in getattr(g, "rtl_probes", []):
        plist.append((name, "i", i, g._vld(i.lin, i.lat)))
        if q is not None:
            plist.append((name, "q", q, g._vld(q.lin, q.lat)))
    verilog = g.verilog()
    drain = drain if drain is not None else 2000 + n_in * g.in_period // 4
    b, bo = g.spec.input_bits, g.spec.output_bits
    mask = (1 << b) - 1
    ys, probes = [], []
    with tempfile.TemporaryDirectory(prefix="dspgen_rs_") as d:
        d = Path(d)
        (d / "dut.v").write_text(verilog)
        (d / "tb.v").write_text(_tb(g, n_in, [(n, s, v) for n, _, s, v in plist], drain))
        pr = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"], cwd=d, capture_output=True,
                            text=True, timeout=timeout)
        if pr.returncode:
            raise RuntimeError("verilog_compile: " + pr.stderr[-800:])
        for k in range(x_i.shape[0]):
            s = d / f"s{k}"
            s.mkdir()
            (s / "in.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in x_i[k]) + "\n")
            if x_q is not None:
                (s / "inq.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in x_q[k]) + "\n")
            pr = subprocess.run(["vvp", "-n", str(d / "sim")], cwd=s, capture_output=True, text=True, timeout=timeout)
            if pr.returncode:
                raise RuntimeError("verilog_sim: " + (pr.stderr or pr.stdout)[-800:])
            rows = [list(map(int, l.split())) for l in (s / "out.txt").read_text().splitlines() if l.strip()]
            a = np.array(rows, dtype=np.float64).reshape(len(rows), -1) / float(1 << (bo - 1))
            ys.append(a[:, 0] + 1j * a[:, 1] if a.shape[1] > 1 else a[:, 0])
            pv = {}
            for j, (name, part, sig, _) in enumerate(plist):
                txt = (s / f"probe{j}.txt").read_text().split()
                v = np.array([int(t) for t in txt], dtype=np.float64) / 2.0 ** sig.F
                pv.setdefault(name, {})[part] = v
            probes.append({n: (p["i"] if "q" not in p else
                               p["i"][:min(len(p["i"]), len(p["q"]))] + 1j * p["q"][:min(len(p["i"]), len(p["q"]))])
                           for n, p in pv.items()})
    return ys, probes, verilog
