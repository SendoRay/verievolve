"""Joint structure/precision/microarchitecture adapter for ``cordic_sincos``.

This is deliberately a narrow family adapter.  A quarter-wave lookup design
and an iterative CORDIC are not disguised as the low-level arithmetic nodes of
``joint_design_ir``: their algorithm choice is represented explicitly here and
then lowered through the repository's existing, bit-true checked generators.

Structural admission and numerical acceptance are separate operations.
``validate_candidate`` only checks that a proposal is well formed and safe for
this task.  ``evaluate_exact`` enumerates all 65,536 input angle codes, while
``quality_gate`` applies the frozen threshold afterwards.  Consequently an
approximate proposal can enter evaluation without being required to reproduce
the reference formula node by node.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping

import numpy as np

from certfit import tpl_cordic
from design_gen import gen_cordic, gen_lut_quarter


SCHEMA_VERSION = "verievolve-joint-sincos-v1"
TASK_ID = "cordic_sincos"
FORMULA_ID = "sincos-angle-q15-v1"


class SincosCandidateError(ValueError):
    """A proposal is not a structurally valid sin/cos candidate."""


def _fail(path: str, message: str) -> None:
    raise SincosCandidateError(f"{path}: {message}")


def _exact_fields(value: Any, path: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "expected an object")
    if set(value) != fields:
        _fail(path, f"fields must be exactly {sorted(fields)}")
    return value


def _integer(value: Any, path: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        _fail(path, f"expected an integer in [{low},{high}]")
    return int(value)


def _finite(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "expected a finite number")
    result = float(value)
    if not math.isfinite(result):
        _fail(path, "expected a finite number")
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def candidate_hash(candidate: Mapping[str, Any]) -> str:
    """Hash all implementation semantics while ignoring descriptive metadata."""
    semantic = {key: value for key, value in candidate.items() if key != "metadata"}
    return hashlib.sha256(_canonical(semantic).encode("utf-8")).hexdigest()


def _precision(phase_bits: int) -> dict[str, Any]:
    return {
        "phase_bits": int(phase_bits),
        "output_width": 16,
        "output_frac": 15,
        "rounding": "nearest_ties_up",
        "overflow": "saturate",
    }


def _quality(minimum_sqnr_db: float) -> dict[str, Any]:
    return {
        "metric": "sqnr_db",
        "direction": "max",
        "threshold": float(minimum_sqnr_db),
        "aggregation": "minimum_across_sin_cos",
        "evaluation": "integer-domain exhaustive enumeration of 65536 angle codes",
    }


def lut_candidate(
    table_depth: int,
    interpolation: str,
    *,
    phase_bits: int = 16,
    minimum_sqnr_db: float = 60.0,
    name: str | None = None,
) -> dict[str, Any]:
    """Construct a quarter-wave lookup candidate compatible with the task RTL."""
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "task": {"task_id": TASK_ID, "formula_id": FORMULA_ID},
        "algorithm": {
            "family": "quarter_wave_lut",
            "table_depth": int(table_depth),
            "interpolation": str(interpolation),
        },
        "precision": _precision(phase_bits),
        "microarchitecture": {
            "datapath": "combinational_lookup",
            "pipeline_stages": 1,
            "latency_cycles": 1,
            "initiation_interval": 1,
            "resource_sharing": False,
        },
        "quality_contract": _quality(minimum_sqnr_db),
        "metadata": {"name": name or f"lut_{table_depth}_{interpolation}"},
    }
    validate_candidate(candidate)
    return candidate


def cordic_candidate(
    iterations: int,
    *,
    phase_bits: int = 16,
    minimum_sqnr_db: float = 60.0,
    name: str | None = None,
) -> dict[str, Any]:
    """Construct the existing single-rotator iterative CORDIC realization."""
    iterations = int(iterations)
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "task": {"task_id": TASK_ID, "formula_id": FORMULA_ID},
        "algorithm": {"family": "iterative_cordic", "iterations": iterations},
        "precision": _precision(phase_bits),
        "microarchitecture": {
            "datapath": "iterative_shift_add",
            "pipeline_stages": 1,
            "latency_cycles": iterations + 1,
            "initiation_interval": iterations + 2,
            "resource_sharing": True,
        },
        "quality_contract": _quality(minimum_sqnr_db),
        "metadata": {"name": name or f"cordic_{iterations}"},
    }
    validate_candidate(candidate)
    return candidate


def validate_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Validate representation and bounds, without testing formula equality."""
    obj = _exact_fields(candidate, "$", {
        "schema_version", "task", "algorithm", "precision",
        "microarchitecture", "quality_contract", "metadata",
    })
    if obj["schema_version"] != SCHEMA_VERSION:
        _fail("$.schema_version", f"expected {SCHEMA_VERSION}")
    task = _exact_fields(obj["task"], "$.task", {"task_id", "formula_id"})
    if task != {"task_id": TASK_ID, "formula_id": FORMULA_ID}:
        _fail("$.task", "candidate is not bound to the frozen cordic_sincos contract")

    algorithm = obj["algorithm"]
    if not isinstance(algorithm, Mapping):
        _fail("$.algorithm", "expected an object")
    family = algorithm.get("family")
    if family == "quarter_wave_lut":
        _exact_fields(algorithm, "$.algorithm", {
            "family", "table_depth", "interpolation",
        })
        depth = _integer(algorithm["table_depth"], "$.algorithm.table_depth", 64, 1024)
        if depth not in {64, 128, 256, 512, 1024}:
            _fail("$.algorithm.table_depth", "must be a supported power-of-two table")
        if algorithm["interpolation"] not in {"nearest", "linear", "quad"}:
            _fail("$.algorithm.interpolation", "expected nearest, linear, or quad")
    elif family == "iterative_cordic":
        _exact_fields(algorithm, "$.algorithm", {"family", "iterations"})
        _integer(algorithm["iterations"], "$.algorithm.iterations", 7, 20)
    else:
        _fail("$.algorithm.family", "expected quarter_wave_lut or iterative_cordic")

    precision = _exact_fields(obj["precision"], "$.precision", {
        "phase_bits", "output_width", "output_frac", "rounding", "overflow",
    })
    _integer(precision["phase_bits"], "$.precision.phase_bits", 8, 16)
    if precision["output_width"] != 16 or precision["output_frac"] != 15:
        _fail("$.precision", "external output format must remain signed Q1.15")
    if precision["rounding"] != "nearest_ties_up":
        _fail("$.precision.rounding", "current checked backend implements nearest_ties_up")
    if precision["overflow"] != "saturate":
        _fail("$.precision.overflow", "current checked backend implements saturation")

    micro = _exact_fields(obj["microarchitecture"], "$.microarchitecture", {
        "datapath", "pipeline_stages", "latency_cycles",
        "initiation_interval", "resource_sharing",
    })
    if micro["datapath"] not in {
        "combinational_lookup", "iterative_shift_add", "fully_pipelined_shift_add",
    }:
        _fail("$.microarchitecture.datapath", "unknown datapath style")
    _integer(micro["pipeline_stages"], "$.microarchitecture.pipeline_stages", 1, 64)
    _integer(micro["latency_cycles"], "$.microarchitecture.latency_cycles", 1, 128)
    _integer(micro["initiation_interval"], "$.microarchitecture.initiation_interval", 1, 128)
    if type(micro["resource_sharing"]) is not bool:
        _fail("$.microarchitecture.resource_sharing", "expected a boolean")

    quality = _exact_fields(obj["quality_contract"], "$.quality_contract", {
        "metric", "direction", "threshold", "aggregation", "evaluation",
    })
    if quality["metric"] != "sqnr_db" or quality["direction"] != "max":
        _fail("$.quality_contract", "this adapter gates minimum SQNR")
    _finite(quality["threshold"], "$.quality_contract.threshold")
    if quality["aggregation"] != "minimum_across_sin_cos":
        _fail("$.quality_contract.aggregation", "must aggregate the worse output component")
    if quality["evaluation"] != "integer-domain exhaustive enumeration of 65536 angle codes":
        _fail("$.quality_contract.evaluation", "must use the frozen exhaustive evaluation")
    if not isinstance(obj["metadata"], Mapping):
        _fail("$.metadata", "expected an object")
    try:
        _canonical(obj)
    except (TypeError, ValueError) as exc:
        _fail("$", f"candidate is not canonical JSON: {exc}")
    return {
        "candidate_hash": candidate_hash(obj),
        "algorithm_family": family,
        "phase_bits": int(precision["phase_bits"]),
        "exact_formula_equality_required": False,
    }


def backend_parameters(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Translate only implementations supported by the checked family backend."""
    validate_candidate(candidate)
    algorithm = candidate["algorithm"]
    micro = candidate["microarchitecture"]
    if algorithm["family"] == "quarter_wave_lut":
        expected = {
            "datapath": "combinational_lookup", "pipeline_stages": 1,
            "latency_cycles": 1, "initiation_interval": 1,
            "resource_sharing": False,
        }
        if dict(micro) != expected:
            raise ValueError("sincos backend does not lower this LUT microarchitecture")
        return {
            "algo": "lut", "depth": int(algorithm["table_depth"]),
            "order": algorithm["interpolation"],
        }
    iterations = int(algorithm["iterations"])
    expected = {
        "datapath": "iterative_shift_add", "pipeline_stages": 1,
        "latency_cycles": iterations + 1, "initiation_interval": iterations + 2,
        "resource_sharing": True,
    }
    if dict(micro) != expected:
        raise ValueError("sincos backend does not lower this CORDIC microarchitecture")
    return {"algo": "cordic", "stages": iterations}


def _quantize_phase(z: np.ndarray, phase_bits: int) -> np.ndarray:
    drop = 16 - int(phase_bits)
    unsigned = np.asarray(z, dtype=np.int64) & 0xFFFF
    if drop:
        unsigned &= (0xFFFF << drop) & 0xFFFF
    return np.where(unsigned >= 0x8000, unsigned - 0x10000, unsigned).astype(np.int64)


def evaluate_exact(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic metrics from every possible 16-bit input code."""
    params = backend_parameters(candidate)
    z = np.arange(-(1 << 15), 1 << 15, dtype=np.int64)
    z_impl = _quantize_phase(z, int(candidate["precision"]["phase_bits"]))
    sin_code, cos_code = tpl_cordic.emulate(params, z_impl)
    angle = z.astype(np.float64) * (math.pi / float(1 << 15))
    references = (np.sin(angle) * 32768.0, np.cos(angle) * 32768.0)
    outputs = (sin_code.astype(np.float64), cos_code.astype(np.float64))
    mse = [float(np.mean((got - ref) ** 2)) for got, ref in zip(outputs, references)]
    signal_power = [float(np.mean(ref ** 2)) for ref in references]
    component_sqnr = [
        999.0 if error == 0.0 else 10.0 * math.log10(signal / error)
        for signal, error in zip(signal_power, mse)
    ]
    component_rms = [math.sqrt(error) for error in mse]
    maximum = max(
        float(np.max(np.abs(got - ref))) for got, ref in zip(outputs, references)
    )
    return {
        "sqnr_db": min(component_sqnr),
        "component_sqnr_db": {"sin": component_sqnr[0], "cos": component_sqnr[1]},
        "component_rms_error_lsb": {"sin": component_rms[0], "cos": component_rms[1]},
        "maximum_error_lsb": maximum,
        "enumerated_input_codes": 65536,
        "phase_bits": int(candidate["precision"]["phase_bits"]),
        "algorithm_family": candidate["algorithm"]["family"],
        "candidate_hash": candidate_hash(candidate),
    }


def quality_gate(candidate: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the frozen quality threshold after independent exact evaluation."""
    validate_candidate(candidate)
    if metrics.get("candidate_hash") != candidate_hash(candidate):
        raise ValueError("metrics are not bound to this sincos candidate")
    measured = _finite(metrics.get("sqnr_db"), "metrics.sqnr_db")
    threshold = float(candidate["quality_contract"]["threshold"])
    passed = measured >= threshold
    return {
        "passed": passed,
        "metric": "sqnr_db",
        "measured": measured,
        "threshold": threshold,
        "verified_reason": None if passed else (
            f"sqnr_db {measured:.12g} is below required {threshold:.12g}"
        ),
    }


def lower_rtl(candidate: Mapping[str, Any]) -> str:
    """Lower to the existing ``cordic_sincos`` stream-v1 evaluator interface."""
    params = backend_parameters(candidate)
    source = (
        gen_lut_quarter(params["depth"], params["order"])
        if params["algo"] == "lut" else gen_cordic(params["stages"])
    )
    phase_bits = int(candidate["precision"]["phase_bits"])
    if phase_bits == 16:
        return source

    # Keep the checked generator intact as a core and make the precision
    # decision explicit at its input.  Token replacement changes the core's
    # port and internal uses together; the public wrapper retains the task IO.
    core = re.sub(r"\bmodule\s+top\b", "module joint_sincos_core", source, count=1)
    core = re.sub(r"\bz\b", "z_core", core)
    drop = 16 - phase_bits
    wrapper = f"""
module top (
    input wire clk, input wire rst_n,
    input wire in_valid, output wire in_ready,
    input wire signed [15:0] z,
    output wire out_valid, input wire out_ready,
    output wire signed [15:0] sin_out,
    output wire signed [15:0] cos_out
);
    wire signed [15:0] z_quantized = {{z[15:{drop}], {drop}'b0}};
    joint_sincos_core core (
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready),
        .z_core(z_quantized), .out_valid(out_valid), .out_ready(out_ready),
        .sin_out(sin_out), .cos_out(cos_out)
    );
endmodule
"""
    return core + wrapper


def evaluator_binding(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Describe the real CommDSP evaluator contract consumed by ``lower_rtl``."""
    validate_candidate(candidate)
    return {
        "task": TASK_ID,
        "environment": {"COMMDSP_TASK": TASK_ID},
        "dut_module": "top",
        "protocol": "stream_v1",
        "input_ports": [{"name": "z", "width": 16, "signed": True}],
        "output_ports": [
            {"name": "sin_out", "width": 16, "signed": True},
            {"name": "cos_out", "width": 16, "signed": True},
        ],
        "metric": "sqnr",
    }
