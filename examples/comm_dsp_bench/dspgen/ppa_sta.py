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
_STA_LOCAL = Path("/Users/chengzhy/verievolve_thirdparty/OpenSTA/build/sta")
STA = os.environ.get("VERIEVOLVE_STA") or shutil.which("sta") or (str(_STA_LOCAL) if _STA_LOCAL.exists() else "sta")
ABC = shutil.which("yosys-abc") or "yosys-abc"


def yosys_script(top: str, fast: bool, split_ports: bool = True) -> str:
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
        "splitnets -ports" if split_ports else "",
        "hilomap -hicell LOGIC1_X1 Z -locell LOGIC0_X1 Z",
        "insbuf -buf BUF_X1 A Z",
        "clean -purge",
        "check -mapped -assert",
        f"tee -o stat.json stat -json -liberty cells.lib -top {top}",
        "write_verilog -noattr -noexpr -nohex -nodec netlist.v",
        "",
    ])


_LIBINFO: dict = {}


def _lib_info():
    """从 liberty 读出每个单元的输出引脚与面积。"""
    if not _LIBINFO:
        txt = LIBERTY.read_text()
        for m in re.finditer(r"\n\s*cell \((\w+)\)\s*\{(.*?)\n\s*cell_footprint|\n\s*cell \((\w+)\)", txt, re.S):
            pass
        cur = None
        outs: dict = {}
        area: dict = {}
        pin = None
        for line in txt.splitlines():
            mc = re.match(r"\s*cell \((\w+)\)", line)
            if mc:
                cur = mc.group(1); outs[cur] = set(); pin = None; continue
            ma = re.match(r"\s*area\s*:\s*([0-9.]+)", line)
            if ma and cur and cur not in area and pin is None:
                area[cur] = float(ma.group(1)); continue
            mp = re.match(r"\s*pin \((\w+)\)", line)
            if mp:
                pin = mp.group(1); continue
            md = re.match(r"\s*direction\s*:\s*(\w+)", line)
            if md and cur and pin and md.group(1) == "output":
                outs[cur].add(pin)
        _LIBINFO.update(outs=outs, area=area)
    return _LIBINFO


def _esc(net: str) -> str:
    """Verilog 转义标识符（以反斜杠开头）必须以空白结束。"""
    return net + " " if net.startswith("\\") else net


def buffer_fanout(netlist: str, max_fanout: int = 16, buf: str = "BUF_X4", skip=("clk",)) -> tuple[str, int, float]:
    """高扇出缓冲：扇出超过 max_fanout 的网插入 buf 缓冲树（逻辑不变）。返回 (新网表, 新增缓冲数, 新增面积)。

    Yosys/ABC 快速流程不会给触发器输出等高扇出网插缓冲，导致个别网驱动上千个引脚、STA 报出不真实的超长延迟；
    真实流程中综合器或布局布线会自动做这一步。这里用确定性的平衡缓冲树近似它，并把缓冲器面积计入总面积。"""
    info = _lib_info()
    inst_re = re.compile(r"^  (\w+) (\S+) \(\n(.*?)\n  \);\n", re.S | re.M)
    pin_re = re.compile(r"\.(\w+)\((.*?)\)(?:,|$)", re.M)
    insts = []
    for m in inst_re.finditer(netlist):
        pins = [(pm.group(1), pm.group(2).strip()) for pm in pin_re.finditer(m.group(3))]
        insts.append([m.group(1), m.group(2), pins, m.start(), m.end()])
    if not insts:
        return netlist, 0, 0.0
    loads: dict = {}
    for ii, (cell, name, pins, *_r) in enumerate(insts):
        outs = info["outs"].get(cell, set())
        for k, (pn, net) in enumerate(pins):
            if pn not in outs and net and not net.startswith(("1'", "0'")):
                loads.setdefault(net, []).append((ii, k))
    nbuf = 0
    new_wires = []
    new_insts = []
    for net, ls in loads.items():
        if len(ls) <= max_fanout or net in skip:
            continue
        level = ls                    # 当前层需要被驱动的负载
        while True:
            groups = [level[i:i + max_fanout] for i in range(0, len(level), max_fanout)]
            nxt = []
            for g in groups:
                nbuf += 1
                w = f"_fobuf{nbuf}_"
                new_wires.append(w)
                for ld in g:
                    if ld[0] == "buf":
                        new_insts[ld[1]][1] = w          # 下一层缓冲器的输入由本层驱动
                    else:
                        ii, k = ld
                        insts[ii][2][k] = (insts[ii][2][k][0], w)
                new_insts.append([f"_fob{nbuf}_", None, w])      # 输入稍后连接
                nxt.append(("buf", len(new_insts) - 1))
            if len(nxt) <= max_fanout:
                for ld in nxt:
                    new_insts[ld[1]][1] = net
                break
            level = nxt
    if not nbuf:
        return netlist, 0, 0.0
    head = netlist[:insts[0][3]]
    body = []
    for cell, name, pins, *_r in insts:
        body.append(f"  {cell} {name} (\n" + ",\n".join(f"    .{pn}({_esc(net)})" for pn, net in pins) + "\n  );\n")
    for name, src, dst in new_insts:
        body.append(f"  {buf} {name} (\n    .A({_esc(src)}),\n    .Z({dst})\n  );\n")
    decl = "".join(f"  wire {w};\n" for w in new_wires)
    tail = netlist[insts[-1][4]:]
    return head + decl + "".join(body) + tail, nbuf, nbuf * info["area"][buf]


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
        nl, nbuf, abuf = buffer_fanout((d / "netlist.v").read_text())
        (d / "netlist.v").write_text(re.sub(r"\bsigned\s+", "", nl))
        stat["area"] = float(stat["area"]) + abuf
        stat["num_cells"] = int(stat["num_cells"]) + nbuf
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
            "fanout_buffers": nbuf, "fanout_buffer_area": abuf,
            "flow": "yosys+abc" + ("(-fast)" if fast else "") + " → 扇出缓冲(≤16, BUF_X4) → OpenSTA; Nangate45 typical; NLDM; 输出负载 5 fF；全局翻转率",
        }


def _power_tb(task, n: int, half_ps: int) -> str:
    """门级功耗仿真用的测试平台：与 rtl._tb 相同的激励协议，时钟周期改为 STA 约束周期，并导出 VCD。"""
    from .rtl import _tb
    tb = _tb(task, n).replace("`timescale 1ns/1ps", "`timescale 1ps/1ps")
    tb = tb.replace("always #5 clk = ~clk;", f"always #{half_ps} clk = ~clk;")
    tb = tb.replace("initial begin\n", 'initial begin\n  $dumpfile("act.vcd"); $dumpvars(0, tb.dut);\n', 1)
    tb = tb.replace("#1 rst = 0;", "#1 rst = 0;").replace("#1 in_valid = 0;", "#1 in_valid = 0;")
    return tb


def evaluate_verilog_vcd(verilog: str, task_name: str, scenario: int = 0, period_ns: float = 2.0,
                         n_in: int | None = None, warm_frac: float = 0.25, fast: bool = True, top: str = "top",
                         clock_port: str = "clk", keep_dir: Path | None = None, expect=None) -> dict:
    """面积 + OpenSTA 时序 + 基于门级仿真翻转率（VCD）的功耗。

    激励取任务场景 scenario 的输入码，每 in_period 个时钟送一个样点（与 RTL 对拍相同的协议）；
    跳过前 warm_frac 的仿真时间（复位与各级建立）后统计功耗。"""
    from .task import get
    import numpy as np
    t0 = time.time()
    task = get(task_name)
    sc = task.scene(scenario)
    n = int(n_in or len(sc["x_codes"]))
    mask = (1 << task.interface["in_bits"]) - 1
    half_ps = int(round(period_ns * 500))
    with tempfile.TemporaryDirectory(prefix="ppa_vcd_") as d:
        d = Path(d)
        (d / "design.v").write_text(verilog)
        shutil.copy(LIBERTY, d / "cells.lib")
        (d / "run.ys").write_text(yosys_script(top, fast, split_ports=False))
        pr = subprocess.run(["yosys", "-q", "-s", "run.ys"], cwd=d, capture_output=True, text=True, timeout=7200)
        if pr.returncode:
            return {"status": "synth_error", "stderr": pr.stderr[-800:]}
        stat = json.loads((d / "stat.json").read_text())["design"]
        nl, nbuf, abuf = buffer_fanout((d / "netlist.v").read_text())
        (d / "netlist.v").write_text(nl)
        stat["area"] = float(stat["area"]) + abuf
        stat["num_cells"] = int(stat["num_cells"]) + nbuf
        # 单元行为模型：由 liberty 的 function / ff 描述生成
        pc = subprocess.run(["yosys", "-q", "-p", "read_liberty -ignore_miss_func cells.lib; "
                             "write_verilog -noattr cells_sim.v"], cwd=d, capture_output=True, text=True)
        if pc.returncode:
            return {"status": "cellmodel_error", "stderr": pc.stderr[-800:]}
        (d / "tb.v").write_text(_power_tb(task, n, half_ps))
        (d / "in.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc["x_codes"][:n]) + "\n")
        if "xq_codes" in sc:
            (d / "inq.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in sc["xq_codes"][:n]) + "\n")
        pi = subprocess.run(["iverilog", "-g2012", "-o", "sim", "tb.v", "netlist.v", "cells_sim.v"], cwd=d,
                            capture_output=True, text=True)
        if pi.returncode:
            return {"status": "gatesim_compile_error", "stderr": pi.stderr[-1200:]}
        t1 = time.time()
        subprocess.run(["vvp", "-n", "sim"], cwd=d, capture_output=True, text=True, timeout=7200)
        t_sim = time.time() - t1
        if not (d / "act.vcd").exists():
            return {"status": "gatesim_error"}
        gate_check = None
        if expect is not None and (d / "out.txt").exists():      # 门级网表（含扇出缓冲）输出与整数模型逐位对拍
            import numpy as np
            rows = [l.split() for l in (d / "out.txt").read_text().splitlines() if l.strip()]
            rows = [list(map(int, r)) for r in rows if "x" not in "".join(r) and "z" not in "".join(r)]
            got = np.array(rows, dtype=np.int64).reshape(len(rows), -1) if rows else np.zeros((0, 2), np.int64)
            exp = np.asarray(expect, dtype=np.int64)
            m = min(len(got), len(exp))
            bad = int(np.count_nonzero(got[:m] != exp[:m]))
            gate_check = {"compared": m, "mismatches": bad, "gate_outputs": len(got), "expected": len(exp)}
        P = task.iface("in_period")
        total_ps = (n * P + 514) * 2 * half_ps
        begin_ps = int(total_ps * warm_frac)
        end_ps = int(n * P * 2 * half_ps)
        # OpenSTA 的 Verilog 读入器不接受 signed 关键字；只影响端口声明，不改变网表连接
        (d / "netlist_sta.v").write_text(re.sub(r"\bsigned\s+", "", (d / "netlist.v").read_text()))
        tcl = sta_script(top, clock_port, period_ns, 0.1).replace("read_verilog netlist.v", "read_verilog netlist_sta.v").replace(
            "set_power_activity -global -activity 0.1\n",
            f"read_vcd -scope tb/dut -begin_time {begin_ps} -end_time {end_ps} act.vcd\n"
            "report_activity_annotation > annot.rpt\n")
        (d / "run.tcl").write_text(tcl)
        ps = subprocess.run([str(STA), "-no_init", "-no_splash", "-exit", "run.tcl"], cwd=d,
                            capture_output=True, text=True, timeout=3600)
        path = (d / "path.rpt").read_text() if (d / "path.rpt").exists() else ""
        cp = parse_path(path)
        power = (d / "power.rpt").read_text() if (d / "power.rpt").exists() else ""
        annot = (d / "annot.rpt").read_text() if (d / "annot.rpt").exists() else ""
        if keep_dir:
            keep_dir.mkdir(parents=True, exist_ok=True)
            for f in ("netlist.v", "path.rpt", "power.rpt", "annot.rpt", "run.tcl", "tb.v"):
                if (d / f).exists():
                    shutil.copy(d / f, keep_dir / f)
        if cp["arrival_ns"] is None:
            return {"status": "sta_error", "area_um2": float(stat["area"]), "sta_output": (ps.stdout + ps.stderr)[-1500:]}
        wns = cp["required_ns"] - cp["arrival_ns"]
        crit = period_ns - wns
        return {"status": "ok", "area_um2": float(stat["area"]), "cells": int(stat["num_cells"]),
                "clock_ns": period_ns, "wns_ns": round(wns, 4), "min_period_ns": crit,
                "fmax_mhz": 1e3 / crit if crit > 0 else None, "critical_path": cp,
                "power_vcd": parse_power(power), "annotation": annot[-600:], "gate_vs_model": gate_check,
                "vcd_window_ps": [begin_ps, end_ps], "scenario": scenario, "n_in": n,
                "gatesim_seconds": t_sim, "total_seconds": time.time() - t0,
                "fanout_buffers": nbuf, "fanout_buffer_area": abuf,
                "flow": "yosys+abc" + ("(-fast)" if fast else "") + " → 扇出缓冲(≤16, BUF_X4) → 门级 iverilog 仿真（任务场景激励）→ OpenSTA read_vcd；"
                        "Nangate45 typical；输出负载 5 fF"}


def evaluate_program_vcd(task: str, prog: Path, **kw) -> dict:
    from .task import run_program, get
    import numpy as np
    t = get(task)
    sc0 = list(t.search_scenarios)[0]
    r = run_program(prog.read_text(), task, [sc0], want_verilog=True, timeout=600)
    if not r.get("ok"):
        return {"status": "build_error", "error": r.get("error")}
    bo = t.interface["out_bits"]
    outs = r["outputs"][str(sc0)]
    cols = [np.round(np.array(o) * (1 << (bo - 1))).astype(np.int64) for o in outs]
    expect = np.stack(cols, axis=1) if len(cols) > 1 else cols[0][:, None]
    return evaluate_verilog_vcd(r["verilog"], task, scenario=sc0, expect=expect, **kw)


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
    ap.add_argument("--vcd", action="store_true", help="功耗用门级仿真翻转率（VCD），而不是全局翻转率")
    ap.add_argument("--n-in", type=int, default=None)
    a = ap.parse_args()
    if a.vcd:
        print(json.dumps(evaluate_program_vcd(a.task, a.prog, period_ns=a.clock_ns, fast=a.fast, n_in=a.n_in,
                                              keep_dir=a.keep), ensure_ascii=False, indent=1))
        raise SystemExit
    print(json.dumps(evaluate_program(a.task, a.prog, period_ns=a.clock_ns, activity=a.activity, fast=a.fast,
                                      keep_dir=a.keep), ensure_ascii=False, indent=1))
