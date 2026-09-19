#!/usr/bin/env python
"""E3：证书引导的等价类导航 vs 目录扫描 vs 随机搜索（确定性，无 LLM）。

核心问题：模板空间中综合（Yosys）是最昂贵的资源。若证书精度能预测"哪些配置
值得综合"，则以证书为代价函数的图导航可以用少量综合调用恢复真实 Pareto 前沿。

策略对比（横轴 = 已用综合调用数，纵轴 = 当前 HV）：
  cert-guided : 按（cert_mean 降序、cert_wc tiebreak）排序，逐个综合
  random      : 随机置换逐个综合（期望曲线，5 次随机种子取均值）
  exhaustive  : 全部综合（上界，等于全空间扫描）

产出：experiments_e1/e3_nav.json
"""
import json
import os
import random
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

from run_experiments import pareto_filter, hypervolume_3d  # noqa: E402
from run_e1 import TASK_NORM  # noqa: E402
from certfit import tpl_cordic, tpl_atan2, tpl_cmul  # noqa: E402

os.environ.setdefault("COMMDSP_TASK", "cordic_sincos")
import evaluator as base  # noqa: E402

CACHE = BENCH / ".certfit_cache" / "e3"
CACHE.mkdir(parents=True, exist_ok=True)


def synth(vtext: str, key: str) -> int:
    """ice40 综合（文件缓存），返回 LUT 数。"""
    mark = CACHE / f"{key}.json"
    if mark.exists():
        return json.loads(mark.read_text())["area"]
    with tempfile.TemporaryDirectory() as td:
        vf = Path(td) / "d.v"
        vf.write_text(vtext)
        area, counts, err = base._run_yosys(td, str(vf), 300)
    if area is None:
        area = 10000
    mark.write_text(json.dumps({"area": area}))
    return area


def cordic_space():
    pts = []
    for N in [64, 128, 256, 512, 1024]:
        for order in ["nearest", "linear", "quad"]:
            if order == "nearest" and N > 1024:
                continue
            p = {"algo": "lut", "order": order, "depth": N, "stages": 12}
            pts.append(p)
    for st in range(8, 21):
        pts.append({"algo": "cordic", "order": "linear", "depth": 64, "stages": st})
    return pts


def atan2_space():
    pts = []
    for D in [64, 128, 256, 512, 1024]:
        for interp in ["nearest", "linear"]:
            for pf in [8, 10, 12, 14, 16]:
                pts.append({"depth": D, "interp": interp, "div_frac": pf})
    return pts


def cmul_space():
    pts = []
    for so in range(0, 11, 2):
        for sd in [0, 2, 4]:
            for st in ["direct", "karatsuba"]:
                pts.append({"operand_trunc": so, "prod_drop": sd,
                            "rounding": "rne", "structure": st})
    return pts


def hv_curve(items, norm):
    """items: [(prec, area, thr)] 按给定顺序逐个加入，返回 HV 序列。"""
    acc, curve = [], []
    for it in items:
        acc.append(it)
        front = pareto_filter(list(acc))
        curve.append(hypervolume_3d(front, norm))
    return curve


def main():
    tasks = [
        ("cordic_sincos", cordic_space(), tpl_cordic,
         {"prec": 120.0, "area": 3000.0, "area_asic": 3000.0}),
        ("atan2_w16", atan2_space(), tpl_atan2,
         {"prec": 120.0, "area": 6000.0, "area_asic": 8000.0}),
        ("cmul_w16_free", cmul_space(), tpl_cmul,
         {"prec": 120.0, "area": 8000.0, "area_asic": 10000.0}),
    ]
    out = {}
    for task, space, tpl, norm in tasks:
        os.environ["COMMDSP_TASK"] = task
        import importlib
        importlib.reload(base)
        items = []
        print(f"== {task}: |space| = {len(space)}")
        for i, p in enumerate(space):
            ok, msg = tpl.validate(p)
            if not ok:
                continue
            c = tpl.cert_metrics(p)
            key = f"{task}_{json.dumps(p, sort_keys=True)}"
            vtext = tpl.generate_verilog(p)
            area = synth(vtext, key.replace("/", "_").replace(" ", ""))
            thr = c.get("throughput", 0.908)
            items.append({"params": p, "prec": c["precision"], "wc": c["precision_wc"],
                          "area": area, "thr": thr})
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(space)} done")

        # 真实前沿（全量）
        full = [(x["prec"], x["area"], x["thr"]) for x in items]
        true_front = pareto_filter(list(full))
        hv_true = hypervolume_3d(true_front, norm)

        # cert-guided：按 prec 降序（同 prec 按 wc 降序）
        guided = sorted(items, key=lambda x: (-x["prec"], -x["wc"]))
        curve_g = hv_curve([(x["prec"], x["area"], x["thr"]) for x in guided], norm)

        # random：5 次取均值
        curves_r = []
        rng = random.Random(7)
        for _ in range(5):
            perm = items[:]
            rng.shuffle(perm)
            curves_r.append(hv_curve([(x["prec"], x["area"], x["thr"]) for x in perm], norm))
        n = len(curves_r[0])
        curve_r = [sum(c[k] for c in curves_r) / len(curves_r) for k in range(n)]

        # cert-guided 达到 99% 满额度 HV 所需综合数
        def budget_to(curve, frac):
            tgt = frac * hv_true
            for k, v in enumerate(curve):
                if v >= tgt:
                    return k + 1
            return n
        entry = {
            "space_size": len(items),
            "hv_true": round(hv_true, 4),
            "front_size": len(true_front),
            "budget_guided_99": budget_to(curve_g, 0.99),
            "budget_random_99": round(sum(budget_to(c, 0.99) for c in curves_r) / 5, 1),
            "curve_guided": [round(v, 4) for v in curve_g],
            "curve_random": [round(v, 4) for v in curve_r],
            "true_front": [{"prec": round(p, 2), "area": int(a), "thr": round(t, 3)}
                           for p, a, t in sorted(true_front, key=lambda x: x[1])],
        }
        out[task] = entry
        print(f"  HV_true={entry['hv_true']}  front={entry['front_size']}"
              f"  综合预算(99%): guided={entry['budget_guided_99']}"
              f" random={entry['budget_random_99']} / {len(items)}")
        (BENCH / "experiments_e1" / "e3_nav.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False))
    print("-> e3_nav.json")


if __name__ == "__main__":
    main()
