"""OpenEvolve 评价入口（通用）：环境变量 DSPG_TASK 指定 Task；反馈为 metrics 档。"""
import json, math, os, sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent.parent))
from dspgen.task import evaluate_program, get  # noqa: E402
from dspgraph.llm_prog import feedback  # noqa: E402
from openevolve.evaluation_result import EvaluationResult  # noqa: E402

_NAIVE = {}


def _naive(name):
    if name not in _NAIVE:
        _NAIVE[name] = evaluate_program(get(name).direct_start(), name)["area"]
    return _NAIVE[name]


def _count_inner(n):
    p = os.environ.get("DSPG_INNER_LOG")
    if p:
        with open(p, "a") as f:
            f.write(f"{n}\n")


def evaluate(program_path):
    name = os.environ["DSPG_TASK"]
    code = Path(program_path).read_text()
    r = evaluate_program(code, name)
    fb = json.dumps(feedback(r, "metrics"), ensure_ascii=False)
    inner = int(os.environ.get("DSPG_INNER_SPACE", "0"))   # 统一系统：内层在候选声明的参数空间内搜索
    if inner and r.get("valid"):
        from dspgen import space_tune
        t = space_tune.tune(code, name, inner, float(os.environ.get("DSPG_MARGIN_DB", "0")), evaluate_program)
        _count_inner(t.get("evals_used", 0) + 1)
        if t.get("final", {}).get("valid") and space_tune.badness(t["final"], float(os.environ.get("DSPG_MARGIN_DB", "0"))) \
                < space_tune.badness(r, float(os.environ.get("DSPG_MARGIN_DB", "0"))):
            r = t["final"]
            extra = {"说明": "以下指标与面积是在你声明的参数空间内自动搜索后的结果"}
            if t.get("params") is not None:
                extra["搜索得到的参数 P"] = t["params"]
            fb = json.dumps(feedback(r, "metrics") | extra, ensure_ascii=False)
    if not r.get("valid"):
        return EvaluationResult(metrics={"combined_score": 0.0, "passed": 0.0, "area_log": 7.0, "snr_margin": -100.0},
                                artifacts={"feedback": fb})
    q = r["quality"]
    need = float(os.environ.get("DSPG_MARGIN_DB", "0"))     # 安全裕量变体
    if q["passed"] and q["snr_margin_db"] < need:
        return EvaluationResult(metrics={"combined_score": 1.0 / (1.0 + need - q["snr_margin_db"]), "passed": 0.0,
                                         "area_log": math.log10(r["area"]), "snr_margin": q["snr_margin_db"]},
                                artifacts={"feedback": fb})
    if q["passed"]:
        score = 2.0 + math.log10(_naive(name) / r["area"])
    else:
        v = max(0.0, -q["snr_margin_db"]) + 3 * max(0.0, q["ripple_db"] - q["ripple_max_db"]) / q["ripple_max_db"]
        score = 1.0 / (1.0 + v)
    return EvaluationResult(metrics={"combined_score": score, "passed": float(q["passed"]),
                                     "area_log": math.log10(r["area"]), "snr_margin": q["snr_margin_db"]},
                            artifacts={"feedback": fb})
