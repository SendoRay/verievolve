"""最终评估（裁判 v2）：搜索裕量、留出裕量、校准代理面积、真实综合面积（快速 ABC）、RTL 对拍。

python -m dspgraph.final_eval OUT.json NAME=SPEC=PATH [NAME=SPEC=PATH ...]
PATH 指向 build 程序文件。
"""
import json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from . import judge, hw
from .rtl_judge import evaluate_program, rtl_crosscheck, run_program


def job(it):
    name, spec, path = it
    code = Path(path).read_text()
    t0 = time.time()
    s = evaluate_program(code, spec)
    if not s.get("valid"):
        return {"name": name, "spec": spec, "path": path, "valid": False, "error": s.get("error")}
    h = evaluate_program(code, spec, scenarios=judge.HOLDOUT_SCENARIOS)
    if not h.get("valid"):      # 例如留出场景评价超时：记为未判定
        h = {"quality": {"passed": None, "snr_margin_db": None, "ripple_db": None, "scenarios": []}, "error": h.get("error")}
    n_x = int(os.environ.get("DSPG_XCHECK_N", "4000"))
    try:
        x = rtl_crosscheck(code, spec, 0, n_in=n_x)
    except Exception as e:      # 仿真超时等工具问题记为未判定，不当成设计失败
        x = {"passed": None, "error": repr(e)[:300]}
    v = run_program(code, spec, [0], want_verilog=True)["verilog"]
    syn = hw.synth_area(v, "top", timeout=3600, fast=True)
    return {"name": name, "spec": spec, "path": path, "valid": True,
            "proxy_area_um2": s["area"], "area_per_scope": s["area_per_scope"],
            "search_passed": s["quality"]["passed"], "search_margin_db": s["quality"]["snr_margin_db"],
            "search_ripple_db": s["quality"]["ripple_db"],
            "holdout_passed": h["quality"]["passed"], "holdout_margin_db": h["quality"]["snr_margin_db"],
            "holdout_ripple_db": h["quality"]["ripple_db"],
            "holdout_scenarios": [(r["scenario"], r["snr_db"], r["snr_min_db"]) for r in h["quality"]["scenarios"]],
            "holdout_error": h.get("error"),
            "rtl_crosscheck": x, "synth_fast_abc": syn, "judge_version": judge.JUDGE_VERSION,
            "seconds": time.time() - t0}


def main():
    out = Path(sys.argv[1])
    items = [tuple(a.split("=", 2)) for a in sys.argv[2:]]
    with ProcessPoolExecutor(4) as ex:
        rows = []
        for r in ex.map(job, items):
            rows.append(r)
            out.write_text(json.dumps(rows, indent=1, default=float))
            print(r["name"], r["spec"], r.get("search_margin_db"), r.get("holdout_margin_db"),
                  r.get("proxy_area_um2"), (r.get("synth_fast_abc") or {}).get("area_um2"),
                  (r.get("rtl_crosscheck") or {}).get("passed"), flush=True)


if __name__ == "__main__":
    main()
