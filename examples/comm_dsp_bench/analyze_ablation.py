#!/usr/bin/env python
"""三组消融对比分析：diff-only (A) vs full-rewrite-only (B) vs mixed (C)

从各组最终 checkpoint 提取：Pareto 前沿、精确 3D 超体积、算法族多样性、最优指标。
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import hypervolume_3d, pareto_filter

BENCH = Path(__file__).resolve().parent
NORM = {"prec": 120.0, "area": 3000.0}


def classify_family(code: str) -> str:
    if "alpha_rom" in code:
        m = re.search(r"CORDIC-(\d+)", code)
        return f"CORDIC-{m.group(1)}" if m else "CORDIC"
    if "Tq" in code:
        m = re.search(r"qw_lut_(\w+)_N(\d+)", code)
        if m:
            return f"QW-{m.group(1)}-N{m.group(2)}"
        if "interpq" in code or ("a2" in code and "s2" in code):
            m = re.search(r"case \(k\)\s*\n\s*\d+'d(\d+):", code)
            return "QW-quad"
        return "QW-lin"
    if "frac" in code and "ds" in code:
        return "FW-interp-lin"
    if "sin_lut" in code:
        m = re.search(r"6'd(\d+): sin_lut", code)
        return "NN64" if m else "NN-table"
    return "other"


def load_group(name: str):
    out = BENCH / f"output_abl_{name}"
    ckpts = sorted(out.glob("checkpoints/checkpoint_*"), key=lambda p: int(p.name.split("_")[1]))
    if not ckpts:
        return None
    last = ckpts[-1]
    progs = {}
    for pf in (last / "programs").glob("*.json"):
        d = json.loads(pf.read_text())
        progs[d["id"]] = d
    return last, progs


def main():
    groups = {}
    for g in ["A", "B", "C"]:
        loaded = load_group(g)
        if loaded is None:
            print(f"组 {g}: 无 checkpoint，跳过")
            continue
        last, progs = loaded
        valid = [p for p in progs.values()
                 if p["metrics"].get("combined_score", 0) > 0.1
                 and p["metrics"].get("precision", 0) > 1.0]
        pts = [(p["metrics"]["precision"], p["metrics"]["area"], p["metrics"]["throughput"])
               for p in valid]
        front = pareto_filter(pts)
        hv = hypervolume_3d(front, NORM)
        fams = {}
        for p in valid:
            fams.setdefault(classify_family(p["code"]), set()).add(p["id"])
        best = max(valid, key=lambda p: p["metrics"]["combined_score"]) if valid else None
        groups[g] = {
            "checkpoint": last.name, "n_programs": len(progs), "n_valid": len(valid),
            "front": front, "hv": hv,
            "families": {k: len(v) for k, v in sorted(fams.items())},
            "best": (best["metrics"]["precision"], best["metrics"]["area"],
                     best["metrics"]["throughput"], best["metrics"]["combined_score"]) if best else None,
        }

    labels = {"A": "diff-only", "B": "full-rewrite-only", "C": "mixed-50%"}
    print("=" * 78)
    print("消融实验对比（同起点 checkpoint_40，各 52 迭代，manual 模式）")
    print("=" * 78)
    for g, d in groups.items():
        print(f"\n【{g} 组 · {labels[g]}】 checkpoint={d['checkpoint']}  "
              f"程序 {d['n_programs']}（有效 {d['n_valid']}）")
        print(f"  超体积 HV = {d['hv']:.4f}")
        if d["best"]:
            print(f"  最优: {d['best'][0]:.1f} dB / {d['best'][1]:.0f} LUT / thr={d['best'][2]:.3f} "
                  f"(score {d['best'][3]:.4f})")
        print(f"  前沿 {len(d['front'])} 点:")
        for p in sorted(d["front"], key=lambda x: x[1]):
            print(f"    {p[0]:7.1f} dB  {p[1]:5.0f} LUT  thr={p[2]:.3f}")
        print(f"  算法族 ({len(d['families'])}):")
        for fam, cnt in d["families"].items():
            print(f"    {fam}: {cnt}")

    if len(groups) == 3:
        print("\n" + "=" * 78)
        print("结论摘要")
        print("=" * 78)
        hvs = {g: d["hv"] for g, d in groups.items()}
        fams = {g: len(d["families"]) for g, d in groups.items()}
        bestp = {g: d["best"][0] for g, d in groups.items() if d["best"]}
        print(f"  HV:   A={hvs['A']:.4f}  B={hvs['B']:.4f}  C={hvs['C']:.4f}")
        print(f"  族数: A={fams['A']}  B={fams['B']}  C={fams['C']}")
        if bestp:
            print(f"  最高精度: A={bestp.get('A', 0):.1f} dB  B={bestp.get('B', 0):.1f} dB  "
                  f"C={bestp.get('C', 0):.1f} dB")

    out = BENCH / "ablation_results.json"
    out.write_text(json.dumps(
        {g: {"hv": d["hv"], "families": d["families"],
             "front": [list(p) for p in d["front"]],
             "best": list(d["best"]) if d["best"] else None}
         for g, d in groups.items()}, indent=2))
    print(f"\nresults -> {out}")


if __name__ == "__main__":
    main()
