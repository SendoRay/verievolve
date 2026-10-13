"""用真实综合（快速 ABC，Nangate45）校准 sdf 代理面积的资源单价。

样本：随机专家模板参数、直写起点的若干变体、已有 LLM 最优程序。奇偶划分训练/留出。
python -m dspgraph.calibrate_sdf OUT_DIR
"""
import json, random, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from scipy.optimize import nnls
from scipy.stats import spearmanr
from . import hw, template as T
from .blocks import area
from .rtl_judge import run_program
from .rx_spec import DEV_SPECS

KEYS = list(area.PRIOR)
E = Path(__file__).resolve().parent.parent / "experiments_dspgraph"


def job(it):
    name, spec, code = it
    r = run_program(code, spec, [0], want_verilog=True)
    if not r.get("ok"):
        return {"name": name, "spec": spec, "status": "build_error"}
    syn = hw.synth_area(r["verilog"], "top", timeout=1500, fast=True)
    return {"name": name, "spec": spec, "status": syn.get("status"), "area_um2": syn.get("area_um2"),
            "units": r["area"]["units"], "proxy_old": r["area"]["total"]}


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True)
    rng = random.Random(20261010)
    items = []
    for k in range(54):
        sp = DEV_SPECS[k % 6]
        p = T.random_params(sp, rng)
        p["fir_taps"] = min(p["fir_taps"], 63)
        items.append((f"tmpl{k}", sp.name, T.code(p)))
    naive = (Path(__file__).parent / "seeds/naive.py").read_text()
    for k, (lo, n, w) in enumerate(((22, 1024, 14), (20, 4096, 16), (24, 256, 12), (18, 16384, 18))):
        v = naive.replace("g.bits(ph, 31, 16)", f"g.bits(ph, 31, {lo})").replace("65536", str(n)) \
                 .replace("], 20, 18)", f"], {w}, {w - 2})").replace("kaiserord(100.0", "kaiserord(60.0")
        items.append((f"naive_var{k}", "dev_r16_narrow", v))
    for d in ("p2_oe_dev_verified_v1_20261009", "p2_oe_dev_verified_v1b_20261010",
              "p2_oe_from_expert_structonly_v1_20261010"):
        for bp in sorted((E / d).glob("*__verified__s0/best_program.py")):
            if "r32_wide" in str(bp) and "structonly" not in d:
                continue      # 全速率长 FIR，综合过慢
            items.append((f"llm_{d[:14]}", bp.parent.name.split("__")[0], bp.read_text()))
    with ProcessPoolExecutor(6) as ex:
        rows = list(ex.map(job, items))
    ok = [r for r in rows if r["status"] == "ok"]
    X = np.array([[r["units"].get(k, 0.0) for k in KEYS] for r in ok])
    y = np.array([r["area_um2"] for r in ok])
    tr, te = np.arange(len(ok)) % 2 == 0, np.arange(len(ok)) % 2 == 1
    w = 1.0 / y[tr]
    coef, _ = nnls(X[tr] * w[:, None], y[tr] * w)

    def rep(c, m):
        p = X[m] @ c
        return {"n": int(m.sum()), "spearman": float(spearmanr(p, y[m]).correlation),
                "median_abs_rel_err": float(np.median(np.abs(p - y[m]) / y[m])),
                "p90_abs_rel_err": float(np.quantile(np.abs(p - y[m]) / y[m], 0.9))}
    prior = np.array([area.PRIOR[k] for k in KEYS])
    summ = {"n_ok": len(ok), "n_total": len(rows), "coefficients": dict(zip(KEYS, map(float, coef))),
            "prior": area.PRIOR, "heldout_calibrated": rep(coef, te), "heldout_prior": rep(prior, te),
            "train_calibrated": rep(coef, tr), "synthesis": "Nangate45, fast ABC script"}
    (out / "samples.json").write_text(json.dumps(rows, indent=1, default=float))
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
