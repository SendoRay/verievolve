"""命题 1：联合设计 vs 按角色强分阶段设计（同一积木库、同一评价器、同一预算）。

python -m dspgraph.run_p1 --out <dir> --specs dev --seeds 0-9 --budget 3000 --jobs 8

每个 (规格, seed) 上两种方法各运行一次；最终设计做逐块 Nangate45 映射（分层综合口径）
并对整链 RTL 与逐位模型做协同仿真。统计单位是 (规格, seed) 配对。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

from . import blocks  # noqa: F401
from . import hw, search
from .blocks import area
from .rx_family import build_rx, evaluate, scenario
from .rx_spec import DEV_SPECS, HELDOUT_SPECS, SPECS

PKG = Path(__file__).resolve().parent


def code_identity() -> dict:
    files = sorted(PKG.rglob("*.py"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.relative_to(PKG).as_posix().encode())
        h.update(f.read_bytes())
    cal = area.CAL_PATH
    return {"dspgraph_sha256": h.hexdigest(),
            "calibration_sha256": hashlib.sha256(cal.read_bytes()).hexdigest() if cal.is_file() else None,
            "price": dict(area.C)}


METHODS = {"staged": search.staged_search, "joint": search.joint_search}


def run_one(args):
    spec_name, seed, method, budget = args
    spec = SPECS[spec_name]
    ev = search.Evaluator(spec, build_rx, evaluate, budget=budget)
    t0 = time.time()
    res = METHODS[method](ev, spec, seed=seed * 1000 + 17)
    best = res["best"]
    curve = ev.curve()
    marks = [int(budget * f) for f in (0.1, 0.25, 0.5, 0.75, 1.0)]
    return {
        "spec": spec_name, "seed": seed, "method": method, "budget": budget,
        "evals_used": ev.used, "invalid_proposals": ev.invalid, "seconds": time.time() - t0,
        "found": best is not None,
        "proxy_area": best["area"] if best else None,
        "quality": best["quality"] if best else None,
        "plan": best["plan"] if best else None,
        "curve_at": {str(m): (curve[m - 1] if m - 1 < len(curve) and math.isfinite(curve[m - 1])
                              else None) for m in marks},
        "log": res.get("log"),
    }


def hw_one(args):
    spec_name, plan = args
    spec = SPECS[spec_name]
    ch = build_rx(plan, spec)
    area_r = hw.chain_area(ch, timeout=1200)
    sc = scenario(spec)
    n = min(len(sc.x_codes), 48 * spec.r_total + 4096)
    x = sc.x_codes[:n] / float(1 << (spec.input_bits - 1))
    try:
        sim = hw.check_chain(ch, x)
    except Exception as e:  # 仿真工具错误记为未判定，不当作设计失败
        sim = {"status": "tool_error", "error": str(e)[-500:]}
    return {"hash": ch.hash, "synth": area_r, "rtl_cosim": sim}


def parse_seeds(s: str) -> list[int]:
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--specs", default="dev")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--budget", type=int, default=3000)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--no-hw", action="store_true")
    a = ap.parse_args(argv)
    if a.out.exists():
        sys.exit(f"refusing to overwrite {a.out}")
    a.out.mkdir(parents=True)
    specs = ([s.name for s in DEV_SPECS] if a.specs == "dev" else
             [s.name for s in HELDOUT_SPECS] if a.specs == "heldout" else a.specs.split(","))
    seeds = parse_seeds(a.seeds)
    manifest = {"schema": "dspgraph-p1-v1", "question": "joint vs role-staged design",
                "specs": {n: SPECS[n].to_dict() for n in specs}, "seeds": seeds,
                "budget_evals": a.budget, "methods": list(METHODS), "code": code_identity(),
                "area_metric": "sum of per-block Nangate45 mapped area (hierarchical), no STA",
                "started": time.time()}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    tasks = [(s, sd, m, a.budget) for s in specs for sd in seeds for m in METHODS]
    with ProcessPoolExecutor(a.jobs) as ex:
        rows = list(ex.map(run_one, tasks))
    (a.out / "search_rows.json").write_text(json.dumps(rows, indent=1, default=float))
    if not a.no_hw:
        plans = {}
        for r in rows:
            if r["plan"]:
                plans[json.dumps(r["plan"], sort_keys=True)] = (r["spec"], r["plan"])
        keys = list(plans)
        with ProcessPoolExecutor(a.jobs) as ex:
            hws = list(ex.map(hw_one, [plans[k] for k in keys]))
        hwmap = dict(zip(keys, hws))
        for r in rows:
            if r["plan"]:
                h = hwmap[json.dumps(r["plan"], sort_keys=True)]
                r["synth_area"] = h["synth"]["total_um2"]
                r["synth_status"] = h["synth"]["status"]
                r["rtl_cosim"] = h["rtl_cosim"]
                r["synth_per_block"] = {k: v.get("area_um2") for k, v in h["synth"]["per_block"].items()}
    summary = analyze(rows, specs, seeds)
    (a.out / "results.json").write_text(json.dumps({"manifest": manifest, "rows": rows,
                                                    "summary": summary}, indent=1, default=float))
    print(json.dumps(summary, indent=1, default=float))


def analyze(rows, specs, seeds, key="synth_area"):
    by = {(r["spec"], r["seed"], r["method"]): r for r in rows}
    out = {"per_spec": {}, "pairs": []}
    ratios = []
    for s in specs:
        rs = []
        for sd in seeds:
            j, st = by.get((s, sd, "joint")), by.get((s, sd, "staged"))
            if not j or not st:
                continue
            kj = j.get(key) if j.get(key) is not None else None
            ks = st.get(key) if st.get(key) is not None else None
            pair = {"spec": s, "seed": sd, "joint": kj, "staged": ks,
                    "joint_proxy": j["proxy_area"], "staged_proxy": st["proxy_area"]}
            out["pairs"].append(pair)
            if kj and ks:
                rs.append(kj / ks)
        if rs:
            out["per_spec"][s] = {"n": len(rs), "median_ratio_joint_over_staged": float(np.median(rs)),
                                  "min": float(min(rs)), "max": float(max(rs)),
                                  "joint_better_count": int(sum(r < 1 for r in rs))}
            ratios += rs
    if ratios:
        lr = np.log(ratios)
        out["overall"] = {"n_pairs": len(ratios), "geomean_ratio": float(np.exp(lr.mean())),
                          "joint_better_count": int(sum(r < 1 for r in ratios))}
        if len(ratios) >= 6 and np.any(lr != 0):
            out["overall"]["wilcoxon_p_two_sided"] = float(wilcoxon(lr).pvalue)
        # 按规格做配对 bootstrap 的 95% CI（规格内重采样 seed）
        rng = np.random.default_rng(0)
        bs = []
        arr = np.array(lr)
        for _ in range(4000):
            bs.append(np.exp(rng.choice(arr, len(arr)).mean()))
        out["overall"]["geomean_ratio_ci95"] = [float(np.quantile(bs, 0.025)),
                                                float(np.quantile(bs, 0.975))]
    found = {}
    for r in rows:
        found.setdefault(r["method"], [0, 0])
        found[r["method"]][0] += int(r["found"])
        found[r["method"]][1] += 1
    out["found_rate"] = found
    return out


if __name__ == "__main__":
    main()
