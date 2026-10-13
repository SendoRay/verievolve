"""E-H 对照收尾：每个尝试的最优达标程序 → 位宽/复用旋钮下降（预算 60，裕量 ≥ 0.3 dB）→ final_eval。
同时导出“评价次数 → 当前最优达标面积”轨迹。

python -m dspgen.eh_finalize EH_DIR
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from dspgraph import tune as width_tune
from .final_eval import job as final_job
from .task import evaluate_program

MARGIN = 0.3
BUDGET = 60


def finish(it):
    arm, task, variant, path = it
    code = Path(path).read_text()
    w = width_tune.tune(code, task, BUDGET, MARGIN, evaluate=lambda c, t: evaluate_program(c, t))
    final = w["code"] if w.get("status") == "ok" else code
    fp = Path(path).with_name(Path(path).stem + "_tuned.py")
    fp.write_text(final)
    fe = final_job((f"{arm}/{task}/v{variant}", task, str(fp)))
    return {"arm": arm, "task": task, "variant": variant, "best_path": path, "tune_status": w.get("status"),
            "tune_start_area": w.get("start_area"), "tune_area": w.get("area"), "tune_evals": w.get("evals_used"),
            "final": fe}


def _ev(text):
    body = text.split("\n（已用 ")[0]
    try:
        return json.loads(body[body.index("{"):])
    except Exception:
        return None


def curves(eh: Path):
    """由转录重建每个尝试的轨迹（不依赖 results.json 的 best 字段，见协议追加 3）。
    agent：第 n 次工具调用的结果对应文件 v{variant}_t{n}.py；只有 eval 结果计入评价次数。"""
    out = []
    for f in sorted(eh.glob("*/*/*/results.json")):
        arm = f.parts[-4]
        for r in json.loads(f.read_text()):
            v, d = r["variant"], f.parent
            if r.get("mode") == "bare":
                b = r.get("best")
                out.append({"arm": arm, "task": r["task"], "variant": v, "curve": [[1, b and b["area"]]], "best": b,
                            "eval_result": r.get("eval")})
                continue
            msgs = json.loads((d / f"v{v}_transcript.json").read_text())
            best, pts, n_eval, call = None, [], 0, 0
            tools = []
            for m in msgs:
                if m["role"] != "user" or not m["content"].startswith("工具结果"):
                    continue
                call += 1
                ev = _ev(m["content"])
                is_eval = ev is not None and ("passed" in ev or "valid" in ev)
                tools.append("eval" if is_eval else "other")
                if not is_eval:
                    continue
                n_eval += 1
                if ev.get("passed") and ev.get("snr_margin_db", -1) >= MARGIN and \
                        (best is None or ev["area_um2_est"] < best["area"]):
                    best = {"area": ev["area_um2_est"], "margin": ev["snr_margin_db"], "path": str(d / f"v{v}_t{call}.py"),
                            "call": call}
                pts.append([n_eval, best and best["area"]])
            out.append({"arm": arm, "task": r["task"], "variant": v, "curve": pts, "best": best,
                        "tool_calls": call, "evals": n_eval, "tools": tools})
    return out


if __name__ == "__main__":
    eh = Path(sys.argv[1])
    cv = curves(eh)
    (eh / "curves.json").write_text(json.dumps(cv, ensure_ascii=False, indent=1))
    items = [(c["arm"], c["task"], c["variant"], c["best"]["path"]) for c in cv if c.get("best")]
    with ProcessPoolExecutor(6) as ex:
        rows = list(ex.map(finish, items))
    (eh / "final.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=float))
    for r in rows:
        f = r["final"]
        print(r["arm"], r["task"], r["variant"], r["tune_start_area"], "->", r["tune_area"],
              f.get("search_margin_db"), f.get("holdout_margin_db"), f.get("holdout_passed"),
              (f.get("synth_fast_abc") or {}).get("area_um2"), flush=True)
