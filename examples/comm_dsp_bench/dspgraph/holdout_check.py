"""把已有最优设计在留出场景（搜索与 LLM 都未见过）上重新打分。只读已有产物。"""
import json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from . import judge, template as T
from .rtl_judge import evaluate_program

E = Path(__file__).resolve().parent.parent / "experiments_dspgraph"


def job(it):
    name, spec, code = it
    s = evaluate_program(code, spec)
    h = evaluate_program(code, spec, scenarios=judge.HOLDOUT_SCENARIOS)
    return {"name": name, "spec": spec, "area": s.get("area"),
            "search_margin": s["quality"]["snr_margin_db"], "search_passed": s["quality"]["passed"],
            "holdout_margin": h["quality"]["snr_margin_db"], "holdout_passed": h["quality"]["passed"],
            "holdout_ripple_ok": h["quality"]["ripple_db"] <= h["quality"]["ripple_max_db"]}


def main():
    items = []
    for r in json.load(open(E / "p1_template_dev_v1_20261009/results.json"))["rows"]:
        if r["best"]:
            items.append((f"p1_{r['method']}_s{r['seed']}", r["spec"], T.code(r["best"]["params"])))
    for tag, d in (("p2_naive", "p2_oe_dev_verified_v1_20261009"), ("p2_naive", "p2_oe_dev_verified_v1b_20261010"),
                   ("p2_expert", "p2_oe_from_expert_v1_20261010"),
                   ("p2_struct", "p2_oe_from_expert_structonly_v1_20261010")):
        for bp in sorted((E / d).glob("*__verified__s0/best_program.py")):
            items.append((tag, bp.parent.name.split("__")[0], bp.read_text()))
    with ProcessPoolExecutor(6) as ex:
        rows = list(ex.map(job, items))
    (E / "holdout_check_v1_20261010.json").write_text(json.dumps(rows, indent=1, default=float))
    import collections
    agg = collections.defaultdict(list)
    for r in rows:
        agg[r["name"].rsplit("_s", 1)[0] if r["name"].startswith("p1") else r["name"]].append(r)
    for k, v in agg.items():
        m = sorted(x["holdout_margin"] for x in v)
        print(k, "n", len(v), "holdout_pass", sum(x["holdout_passed"] for x in v),
              "median_search_margin", round(sorted(x["search_margin"] for x in v)[len(v) // 2], 2),
              "holdout_margin min/median", round(m[0], 2), round(m[len(m) // 2], 2))


if __name__ == "__main__":
    main()
