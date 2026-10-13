"""通用硬件后端：逐块/整链 RTL 生成、iverilog 逐位对拍、Yosys+ABC Nangate45 映射面积。

对任意已登记积木通用：积木只需实现 rtl()；这里负责测试平台、仿真、综合与缓存。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from .core import Chain, run_chain

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
from mapped_area import DEFAULT_LIBERTY, synthesis_script  # noqa: E402

CACHE_DIR = BENCH / "dspgraph_cache" / "synth"
_MAIN_LIB = BENCH / "pdk" / "NangateOpenCellLibrary_typical.lib"
LIBERTY = Path(DEFAULT_LIBERTY) if Path(DEFAULT_LIBERTY).is_file() else _MAIN_LIB
SYNTH_SCHEMA = "dspgraph-synth-v1"


def module_name(chain: Chain, i: int) -> str:
    return f"blk{i}_{chain.stages[i].block.type}_{chain.hash[:8]}"


def block_verilog(chain: Chain, i: int, module: str | None = None) -> tuple[str, str]:
    st = chain.stages[i]
    mod = module or module_name(chain, i)
    return mod, st.block.rtl(st.params, st.ctx, st.aux, mod)


def chain_verilog(chain: Chain, top: str = "chain_top") -> str:
    """把各块按统一端口串接成整链顶层。"""
    parts, inst = [], []
    w0 = chain.stages[0].ctx["width_in"]
    prev_v, prev_i, prev_q = "in_valid", "in_i", None
    for i, st in enumerate(chain.stages):
        mod, v = block_verilog(chain, i, f"{top}_b{i}")
        parts.append(v)
        wo = st.ctx["width_out"] if "width_out" in st.ctx else st.params.get("out_bits")
        inst.append(f"wire v{i}; wire signed [{wo - 1}:0] i{i}, q{i};")
        conn = [".clk(clk)", ".rst(rst)", f".in_valid({prev_v})", f".in_i({prev_i})"]
        if st.block.in_kind == "complex":
            conn.append(f".in_q({prev_q})")
        conn += [f".out_valid(v{i})", f".out_i(i{i})", f".out_q(q{i})"]
        inst.append(f"{mod} u{i} ({', '.join(conn)});")
        prev_v, prev_i, prev_q = f"v{i}", f"i{i}", f"q{i}"
    wl = chain.stages[-1].params["out_bits"]
    top_v = [f"module {top} (input wire clk, input wire rst, input wire in_valid, "
             f"input wire signed [{w0 - 1}:0] in_i, output wire out_valid, "
             f"output wire signed [{wl - 1}:0] out_i, output wire signed [{wl - 1}:0] out_q);"]
    top_v += inst
    top_v.append(f"assign out_valid = {prev_v}; assign out_i = {prev_i}; assign out_q = {prev_q};")
    top_v.append("endmodule")
    return "\n".join(parts) + "\n" + "\n".join(top_v) + "\n"


# ---------------------------------------------------------------------------
# 仿真对拍
# ---------------------------------------------------------------------------

def _tb(top: str, w_in: int, w_out: int, complex_in: bool, gap: int, n_in: int) -> str:
    q_decl = f"reg signed [{w_in - 1}:0] in_q;" if complex_in else ""
    q_conn = ".in_q(in_q)," if complex_in else ""
    q_read = "r = $fscanf(fi, \"%d %d\\n\", vi, vq); in_q = vq;" if complex_in else \
        "r = $fscanf(fi, \"%d\\n\", vi);"
    return f"""
`timescale 1ns/1ps
module tb;
reg clk = 0; reg rst = 1; reg in_valid = 0;
reg signed [{w_in - 1}:0] in_i; {q_decl}
wire out_valid; wire signed [{w_out - 1}:0] out_i, out_q;
integer fi, fo, r, k, g; integer vi, vq;
{top} dut (.clk(clk), .rst(rst), .in_valid(in_valid), .in_i(in_i), {q_conn}
           .out_valid(out_valid), .out_i(out_i), .out_q(out_q));
always #5 clk = ~clk;
always @(posedge clk) if (!rst && out_valid) $fwrite(fo, "%0d %0d\\n", out_i, out_q);
initial begin
  fi = $fopen("in.txt", "r"); fo = $fopen("out.txt", "w");
  in_i = 0; vq = 0;
  @(posedge clk); @(posedge clk); #1 rst = 0;
  for (k = 0; k < {n_in}; k = k + 1) begin
    {q_read} in_i = vi;
    in_valid = 1; @(posedge clk); #1 in_valid = 0;
    for (g = 1; g < {gap}; g = g + 1) begin @(posedge clk); #1; end
  end
  repeat ({4 * gap + 64}) @(posedge clk);
  $fclose(fo); $finish;
end
endmodule
"""


def _codes(x: np.ndarray, w: int) -> np.ndarray:
    return np.round(x * float(1 << (w - 1))).astype(np.int64)


def simulate(verilog: str, top: str, x_codes_i, x_codes_q, w_in, w_out, gap,
             complex_in: bool) -> np.ndarray:
    with tempfile.TemporaryDirectory(prefix="dspg_sim_") as d:
        d = Path(d)
        (d / "dut.v").write_text(verilog)
        n = len(x_codes_i)
        (d / "tb.v").write_text(_tb(top, w_in, w_out, complex_in, gap, n))
        lines = [f"{a} {b}" for a, b in zip(x_codes_i, x_codes_q)] if complex_in else \
            [str(a) for a in x_codes_i]
        (d / "in.txt").write_text("\n".join(lines) + "\n")
        subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"], cwd=d,
                       check=True, capture_output=True, text=True)
        subprocess.run(["vvp", "-n", "sim"], cwd=d, check=True, capture_output=True, text=True,
                       timeout=3600)
        rows = [tuple(map(int, l.split())) for l in (d / "out.txt").read_text().splitlines() if l]
    return np.array(rows, dtype=np.int64).reshape(-1, 2)


def check_block(chain: Chain, i: int, x: np.ndarray, gap: int | None = None) -> dict:
    """x：该块输入（归一化值，位于输入网格）。返回逐位比较结果。"""
    st = chain.stages[i]
    mod, v = block_verilog(chain, i)
    w_in = st.ctx["width_in"]
    w_out = st.params["out_bits"]
    gap = gap or st.ctx["rate_in"]
    y = st.block.run(x, st.params, st.ctx, st.aux, exact=True, ideal_coef=False, stats={})
    exp = np.stack([_codes(np.real(y), w_out), _codes(np.imag(y), w_out)], axis=1)
    cx = st.block.in_kind == "complex"
    xi = _codes(np.real(x), w_in)
    xq = _codes(np.imag(x), w_in) if cx else xi * 0
    got = simulate(v, mod, xi, xq, w_in, w_out, gap, cx)
    n = min(len(got), len(exp))
    mism = int(np.count_nonzero(np.any(got[:n] != exp[:n], axis=1)))
    return {"block": st.block.type, "expected": len(exp), "received": len(got), "compared": n,
            "mismatches": mism, "passed": mism == 0 and len(got) == len(exp)}


def check_chain(chain: Chain, x: np.ndarray) -> dict:
    v = chain_verilog(chain)
    y, _ = run_chain(chain, x)
    w_out = chain.stages[-1].params["out_bits"]
    exp = np.stack([_codes(y.real, w_out), _codes(y.imag, w_out)], axis=1)
    w_in = chain.stages[0].ctx["width_in"]
    xi = _codes(x, w_in)
    got = simulate(v, "chain_top", xi, xi * 0, w_in, w_out, 1, False)
    n = min(len(got), len(exp))
    mism = int(np.count_nonzero(np.any(got[:n] != exp[:n], axis=1)))
    return {"expected": len(exp), "received": len(got), "mismatches": mism,
            "passed": mism == 0 and len(got) == len(exp)}


# ---------------------------------------------------------------------------
# 综合（逐块，按 RTL 内容缓存）
# ---------------------------------------------------------------------------

def _abc_path() -> str:
    p = shutil.which("yosys-abc")
    if not p:
        raise RuntimeError("yosys-abc not found")
    return p


def synth_area(verilog: str, top: str, timeout: float = 1200.0, fast: bool = False) -> dict:
    script = synthesis_script(_abc_path(), top)
    if fast:   # ABC 快速映射：更快、面积略差，用于超大设计（结果单独标注）
        script = script.replace("-liberty cells.lib\nclean", "-liberty cells.lib -script +strash;&get,-n;&nf;&put\nclean")
    lib = LIBERTY
    key = hashlib.sha256((SYNTH_SCHEMA + script + verilog +
                          hashlib.sha256(lib.read_bytes()).hexdigest()).encode()).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpath = CACHE_DIR / f"{key}.json"
    if cpath.is_file():
        return json.loads(cpath.read_text()) | {"cache_hit": True}
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="dspg_syn_") as d:
        d = Path(d)
        (d / "design.v").write_text(verilog)
        (d / "cells.lib").write_bytes(lib.read_bytes())
        (d / "run.ys").write_text(script)
        try:
            pr = subprocess.run(["yosys", "-q", "-s", "run.ys"], cwd=d, capture_output=True,
                                text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            res = {"status": "timeout", "seconds": time.time() - t0, "key": key}
            cpath.write_text(json.dumps(res))
            return res
        if pr.returncode != 0:
            res = {"status": "error", "stderr": pr.stderr[-2000:], "seconds": time.time() - t0,
                   "key": key}
            return res
        stat = json.loads((d / "stat.json").read_text())
    design = stat.get("design", {})
    area = design.get("area")
    if area is None:
        mods = stat.get("modules", {})
        area = sum(m.get("area", 0) for m in mods.values())
    res = {"status": "ok", "fast_abc": fast, "area_um2": float(area), "num_cells": design.get("num_cells"),
           "seconds": time.time() - t0, "key": key}
    cpath.write_text(json.dumps(res))
    return res


def chain_area(chain: Chain, timeout: float = 1200.0) -> dict:
    """逐块综合并求和（分层综合口径）。"""
    per, total, ok = {}, 0.0, True
    for i, key in enumerate(chain.keys):
        mod, v = block_verilog(chain, i, f"blk{i}")
        r = synth_area(v, mod, timeout)
        per[key] = r
        if r.get("status") != "ok":
            ok = False
        else:
            total += r["area_um2"]
    return {"status": "ok" if ok else "incomplete", "total_um2": total if ok else None,
            "per_block": per}
