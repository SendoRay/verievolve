"""对 LLM 最优程序与专家模板最优参数做 RTL 对拍和真实 Nangate45 综合（分层前的整体映射）。"""
import json, sys, glob
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from . import template as T, hw
from .rtl_judge import run_program, rtl_crosscheck
from .rx_spec import SPECS


def job(item):
    name, spec, code = item
    x = rtl_crosscheck(code, spec, 0, n_in=4000)
    r = run_program(code, spec, [0], want_verilog=True)
    syn = hw.synth_area(r["verilog"], "top", timeout=3000) if r.get("ok") else {"status": "build_error"}
    return {"name": name, "spec": spec, "proxy_area": r.get("area", {}).get("total"),
            "rtl_crosscheck": x, "synth": syn}


def main():
    p1, p2, out = map(Path, sys.argv[1:4])
    rows = json.load(open(p1 / "progress.json"))
    items = []
    for d in sorted(p2.glob("*__verified__s0")):
        spec = d.name.split("__")[0]
        bp = d / "best_program.py"
        if bp.exists():
            items.append((f"llm_oe|{spec}", spec, bp.read_text()))
        for m in ("staged", "joint"):
            c = [r for r in rows if r["spec"] == spec and r["method"] == m and r["best"]]
            if c:
                b = min(c, key=lambda r: r["best"]["area"])
                items.append((f"expert_{m}_best|{spec}", spec, T.code(b["best"]["params"])))
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(job, items))
    out.write_text(json.dumps(res, indent=1, default=float))
    for r in res:
        print(r["name"], r["proxy_area"], r["rtl_crosscheck"].get("passed"), r["synth"].get("status"), r["synth"].get("area_um2"))


if __name__ == "__main__":
    main()
