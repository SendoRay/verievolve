"""G3 一致性门：LLM 写的 RTL 是否逐位忠实于冻结契约（FRAMEWORK_v5 §4.2）。

检查：① iverilog 编译；② 各向量集上第 k 次 out_valid 的输出 = 参考第 k 个样点（排除暖机输出）；
③ 输出个数与吞吐（每 ii 个时钟一个输入，不能反压）；④ 承诺：乘法器数量（综合前统计 $mul）；
⑤ 有承诺的分段必须带 ve_scope 标注。返回的报告给 Lowering Agent 做局部修复。
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

DRAIN = 4096


def _tb(it: dict, n: int, ii: int) -> str:
    b, bo = it["in_bits"], it["out_bits"]
    cx_in, cx_out = it["in_kind"] == "complex", it["out_kind"] == "complex"
    qd = f"reg signed [{b - 1}:0] in_q = 0; reg [{b - 1}:0] memq [0:{n - 1}];" if cx_in else ""
    qc = ".in_q(in_q)," if cx_in else ""
    qr = "in_q = memq[k];" if cx_in else ""
    qm = '$readmemh("inq.hex", memq);' if cx_in else ""
    od = f"wire signed [{bo - 1}:0] out_q;" if cx_out else ""
    oc = ", .out_q(out_q)" if cx_out else ""
    ow = ('$fwrite(fo, "%0d %0d %0d\\n", cyc, out_i, out_q);' if cx_out
          else '$fwrite(fo, "%0d %0d\\n", cyc, out_i);')
    return f"""`timescale 1ns/1ps
module tb;
reg clk = 0; reg rst = 1; reg in_valid = 0; reg signed [{b - 1}:0] in_i = 0; {qd}
wire out_valid; wire signed [{bo - 1}:0] out_i; {od}
reg [{b - 1}:0] mem [0:{n - 1}];
integer fo, fi, k, j, cyc;
top dut (.clk(clk), .rst(rst), .in_valid(in_valid), .in_i(in_i), {qc} .out_valid(out_valid), .out_i(out_i){oc});
always #5 clk = ~clk;
initial cyc = 0;
always @(posedge clk) begin cyc <= cyc + 1; if (!rst && out_valid) {ow} if (!rst && in_valid) $fwrite(fi, "%0d\\n", cyc); end
initial begin
  $readmemh("in.hex", mem); {qm} fo = $fopen("out.txt", "w"); fi = $fopen("in_cyc.txt", "w");
  @(posedge clk); @(posedge clk); #1 rst = 0;
  for (k = 0; k < {n}; k = k + 1) begin
    in_i = mem[k]; {qr} in_valid = 1; @(posedge clk); #1 in_valid = 0;
    for (j = 1; j < {ii}; j = j + 1) begin @(posedge clk); #1; end
  end
  repeat ({DRAIN}) @(posedge clk);
  $fclose(fo); $fclose(fi); $finish;
end
endmodule
"""


def _scopes_in(rtl: str) -> set:
    return set(re.findall(r'\(\*[^*]*ve_scope\s*=\s*"([^"]+)"[^*]*\*\)', rtl))


def _mul_count(rtl: str, d: Path) -> int | None:
    (d / "r.v").write_text(rtl)
    pr = subprocess.run(["yosys", "-q", "-p", "read_verilog -sv r.v; hierarchy -top top; proc; opt; wreduce; "
                         "opt_clean; tee -q -o stat.json stat -json"], cwd=d, capture_output=True, text=True,
                        timeout=600)
    if pr.returncode or not (d / "stat.json").exists():
        return None
    st = json.loads((d / "stat.json").read_text())
    mods = st.get("modules", {})
    return sum(int(m.get("num_cells_by_type", {}).get("$mul", 0)) for m in mods.values())


def check(contract_dir: Path, rtl: str, sets=None, timeout: int = 1800) -> dict:
    """对拍 RTL 与契约。sets：只跑指定的向量集（缺省全部）。"""
    contract_dir = Path(contract_dir)
    c = json.loads((contract_dir / "contract.json").read_text())
    it, ii, warm = c["interface"], int(c["timing"]["ii"]), int(c["warmup_outputs"])
    rep = {"passed": False, "sets": {}, "violations": []}
    with tempfile.TemporaryDirectory(prefix="dspc_g3_") as tmp:
        d = Path(tmp)
        (d / "dut.v").write_text(rtl)
        pr = subprocess.run(["iverilog", "-g2012", "-o", "chk", "dut.v"], cwd=d, capture_output=True, text=True)
        if pr.returncode and "top" not in pr.stderr and "Unknown module" not in pr.stderr:
            rep["violations"].append({"code": "compile", "message": pr.stderr[-1500:]})
            return rep
        for name, meta in c["vectors"].items():
            if sets and name not in sets:
                continue
            vd = contract_dir / "vectors" / name
            run_d = d / name
            run_d.mkdir()
            for f in ("in.hex", "inq.hex"):
                if (vd / f).exists():
                    (run_d / f).write_text((vd / f).read_text())
            (run_d / "tb.v").write_text(_tb(it, meta["n_in"], ii))
            (run_d / "dut.v").write_text(rtl)
            pr = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"], cwd=run_d,
                                capture_output=True, text=True)
            if pr.returncode:
                rep["violations"].append({"code": "compile", "message": pr.stderr[-1500:]})
                return rep
            try:
                subprocess.run(["vvp", "-n", "sim"], cwd=run_d, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                rep["violations"].append({"code": "sim_timeout", "set": name})
                return rep
            exp = [list(map(int, l.split())) for l in (vd / "expected.txt").read_text().splitlines() if l.strip()]
            raw = [l.split() for l in (run_d / "out.txt").read_text().splitlines() if l.strip()]
            got, unknown = [], 0
            for r in raw:
                if any(("x" in v or "z" in v) for v in r[1:]):
                    unknown += 1
                    got.append(None)
                else:
                    got.append([int(r[0])] + list(map(int, r[1:])))
            in_cyc = [int(l) for l in (run_d / "in_cyc.txt").read_text().splitlines() if l.strip()]
            s = {"expected_outputs": len(exp), "rtl_outputs": len(got), "unknown_outputs": unknown}
            m = min(len(exp), len(got))
            first, bad = None, 0
            for k in range(warm, m):
                g = got[k]
                if g is None or g[1:] != exp[k]:
                    bad += 1
                    if first is None:
                        first = {"output_index": k, "expected": exp[k], "got": None if g is None else g[1:],
                                 "cycle": None if g is None else g[0]}
            s["mismatches"] = bad
            if first:
                s["first_mismatch"] = first
            if len(got) < len(exp):
                rep["violations"].append({"code": "too_few_outputs", "set": name,
                                          "message": f"RTL produced {len(got)} outputs, expected {len(exp)}"})
            if bad:
                rep["violations"].append({"code": "mismatch", "set": name, **(first or {})})
            if got and got[0] is not None and in_cyc:
                s["first_output_cycle_after_first_input"] = got[0][0] - in_cyc[0]
            rep["sets"][name] = s
        # 承诺
        missing = [sc for sc in c["commitments"] if sc not in _scopes_in(rtl)]
        if missing:
            rep["violations"].append({"code": "scope_annotation", "message": f"committed scope(s) without "
                                      f"(* ve_scope = ... *): {missing}"})
        mul_caps = [kw["mul_max"] for kw in c["commitments"].values() if "mul_max" in kw]
        if mul_caps:
            n_mul = _mul_count(rtl, d)
            rep["mul_cells"] = n_mul
            covered = set(c["commitments"]) == set(c["scopes"]) and all("mul_max" in kw
                                                                         for kw in c["commitments"].values())
            if n_mul is not None and covered and n_mul > sum(mul_caps):
                rep["violations"].append({"code": "resource", "message": f"{n_mul} multipliers ($mul) exceed the "
                                          f"committed total {sum(mul_caps)}"})
            elif not covered:
                rep["resource_note"] = "承诺未覆盖全部分段，只报告乘法器总数，不做按分段核对"
        tm = c["timing"]
        if tm.get("latency_max") is not None:
            lat = [s.get("first_output_cycle_after_first_input") for s in rep["sets"].values()]
            lat = [v for v in lat if v is not None]
            if lat and max(lat) > tm["latency_max"] * 4:
                rep["latency_note"] = "首个输出相对首个输入的时钟数只作参考（多速率下不等于逐样点延迟）"
    rep["annotated_scopes"] = sorted(_scopes_in(rtl))
    rep["passed"] = not rep["violations"]
    return rep
