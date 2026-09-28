#!/usr/bin/env python3
"""实验 S2：候选子集 Nangate45 综合面积 + 分阶段筛选 vs 全枚举参考（初步）。

口径：仅综合（synth -noabc → dfflibmap → abc → stat），不称物理实现。
子集：6 NCO × 4 FIR × 2 CMUL = 48 设计（FIR 取 f1/f2/f5/f6 覆盖系数字长
16/12/12+饱和/12+trunc）。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import spec, ref_chain, candidates, rtl_gen

OUT = BENCH / "experiments_system" / "s2_synth_subset"
PDK = BENCH / "pdk" / "NangateOpenCellLibrary_typical.lib"
FIR_SUBSET = ("f1_c16", "f2_c12", "f5_c12_acc24", "f6_c12_trunc")


def synth_area(verilog: str, timeout: int = 600) -> tuple:
    """yosys Nangate45 综合 → (area_um2, cell_count, err)。"""
    with tempfile.TemporaryDirectory() as td:
        vp = Path(td) / "top.v"
        vp.write_text(verilog)
        log = Path(td) / "stat.txt"
        # amap-only 面积口径：与完整 abc 默认脚本面积差 <0.1%（实测 27600.7
        # vs 27629.7），单设计 ~150s → ~1s；所有设计同一口径，仅用于相对比较
        script = (
            f"read_verilog {vp}; "
            f"synth -top top -noabc; dffunmap; "
            f"dfflibmap -liberty {PDK}; "
            f"abc -liberty {PDK} -script +amap; "
            f"tee -o {log} stat -liberty {PDK}"
        )
        try:
            p = subprocess.run(["yosys", "-q", "-p", script], cwd=td,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, None, "synth timeout"
        if not log.exists():
            return None, None, (p.stderr or p.stdout)[-400:]
        text = log.read_text()
        m = re.search(r"Chip area for module '\\top':\s*([0-9.]+)", text)
        if not m:
            return None, None, f"no area: {text[-300:]}"
        cells = dict(re.findall(r"\s+(\w+)\s+(\d+)\n", text))
        return float(m.group(1)), cells, ""


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    h = ref_chain.prototype_taps()
    pool = candidates.build_all(h)
    nco_list = pool["nco"]
    fir_list = [f for f in pool["fir"] if f["name"] in FIR_SUBSET]
    cmul_list = pool["cmul"]
    fcw = int(round(0.39e6 / spec.FS_IN * (1 << 32)))

    # S1 质量数据
    s1 = json.load(open(BENCH / "experiments_system" / "s1_local_vs_system" / "results.json"))
    qual = {}   # combo -> {scenario: truth_err_db}
    for r in s1["rows"]:
        qual.setdefault(r["combo"], {})[r["scenario"]] = r["truth_err_db"]
    worst_err = {c: max(v.values()) for c, v in qual.items()}   # 越大越差（dB，负值）

    results = {"chain_version": spec.CHAIN_VERSION, "designs": [], "errors": []}
    n = 0
    for nc in nco_list:
        for fc in fir_list:
            for cm in cmul_list:
                n += 1
                combo = f"{nc['name']}|{fc['name']}|{cm['name']}"
                t_d = time.time()
                verilog = rtl_gen.gen_ddc_verilog(nc, fc, cm, fcw=fcw)
                area, cells, err = synth_area(verilog)
                dt = time.time() - t_d
                if err:
                    results["errors"].append({"combo": combo, "err": err})
                    print(f"[{n}/48] {combo}: FAIL {err[:80]}")
                    continue
                results["designs"].append({
                    "combo": combo, "nco": nc["name"], "fir": fc["name"],
                    "cmul": cm["name"], "area_um2": area,
                    "worst_truth_err_db": worst_err.get(combo),
                    "synth_s": round(dt, 1),
                })
                print(f"[{n}/48] {combo}: area={area:.0f} um2 "
                      f"worst_err={worst_err.get(combo):.2f} dB ({dt:.0f}s)")

    with open(OUT / "results.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print(f"[out] results.json（{time.time()-t0:.0f}s, {len(results['designs'])} 设计）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
