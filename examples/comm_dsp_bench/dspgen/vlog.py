"""外部 Verilog 的评价：用任务的测试平台仿真任意 Verilog（端口与任务接口一致），按任务的指标打分。

用于开源基线（USRP、ZipCPU）和直写 Verilog 的对照，与原语候选使用同一套场景、指标与 PPA 流程。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .rtl import _tb
from .task import get


def simulate_inputs(verilog: str, task_name: str, x, xq=None, reset_cycles: int = 2, lead: int = 0) -> list:
    """任意输入码（[行, 样点]）逐行仿真，返回每行的输出数组。"""
    from types import SimpleNamespace
    t = get(task_name)
    out = []
    for k in range(len(x)):
        sc = {"x_codes": np.asarray(x[k])}
        if xq is not None:
            sc["xq_codes"] = np.asarray(xq[k])
        out.append(_run(verilog, t, sc, reset_cycles, lead))
    return out


def _run(verilog, t, sc, reset_cycles, lead):
    bo = t.interface["out_bits"]
    mask = (1 << t.interface["in_bits"]) - 1
    cx = t.iface("out_kind") == "complex"
    n = len(sc["x_codes"])
    tb = _tb(t, n)
    if reset_cycles != 2:
        tb = tb.replace("@(posedge clk); @(posedge clk); #1 rst = 0;", f"repeat ({reset_cycles}) @(posedge clk); #1 rst = 0;")
    with tempfile.TemporaryDirectory(prefix="vlog_") as d:
        d = Path(d)
        (d / "dut.v").write_text(verilog)
        (d / "tb.v").write_text(tb)
        (d / "in.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc["x_codes"]) + "\n")
        if "xq_codes" in sc:
            (d / "inq.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc["xq_codes"]) + "\n")
        p = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "dut.v"], cwd=d, capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(p.stderr[-1500:])
        subprocess.run(["vvp", "-n", "sim"], cwd=d, capture_output=True, text=True, timeout=7200)
        rows = [l.split() for l in (d / "out.txt").read_text().splitlines() if l.strip()]
    rows = [list(map(int, r)) for r in rows if "x" not in "".join(r) and "z" not in "".join(r)]
    a = np.array(rows, dtype=np.float64).reshape(len(rows), -1) / float(1 << (bo - 1))
    y = (a[:, 0] + 1j * a[:, 1] if a.shape[1] > 1 else a[:, 0]) if cx else a[:, 0]
    if lead:
        y = np.concatenate([np.zeros(lead, dtype=y.dtype), y])
    return y


def simulate(verilog: str, task_name: str, idxs, reset_cycles: int = 2, lead: int = 0, extra_files=None) -> dict:
    """返回 {场景: 输出数组}（按接口缩放的浮点，复数接口为复数）。lead：输出前补的零样点数（只平移时间原点）。"""
    t = get(task_name)
    return {idx: _run(verilog, t, t.scene(idx), reset_cycles, lead) for idx in idxs}


def evaluate(verilog: str, task_name: str, idxs=None, **kw) -> dict:
    t = get(task_name)
    idxs = list(idxs if idxs is not None else t.search_scenarios)
    ys = simulate(verilog, task_name, idxs, **kw)
    q = t.combine([t.score(i, ys[i]) for i in idxs])
    return {"valid": True, "quality": q}
