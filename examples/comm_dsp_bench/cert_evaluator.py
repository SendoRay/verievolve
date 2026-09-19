"""cert_evaluator — Arm C（证书适应度）的 OpenEvolve 评估器。

与 evaluator.py（Arm S）保持同一框架契约：
  evaluate_stage1 / evaluate_stage2 / evaluate -> EvaluationResult

区别：
  1. 被进化程序是 Python 参数文件（PARAMS dict，EVOLVE-BLOCK 内），不是 Verilog；
  2. 精度指标来自 certfit 模板的确定性证书模型（无随机激励、无仿真等待）；
  3. Verilog 由模板从参数生成（逐位对应整数域模型），面积仍走真实 Yosys
     综合（ice40 网格维度 + Nangate45 论文口径），带文件缓存；
  4. 吞吐为模板结构解析值（协议期望吞吐）。

环境变量：
  COMMDSP_TASK              任务名（与 Arm S 相同）
  CERTFIT_SAMPLED_CHECK=1   附加跑一次真实采样评估（模型-vs-RTL 验证实验用）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

_BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(_BENCH))

from openevolve.evaluation_result import EvaluationResult  # noqa: E402

import evaluator as base  # noqa: E402  复用任务加载/Yosys/combined_score

import certfit.common as common  # noqa: E402
import certfit.tpl_cmul as tpl_cmul  # noqa: E402
import certfit.tpl_cordic as tpl_cordic  # noqa: E402
import certfit.tpl_atan2 as tpl_atan2  # noqa: E402
import certfit.tpl_llr as tpl_llr  # noqa: E402

_TEMPLATES = {
    "cmul": tpl_cmul,
    "cordic": tpl_cordic,
    "atan2": tpl_atan2,
    "llr": tpl_llr,
}


def _template():
    name = base.TASK_NAME
    for prefix, mod in _TEMPLATES.items():
        if name.startswith(prefix):
            return mod
    raise ValueError(f"no certfit template for task '{name}'")


def _load_params(program_path: str) -> dict:
    ns: dict = {}
    with open(program_path, "r") as f:
        exec(compile(f.read(), program_path, "exec"), ns)
    p = ns.get("PARAMS")
    if not isinstance(p, dict):
        raise ValueError("program file must define a PARAMS dict")
    # 只接受模板已知键 + 可 JSON 化的值
    tpl = _template()
    merged = dict(tpl.DEFAULTS)
    merged.update({k: v for k, v in p.items() if k in tpl.DEFAULTS})
    return merged


# ---------------------------------------------------------------------------
# 文件缓存：params -> 生成的 Verilog + 综合结果
# ---------------------------------------------------------------------------

def _cache_dir(task: str, params: dict) -> Path:
    import hashlib
    key = hashlib.sha256(
        json.dumps(params, sort_keys=True).encode()
    ).hexdigest()[:16]
    d = _BENCH / ".certfit_cache" / task / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _materialize(task: str, params: dict) -> Path:
    """生成 Verilog（缓存）并返回文件路径。"""
    tpl = _template()
    d = _cache_dir(task, params)
    vfile = d / "design.v"
    if not vfile.exists():
        vfile.write_text(tpl.generate_verilog(params))
    return vfile


def _synth_cached(task: str, params: dict, vfile: Path, timeout: int):
    """ice40 + Nangate45 综合（文件缓存，两 worker 并发安全足够）。"""
    d = _cache_dir(task, params)
    mark = d / "synth.json"
    if mark.exists():
        try:
            j = json.loads(mark.read_text())
            return j.get("area"), j.get("counts", {}), j.get("area_um2"), None
        except json.JSONDecodeError:
            pass
    area, counts, err = base._run_yosys(str(d), str(vfile), timeout)
    with tempfile.TemporaryDirectory(prefix="certfit_asic_") as td:
        area_um2, asic_err = base._run_yosys_asic(td, str(vfile), timeout)
    if area is not None:
        mark.write_text(json.dumps({
            "area": area, "counts": counts, "area_um2": area_um2,
        }))
        return area, counts, area_um2, None
    return None, {}, area_um2, err or asic_err


def _compile_check(vfile: Path) -> Tuple[bool, str]:
    r = subprocess.run(
        ["iverilog", "-g2005", "-o", str(vfile.parent / "design.o"), str(vfile)],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0, (r.stderr or r.stdout)[-800:]


# ---------------------------------------------------------------------------
# 证书评估
# ---------------------------------------------------------------------------

def _cert_result(program_path: str) -> tuple:
    """返回 (params, tpl, cert_metrics_dict, vfile, error)。"""
    tpl = _template()
    try:
        params = _load_params(program_path)
    except Exception as e:
        return None, tpl, None, None, f"params_error: {e}"
    ok, msg = tpl.validate(params)
    if not ok:
        return params, tpl, None, None, f"params_invalid: {msg}"
    task = base.TASK_NAME
    vfile = _materialize(task, params)
    ok, err = _compile_check(vfile)
    if not ok:
        return params, tpl, None, vfile, f"verilog_compile_fail: {err}"
    return params, tpl, tpl.cert_metrics(params), vfile, None


def _error_result(stage: str, msg: str, suggestion: str = "") -> EvaluationResult:
    return EvaluationResult(
        metrics={
            "combined_score": 0.0,
            "precision": 0.0,
            "area": 10000.0,
            "throughput": 0.0,
        },
        artifacts={
            "error_type": stage,
            "error_message": (msg or "")[-1500:],
            "suggestion": suggestion or "Adjust PARAMS to a legal point in the template space.",
        },
    )


def evaluate_stage1(program_path: str) -> EvaluationResult:
    """L1：参数合法性 + 生成的 Verilog 可编译 + 证书冒烟分。"""
    try:
        params, tpl, cert, vfile, err = _cert_result(program_path)
    except Exception as e:
        import traceback
        return _error_result("evaluator_exception", traceback.format_exc(),
                             "Internal certfit error.")
    if cert is None:
        return _error_result("cert_fail", err)
    prec = cert["precision"]
    combined = min(max(prec / 60.0, 0.0), 1.0) * 0.49
    return EvaluationResult(
        metrics={
            "stage1_passed": 1.0,
            "combined_score": combined,
            "precision": 0.0,
            "area": 10000.0,
            "throughput": 0.0,
        },
        artifacts={
            "params": json.dumps(params, ensure_ascii=False),
            "cert_mean_sqnr_db": f"{prec:.2f}",
            "cert_wc_sqnr_db": f"{cert['precision_wc']:.2f}",
        },
    )


def evaluate_stage2(program_path: str) -> EvaluationResult:
    """L2：证书精度 + 真实综合面积 + 结构吞吐。"""
    try:
        params, tpl, cert, vfile, err = _cert_result(program_path)
    except Exception as e:
        import traceback
        return _error_result("evaluator_exception", traceback.format_exc(),
                             "Internal certfit error.")
    if cert is None:
        return _error_result("cert_fail", err)

    task = base.TASK_NAME
    t = (base._load_task() or {}).get("timeouts", {})
    synth_timeout = int(t.get("L2_synth", 60)) + 10
    area, counts, area_um2, synth_err = _synth_cached(task, params, vfile, synth_timeout)
    if area is None:
        return _error_result("synth_fail", synth_err or "yosys failed",
                             "Check generated Verilog synthesizability.")

    prec = cert["precision"]
    thr = cert["throughput"]
    combined = base._combined_score(prec, area, thr)
    metrics = {
        "precision": round(prec, 4),
        "area": float(area),
        "throughput": round(thr, 6),
        "combined_score": combined,
    }
    if area_um2 is not None:
        metrics["area_um2"] = round(area_um2, 2)

    artifacts = {
        "params": json.dumps(params, ensure_ascii=False),
        "cert_mean_sqnr_db": f"{prec:.2f}",
        "cert_wc_sqnr_db": f"{cert['precision_wc']:.2f}",
        "area_lut": str(area),
        "cell_counts": json.dumps(counts),
        "area_um2": f"{area_um2:.2f}" if area_um2 is not None else "n/a",
        "oracle": "certfit-L2-sobol+deterministic",
        "design_v": vfile.read_text()[-4000:],
    }
    if "exact_lemma_sqnr" in cert:
        artifacts["exact_lemma_sqnr_db"] = f"{cert['exact_lemma_sqnr']:.2f}"

    # 模型-vs-RTL 验证钩子（论文校准实验；正常进化关闭）
    if os.environ.get("CERTFIT_SAMPLED_CHECK") == "1":
        result, sim_err = base._simulate(str(vfile),
                                         int(base.FULL_SAMPLES),
                                         int(t.get("L2_sim", 30)) + 10)
        if result is not None:
            artifacts["sampled_sqnr_db"] = f"{result['sqnr_db']:.2f}"
            artifacts["sampled_throughput"] = f"{result['throughput']:.4f}"
        else:
            artifacts["sampled_sqnr_db"] = f"sim_fail: {sim_err[-200:]}"

    return EvaluationResult(metrics=metrics, artifacts=artifacts)


def evaluate(program_path: str) -> EvaluationResult:
    r1 = evaluate_stage1(program_path)
    if r1.metrics.get("combined_score", 0.0) <= 0.0:
        return r1
    return evaluate_stage2(program_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: python {sys.argv[0]} <program_template.py>")
        sys.exit(1)
    res = evaluate(sys.argv[1])
    print("metrics:", json.dumps(res.metrics, indent=2))
    print("artifacts:", json.dumps({k: v for k, v in res.artifacts.items()
                                    if k != "design_v"}, indent=2, ensure_ascii=False))
