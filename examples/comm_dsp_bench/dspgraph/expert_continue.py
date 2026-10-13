"""对照：从专家最优参数出发，纯参数联合搜索再追加 N 次评价（与 LLM 从专家设计出发的预算对齐）。"""
import json, random, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from . import template as T
from .template_search import Ledger, evolve
from .rx_spec import SPECS


def one(args):
    spec, seed, budget, params = args
    sp = SPECS[spec]
    led = Ledger(sp, budget)
    evolve(led, sp, random.Random(seed), {"structure", "precision", "micro"}, [params])
    b = led.best()
    return {"spec": spec, "seed": seed, "start_area": led.cache[led.key(params)].get("area"),
            "best_area": b["area"] if b else None, "used": led.used}


def main():
    p1, out, budget = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    rows = json.load(open(p1 / "results.json"))["rows"]
    tasks = []
    for spec in sorted({r["spec"] for r in rows}):
        b = min([r for r in rows if r["spec"] == spec and r["best"]], key=lambda r: r["best"]["area"])
        tasks += [(spec, sd, budget, b["best"]["params"]) for sd in (0, 1)]
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(one, tasks))
    out.write_text(json.dumps(res, indent=1, default=float))
    for r in res:
        print(r)


if __name__ == "__main__":
    main()
