"""E3.6：从两层搜索的运行目录取最优程序，重新执行同一确定性内层调优，得到最终设计。
python -m dspgraph.e36_finalize RUN_DIR [...]   （在各目录写 final_program.py 与 e36_final.json）
"""
import json, sys
from pathlib import Path
from . import tune
from .analyze import oe_run

if __name__ == "__main__":
    for a in sys.argv[1:]:
        d = Path(a)
        spec = d.name.split("__")[0]
        r = oe_run(d)
        if not r or not r["best_code"]:
            print(d.name, "no passing program")
            continue
        tune.DICT_KEYS = ("P", "A", "Wm", "Wc", "Wh", "Ch", "Cf", "sh_h", "sh_f") if "expert" in str(d) else ()
        t = tune.tune(r["best_code"], spec, 5, 0.3)
        code = t["code"] if t.get("status") == "ok" else r["best_code"]
        (d / "final_program.py").write_text(code)
        inner = sum(int(x) for x in (d / "inner_evals.log").read_text().split()) if (d / "inner_evals.log").exists() else 0
        out = {"spec": spec, "llm_iterations": r["iterations"], "inner_evals": inner, "score_area": r["best_area"],
               "final_area": t.get("area"), "final_margin": t.get("search_margin_db"),
               "passing": r["passing"], "population": r["population"], "best_iteration": r["best_iteration"]}
        (d / "e36_final.json").write_text(json.dumps(out, indent=1, default=float))
        print(d.name, out)
