#!/usr/bin/env python
"""E5 消融评估器：模板空间 + 采样适应度（Arm C-sampled）。

与 cert_evaluator.py 的唯一差异：precision 来自真实采样仿真（与 Arm S 同口径），
而非证书模型。与 Arm C 对比 → 隔离"适应度函数"因子；与 Arm S 对比 → 隔离
"搜索空间"因子。thr 同样取结构解析值（与 Arm C 一致，保证可比）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(_BENCH))

from openevolve.evaluation_result import EvaluationResult  # noqa: E402

import evaluator as base  # noqa: E402
import cert_evaluator as ce  # noqa: E402  复用 params 加载/物化/缓存


def _sampled_metrics(vfile: Path):
    task = base.TASK_NAME
    t = (base._load_task() or {}).get("timeouts", {})
    r, err = base._simulate(str(vfile), base.FULL_SAMPLES,
                            int(t.get("L2_sim", 30)) + 10)
    if r is None:
        return None, err
    area, counts, aerr = base._run_yosys(str(Path(vfile).parent), str(vfile),
                                         int(t.get("L2_synth", 60)) + 10)
    if area is None:
        return None, aerr or "synth fail"
    with tempfile_dir() as td:
        area_um2, _ = base._run_yosys_asic(td, str(vfile), int(t.get("L2_synth", 60)) + 10)
    return {"sqnr": r["sqnr_db"], "area": area, "counts": counts,
            "area_um2": area_um2, "thr_meas": r["throughput"],
            "cycles": r["cycles"]}, None


class tempfile_dir:
    def __enter__(self):
        import tempfile
        self.td = tempfile.TemporaryDirectory()
        return Path(self.td.name)

    def __exit__(self, *a):
        self.td.cleanup()


def _eval_common(program_path: str, full: bool):
    try:
        params, tpl, cert, vfile, err = ce._cert_result(program_path)
    except Exception as e:
        import traceback
        return ce._error_result("evaluator_exception", traceback.format_exc())
    if cert is None:
        return ce._error_result("cert_fail", err)
    task = base.TASK_NAME
    t = (base._load_task() or {}).get("timeouts", {})
    if not full:
        # 冒烟：256 样本真实仿真
        r, err = base._simulate(str(vfile), base.SMOKE_SAMPLES,
                                int(t.get("L1", 5)) + 5, metric_mode="sqnr")
        if r is None:
            return ce._error_result("smoke_fail", err)
        prec = r["sqnr_db"]
        combined = min(max(prec / 60.0, 0.0), 1.0) * 0.49
        return EvaluationResult(
            metrics={"stage1_passed": 1.0, "combined_score": combined,
                     "precision": 0.0, "area": 10000.0, "throughput": 0.0},
            artifacts={"params": json.dumps(params, ensure_ascii=False),
                       "smoke_sqnr_db": f"{prec:.2f}"})
    # 全量
    m, err = _sampled_metrics(vfile)
    if m is None:
        return ce._error_result("full_eval_fail", err or "")
    combined = base._combined_score(m["sqnr"], m["area"], m["thr_meas"])
    metrics = {"precision": round(m["sqnr"], 4), "area": float(m["area"]),
               "throughput": round(m["thr_meas"], 6), "combined_score": combined}
    if m["area_um2"] is not None:
        metrics["area_um2"] = round(m["area_um2"], 2)
    return EvaluationResult(
        metrics=metrics,
        artifacts={"params": json.dumps(params, ensure_ascii=False),
                   "sqnr_db": f"{m['sqnr']:.2f}",
                   "area_lut": str(m["area"]),
                   "area_um2": f"{m['area_um2']:.2f}" if m["area_um2"] is not None else "n/a",
                   "oracle": "template+sampled"})


def evaluate_stage1(program_path: str) -> EvaluationResult:
    try:
        return _eval_common(program_path, full=False)
    except Exception as e:
        import traceback
        return ce._error_result("evaluator_exception", traceback.format_exc())


def evaluate_stage2(program_path: str) -> EvaluationResult:
    try:
        return _eval_common(program_path, full=True)
    except Exception as e:
        import traceback
        return ce._error_result("evaluator_exception", traceback.format_exc())


def evaluate(program_path: str) -> EvaluationResult:
    r1 = evaluate_stage1(program_path)
    if r1.metrics.get("combined_score", 0.0) <= 0.0:
        return r1
    return evaluate_stage2(program_path)


if __name__ == "__main__":
    res = evaluate(sys.argv[1])
    print(json.dumps(res.metrics, indent=2))
