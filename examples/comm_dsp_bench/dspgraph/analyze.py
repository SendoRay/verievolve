"""汇总三个命题的实验结果（只读已落盘产物）。

python -m dspgraph.analyze --p1 DIR --p2 DIR --p3 DIR --out FILE.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path

import numpy as np

from .rtl_judge import evaluate_program

PKG = Path(__file__).resolve().parent


def oe_run(d: Path) -> dict | None:
    cks = sorted(glob.glob(str(d / "checkpoints/checkpoint_*")), key=lambda p: int(p.split("_")[-1]))
    if not cks:
        return None
    progs = [json.load(open(f)) for f in glob.glob(cks[-1] + "/programs/*.json")]
    passing = [p for p in progs if p["metrics"].get("passed")]
    best = min(passing, key=lambda p: 10 ** p["metrics"]["area_log"]) if passing else None
    # 每次迭代的最优曲线（按 iteration_found）
    traj = sorted(((p.get("iteration_found", 0), 10 ** p["metrics"]["area_log"]) for p in passing))
    return {"iterations": int(cks[-1].split("_")[-1]), "population": len(progs), "passing": len(passing),
            "best_area": 10 ** best["metrics"]["area_log"] if best else None,
            "best_iteration": best.get("iteration_found") if best else None,
            "best_code": best["code"] if best else None, "trajectory": traj}


def naive_area(spec: str, cache={}):
    if spec not in cache:
        cache[spec] = evaluate_program((PKG / "seeds/naive.py").read_text(), spec)["area"]
    return cache[spec]


def area_at(traj, it):
    v = [a for i, a in traj if i <= it]
    return min(v) if v else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--p1", type=Path)
    ap.add_argument("--p2", type=Path)
    ap.add_argument("--p3", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    res = {}
    p1rows = []
    if a.p1:
        f = a.p1 / "results.json"
        p1rows = json.load(open(f))["rows"] if f.exists() else json.load(open(a.p1 / "progress.json"))
        by = {}
        for r in p1rows:
            if r["best"]:
                by.setdefault((r["spec"], r["method"]), []).append(r["best"]["area"])
        res["p1"] = {f"{s}|{m}": {"n": len(v), "median": float(np.median(v)), "min": float(min(v))}
                     for (s, m), v in sorted(by.items())}
        pairs = {}
        for r in p1rows:
            pairs.setdefault((r["spec"], r["seed"]), {})[r["method"]] = r["best"]["area"] if r["best"] else None
        lr = [math.log(v["joint"] / v["staged"]) for v in pairs.values()
              if v.get("joint") and v.get("staged")]
        if lr:
            from scipy.stats import wilcoxon
            res["p1_overall"] = {"n_pairs": len(lr), "geomean_joint_over_staged": float(np.exp(np.mean(lr))),
                                 "joint_better": int(sum(x < 0 for x in lr)),
                                 "wilcoxon_p": float(wilcoxon(lr).pvalue) if len(lr) >= 6 else None}
    if a.p2:
        out = {}
        for d in sorted(a.p2.glob("*__*__s*")):
            spec = d.name.split("__")[0]
            r = oe_run(d)
            if not r:
                continue
            na = naive_area(spec)
            exp = res.get("p1", {})
            out[spec] = {"naive_area": na, "llm_best_area": r["best_area"],
                         "llm_reduction_vs_naive": (1 - r["best_area"] / na) if r["best_area"] else None,
                         "expert_staged_median": exp.get(f"{spec}|staged", {}).get("median"),
                         "expert_joint_median": exp.get(f"{spec}|joint", {}).get("median"),
                         "passing_in_population": f"{r['passing']}/{r['population']}",
                         "iterations": r["iterations"], "best_iteration": r["best_iteration"]}
            if r["best_code"]:
                (d / "best_program.py").write_text(r["best_code"])
        res["p2"] = out
    if a.p3:
        rows = []
        for d in sorted(a.p3.glob("*__*__s*")):
            spec, mode, s = d.name.split("__")
            r = oe_run(d)
            if not r:
                continue
            na = naive_area(spec)
            rows.append({"spec": spec, "mode": mode, "seed": int(s[1:]), "best_area": r["best_area"],
                         "rel": (r["best_area"] / na) if r["best_area"] else 1.0,
                         "rel_at_40": (area_at(r["trajectory"], 40) or na) / na,
                         "rel_at_80": (area_at(r["trajectory"], 80) or na) / na,
                         "passing": r["passing"], "population": r["population"]})
        res["p3_rows"] = rows
        summ = {}
        for m in sorted({r["mode"] for r in rows}):
            v = [r["rel"] for r in rows if r["mode"] == m]
            summ[m] = {"n": len(v), "geomean_area_rel_naive": float(np.exp(np.mean(np.log(v)))),
                       "geomean_at_40": float(np.exp(np.mean(np.log([r["rel_at_40"] for r in rows if r["mode"] == m])))),
                       "geomean_at_80": float(np.exp(np.mean(np.log([r["rel_at_80"] for r in rows if r["mode"] == m])))),
                       "mean_pass_fraction": float(np.mean([r["passing"] / r["population"] for r in rows if r["mode"] == m]))}
        res["p3_summary"] = summ
        key = {(r["spec"], r["seed"], r["mode"]): r["rel"] for r in rows}
        for a_m, b_m in (("verified", "scalar"), ("verified", "metrics"), ("metrics", "scalar")):
            d_ = [math.log(key[(s, sd, a_m)] / key[(s, sd, b_m)]) for (s, sd, m) in key
                  if m == a_m and (s, sd, b_m) in key]
            if d_:
                res.setdefault("p3_pairs", {})[f"{a_m}_vs_{b_m}"] = {
                    "n": len(d_), "geomean_ratio": float(np.exp(np.mean(d_))),
                    "first_better": int(sum(x < 0 for x in d_)), "ties": int(sum(x == 0 for x in d_))}
    a.out.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: v for k, v in res.items() if k != "p3_rows"}, indent=1, default=float))


if __name__ == "__main__":
    main()
