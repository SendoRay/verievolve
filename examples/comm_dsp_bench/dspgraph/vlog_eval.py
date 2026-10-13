"""B1 对照：评价 LLM 直接写的 Verilog（与本方法同一裁判、同一面积口径）。

候选格式：一个 Verilog 文件，顶层模块 top，端口
  input clk, rst, in_valid, input signed [input_bits-1:0] in_i,
  output out_valid, output signed [output_bits-1:0] out_i, out_q
输入每个时钟一个样点（in_valid 恒为 1）；out_valid 为 1 的周期给出一个复基带输出样点。

离线计算（与本方法程序可用 numpy/scipy 设计系数对等）：
  // @py <Python 语句>          按顺序执行；可用 np、scipy、math、spec
  // @hex <文件名> <位宽> <表达式>  表达式给出整数列表，写成二进制补码 hex 文件，供 $readmemh 读取
  {{<表达式>}}                  在 Verilog 正文中替换为表达式的值
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from . import judge, hw
from .rx_spec import SPECS

SIM_TIMEOUT = 900
DIRECTIVE = re.compile(r"^\s*//\s*@(py|hex)\s+(.*)$")


class VError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def render(text: str, spec) -> tuple[str, dict]:
    """执行 @py/@hex 指令并替换 {{...}}，返回 (Verilog, {文件名: 内容})。"""
    import scipy
    import scipy.signal
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "spec": spec}
    files = {}
    for ln, line in enumerate(text.splitlines(), 1):
        m = DIRECTIVE.match(line)
        if not m:
            continue
        kind, body = m.groups()
        try:
            if kind == "py":
                exec(body, env)
            else:
                name, width, expr = body.split(None, 2)
                if not re.fullmatch(r"[A-Za-z0-9_.]+\.hex", name):
                    raise VError("directive", f"line {ln}: bad hex file name {name!r}")
                w = int(width)
                vals = [int(v) for v in eval(expr, env)]
                if len(vals) > 1 << 17:
                    raise VError("directive", f"line {ln}: table too large ({len(vals)})")
                lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
                bad = [v for v in vals if v < lo or v > hi]
                if bad:
                    raise VError("directive", f"line {ln}: value {bad[0]} does not fit signed {w} bits")
                nd = (w + 3) // 4
                files[name] = "\n".join(f"{v & ((1 << w) - 1):0{nd}x}" for v in vals) + "\n"
        except VError:
            raise
        except Exception as e:
            raise VError("python_error", f"line {ln}: {type(e).__name__}: {str(e)[:300]}")

    def sub(m):
        try:
            return str(eval(m.group(1), env))
        except Exception as e:
            raise VError("python_error", f"{{{{{m.group(1)}}}}}: {type(e).__name__}: {str(e)[:200]}")
    return re.sub(r"\{\{(.*?)\}\}", sub, text), files


def _tb(w_in, w_out, n):
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
  in_valid = 0; repeat (512) @(posedge clk);
  $fclose(fo); $finish;
end
endmodule
"""


def simulate(verilog: str, files: dict, spec, scenarios) -> dict:
    out = {}
    with tempfile.TemporaryDirectory(prefix="b1_") as d:
        d = Path(d)
        (d / "dut.v").write_text(verilog)
        for k, v in files.items():
            (d / k).write_text(v)
        n = judge.n_in(spec)
        (d / "tb.v").write_text(_tb(spec.input_bits, spec.output_bits, n))
        pr = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"], cwd=d,
                            capture_output=True, text=True)
        if pr.returncode:
            raise VError("verilog_compile", pr.stderr[-1500:])
        mask = (1 << spec.input_bits) - 1
        for i in scenarios:
            sc = judge.scene(spec, i)
            (d / "in.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc.x_codes) + "\n")
            try:
                r = subprocess.run(["vvp", "-n", "sim"], cwd=d, capture_output=True, text=True,
                                   timeout=SIM_TIMEOUT)
            except subprocess.TimeoutExpired:
                raise VError("sim_timeout", f"simulation exceeded {SIM_TIMEOUT} s")
            if "error" in r.stdout.lower() and "out.txt" not in r.stdout:
                pass
            txt = (d / "out.txt").read_text() if (d / "out.txt").exists() else ""
            rows = [l.split() for l in txt.splitlines() if l.strip()]
            try:
                arr = np.array(rows, dtype=np.int64).reshape(-1, 2)
            except ValueError:
                raise VError("sim_output", "outputs contain x/z (uninitialized or undriven signals)")
            out[i] = (arr[:, 0] + 1j * arr[:, 1]) / float(1 << (spec.output_bits - 1))
    return out


def synth(verilog: str, files: dict, timeout=900) -> dict:
    """面积：Yosys + Nangate45，快速 ABC 脚本（与校准代理同口径）。表文件随设计一起综合。"""
    blob = verilog + "".join(f"\n//FILE {k}\n{v}" for k, v in sorted(files.items()))
    key = hashlib.sha256(blob.encode()).hexdigest()
    cache = hw.CACHE_DIR / f"b1_{key}.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    script = hw.synthesis_script(hw._abc_path(), "top").replace(
        "-liberty cells.lib\nclean", "-liberty cells.lib -script +strash;&get,-n;&nf;&put\nclean")
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="b1syn_") as d:
        d = Path(d)
        (d / "design.v").write_text(verilog)
        for k, v in files.items():
            (d / k).write_text(v)
        shutil.copy(hw.LIBERTY, d / "cells.lib")
        (d / "run.ys").write_text(script)
        try:
            pr = subprocess.run(["yosys", "-q", "-s", "run.ys"], cwd=d, capture_output=True, text=True,
                                timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "seconds": time.time() - t0}
        if pr.returncode:
            return {"status": "error", "stderr": (pr.stderr or pr.stdout)[-800:]}
        st = json.loads((d / "stat.json").read_text())["design"]
    res = {"status": "ok", "area_um2": float(st["area"]), "num_cells": st.get("num_cells"),
           "seconds": time.time() - t0}
    hw.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res))
    return res


def evaluate_verilog_program(text: str, spec_name: str, scenarios=judge.SEARCH_SCENARIOS,
                             with_area=True) -> dict:
    spec = SPECS[spec_name]
    t0 = time.time()
    try:
        v, files = render(text, spec)
        ys = simulate(v, files, spec, list(scenarios))
    except VError as e:
        return {"valid": False, "error": {"code": e.code, "message": e.message}, "seconds": time.time() - t0}
    q = judge.combine(spec, [judge.score(spec, i, ys[i]) for i in scenarios])
    q["saturation"] = {}
    out = {"valid": True, "quality": q, "seconds_sim": time.time() - t0}
    if with_area:
        a = synth(v, files)
        if a.get("status") != "ok":
            return {"valid": False, "error": {"code": "synthesis_" + a.get("status", "error"),
                                              "message": a.get("stderr", "synthesis failed or timed out")},
                    "quality": q}
        out["area"] = a["area_um2"]
        out["area_per_scope"] = {"top": a["area_um2"]}
    out["seconds"] = time.time() - t0
    return out
