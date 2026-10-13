"""PPA 评估（批量）：Yosys+ABC 映射到 Nangate45，OpenSTA 做静态时序与功耗分析。

取代原先的 ABC stime 粗估（见 dspgraph/timing.py，仅保留用于复现旧结果）。

python -m dspgen.timing OUT.json [--clock-ns 2.0] [--fast] NAME=TASK=PATH ...
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .ppa_sta import evaluate_program


def job(args):
    (name, task, path), clock_ns, fast = args
    r = evaluate_program(task, Path(path), period_ns=clock_ns, fast=fast)
    r.update(name=name, task=task, path=path)
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("items", nargs="+")
    ap.add_argument("--clock-ns", type=float, default=2.0)
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    items = [(tuple(s.split("=", 2)), a.clock_ns, a.fast) for s in a.items]
    rows = []
    with ProcessPoolExecutor(4) as ex:
        for r in ex.map(job, items):
            rows.append(r)
            a.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=float))
            print(r["name"], r["task"], r.get("status"), r.get("area_um2"), r.get("fmax_mhz"),
                  (r.get("power_at_clock") or {}).get("total_mw"), flush=True)
