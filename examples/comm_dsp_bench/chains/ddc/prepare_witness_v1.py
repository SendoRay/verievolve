#!/usr/bin/env python3
"""生成 DDC witness 的正式运行前预检 manifest；本文件不运行 chain truth。

冻结协议要求第一阶段只改变 NCO。这里把 26 点候选池、固定下游实现、
场景版本、模型—RTL 等价报告和 q_cal/epsilon_Q 一次性钉死。正式 runner
必须读取并校验该 manifest，不能回退到历史 ``run_s1.py`` 的 6×8×2 池。
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy


BENCH = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import candidates, metrics, ref_chain, spec


PROTOCOL = "WITNESS_FROZEN_DDC_v1"
FIXED_FIR_NAME = "f1_c16"
FIXED_CMUL_NAME = "c1_exact_rne"
RTL_REPORT = BENCH / "experiments_system" / "nco_rtl_equiv_v1" / "report.json"
OUT = BENCH / "experiments_system" / "ddc_witness_v1" / "preflight_manifest.json"
PDK = BENCH / "pdk" / "NangateOpenCellLibrary_typical.lib"
PROTOCOL_DOC = BENCH.parent.parent / "thesis" / "WITNESS_FROZEN_DDC_v1.md"

# 只冻结脚本文本；正式面积准备阶段把三个占位符替换为绝对临时路径。
# 主口径是 NCO-only，完整链面积只作固定下游 context，不参与主判定。
NCO_AREA_SCRIPT_TEMPLATE = (
    "read_verilog {verilog}; "
    "synth -top nco_map -noabc; dffunmap; "
    "dfflibmap -liberty {liberty}; "
    "abc -liberty {liberty}; "
    "tee -o {log} stat -liberty {liberty}"
)

Q_BUDGET = (10 ** (0.10 / 10.0) - 1.0) / (10 ** (30.0 / 10.0))
LOCAL_TOLERANCES = {
    "sqnr_db": 0.10,
    "wce_lsb": 1.0,
    "last_bit_probability_mass": 2.0 ** -32,
    "sfdr_db": 0.25,
}


def exact_zero_q_calibration() -> dict:
    """exact-representable 零误差例；只校准 evaluator 数值底，不跑候选。"""
    code = np.arange(256, dtype=np.int64) - 128
    y = (code + 1j * code[::-1]) / float(1 << 15)
    result = metrics.aligned_impl_error(y, y.copy(), 64, y_des_ref=y)
    if result["err_aligned"] != 0.0 or result["gain_off_db"] != 0.0:
        raise RuntimeError(f"zero-error q_cal 失败: {result}")
    q_cal = float(result["err_aligned"])
    return {
        "kind": "exact-representable-identical-reference",
        "n_samples": len(y),
        "n_pre_out": 64,
        "q_cal": q_cal,
        "q_budget": Q_BUDGET,
        "epsilon_q": max(q_cal, 0.1 * Q_BUDGET),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _command_output(argv: list[str]) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=10,
                           check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (p.stdout or p.stderr).strip() or f"exit={p.returncode}"


def _code_fingerprints() -> dict:
    rels = (
        "chains/ddc/candidates.py",
        "chains/ddc/fixed_chain.py",
        "chains/ddc/metrics.py",
        "chains/ddc/prepare_witness_v1.py",
        "chains/ddc/ref_chain.py",
        "chains/ddc/rtl_gen.py",
        "chains/ddc/run_witness_v1.py",
        "chains/ddc/scenarios.py",
        "chains/ddc/spec.py",
        "certfit/tpl_cordic.py",
    )
    missing = [rel for rel in rels if not (BENCH / rel).is_file()]
    if missing:
        raise RuntimeError(f"witness 代码指纹文件缺失: {missing}")
    return {rel: _sha256(BENCH / rel) for rel in rels}


def _git_identity() -> dict:
    root = BENCH.parent.parent
    head = _command_output(["git", "-C", str(root), "rev-parse", "HEAD"])
    status = _command_output(["git", "-C", str(root), "status", "--porcelain"])
    return {"head": head, "working_tree_dirty": bool(status)}


def synthesis_contract() -> dict:
    """冻结 decision witness 的主综合口径；这里只登记，不运行综合。"""
    if not PDK.is_file():
        raise RuntimeError(f"缺少 Nangate45 liberty: {PDK}")
    yosys = shutil.which("yosys")
    if yosys is None:
        raise RuntimeError("未找到 yosys，不能冻结面积口径")
    return {
        "primary_scope": "NCO-only",
        "primary_top_module": "nco_map",
        "rtl_generator": "chains/ddc/rtl_gen.py::gen_nco_verilog",
        "context_scope": "fixed full DDC; report only, not primary decision cost",
        "context_top_module": "top",
        "tool": {"executable": yosys, "version": _command_output([yosys, "-V"])},
        "liberty": {
            "path": str(PDK.relative_to(BENCH)),
            "sha256": _sha256(PDK),
            "corner": "Nangate45 typical",
        },
        "script_template": NCO_AREA_SCRIPT_TEMPLATE,
        "script_sha256": _text_sha256(NCO_AREA_SCRIPT_TEMPLATE),
        "metric": "mapped Chip area for module nco_map (um^2)",
        "sdc": None,
        "timing_power_claims_allowed": False,
    }


def _validated_rtl_report() -> dict:
    if not RTL_REPORT.exists():
        raise RuntimeError(f"缺少模型—RTL 等价报告: {RTL_REPORT}")
    report = json.loads(RTL_REPORT.read_text(encoding="utf-8"))
    if report.get("schema_version") != "nco-rtl-equiv-v1":
        raise RuntimeError("模型—RTL 报告 schema 不匹配")
    rows = report.get("results", {})
    if len(rows) != 26 or not all(row.get("pass") for row in rows.values()):
        raise RuntimeError("模型—RTL gate 未达到 26/26 pass")
    return report


def build_preflight_manifest() -> dict:
    """构造但不落盘；供单测和正式入口共同调用。"""
    rtl_report = _validated_rtl_report()
    h_ideal = ref_chain.prototype_taps()
    full = candidates.build_all(h_ideal)
    if full["illegal"]:
        raise RuntimeError(f"历史下游候选含非法项: {full['illegal']}")
    fir = next(x for x in full["fir"] if x["name"] == FIXED_FIR_NAME)
    cmul = next(x for x in full["cmul"] if x["name"] == FIXED_CMUL_NAME)
    ncos = candidates.witness_nco_candidates(include_legacy=True)
    scenario_manifest = spec.export_witness_manifest()
    n_pre_in = spec.N_WARMUP_SYM * int(round(spec.SPS_IN))
    n_pre_out = (n_pre_in - (spec.N_TAPS - 1)) // spec.R

    # ndarray 系数不直接进 JSON；记录整数系数本身与哈希，避免只写候选名。
    hq = np.asarray(fir["hq"], dtype=np.int64)
    fir_json = {k: v for k, v in fir.items() if k != "hq"}
    fir_json["hq"] = hq.tolist()
    fir_json["hq_sha256"] = hashlib.sha256(hq.astype("<i8").tobytes()).hexdigest()

    return {
        "schema_version": "ddc-witness-preflight-v1",
        "protocol": PROTOCOL,
        "status": "preflight-only; no chain truth",
        "candidate_set": {
            "name": "legacy6+frozen-v2-20",
            "count": len(ncos),
            "candidates": ncos,
        },
        "fixed_downstream": {
            "reason": "isolate NCO mechanism with highest-fidelity registered FIR/CMUL",
            "fir": fir_json,
            "cmul": cmul,
            "decimation_rate": spec.R,
            "decimation_phase": spec.DECIM_PHASE,
        },
        "quality_contract": {
            "q": "aligned sample-domain implementation NMSE; desired-only denominator",
            "rho": "grid worst over C_main",
            "calibration": exact_zero_q_calibration(),
            "local_tolerances": LOCAL_TOLERANCES,
            "measurement_segments": {
                "input_preamble_samples": n_pre_in,
                "output_alignment_samples": n_pre_out,
                "alignment_segment": f"P_c=[0,{n_pre_out})",
                "measurement_segment": f"M_c=[{n_pre_out},end)",
                "mapping": "33-tap valid FIR, phase-0 R=2 decimation",
            },
            "sfdr": {
                "n_samples": 1 << 16,
                "zero_pad_factor": 8,
                "window": "four-term Blackman-Harris, sym=True",
                "coefficients": [0.35875, 0.48829, 0.14128, 0.01168],
                "carrier_removal": "known integer-FCW least-squares complex tone",
                "main_aggregation": "minimum dBc over 9 C_main FCWs",
            },
        },
        "synthesis_contract": synthesis_contract(),
        "reproducibility": {
            "protocol_document": {
                "path": str(PROTOCOL_DOC.relative_to(BENCH.parent.parent)),
                "sha256": _sha256(PROTOCOL_DOC),
            },
            "code_sha256": _code_fingerprints(),
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "numpy": np.__version__,
                "scipy": scipy.__version__,
            },
            "git": _git_identity(),
        },
        "scenario_manifest": scenario_manifest,
        "rtl_equivalence": {
            "path": str(RTL_REPORT.relative_to(BENCH)),
            "sha256": _sha256(RTL_REPORT),
            "schema_version": rtl_report["schema_version"],
            "pool_size": rtl_report["pool_size"],
            "all_pass": True,
            "classes": rtl_report["classes"],
        },
        "truth_runner": {
            "allowed": False,
            "remaining_gate": ("run run_witness_v1.py prepare to freeze local metrics, "
                               "pair selection, and NCO-only area before formal truth"),
            "formal_entrypoint": "chains/ddc/run_witness_v1.py truth",
            "forbidden_entrypoint": "chains/ddc/run_s1.py",
        },
    }


def main() -> int:
    manifest = build_preflight_manifest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    eps = manifest["quality_contract"]["calibration"]["epsilon_q"]
    print(f"[preflight] 26 NCO, fixed={FIXED_FIR_NAME}+{FIXED_CMUL_NAME}")
    print(f"[preflight] q_cal=0, epsilon_Q={eps:.12g}; truth 未运行")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
