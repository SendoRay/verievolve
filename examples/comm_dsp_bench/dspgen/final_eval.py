"""通用最终评估：搜索/留出裕量、校准面积、真实面积（快速 ABC）、RTL 对拍。
python -m dspgen.final_eval OUT.json NAME=TASK=PATH ...
"""
import json, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from dspgraph import hw
from .rtl import crosscheck
from .task import evaluate_program, get, run_program


def job(it):
    name, task, path = it
    t = get(task)
    code = Path(path).read_text()
    s = evaluate_program(code, task)
    if not s.get("valid"):
        return {"name": name, "task": task, "valid": False, "error": s.get("error")}
    h = evaluate_program(code, task, scenarios=t.holdout_scenarios)
    try:
        x = crosscheck(code, task, 0, n_in=int(400 * t.rate()) if t.rate() > 1 else 400)
    except Exception as e:
        x = {"passed": None, "error": repr(e)[:300]}
    v = run_program(code, task, [0], want_verilog=True)["verilog"]
    syn = hw.synth_area(v, "top", timeout=3600, fast=True)
    return {"name": name, "task": task, "valid": True, "proxy_area_um2": s["area"],
            "search_passed": s["quality"]["passed"], "search_margin_db": s["quality"]["snr_margin_db"],
            "holdout_passed": h["quality"]["passed"], "holdout_margin_db": h["quality"]["snr_margin_db"],
            "ripple_db": s["quality"]["ripple_db"], "rtl_crosscheck": x, "synth_fast_abc": syn}


if __name__ == "__main__":
    out = Path(sys.argv[1])
    items = [tuple(a.split("=", 2)) for a in sys.argv[2:]]
    rows = []
    with ProcessPoolExecutor(3) as ex:
        for r in ex.map(job, items):
            rows.append(r)
            out.write_text(json.dumps(rows, indent=1, default=float))
            print(r["name"], r["task"], r.get("search_margin_db"), r.get("holdout_margin_db"), r.get("proxy_area_um2"),
                  (r.get("synth_fast_abc") or {}).get("area_um2"), (r.get("rtl_crosscheck") or {}).get("passed"), flush=True)
