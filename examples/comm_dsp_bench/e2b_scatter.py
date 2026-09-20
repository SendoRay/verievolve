#!/usr/bin/env python
"""E2b：证书精度 vs 采样精度全空间扫描（论文图 4.x / 5.x 数据）。

对 cordic（全枚举证书）与 llr（确定性 Sobol 证书）的全部模板配置：
  - 证书精度（确定性，L2）
  - 采样精度（真实 iverilog 65536 样本，L1）
产出散点数据 + 一致性统计（平滑族 vs 重尾族的对照）。
"""
import json
import os
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

from certfit import tpl_cordic, tpl_llr  # noqa: E402

OUT = BENCH / "experiments_e1" / "e2b_scatter.json"


def run(task, tpl, space):
    os.environ["COMMDSP_TASK"] = task
    import evaluator as base
    import importlib
    importlib.reload(base)
    rows = []
    for i, p in enumerate(space):
        ok, msg = tpl.validate(p)
        if not ok:
            continue
        c = tpl.cert_metrics(p)
        vtext = tpl.generate_verilog(p)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "d.v"
            vf.write_text(vtext)
            r, err = base._simulate(str(vf), base.FULL_SAMPLES, 90)
        rows.append({
            "params": p,
            "cert": c["precision"],
            "sampled": round(r["sqnr_db"], 3) if r else None,
        })
        print(f"[{task}] {i+1}/{len(space)}: cert={c['precision']:.2f} "
              f"sampled={rows[-1]['sampled']}")
    return rows


def main():
    out = {}
    cordic_space = []
    for N in [64, 128, 256, 512, 1024]:
        for order in ["nearest", "linear", "quad"]:
            if N == 64 and order == "quad":
                continue
            if order == "nearest" and N not in (64, 128, 256):
                continue
            cordic_space.append({"algo": "lut", "order": order, "depth": N, "stages": 12})
    for st in range(8, 21, 2):
        cordic_space.append({"algo": "cordic", "order": "linear", "depth": 64, "stages": st})
    out["cordic_sincos"] = run("cordic_sincos", tpl_cordic, cordic_space)

    llr_space = [{"metric": m, "corr_entries": 0, "corr_frac": 8, "input_trunc": it}
                 for m in ["l2", "l1"] for it in [2, 4, 6]]
    out["llr_64qam_snr20"] = run("llr_64qam_snr20", tpl_llr, llr_space)

    OUT.write_text(json.dumps(out, indent=2))
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
