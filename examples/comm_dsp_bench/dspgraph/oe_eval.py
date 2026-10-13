"""OpenEvolve 评价入口：把 build 程序交给 dspgraph 编译与裁判，返回分数与反馈。

环境变量：DSPG_SPEC（规格名）、DSPG_MODE（scalar|metrics|verified 反馈档位）。
combined_score：不合法 0；合法未达标 ∈ (0,1)（越接近达标越高）；达标 ≥ 2，面积越小越高。
"""

import json
import math
import os
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent.parent))

from dspgraph import rtl_judge  # noqa: E402
from dspgraph.llm_prog import feedback  # noqa: E402
from openevolve.evaluation_result import EvaluationResult  # noqa: E402

NAIVE_AREA = {}


def _naive(spec):
    if spec not in NAIVE_AREA:
        r = rtl_judge.evaluate_program((BENCH / "dspgraph/seeds/naive.py").read_text(), spec)
        NAIVE_AREA[spec] = r["area"]
    return NAIVE_AREA[spec]


import re


def _strip_params(code):
    code = re.sub(r"# 专家模板实例：.*\n", "", code)
    code = re.sub(r"P_ = \{.*?\}\n", "", code)
    return re.sub(r"\s+", "", code)


def _count_inner(n):
    p = os.environ.get("DSPG_INNER_LOG")
    if p:
        with open(p, "a") as f:
            f.write(f"{n}\n")


def evaluate(program_path):
    spec = os.environ["DSPG_SPEC"]
    mode = os.environ.get("DSPG_MODE", "verified")
    rtl_judge.HARNESS.update(probes=(mode == "verified"))
    code = Path(program_path).read_text()
    seed = os.environ.get("DSPG_STRUCT_ONLY_SEED")
    if seed and _strip_params(code) == _strip_params(Path(seed).read_text()):
        # harness 强制：只改参数的候选不被接受（参数已由搜索调到最优）
        fb = json.dumps({"合法": False, "错误": "本轮只接受结构或算法层面的改动；只修改参数字典 P_ 的方案不被接受"},
                        ensure_ascii=False)
        return EvaluationResult(metrics={"combined_score": 0.0, "passed": 0.0, "area_log": 7.0,
                                         "snr_margin": -100.0}, artifacts={"feedback": fb})
    r = rtl_judge.evaluate_program(code, spec, diagnose=(mode == "verified"))
    fb = json.dumps(feedback(r, mode), ensure_ascii=False)
    if not r.get("valid"):
        return EvaluationResult(metrics={"combined_score": 0.0, "passed": 0.0, "area_log": 7.0,
                                         "snr_margin": -100.0}, artifacts={"feedback": fb})
    inner = int(os.environ.get("DSPG_INNER_TUNE", "0"))      # 两层搜索：内层确定性位宽/复用调优的评价预算
    if inner and r.get("valid") and r["quality"]["passed"] and \
            r["quality"]["snr_margin_db"] >= float(os.environ.get("DSPG_MARGIN_DB", "0")):
        from dspgraph import tune
        tune.DICT_KEYS = tuple(k for k in os.environ.get("DSPG_TUNE_KEYS", "").split(",") if k)
        t = tune.tune(code, spec, inner, float(os.environ.get("DSPG_MARGIN_DB", "0")))
        if t.get("status") == "ok":
            _count_inner(t["evals_used"] + 1)
            if t["accepted"]:
                r = dict(t["final"], notes=[f"内层调优：{t['accepted']} 处位宽/复用改动，面积 {t['start_area']:.0f} → {t['area']:.0f}"])
                fb = json.dumps(feedback(r, mode) | {"说明": "面积为确定性位宽/复用调优之后的值；你只需关注结构"},
                                ensure_ascii=False)
    q = r["quality"]
    area = r["area"]
    need = float(os.environ.get("DSPG_MARGIN_DB", "0"))     # 安全裕量变体：搜索裕量需 ≥ need
    ok = q["passed"] and q["snr_margin_db"] >= need
    if ok:
        score = 2.0 + math.log10(_naive(spec) / area)
    else:
        v = max(0.0, -q["snr_margin_db"]) + 3 * max(0.0, q["ripple_db"] - q["ripple_max_db"]) / q["ripple_max_db"]
        score = 1.0 / (1.0 + v)
    if q["passed"] and not ok:
        score = 1.0 / (1.0 + (need - q["snr_margin_db"]))
    return EvaluationResult(metrics={"combined_score": score, "passed": float(ok),
                                     "area_log": math.log10(area), "snr_margin": q["snr_margin_db"]},
                            artifacts={"feedback": fb})
