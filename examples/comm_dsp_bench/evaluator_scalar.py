"""B3 基线：标量-二值口径（EvolVE / REvolution 共同特征复刻）

与主 evaluator 的差异（对齐竞品口径）：
  1. 正确性为二值门槛：SQNR ≥ CORRECT_THRESHOLD 视为"功能正确"（模拟全测试
     通过），否则 fitness = 失败（不进网格有效格）
  2. 适应度为标量 AT 积：fitness = -area * cycles / ETA（EvolVE 式），单点输出
  3. 无精度/吞吐 Pareto 维度——grid 用框架默认 (complexity, diversity)

复用主 evaluator 的仿真/综合机制（同 testbench、同 golden、同 ASIC 口径）。
"""

import json
import math
import os
import random
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

# 复用主评估器机制（COMMDSP_TASK 同源）
import evaluator as base
from openevolve.evaluation_result import EvaluationResult

# 口径参数
CORRECT_THRESHOLD_DB = 60.0   # 二值正确门槛（模拟"全测试通过"）
ETA = 1e5                     # AT 积归一化（EvolVE 取 1e5）


def _scalar_eval(program_path: str, n_samples: int, sim_timeout: int):
    """跑一次仿真+综合，返回 (correct, at_fitness, detail)"""
    result, err = base._simulate(program_path, n_samples, sim_timeout)
    if result is None:
        return None, None, err
    area, counts, synth_err = base._synthesize(program_path, 180)
    if area is None:
        return None, None, synth_err or "synth fail"
    sqnr = result["sqnr_db"]
    cycles = max(result["cycles"], 1)
    correct = sqnr >= CORRECT_THRESHOLD_DB
    at = float(area) * float(cycles)
    fitness = (-at / ETA) if correct else -1e5   # C_penalty（EvolVE 式）
    return correct, fitness, {
        "sqnr_db": sqnr, "area": area, "cycles": cycles,
        "at": at, "throughput": result["throughput"],
    }


def evaluate_stage1(program_path: str) -> EvaluationResult:
    """L1 冒烟（与主评估器一致，网关用）"""
    task = base._load_task()
    t = task.get("timeouts", {})
    sim_timeout = int(t.get("L1", 5)) + 5
    try:
        result, err = base._simulate(program_path, base.SMOKE_SAMPLES, sim_timeout,
                                     metric_mode="sqnr")
        if result is None:
            return base._error_result("smoke_fail", err)
        combined = min(max(result["sqnr_db"] / 60.0, 0.0), 1.0) * 0.49
        return EvaluationResult(
            metrics={"stage1_passed": 1.0, "combined_score": combined},
            artifacts={"smoke_sqnr_db": f"{result['sqnr_db']:.2f}"},
        )
    except Exception as e:
        import traceback
        return base._error_result("evaluator_exception", traceback.format_exc())


def evaluate_stage2(program_path: str) -> EvaluationResult:
    """L2：二值正确性 + 标量 AT 积（竞品口径）"""
    task = base._load_task()
    t = task.get("timeouts", {})
    sim_timeout = int(t.get("L2_sim", 30)) + 10
    full = int(task["golden"]["stimulus"].get("samples", base.FULL_SAMPLES))
    try:
        correct, fitness, detail = _scalar_eval(program_path, full, sim_timeout)
        if correct is None:
            return base._error_result("full_eval_fail", detail)
        metrics = {
            "correct": 1.0 if correct else 0.0,
            "fitness": round(fitness, 4),
            "combined_score": round(fitness, 4),
            # 记录性指标（不进适应度）——供结果分析对比
            "precision": round(detail["sqnr_db"], 4),
            "area": float(detail["area"]),
            "throughput": round(detail["throughput"], 6),
        }
        return EvaluationResult(
            metrics=metrics,
            artifacts={
                "baseline": "scalar-boolean (EvolVE/REvolution-style)",
                "correct_threshold_db": str(CORRECT_THRESHOLD_DB),
                "at_product": str(detail["at"]),
                "note": "fitness = -AT/eta if SQNR>=threshold else -1e5",
            },
        )
    except Exception as e:
        import traceback
        return base._error_result("evaluator_exception", traceback.format_exc())


def evaluate(program_path: str) -> EvaluationResult:
    r1 = evaluate_stage1(program_path)
    if r1.metrics.get("combined_score", 0.0) <= 0.0:
        return r1
    return evaluate_stage2(program_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: python {sys.argv[0]} <program.v>")
        sys.exit(1)
    res = evaluate(sys.argv[1])
    print("metrics:", json.dumps(res.metrics, indent=2))
    print("artifacts:", json.dumps(res.artifacts, indent=2))
