"""【已弃用，仅用于复现旧结果；新评估请用 dspgen.timing / dspgen.ppa_sta（OpenSTA）】\n关键路径延迟（ABC stime）：Nangate45 typical，快速映射脚本，无线负载模型，
只含寄存器到寄存器的组合路径延迟（不含 clk-to-q、建立时间与时钟偏斜）；按单周期路径统计。

python -m dspgraph.timing OUT.json NAME=SPEC=PATH ...
"""
import json, os, re, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from . import hw
from .rtl_judge import run_program
from .rx_spec import SPECS


def job(it):
    name, spec, path = it
    r = run_program(Path(path).read_text(), spec, [0], want_verilog=True)
    script = hw.synthesis_script(hw._abc_path(), "top").replace(
        "-liberty cells.lib\nclean", "-liberty cells.lib -script +strash;&get,-n;&nf;&put;topo;"
        + ("buffer;upsize;dnsize;" if os.environ.get("DSPG_TIMING_SIZED") else "") + "stime,-p\nclean")
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="tim_") as d:
        d = Path(d)
        (d / "design.v").write_text(r["verilog"])
        shutil.copy(hw.LIBERTY, d / "cells.lib")
        (d / "run.ys").write_text(script)
        try:
            pr = subprocess.run(["yosys", "-s", "run.ys"], cwd=d, capture_output=True, text=True, timeout=5400)
        except subprocess.TimeoutExpired:
            return {"name": name, "spec": spec, "status": "timeout"}
        if pr.returncode:
            return {"name": name, "spec": spec, "status": "error", "stderr": pr.stderr[-400:]}
        delays = [float(x) for x in re.findall(r"Delay =\s*([0-9.]+) ps", pr.stdout)]
        area = json.loads((d / "stat.json").read_text())["design"]["area"]
    dmax = max(delays) if delays else None
    return {"name": name, "spec": spec, "status": "ok", "critical_path_ps": dmax,
            "fmax_mhz": 1e6 / dmax if dmax else None, "area_um2": float(area), "sized": bool(os.environ.get("DSPG_TIMING_SIZED")),
            "cycles_per_input_sample": 1, "cycles_per_output_sample": SPECS[spec].r_total,
            "seconds": time.time() - t0}


if __name__ == "__main__":
    out = Path(sys.argv[1])
    items = [tuple(a.split("=", 2)) for a in sys.argv[2:]]
    rows = []
    with ProcessPoolExecutor(3) as ex:
        for r in ex.map(job, items):
            rows.append(r)
            out.write_text(json.dumps(rows, indent=1, default=float))
            print(r["name"], r["spec"], r["status"], r.get("critical_path_ps"), r.get("fmax_mhz"), r.get("area_um2"), flush=True)
