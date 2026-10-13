"""B1：OpenEvolve 评价入口（LLM 直接写 Verilog）。与 oe_eval.py 同一裁判、同一打分公式；
面积为 Yosys + Nangate45 快速 ABC 的真实映射面积（与本方法的校准代理同口径）。
反馈为 metrics 档：编译/仿真错误、各场景 SNR 与门槛、纹波、面积。"""

import json, math, os, sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent.parent))

from dspgraph import vlog_eval  # noqa: E402
from dspgraph.llm_prog import feedback  # noqa: E402
from openevolve.evaluation_result import EvaluationResult  # noqa: E402

START = BENCH / "dspgraph/seeds/naive_verilog.v"
_NAIVE = {}


def _naive(spec):
    if spec not in _NAIVE:
        cache = BENCH / "dspgraph_cache" / f"b1_naive_area_{spec}.json"
        if cache.is_file():
            _NAIVE[spec] = json.loads(cache.read_text())["area"]
        else:
            r = vlog_eval.evaluate_verilog_program(START.read_text(), spec)
            _NAIVE[spec] = r["area"]
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps({"area": r["area"]}))
    return _NAIVE[spec]


def evaluate(program_path):
    spec = os.environ["DSPG_SPEC"]
    r = vlog_eval.evaluate_verilog_program(Path(program_path).read_text(), spec)
    fb = json.dumps(feedback(r, "metrics"), ensure_ascii=False)
    if not r.get("valid"):
        return EvaluationResult(metrics={"combined_score": 0.0, "passed": 0.0, "area_log": 7.0,
                                         "snr_margin": -100.0}, artifacts={"feedback": fb})
    q = r["quality"]
    if q["passed"]:
        score = 2.0 + math.log10(_naive(spec) / r["area"])
    else:
        v = max(0.0, -q["snr_margin_db"]) + 3 * max(0.0, q["ripple_db"] - q["ripple_max_db"]) / q["ripple_max_db"]
        score = 1.0 / (1.0 + v)
    return EvaluationResult(metrics={"combined_score": score, "passed": float(q["passed"]),
                                     "area_log": math.log10(r["area"]), "snr_margin": q["snr_margin_db"]},
                            artifacts={"feedback": fb})
