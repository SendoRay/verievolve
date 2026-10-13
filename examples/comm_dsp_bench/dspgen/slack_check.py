"""内层预算是否把裕量用掉：从最终设计出发，用更大的预算继续做同一声明空间搜索，再做位宽/复用旋钮下降，看面积还能降多少。
python -m dspgen.slack_check OUT.json NAME=TASK=PATH ...
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import space_tune
from .run_unified import MARGIN
from .task import evaluate_program
from dspgraph import tune as width_tune


def job(it):
    name, task, path = it
    code = Path(path).read_text()
    r0 = evaluate_program(code, task)
    s = space_tune.tune(code, task, 60, MARGIN, evaluate_program)
    c1 = s.get("code") if s.get("status") == "ok" and s.get("code") else code
    w = width_tune.tune(c1, task, 120, MARGIN, evaluate=lambda c, t: evaluate_program(c, t))
    return {"name": name, "task": task, "start_area": r0.get("area"), "start_margin": r0["quality"]["snr_margin_db"],
            "space60_area": s.get("area"), "space60_evals": s.get("evals_used"), "space60_accepted": s.get("accepted"),
            "space60_margin": (s.get("final") or {}).get("quality", {}).get("snr_margin_db"), "n_space_keys": len((space_tune.read_space(code) or ({},))[0]),
            "width_area": w.get("area"), "width_evals": w.get("evals_used"), "width_accepted": w.get("accepted"),
            "width_margin": w.get("search_margin_db"), "width_status": w.get("status")}


if __name__ == "__main__":
    items = [tuple(a.split("=", 2)) for a in sys.argv[2:]]
    with ProcessPoolExecutor(6) as ex:
        rows = list(ex.map(job, items))
    json.dump(rows, open(sys.argv[1], "w"), indent=1, default=float)
    for r in rows:
        print(r, flush=True)
