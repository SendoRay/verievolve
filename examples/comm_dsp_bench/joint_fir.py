"""FIR-decimator adapter for the task-independent joint design IR.

The stream shell is deliberately frozen: decimate-by-two phase control, one
elastic output register, and the ``stream_v1`` ready/valid contract.  The v2
joint candidate itself contains the accepted-transaction delay line, explicit
constants, arithmetic topology, and a precision decision for every constant.

The existing FIR graph lowerer requires exact formula equality and therefore
cannot lower coefficient approximations.  This adapter reuses its audited
graph validator and frozen shell semantics, and uses the independently
derived IID signed-16 analytic error calculation from the nonuniform-
precision experiment.  Unsupported pipeline schedules and resource sharing
are rejected rather than ignored.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import math
from typing import Any, Mapping

from fir_decim_graph import (
    COEFFICIENTS_Q15,
    graph_sha256,
    validate_graph,
)
from joint_design_ir import (
    SCHEMA_VERSION,
    candidate_hash,
    quality_gate_passes,
    validate_candidate,
)


TASK_ID = "fir_decim_t16_r2_joint"
FORMULA_ID = "fir16-q15-decimate2-v1"
INPUT_MEAN = Fraction(-1, 2)
INPUT_VARIANCE = Fraction(65536**2 - 1, 12)
SIGNAL_POWER = (
    INPUT_VARIANCE * sum(value * value for value in COEFFICIENTS_Q15)
    + INPUT_MEAN * INPUT_MEAN * sum(COEFFICIENTS_Q15) ** 2
)


def _format(width: int, frac: int, *, drop_lsb: int = 0) -> dict[str, Any]:
    return {
        "signed": True,
        "width": int(width),
        "frac": int(frac),
        "rounding": "trunc",
        "overflow": "wrap",
        "drop_lsb": int(drop_lsb),
    }


def _quantize_coefficient(value: int, drop: int) -> int:
    """Clear magnitude low bits, then restore sign (toward-zero truncation)."""
    magnitude = (abs(int(value)) >> int(drop)) << int(drop)
    return magnitude if value >= 0 else -magnitude


def _fraction_record(value: Fraction) -> dict[str, Any]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "float": float(value),
    }


def candidate_from_graph(
    graph: Mapping[str, Any],
    *,
    coefficient_drops: Mapping[str, int],
    pipeline_stages: Mapping[str, int] | None = None,
    resource_groups: Mapping[str, str | None] | None = None,
    minimum_sqnr_db: float = 60.0,
    name: str | None = None,
) -> dict[str, Any]:
    """Combine an exact FIR topology and coefficient precisions.

    ``coefficient_drops`` must name every constant-multiply node.  A drop is
    applied to the explicit v2 ``constant`` before multiplication; it is not a
    post-product truncation.
    """
    exact = validate_graph(graph)
    pipeline_stages = {} if pipeline_stages is None else dict(pipeline_stages)
    resource_groups = {} if resource_groups is None else dict(resource_groups)
    products = [node for node in graph["nodes"] if node["op"] == "constant_multiply"]
    product_ids = {node["id"] for node in products}
    if set(coefficient_drops) != product_ids:
        raise ValueError("coefficient_drops must name every and only constant_multiply node")
    if set(pipeline_stages) - {node["id"] for node in graph["nodes"]}:
        raise ValueError("pipeline_stages names an unknown source node")
    if set(resource_groups) - {node["id"] for node in graph["nodes"]}:
        raise ValueError("resource_groups names an unknown source node")
    for node_id, drop in coefficient_drops.items():
        if type(drop) is not int or not 0 <= drop <= 15:
            raise ValueError(f"coefficient drop for {node_id} must be an integer in [0,15]")

    source_ref = {"x": "x"}
    joint_nodes: list[dict[str, Any]] = []
    value_kind = {"x": "sample"}
    output_source = None
    for node in graph["nodes"]:
        node_id, op = node["id"], node["op"]
        if op == "input":
            continue
        if op == "output":
            output_source = source_ref[node["input"]]
            continue
        if op == "delay":
            refs = [source_ref[node["source"]]]
            joint_op, kind = "delay", "sample"
            fixed = _format(16, 0)
            parameters = {
                "cycles": int(node["cycles"]),
                "advance_on": "accepted_transaction",
            }
        elif op == "constant_multiply":
            constant_id = f"k_{node_id}"
            joint_nodes.append({
                "id": constant_id,
                "op": "constant",
                "inputs": [],
                "parameters": {"value": int(node["coefficient"])},
                "fixed_point": _format(
                    16, 15, drop_lsb=coefficient_drops[node_id]),
                "microarchitecture": {
                    "pipeline_stage": 0,
                    "resource_group": None,
                    "latency": 0,
                },
            })
            source_ref[constant_id] = constant_id
            value_kind[constant_id] = "coefficient"
            refs = [source_ref[node["input"]], constant_id]
            joint_op, kind = "multiply", "product"
            fixed = _format(40, 15)
            parameters = None
        elif op in {"add", "sub"}:
            refs = [source_ref[value] for value in node["inputs"]]
            parent_kinds = {value_kind[value] for value in refs}
            if parent_kinds == {"sample"}:
                kind, fixed = "sample", _format(17, 0)
            elif parent_kinds == {"product"}:
                kind, fixed = "product", _format(40, 15)
            else:
                raise ValueError(f"unsupported mixed numeric kinds at {node_id}")
            joint_op = op
            parameters = None
        elif op == "register":
            refs = [source_ref[node["input"]]]
            kind = value_kind[refs[0]]
            if kind != "product":
                raise ValueError("FIR output register must store the product-domain sum")
            joint_op, fixed = "register", _format(40, 15)
            parameters = None
        else:
            raise ValueError(f"joint FIR adapter does not support source op {op!r}")
        stage = int(pipeline_stages.get(node_id, 1 if op == "register" else 0))
        joint_node = {
            "id": node_id,
            "op": joint_op,
            "inputs": refs,
            "fixed_point": fixed,
            "microarchitecture": {
                "pipeline_stage": stage,
                "resource_group": resource_groups.get(node_id),
                "latency": 1 if op == "register" else 0,
            },
        }
        if parameters is not None:
            joint_node["parameters"] = parameters
        joint_nodes.append(joint_node)
        source_ref[node_id] = node_id
        value_kind[node_id] = kind
    if output_source is None:
        raise ValueError("source graph has no output")

    candidate = {
        "schema_version": SCHEMA_VERSION,
        "task": {"task_id": TASK_ID, "formula_id": FORMULA_ID},
        "inputs": [{"id": "x", "width": 16, "signed": True}],
        "outputs": [{"id": "y", "source": output_source, "width": 40, "signed": True}],
        "nodes": joint_nodes,
        "quality_contract": {
            "metric": "sqnr_db",
            "direction": "max",
            "threshold": float(minimum_sqnr_db),
            "aggregation": "mean_squared_error_under_iid_signed16_inputs",
            "evaluation": "exact first-two-moment FIR coefficient-error model",
        },
        "metadata": {
            "name": name or graph.get("name", "joint_fir"),
            "source_graph_sha256": exact["graph_sha256"],
            "frozen_shell": "R=2; warmup=15; one elastic output register",
            "constant_drop_semantics": "coefficient magnitude low-bit clearing toward zero",
        },
    }
    validate_candidate(candidate)
    # Reconstructing here proves the generic representation did not lose any
    # of the exact source topology before approximate precision is applied.
    graph_from_candidate(candidate)
    return candidate


def graph_from_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Recover and exact-validate the source arithmetic graph."""
    validation = validate_candidate(candidate)
    if validation["task_id"] != TASK_ID or validation["formula_id"] != FORMULA_ID:
        raise ValueError("candidate is not a joint FIR-decimator design")
    if validation["schema_version"] != SCHEMA_VERSION:
        raise ValueError("joint FIR adapter requires the v2 native constant/delay schema")
    if candidate["inputs"] != [{"id": "x", "width": 16, "signed": True}]:
        raise ValueError("joint FIR external inputs must contain only signed-16 x")

    reverse_ref = {"x": "x"}
    nodes: list[dict[str, Any]] = [{"id": "x", "op": "input"}]
    constants: dict[str, int] = {}
    used_constants: set[str] = set()
    for node in candidate["nodes"]:
        node_id, op = node["id"], node["op"]
        if op == "constant":
            constants[node_id] = int(node["parameters"]["value"])
            continue
        if op == "delay":
            source = node["inputs"][0]
            if source not in reverse_ref:
                raise ValueError("FIR delay references an unsupported value")
            source_node = {
                "id": node_id,
                "op": "delay",
                "source": reverse_ref[source],
                "cycles": int(node["parameters"]["cycles"]),
            }
        elif op == "multiply":
            data_ref, constant_ref = node["inputs"]
            if constant_ref not in constants or data_ref not in reverse_ref:
                raise ValueError("FIR multiply must consume one data value and one explicit constant")
            used_constants.add(constant_ref)
            source_node = {
                "id": node_id,
                "op": "constant_multiply",
                "input": reverse_ref[data_ref],
                "coefficient": constants[constant_ref],
            }
        elif op in {"add", "sub"}:
            if any(ref not in reverse_ref for ref in node["inputs"]):
                raise ValueError("FIR arithmetic references an unsupported value")
            source_node = {"id": node_id, "op": op,
                           "inputs": [reverse_ref[ref] for ref in node["inputs"]]}
        elif op == "register":
            ref = node["inputs"][0]
            if ref not in reverse_ref:
                raise ValueError("FIR register references an unsupported value")
            source_node = {"id": node_id, "op": "register", "input": reverse_ref[ref]}
        else:
            raise ValueError(f"joint FIR backend does not support op {op!r}")
        nodes.append(source_node)
        reverse_ref[node_id] = node_id
    if used_constants != set(constants):
        raise ValueError("every explicit constant must feed the arithmetic graph")
    if len(candidate["outputs"]) != 1 or candidate["outputs"][0]["id"] != "y":
        raise ValueError("joint FIR requires the frozen single y output")
    output_ref = candidate["outputs"][0]["source"]
    if output_ref not in reverse_ref:
        raise ValueError("joint FIR output references an unsupported value")
    nodes.append({"id": "y", "op": "output", "input": reverse_ref[output_ref]})
    graph = {
        "schema_version": "fir-decim-arithmetic-graph-v1",
        "formula_version": FORMULA_ID,
        "name": str(candidate["metadata"].get("name", "joint_fir")),
        "phase_control": {"counter_modulus": 2, "emit_remainder": 1, "warmup_samples": 15},
        "nodes": nodes,
    }
    validate_graph(graph)
    expected = candidate["metadata"].get("source_graph_sha256")
    if expected is not None and graph_sha256(graph) != expected:
        raise ValueError("joint candidate structure differs from its bound source graph")
    return graph


def _ensure_supported_backend(candidate: Mapping[str, Any]) -> None:
    for node in candidate["nodes"]:
        expected_stage = 1 if node["op"] == "register" else 0
        if node["microarchitecture"]["pipeline_stage"] != expected_stage:
            raise ValueError("FIR backend does not yet lower this pipeline schedule")
        expected_latency = 1 if node["op"] == "register" else 0
        if node["microarchitecture"]["latency"] != expected_latency:
            raise ValueError("FIR backend does not yet lower this node latency")
        if node["microarchitecture"]["resource_group"] is not None:
            raise ValueError("FIR backend does not yet lower shared resource groups")
        if node["fixed_point"]["rounding"] != "trunc":
            raise ValueError("FIR coefficient backend only supports toward-zero low-bit clearing")


def _materialize(candidate: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    source = graph_from_candidate(candidate)
    _ensure_supported_backend(candidate)
    joint_by_id = {node["id"]: node for node in candidate["nodes"]}
    effective: dict[str, int] = {}
    graph = deepcopy(source)
    for node in graph["nodes"]:
        if node["op"] != "constant_multiply":
            continue
        multiply = joint_by_id[node["id"]]
        constant = joint_by_id[multiply["inputs"][1]]
        if constant["op"] != "constant":
            raise ValueError("FIR multiply precision must bind to an explicit constant")
        drop = constant["fixed_point"]["drop_lsb"]
        node["coefficient"] = _quantize_coefficient(node["coefficient"], drop)
        effective[node["id"]] = node["coefficient"]
    return graph, effective


def _impulse_response(graph: Mapping[str, Any]) -> tuple[int, ...]:
    values: dict[str, tuple[int, ...]] = {}
    for node in graph["nodes"]:
        op = node["op"]
        if op == "input":
            value = (1,) + (0,) * 15
        elif op == "delay":
            cycles = node["cycles"]
            value = (0,) * cycles + (1,) + (0,) * (15 - cycles)
        elif op == "constant_multiply":
            value = tuple(node["coefficient"] * item for item in values[node["input"]])
        elif op in {"add", "sub"}:
            left, right = (values[ref] for ref in node["inputs"])
            sign = 1 if op == "add" else -1
            value = tuple(a + sign * b for a, b in zip(left, right))
        elif op in {"register", "output"}:
            value = values[node["input"]]
        else:
            raise ValueError(f"unsupported materialized FIR op {op!r}")
        values[node["id"]] = value
    return values[graph["nodes"][-1]["id"]]


def evaluate_analytic(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Compute deterministic MSE/SQNR from the complete impulse-response error."""
    materialized, effective = _materialize(candidate)
    impulse = _impulse_response(materialized)
    delta = tuple(value - reference
                  for value, reference in zip(impulse, COEFFICIENTS_Q15))
    mean_error = INPUT_MEAN * sum(delta)
    error_variance = INPUT_VARIANCE * sum(value * value for value in delta)
    mse = error_variance + mean_error * mean_error
    sqnr = 999.0 if mse == 0 else 10.0 * math.log10(float(SIGNAL_POWER / mse))
    metrics = {
        "sqnr_db": sqnr,
        "mean_error": _fraction_record(mean_error),
        "error_variance": _fraction_record(error_variance),
        "mse": _fraction_record(mse),
        "effective_impulse_response": list(impulse),
        "delta_impulse_response": list(delta),
        "effective_coefficients_by_node": effective,
        "quality_threshold_db": candidate["quality_contract"]["threshold"],
        "candidate_semantics": "exact" if mse == 0 else "approximate",
    }
    metrics["quality_passed"] = quality_gate_passes(candidate, metrics)
    return metrics


def _literal(value: int) -> str:
    return f"-40'sd{abs(value)}" if value < 0 else f"40'sd{value}"


def lower_rtl(candidate: Mapping[str, Any]) -> str:
    """Lower the supported joint candidate through the frozen stream shell."""
    graph, _ = _materialize(candidate)
    lines: list[str] = []
    for node in graph["nodes"]:
        node_id, op = node["id"], node["op"]
        if op in {"input", "output", "register"}:
            continue
        if op == "delay":
            lines.append(
                f"wire signed [39:0] {node_id} = "
                f"{{{{24{{delay_{node['cycles']}[15]}}}}, delay_{node['cycles']}}};"
            )
        elif op == "constant_multiply":
            lines.append(
                f"wire signed [39:0] {node_id} = "
                f"$signed({node['input']}) * {_literal(node['coefficient'])};"
            )
        elif op in {"add", "sub"}:
            symbol = "+" if op == "add" else "-"
            lines.append(
                f"wire signed [39:0] {node_id} = "
                f"$signed({node['inputs'][0]}) {symbol} $signed({node['inputs'][1]});"
            )
        else:
            raise ValueError(f"unsupported materialized FIR op {op!r}")
    register = next(node for node in graph["nodes"] if node["op"] == "register")
    reset_delays = "\n            ".join(
        f"delay_{index} <= 16'sd0;" for index in range(1, 16))
    update_delays = "\n                ".join(
        [f"delay_{index} <= delay_{index - 1};" for index in range(15, 1, -1)]
        + ["delay_1 <= x;"]
    )
    wires = "\n    ".join(lines).replace("$signed(x)", "$signed(x_graph)")
    return f"""// joint_candidate_sha256={candidate_hash(candidate)}; source_graph_sha256={graph_sha256(graph_from_candidate(candidate))}
module top(
    input wire clk, input wire rst_n,
    input wire in_valid, output wire in_ready,
    input wire signed [15:0] x,
    output reg out_valid, input wire out_ready,
    output reg signed [39:0] y
);
    reg signed [15:0] {', '.join(f'delay_{index}' for index in range(1, 16))};
    reg phase;
    reg [4:0] accepted_count;
    wire signed [39:0] x_graph = {{{{24{{x[15]}}}}, x}};
    {wires}
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            {reset_delays}
            phase <= 1'b0;
            accepted_count <= 5'd0;
            out_valid <= 1'b0;
            y <= 40'sd0;
        end else begin
            if (out_valid && out_ready)
                out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                {update_delays}
                if (accepted_count != 5'd31)
                    accepted_count <= accepted_count + 1'b1;
                phase <= ~phase;
                if (accepted_count >= 5'd15 && phase == 1'b1) begin
                    y <= {register['input']};
                    out_valid <= 1'b1;
                end
            end
        end
    end
endmodule
"""
