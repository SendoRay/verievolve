"""统一系统收尾：取最后检查点种群中按搜索后指标达标（裕量 ≥ MARGIN）且面积最小的程序，
再执行一次同一内层搜索得到最终设计（可复现），并追溯其祖先是直写起点还是哪个结构生成方案。

python -m dspgen.unified_finalize RUN_DIR [...]   （在各目录写 final_program.py 与 unified_final.json）
"""
import json
import sys
from pathlib import Path

from . import space_tune
from .run_unified import INNER, MARGIN
from .task import evaluate_program


def _root(progs, p):
    by = {q["id"]: q for q in progs}
    n = 0
    while p.get("parent_id") in by:
        p, n = by[p["parent_id"]], n + 1
    return p, n


def finalize(run: Path) -> dict:
    task = run.name.split("__")[0]
    cks = sorted((run / "checkpoints").glob("checkpoint_*"), key=lambda p: int(p.name.split("_")[1]))
    progs = [json.loads(f.read_text()) for f in (cks[-1] / "programs").glob("*.json")]
    best_file = run / "best" / "best_program_info.json"
    if best_file.exists():           # 最后一次检查点之后找到的最优程序也纳入
        info = json.loads(best_file.read_text())
        if info["id"] not in {p["id"] for p in progs}:
            progs.append(info | {"code": (run / "best" / "best_program.py").read_text(),
                                 "iteration_found": info.get("iteration")})
    ok = [p for p in progs if p["metrics"].get("passed") == 1.0 and p["metrics"].get("snr_margin", -1) >= MARGIN]
    seeds = json.loads((run / "seed_codes.json").read_text())
    out = {"task": task, "checkpoint": cks[-1].name, "passing_in_population": f"{len(ok)}/{len(progs)}"}
    if not ok:
        return out | {"note": "no passing program"}
    best = min(ok, key=lambda p: p["metrics"]["area_log"])
    hist = {}                        # 祖先可能已被淘汰出最后的种群：用全部检查点追溯
    for ck in cks:
        for f in (ck / "programs").glob("*.json"):
            q = json.loads(f.read_text())
            hist[q["id"]] = q
    hist.update({q["id"]: q for q in progs})
    root, depth = _root(list(hist.values()), best)
    body = root["code"].replace("# EVOLVE-BLOCK-START\n", "").replace("# EVOLVE-BLOCK-END\n", "")
    origin = next((f"structgen_{k}" for k, s in enumerate(seeds) if s.strip() == body.strip()), None)
    if origin is None:
        origin = "direct_start" if root.get("iteration_found", 0) == 0 else f"root_not_in_population(iter {root.get('iteration_found')})"
    code = best["code"].replace("# EVOLVE-BLOCK-START\n", "").replace("# EVOLVE-BLOCK-END\n", "")
    t = space_tune.tune(code, task, INNER, MARGIN, evaluate_program)
    final = t.get("code") if t.get("status", "ok") == "ok" and t.get("code") else code
    (run / "final_program.py").write_text(final)
    r = evaluate_program(final, task)
    return out | {"best_id": best["id"], "best_iteration": best.get("iteration_found"), "origin": origin,
                  "lineage_depth": depth, "tune_mode": t.get("mode"), "has_space": space_tune.read_space(code) is not None,
                  "final_valid": r.get("valid"), "final_area": r.get("area"),
                  "final_margin": (r.get("quality") or {}).get("snr_margin_db"),
                  "final_passed": (r.get("quality") or {}).get("passed")}


if __name__ == "__main__":
    for a in sys.argv[1:]:
        r = finalize(Path(a))
        (Path(a) / "unified_final.json").write_text(json.dumps(r, indent=1, default=float))
        print(Path(a).name, r, flush=True)
