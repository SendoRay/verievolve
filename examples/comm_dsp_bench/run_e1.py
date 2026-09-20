#!/usr/bin/env python
"""E1 实验运行器：采样适应度(Arm S) vs 证书适应度(Arm C)，真 LLM 后端。

用法:
  # 冒烟：cmul 2 迭代
  python run_e1.py --task cmul --arm S --iterations 2 --tag smoke

  # 正式：单任务单臂 40 迭代
  python run_e1.py --task cordic_sincos --arm S --iterations 40 --tag e1

Arm S: 现有 evaluator.py（fresh-seed 蒙特卡罗采样 SQNR）
Arm C: cert_evaluator.py（证书适应度，模板空间）
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent.parent
PYTHON = sys.executable

# HV 归一化常数（精度上限 dB / 面积参考 LUT / ASIC μm² 参考）
TASK_NORM = {
    "cmul": {"prec": 120.0, "area": 8000.0, "area_asic": 10000.0},
    "cmul_w16_free": {"prec": 120.0, "area": 8000.0, "area_asic": 10000.0},
    "cordic_sincos": {"prec": 120.0, "area": 3000.0, "area_asic": 3000.0},
    "atan2_w16": {"prec": 120.0, "area": 6000.0, "area_asic": 8000.0},
    "llr_64qam_snr20": {"prec": 120.0, "area": 15000.0, "area_asic": 15000.0},
    "nco": {"prec": 120.0, "area": 3000.0, "area_asic": 3000.0},
    "nco_p24_t256": {"prec": 120.0, "area": 3000.0, "area_asic": 3000.0},
    "fir": {"prec": 120.0, "area": 10000.0, "area_asic": 15000.0},
    "fir_t16_c25_sym": {"prec": 120.0, "area": 12000.0, "area_asic": 18000.0},
}

ARM_EVALUATOR = {"S": BENCH_DIR / "evaluator.py", "C": BENCH_DIR / "cert_evaluator.py", "CS": BENCH_DIR / "e5_cs_evaluator.py"}


def run_one(task: str, arm: str, seed: int, iterations: int, out_dir: Path,
            base_config: Path) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    base_cfg = yaml.safe_load(base_config.read_text())
    base_cfg["random_seed"] = seed
    base_cfg["max_iterations"] = iterations
    cfg_path = out_dir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(base_cfg, sort_keys=False, allow_unicode=True))

    env = os.environ.copy()
    env["COMMDSP_TASK"] = task
    key_file = BENCH_DIR / ".api_key_deepseek"
    if key_file.exists():
        env["DEEPSEEK_API_KEY"] = key_file.read_text().strip()

    initial = BENCH_DIR / f"tasks/{task}/initial_program.v"
    if arm in ("C", "CS"):
        initial = BENCH_DIR / f"certfit/{task}_template.py"
    cmd = [
        PYTHON, str(REPO_ROOT / "openevolve-run.py"),
        str(initial), str(ARM_EVALUATOR[arm]),
        "--config", str(cfg_path),
        "--output", str(out_dir),
        "--iterations", str(iterations),
    ]
    print(f"[{task} arm{arm} seed{seed}] -> {out_dir}", flush=True)
    r = subprocess.run(cmd, env=env, cwd=str(REPO_ROOT))
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=sorted(TASK_NORM.keys()))
    ap.add_argument("--arm", default="S", choices=["S", "C", "CS"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--iterations", type=int, default=40)
    ap.add_argument("--tag", default="e1")
    ap.add_argument("--config", default=str(BENCH_DIR / "config_e1.yaml"))
    args = ap.parse_args()

    out_dir = BENCH_DIR / "experiments_e1" / f"{args.tag}_{args.task}_arm{args.arm}_seed{args.seed}"
    ok = run_one(args.task, args.arm, args.seed, args.iterations, out_dir, Path(args.config))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
