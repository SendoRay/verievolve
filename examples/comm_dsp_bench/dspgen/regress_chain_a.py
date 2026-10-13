"""链 A 回归：新框架必须原样复现现有裁判与已有设计的成绩。
断言 1：12 规格 × 5 场景的输入码、上限、门槛逐位相同。
断言 2：直写起点、6 个 M 最优、6 个 R 最优在搜索与留出场景上的 SNR、纹波、面积完全相同。
断言 3：由理想版程序自动生成的直写起点：输出增益固定为 2^3 时与手写 naive.py 的指标逐位一致、面积相对误差 < 1e-9；
        用自动增益规则时达标且面积差 < 5%。
python -m dspgen.regress_chain_a
"""
import json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from dspgraph import judge, rtl_judge
from dspgraph.rx_spec import DEV_SPECS, SPECS
from . import task as TK

B = Path(__file__).resolve().parent.parent
E = B / "experiments_dspgraph"


def a1():
    bad = 0
    for name, sp in SPECS.items():
        t = TK.get(name)
        for i in (0, 1, 10, 11, 12):
            a, b = t.scene(i), judge.scene(sp, i)
            if not (a["ceiling_db"] == b.ceiling_db and a["snr_min_db"] == judge.snr_min(sp, i)
                    and (a["x_codes"] == b.x_codes).all()):
                bad += 1
    return {"checked": len(SPECS) * 5, "mismatches": bad}


def one(it):
    name, spec, path = it
    code = Path(path).read_text()
    diffs = 0
    for scen in (judge.SEARCH_SCENARIOS, judge.HOLDOUT_SCENARIOS):
        old = rtl_judge.evaluate_program(code, spec, scenarios=scen)
        new = TK.evaluate_program(code, spec, scenarios=scen)
        same = (old["area"] == new["area"] and old["quality"]["passed"] == new["quality"]["passed"]
                and all(o["snr_db"] == n["snr_db"] and o["ripple_db"] == n["ripple_db"]
                        for o, n in zip(old["quality"]["scenarios"], new["quality"]["scenarios"])))
        diffs += 0 if same else 1
    return name, spec, diffs


def a2():
    items = []
    m = {"dev_r16_narrow": "p3_oe_feedback_v3_judge2_20261010", "dev_r32_wide": "p3_oe_feedback_v3_judge2_20261010",
         "dev_r64_narrow": "p3_oe_feedback_v3_judge2_20261010", "dev_r16_wide": "p2_oe_naive_v3_judge2_20261010",
         "dev_r32_narrow": "p2_oe_naive_v3_judge2_20261010", "dev_r64_wide": "p2_oe_naive_v3_judge2_20261010"}
    for s in DEV_SPECS:
        items.append(("naive", s.name, B / "dspgraph/seeds/naive.py"))
        items.append(("M", s.name, E / m[s.name] / f"{s.name}__verified__s0/best_program.py"))
        items.append(("R", s.name, E / "p1_template_dev_v2_judge2_20261010" / f"R_best_{s.name}.py"))
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(one, items))
    return {"designs": len(res), "scenario_sets_each": 2, "mismatches": sum(r[2] for r in res),
            "detail": [r for r in res if r[2]]}


def a3_one(name):
    t = TK.get(name)
    naive = (B / "dspgraph/seeds/naive.py").read_text()
    a = TK.evaluate_program(naive, name)
    b = TK.evaluate_program(t.direct_start(3), name)          # 增益固定为 naive.py 的 2^3：应完全等价
    c = TK.evaluate_program(t.direct_start(), name)           # 自动增益规则
    ident = (abs(a["area"] - b["area"]) <= 1e-9 * a["area"]
             and all(x["snr_db"] == y["snr_db"] and x["ripple_db"] == y["ripple_db"]
                     for x, y in zip(a["quality"]["scenarios"], b["quality"]["scenarios"])))
    return {"task": name, "fixed_gain_identical": bool(ident), "auto_passed": c["quality"]["passed"],
            "auto_margin_db": c["quality"]["snr_margin_db"], "naive_margin_db": a["quality"]["snr_margin_db"],
            "auto_area_ratio": c["area"] / a["area"]}


def a3():
    with ProcessPoolExecutor(4) as ex:
        rows = list(ex.map(a3_one, [s.name for s in DEV_SPECS]))
    bad = sum(1 for r in rows if not (r["fixed_gain_identical"] and r["auto_passed"]
                                      and abs(r["auto_area_ratio"] - 1) < 0.05))
    return {"tasks": len(rows), "mismatches": bad, "rows": rows}


if __name__ == "__main__":
    out = {"assertion1": a1(), "assertion2": a2(), "assertion3": a3()}
    (E / "dspgen_regression_chainA.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))
    sys.exit(0 if all(out[k]["mismatches"] == 0 for k in out) else 1)
