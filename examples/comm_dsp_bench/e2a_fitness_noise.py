#!/usr/bin/env python
"""E2a 适应度噪声证据：同一设计在 fresh-seed 采样评估下的分数分布。

对 cordic_sincos 的 4 个已知设计各做 K=10 次 L2 全量评估（每次 fresh seed），
报告每设计的 SQNR 均值±标准差，以及相邻设计间的"秩翻转"次数
（一次评估中 A>B、另一次 B>A）——这是 Arm S 适应度随机性的直接度量，
也是证书适应度（确定性）的动机证据。
"""
import json
import os
import statistics
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
os.environ.setdefault("COMMDSP_TASK", "cordic_sincos")

import evaluator as base  # noqa: E402

DESIGNS = [
    ("nearest64", BENCH / ".designs" / "qw_lut_nearest_N64.v"),
    ("linear256", BENCH / ".designs" / "qw_lut_linear_N256.v"),
    ("quad256", BENCH / ".designs" / "qw_lut_quad_N256.v"),
    ("cordic14", BENCH / ".designs" / "cordic_14.v"),
]
K = 10


def main():
    results = {}
    for name, path in DESIGNS:
        if not path.exists():
            print(f"skip {name} (missing)")
            continue
        scores = []
        for k in range(K):
            r, err = base._simulate(str(path), base.FULL_SAMPLES, 120)
            scores.append(r["sqnr_db"] if r else None)
        good = [s for s in scores if s is not None]
        results[name] = {
            "scores": [round(s, 3) for s in good],
            "mean": round(statistics.mean(good), 3),
            "stdev": round(statistics.stdev(good), 4) if len(good) > 1 else 0.0,
            "range": round(max(good) - min(good), 3),
        }
        print(f"{name}: mean={results[name]['mean']:.2f} "
              f"std={results[name]['stdev']:.3f} range={results[name]['range']:.2f} dB")

    # 秩翻转：相邻精度设计（linear256 vs quad256）
    if "linear256" in results and "quad256" in results:
        a, b = results["linear256"]["scores"], results["quad256"]["scores"]
        n = min(len(a), len(b))
        flips = sum(1 for i in range(n) if (a[i] > b[i]) != (a[0] > b[0]))
        results["rank_flips_linear_vs_quad"] = flips
        print(f"rank flips (linear vs quad, K={n}): {flips}")

    out = BENCH / "experiments_e1" / "fitness_noise.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
