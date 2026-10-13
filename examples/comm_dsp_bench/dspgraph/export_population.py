"""导出 OpenEvolve 运行最终种群中所有达标程序（校准面积、搜索裕量），并标出面积–裕量非支配集。
python -m dspgraph.export_population OUT.json RUN_DIR [RUN_DIR ...]
"""
import glob, json, sys
from pathlib import Path


def export(d: Path) -> dict:
    cks = sorted(glob.glob(str(d / "checkpoints/checkpoint_*")), key=lambda p: int(p.split("_")[-1]))
    if not cks:
        return {"run": str(d), "error": "no checkpoint"}
    progs = [json.load(open(f)) for f in glob.glob(cks[-1] + "/programs/*.json")]
    seen, rows = set(), []
    for p in progs:
        m = p["metrics"]
        if not m.get("passed") or p["code"] in seen:
            continue
        seen.add(p["code"])
        rows.append({"id": p["id"], "iteration": p.get("iteration_found"), "area": 10 ** m["area_log"],
                     "search_margin_db": m["snr_margin"]})
    for r in rows:      # 非支配：面积更小且裕量更大者不存在
        r["pareto_area_margin"] = not any(o["area"] <= r["area"] and o["search_margin_db"] >= r["search_margin_db"]
                                          and (o["area"] < r["area"] or o["search_margin_db"] > r["search_margin_db"])
                                          for o in rows)
    rows.sort(key=lambda r: r["area"])
    return {"run": str(d), "checkpoint": Path(cks[-1]).name, "population": len(progs), "passing_unique": len(rows),
            "rows": rows}


if __name__ == "__main__":
    out = [export(Path(a)) for a in sys.argv[2:]]
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=float))
    for o in out:
        print(Path(o["run"]).name, o.get("passing_unique"), sum(r["pareto_area_margin"] for r in o.get("rows", [])))
