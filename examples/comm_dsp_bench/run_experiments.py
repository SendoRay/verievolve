#!/usr/bin/env python
"""CommDSP-Bench 多 seed 统计实验框架（SPEC §7.4）

用法:
  # 跑 5 seeds x 40 迭代（cordic_sincos 任务）
  python run_experiments.py --task cordic_sincos --iterations 40

  # 只分析已完成的运行
  python run_experiments.py --task cordic_sincos --analyze-only

产出（写入 <output-root>/results.json 并打印）:
  - 每 seed 的最终 Pareto 前沿
  - 每 seed 的 3 维超体积（精确切片算法）
  - HV 均值 ± 标准差（论文主指标口径）
  - 跨 seed 汇聚前沿
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent.parent
PYTHON = sys.executable

# 每任务归一化常数（HV 计算用；精度上限 dB 与面积参考 LUT）
TASK_NORM: Dict[str, Dict[str, float]] = {
    # area = ice40 LUT（当前网格维度）；area_asic = Nangate45 μm²（论文主口径，
    # 2026-09-14 实测基线校准：cmul 8787 / cordic 497 / nco 633 / fir 12732）
    "cmul": {"prec": 120.0, "area": 8000.0, "area_asic": 10000.0},
    "cordic_sincos": {"prec": 120.0, "area": 3000.0, "area_asic": 3000.0},
    "nco": {"prec": 120.0, "area": 3000.0, "area_asic": 3000.0},
    "fir": {"prec": 120.0, "area": 10000.0, "area_asic": 15000.0},
}


# ---------------------------------------------------------------------------
# Pareto 与超体积
# ---------------------------------------------------------------------------

def pareto_filter(pts: List[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
    """最大化 precision/throughput、最小化 area 的非支配过滤"""
    out = []
    for p in pts:
        dominated = False
        for q in pts:
            if q is p:
                continue
            if (q[0] >= p[0] and q[1] <= p[1] and q[2] >= p[2]) and (
                q[0] > p[0] or q[1] < p[1] or q[2] > p[2]
            ):
                dominated = True
                break
        if not dominated:
            out.append(p)
    return out


def _union_rect_area(rects: List[Tuple[float, float]], ref: Tuple[float, float]) -> float:
    """2D 矩形并集面积（矩形 [y, ref_y] × [z, ref_z]，坐标压缩，O(n^2)）"""
    ys = sorted({r[0] for r in rects} | {ref[0]})
    total = 0.0
    for i in range(len(ys) - 1):
        y0, y1 = ys[i], ys[i + 1]
        zs = [r[1] for r in rects if r[0] <= y0]
        if not zs:
            continue
        z_hi = min(min(zs), ref[1])
        if z_hi < ref[1]:
            total += (y1 - y0) * (ref[1] - z_hi)
    return total


def hypervolume_3d(front: List[Tuple[float, float, float]], norm: Dict[str, float]) -> float:
    """精确 3D 超体积（x 轴切片扫描 + 2D 矩形并集）

    目标（全部最小化）：(1 - prec/prec_max, area/area_max, 1 - thr)
    参考点 (1.05, 1.05, 1.05)，归一化后 HV ∈ [0, 1.05^3]
    """
    ref = (1.05, 1.05, 1.05)
    objs = []
    for prec, area, thr in front:
        x = 1.0 - min(max(prec / norm["prec"], 0.0), 1.0)
        y = min(area / norm["area"], 1.05)
        z = 1.0 - min(max(thr, 0.0), 1.0)
        if x < ref[0] and y < ref[1] and z < ref[2]:
            objs.append((x, y, z))
    if not objs:
        return 0.0

    xs = sorted({p[0] for p in objs} | {ref[0]})
    total = 0.0
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        active = [p for p in objs if p[0] <= x0]
        if not active:
            continue
        area2d = _union_rect_area([(p[1], p[2]) for p in active], (ref[1], ref[2]))
        total += (x1 - x0) * area2d
    return total


# ---------------------------------------------------------------------------
# 运行与结果提取
# ---------------------------------------------------------------------------

def run_one(task: str, seed: int, iterations: int, out_dir: Path) -> bool:
    """单个 seed 的进化运行（生成 per-seed config 覆盖 random_seed）"""
    out_dir.mkdir(parents=True, exist_ok=True)
    base_cfg = yaml.safe_load((BENCH_DIR / "config.yaml").read_text())
    base_cfg["random_seed"] = seed
    base_cfg["max_iterations"] = iterations
    cfg_path = out_dir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(base_cfg, sort_keys=False, allow_unicode=True))

    key_file = BENCH_DIR / ".api_key"
    env = os.environ.copy()
    env["COMMDSP_TASK"] = task
    if key_file.exists():
        env["COMMDSP_API_KEY"] = key_file.read_text().strip()

    cmd = [
        PYTHON, str(REPO_ROOT / "openevolve-run.py"),
        str(BENCH_DIR / f"tasks/{task}/initial_program.v"),
        str(BENCH_DIR / "evaluator.py"),
        "--config", str(cfg_path),
        "--output", str(out_dir),
        "--iterations", str(iterations),
    ]
    print(f"[seed {seed}] running: {task} x {iterations} iters -> {out_dir}")
    r = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
    return r.returncode == 0


def load_final_front(out_dir: Path) -> List[Tuple[float, float, float]]:
    """从最终 checkpoint 提取 Pareto 前沿"""
    ckpt_root = out_dir / "checkpoints"
    ckpts = sorted(
        ckpt_root.glob("checkpoint_*"), key=lambda p: int(p.name.split("_")[1])
    )
    if not ckpts:
        return []
    last = ckpts[-1]
    pts = []
    for pf in (last / "programs").glob("*.json"):
        d = json.loads(pf.read_text())
        m = d.get("metrics", {})
        if m.get("combined_score", 0) > 0 and "precision" in m:
            pts.append((float(m["precision"]), float(m["area"]), float(m["throughput"])))
    return pareto_filter(pts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="cordic_sincos",
                    choices=list(TASK_NORM.keys()))
    ap.add_argument("--seeds", default="0,1,2,3,4",
                    help="逗号分隔的 seed 列表（默认 0-4，共 5 seeds）")
    ap.add_argument("--iterations", type=int, default=40)
    ap.add_argument("--output-root", default=None,
                    help="实验根目录（默认 experiments/<task>_<iters>）")
    ap.add_argument("--analyze-only", action="store_true",
                    help="跳过运行，仅分析已有结果")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    out_root = Path(args.output_root) if args.output_root else (
        BENCH_DIR / "experiments" / f"{args.task}_{args.iterations}"
    )
    norm = TASK_NORM[args.task]

    if not args.analyze_only:
        for seed in seeds:
            run_one(args.task, seed, args.iterations, out_root / f"seed_{seed}")

    # ---- 分析 ----
    results = {"task": args.task, "iterations": args.iterations, "seeds": seeds, "runs": []}
    all_pts = []
    hvs = []
    for seed in seeds:
        sd = out_root / f"seed_{seed}"
        front = load_final_front(sd)
        if not front:
            print(f"[seed {seed}] WARNING: no valid front found in {sd}")
            results["runs"].append({"seed": seed, "front": [], "hv": None})
            continue
        hv = hypervolume_3d(front, norm)
        hvs.append(hv)
        all_pts.extend(front)
        results["runs"].append({
            "seed": seed,
            "hv": round(hv, 6),
            "front": [
                {"precision": round(p, 3), "area": a, "throughput": round(t, 4)}
                for p, a, t in sorted(front, key=lambda x: x[1])
            ],
        })

    agg_front = pareto_filter(all_pts)
    if hvs:
        mean = sum(hvs) / len(hvs)
        std = (sum((h - mean) ** 2 for h in hvs) / len(hvs)) ** 0.5 if len(hvs) > 1 else 0.0
        results["hv_mean"] = round(mean, 6)
        results["hv_std"] = round(std, 6)
    results["aggregate_front"] = [
        {"precision": round(p, 3), "area": a, "throughput": round(t, 4)}
        for p, a, t in sorted(agg_front, key=lambda x: x[1])
    ]

    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # ---- 报告 ----
    print(f"\n{'=' * 64}")
    print(f"CommDSP-Bench 统计报告: {args.task} x {args.iterations} iters x {len(seeds)} seeds")
    print(f"{'=' * 64}")
    for r in results["runs"]:
        if r["hv"] is None:
            print(f"  seed {r['seed']}: FAILED (no front)")
        else:
            print(f"  seed {r['seed']}: HV = {r['hv']:.4f}  ({len(r['front'])} front points)")
    if hvs:
        print(f"\n  Hypervolume: {results['hv_mean']:.4f} ± {results['hv_std']:.4f}")
    print(f"\n  跨 seed 汇聚前沿 ({len(agg_front)} 点):")
    print(f"  {'precision_dB':>12} {'area_LUT':>9} {'throughput':>10}")
    for p, a, t in sorted(agg_front, key=lambda x: x[1]):
        print(f"  {p:12.1f} {a:9.0f} {t:10.3f}")
    print(f"\n  results: {out_root / 'results.json'}")


if __name__ == "__main__":
    main()
