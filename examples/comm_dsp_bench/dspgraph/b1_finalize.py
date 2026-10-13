"""B1（LLM 直接写 Verilog）收尾：取最后检查点种群中搜索场景达标、面积最小的程序，评留出场景与真实面积（快速 ABC）。

python -m dspgraph.b1_finalize RUN_DIR [...]   （在各目录写 best_program.v 与 final_eval.json）
"""
import json
import sys
from pathlib import Path

from . import judge
from .vlog_eval import evaluate_verilog_program

SEED = Path(__file__).parent / "seeds" / "naive_verilog.v"


def finalize(run: Path) -> dict:
    cks = sorted((run / "checkpoints").glob("checkpoint_*"), key=lambda p: int(p.name.split("_")[1]))
    progs = [json.loads(f.read_text()) for f in (cks[-1] / "programs").glob("*.json")]
    spec = run.name.split("__")[0]
    ok = [p for p in progs if p["metrics"].get("passed") == 1.0]
    out = {"spec": spec, "checkpoint": cks[-1].name, "passing_in_population": f"{len(ok)}/{len(progs)}"}
    start = evaluate_verilog_program(SEED.read_text(), spec)
    out["start_real"] = start.get("area")
    if not ok:
        return out | {"best_real": None, "note": "no passing program in final population"}
    best = min(ok, key=lambda p: p["metrics"]["area_log"])
    s = evaluate_verilog_program(best["code"], spec)
    h = evaluate_verilog_program(best["code"], spec, scenarios=judge.HOLDOUT_SCENARIOS, with_area=False)
    (run / "best_program.v").write_text(best["code"])
    return out | {"best_real": s.get("area"), "reduction": 1 - s["area"] / out["start_real"],
                  "search_margin": s["quality"]["snr_margin_db"], "search_passed": s["quality"]["passed"],
                  "holdout_margin": h["quality"]["snr_margin_db"] if h.get("valid") else None,
                  "holdout_passed": h["quality"]["passed"] if h.get("valid") else None,
                  "iteration_found": best.get("iteration_found")}


if __name__ == "__main__":
    for a in sys.argv[1:]:
        r = finalize(Path(a))
        (Path(a) / "final_eval.json").write_text(json.dumps(r, indent=1, default=float))
        print(Path(a).name, r, flush=True)
