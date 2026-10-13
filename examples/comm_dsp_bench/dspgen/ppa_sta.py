"""PPA 评估：Yosys + ABC 映射到 Nangate45（面积），OpenSTA 做静态时序与功耗分析。

与原来的 ABC stime 相比，OpenSTA 计入 clk-to-q、建立时间、输入输出延迟与 Liberty 的 NLDM 表，
按真实时钟约束报告最差裕量（WNS）、最高频率与功耗。

用法（在 examples/comm_dsp_bench 下）：
  python -m dspgen.ppa_sta TASK PROG.py [--clock-ns 2.0] [--activity 0.1] [--fast]
OpenSTA 可执行文件：环境变量 VERIEVOLVE_STA，否则在 PATH 中查找 sta。
输出一个 JSON：area_um2、cells、wns_ns、fmax_mhz、critical_path、power_mw（内部/开关/漏电）。
"""
import argparse
import json
import re
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
LIBERTY = BENCH / "pdk" / "NangateOpenCellLibrary_typical.lib"
STA = os.environ.get("VERIEVOLVE_STA") or shutil.which("sta") or "sta"
ABC = shutil.which("yosys-abc") or "yosys-abc"


def yosys_script(top: str, fast: bool) -> str:
    # 快速模式沿用原流程的轻量 ABC 脚本（与已有 fast_abc 口径一致）
    abc = (f'abc -exe "{ABC}" -liberty cells.lib -script +strash;&get,-n;&nf;&put;topo;buffer;upsize;dnsize'
           if fast else f'abc -exe "{ABC}" -liberty cells.lib')
    return "\n".join([
        "read_liberty -lib cells.lib",
        "read_verilog -sv design.v",
        f"hierarchy -check -top {top}",
        f"synth -top {top} -flatten -noabc",
        "dffunmap",
        "dfflibmap -liberty cells.lib",
        abc,
        "opt_clean -purge",
        "setundef -zero",
        "splitnets -ports",
        "hilomap -hicell LOGIC1_X1 Z -locell LOGIC0_X1 Z",
        "insbuf -buf BUF_X1 A Z",
        "clean -purge",
        "check -mapped -assert",
        f"tee -o stat.json stat -json -liberty cells.lib -top {top}",
        "write_verilog -noattr -noexpr -nohex -nodec netlist.v",
        "",
    ])


def sta_script(top: str, clock_port: str, period_ns: float, activity: float) -> str:
    return "\n".join([
        "read_liberty cells.lib",
        "read_verilog netlist.v",
        f"link_design {top}",
        f"create_clock -name clk -period {period_ns} [get_ports {clock_port}]",
        "set_input_delay 0 -clock clk [delete_from_list [all_inputs] [get_ports " + clock_port + "]]",
        "set_output_delay 0 -clock clk [all_outputs]",
        "set_load 0.005 [all_outputs]",
        "report_checks -path_delay max -fields {slew cap} -digits 4 > path.rpt",
        f"set_power_activity -global -activity {activity}",
        "report_power > power.rpt",
        "exit",
        "",
    ])


def parse_power(text: str) -> dict:
    m = re.search(r"^Total\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)", text, re.M)
    if not m:
        return {}
    i, s, l, t = (float(x) * 1e3 for x in m.groups())     # W → mW
    return {"internal_mw": i, "switching_mw": s, "leakage_mw": l, "total_mw": t}


def parse_path(text: str) -> dict:
    sp = re.search(r"Startpoint:\s*(\S+)", text)
    ep = re.search(r"Endpoint:\s*(\S+)", text)
    arr = re.search(r"([0-9.]+)\s+data arrival time", text)
    req = re.search(r"([0-9.]+)\s+data required time", text)
    return {"startpoint": sp and sp.group(1), "endpoint": ep and ep.group(1),
            "arrival_ns": arr and float(arr.group(1)), "required_ns": req and float(req.group(1))}


def evaluate_verilog(verilog: str, top: str = "top", clock_port: str = "clk", period_ns: float = 2.0,
                     activity: float = 0.1, fast: bool = False, keep_dir: Path | None = None) -> dict:
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="ppa_") as d:
        d = Path(d)
        (d / "design.v").write_text(verilog)
        shutil.copy(LIBERTY, d / "cells.lib")
        (d / "run.ys").write_text(yosys_script(top, fast))
        pr = subprocess.run(["yosys", "-q", "-s", "run.ys"], cwd=d, capture_output=True, text=True, timeout=7200)
        if pr.returncode:
            return {"status": "synth_error", "stderr": pr.stderr[-800:]}
        stat = json.loads((d / "stat.json").read_text())["design"]
        t_syn = time.time() - t0
        (d / "run.tcl").write_text(sta_script(top, clock_port, period_ns, activity))
        ps = subprocess.run([str(STA), "-no_init", "-no_splash", "-exit", "run.tcl"], cwd=d,
                            capture_output=True, text=True, timeout=3600)
        out = ps.stdout + ps.stderr
        path = (d / "path.rpt").read_text() if (d / "path.rpt").exists() else ""
        cp = parse_path(path)
        power = (d / "power.rpt").read_text() if (d / "power.rpt").exists() else ""
        if keep_dir:
            keep_dir.mkdir(parents=True, exist_ok=True)
            for f in ("netlist.v", "path.rpt", "power.rpt", "run.ys", "run.tcl"):
                if (d / f).exists():
                    shutil.copy(d / f, keep_dir / f)
        if cp["arrival_ns"] is None or cp["required_ns"] is None:
            return {"status": "sta_error", "area_um2": float(stat["area"]), "sta_output": out[-1500:]}
        wns_ns = cp["required_ns"] - cp["arrival_ns"]   # 最差裕量（required 已扣除建立时间）
        crit = period_ns - wns_ns            # 最差路径所需的最小周期（含 clk-to-q 与建立时间）
        return {
            "status": "ok", "area_um2": float(stat["area"]), "cells": int(stat["num_cells"]),
            "clock_ns": period_ns, "wns_ns": round(wns_ns, 4),
            "min_period_ns": crit, "fmax_mhz": 1e3 / crit if crit > 0 else None,
            "critical_path": cp, "activity": activity,
            "power_at_clock": parse_power(power),
            "synth_seconds": t_syn, "total_seconds": time.time() - t0,
            "flow": "yosys+abc" + ("(-fast)" if fast else "") + " → OpenSTA; Nangate45 typical; NLDM; 输出负载 5 fF；全局翻转率",
        }


def evaluate_program(task: str, prog: Path, **kw) -> dict:
    from .task import run_program, get
    t = get(task)
    r = run_program(prog.read_text(), task, list(t.search_scenarios)[:1], want_verilog=True, timeout=600)
    if not r.get("ok"):
        return {"status": "build_error", "error": r.get("error")}
    return evaluate_verilog(r["verilog"], **kw)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("prog", type=Path)
    ap.add_argument("--clock-ns", type=float, default=2.0)
    ap.add_argument("--activity", type=float, default=0.1)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--keep", type=Path)
    a = ap.parse_args()
    print(json.dumps(evaluate_program(a.task, a.prog, period_ns=a.clock_ns, activity=a.activity, fast=a.fast,
                                      keep_dir=a.keep), ensure_ascii=False, indent=1))
