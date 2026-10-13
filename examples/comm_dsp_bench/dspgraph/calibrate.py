"""代价代理校准：随机积木样本 → 逐块真实综合 → 非负最小二乘拟合组件单价。

用法：python -m dspgraph.calibrate --n 160 --jobs 8 --out <dir>
校准集与留出集按样本序号奇偶划分；报告留出集的秩相关与相对误差。
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.optimize import nnls
from scipy.stats import spearmanr

from . import blocks  # noqa: F401
from .blocks import area
from .core import PlanError
from .hw import block_verilog, synth_area
from .rx_family import build_rx
from .rx_spec import DEV_SPECS
from .search import random_plan

KEYS = list(area.PRIOR)


def features(stage) -> np.ndarray:
    saved = dict(area.C)
    out = []
    try:
        for k in KEYS:
            area.C.clear()
            area.C.update({kk: (1.0 if kk == k else 0.0) for kk in KEYS})
            out.append(sum(stage.block.cost(stage.params, stage.ctx, stage.aux).values()))
    finally:
        area.C.clear()
        area.C.update(saved)
    return np.array(out)


def _job(args):
    v, mod = args
    return synth_area(v, mod, timeout=900)


def sample(n: int, seed: int):
    rng = random.Random(seed)
    rows, seen = [], set()
    while len(rows) < n:
        spec = rng.choice(DEV_SPECS)
        try:
            ch = build_rx(random_plan(spec, rng), spec)
        except PlanError:
            continue
        for i, st in enumerate(ch.stages):
            # 限制极大 NCO 表，避免校准被少数超大 ROM 主导
            if st.block.type == "nco_mixer" and st.params["phase_bits"] > 14:
                continue
            mod, v = block_verilog(ch, i, f"cal{len(rows)}")
            key = (st.block.type, json.dumps(st.params, sort_keys=True), st.ctx["width_in"],
                   st.ctx["rate_in"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({"type": st.block.type, "params": st.params, "rate_in": st.ctx["rate_in"],
                         "width_in": st.ctx["width_in"], "spec": spec.name,
                         "x": features(st).tolist(), "verilog": v, "module": mod})
            if len(rows) >= n:
                break
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=160)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rows = sample(a.n, a.seed)
    with ProcessPoolExecutor(a.jobs) as ex:
        res = list(ex.map(_job, [(r["verilog"], r["module"]) for r in rows]))
    for r, s in zip(rows, res):
        r["synth"] = s
        del r["verilog"]
    ok = [r for r in rows if r["synth"].get("status") == "ok"]
    train = [r for k, r in enumerate(ok) if k % 2 == 0]
    test = [r for k, r in enumerate(ok) if k % 2 == 1]
    X = np.array([r["x"] for r in train])
    y = np.array([r["synth"]["area_um2"] for r in train])
    w = 1.0 / np.maximum(y, 1.0)          # 相对误差加权
    coef, _ = nnls(X * w[:, None], y * w)
    cal = {k: float(v) for k, v in zip(KEYS, coef)}

    def report(rs, c):
        Xt = np.array([r["x"] for r in rs])
        yt = np.array([r["synth"]["area_um2"] for r in rs])
        pt = Xt @ np.array([c[k] for k in KEYS])
        return {"n": len(rs), "spearman": float(spearmanr(pt, yt).correlation),
                "median_abs_rel_err": float(np.median(np.abs(pt - yt) / yt)),
                "p90_abs_rel_err": float(np.quantile(np.abs(pt - yt) / yt, 0.9))}
    summary = {
        "n_sampled": len(rows), "n_ok": len(ok),
        "n_failed": [r["synth"].get("status") for r in rows if r["synth"].get("status") != "ok"],
        "coefficients": cal, "prior": area.PRIOR,
        "heldout_calibrated": report(test, cal), "heldout_prior": report(test, area.PRIOR),
        "train_calibrated": report(train, cal), "seconds": time.time() - t0,
    }
    (a.out / "samples.json").write_text(json.dumps(rows, indent=1, default=str))
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1))
    area.CAL_PATH.write_text(json.dumps({"coefficients": cal, "source": str(a.out)}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
