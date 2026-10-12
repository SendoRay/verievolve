"""Executable cmul adapter for the task-independent joint design IR.

This adapter reuses the independently checked complex-multiply analytic error
model and RTL lowerer.  The joint candidate remains the archived source of
truth: structure, per-product precision, and the currently supported output
pipeline are validated together before conversion to the family backend.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from cmul_graph import (
    analytic_metrics,
    graph_sha256,
    implementation_record,
    lower_precision_rtl,
    validate_graph,
)
from joint_design_ir import SCHEMA_VERSION, validate_candidate


TASK_ID = "cmul_w16_free"
FORMULA_ID = "cmul-w16-exact-v1"


def _format(width: int, frac: int, *, drop_lsb: int = 0,
            rounding: str = "rne") -> dict[str, Any]:
    return {
        "signed": True,
        "width": int(width),
        "frac": int(frac),
        "rounding": str(rounding),
        "overflow": "wrap",
        "drop_lsb": int(drop_lsb),
    }


def _stage(node: Mapping[str, Any], stages: Mapping[str, int]) -> int:
    if node["id"] in stages:
        return int(stages[node["id"]])
    return 1 if node["op"] == "register" else 0


def candidate_from_graph(
    graph: Mapping[str, Any],
    *,
    multiply_drops: Mapping[str, int],
    rounding: str = "rne",
    pipeline_stages: Mapping[str, int] | None = None,
    resource_groups: Mapping[str, str | None] | None = None,
    minimum_sqnr_db: float = 60.0,
    name: str | None = None,
) -> dict[str, Any]:
    """Bind structure, precision, and microarchitecture into one candidate."""
    exact = validate_graph(graph)
    pipeline_stages = {} if pipeline_stages is None else dict(pipeline_stages)
    resource_groups = {} if resource_groups is None else dict(resource_groups)
    products = {node["id"] for node in graph["nodes"] if node["op"] == "multiply"}
    if set(multiply_drops) != products:
        raise ValueError("multiply_drops must name every and only multiply node")
    graph_nodes = []
    output_bindings: dict[str, str] = {}
    value_kinds = {port: "linear" for port in ("a", "b", "c", "d")}
    for node in graph["nodes"]:
        op, node_id = node["op"], node["id"]
        if op == "input":
            continue
        if op == "output":
            output_bindings[node_id] = node["input"]
            continue
        if op in {"add", "sub", "multiply"}:
            refs = list(node["inputs"])
        elif op == "register":
            refs = [node["input"]]
        else:  # protected by the family validator
            raise AssertionError(op)
        # Linear pre-adds retain Q*.15; products and every descendant of a
        # product use the backend's audited signed-39 Q*.30 representation.
        if op == "multiply":
            kind = "bilinear"
        elif op == "register":
            kind = value_kinds[refs[0]]
        else:
            parent_kinds = {value_kinds[ref] for ref in refs}
            if len(parent_kinds) != 1:
                raise ValueError(f"mixed numeric kinds at {node_id}")
            kind = next(iter(parent_kinds))
        bilinear = kind == "bilinear"
        drop = int(multiply_drops[node_id]) if op == "multiply" else 0
        storage_width = 33 if op == "register" else (39 if bilinear else 17)
        graph_nodes.append({
            "id": node_id,
            "op": op,
            "inputs": refs,
            "fixed_point": _format(storage_width, 30 if bilinear else 15,
                                     drop_lsb=drop, rounding=rounding),
            "microarchitecture": {
                "pipeline_stage": _stage(node, pipeline_stages),
                "resource_group": resource_groups.get(node_id),
                "latency": 1 if op == "register" else 0,
            },
        })
        value_kinds[node_id] = kind
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "task": {"task_id": TASK_ID, "formula_id": FORMULA_ID},
        "inputs": [{"id": value, "width": 16, "signed": True}
                   for value in ("a", "b", "c", "d")],
        "outputs": [
            {"id": "y_re", "source": output_bindings["y_re"], "width": 33, "signed": True},
            {"id": "y_im", "source": output_bindings["y_im"], "width": 33, "signed": True},
        ],
        "nodes": graph_nodes,
        "quality_contract": {
            "metric": "sqnr_db",
            "direction": "max",
            "threshold": float(minimum_sqnr_db),
            "aggregation": "minimum_across_output_components",
            "evaluation": "cmul exact modular product-error moments",
        },
        "metadata": {
            "name": name or graph.get("name", "joint_cmul"),
            "source_graph_sha256": exact["graph_sha256"],
            "candidate_origin": "joint_structure_precision_microarchitecture",
        },
    }
    validate_candidate(candidate)
    return candidate


def graph_from_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Recover the exact structural graph used by the cmul family backend."""
    validation = validate_candidate(candidate)
    if validation["task_id"] != TASK_ID or validation["formula_id"] != FORMULA_ID:
        raise ValueError("candidate is not a cmul_w16 joint design")
    nodes = [{"id": port["id"], "op": "input"} for port in candidate["inputs"]]
    for node in candidate["nodes"]:
        record = {"id": node["id"], "op": node["op"]}
        if node["op"] == "register":
            record["input"] = node["inputs"][0]
        else:
            record["inputs"] = list(node["inputs"])
        nodes.append(record)
    nodes.extend({"id": port["id"], "op": "output", "input": port["source"]}
                 for port in candidate["outputs"])
    graph = {
        "schema_version": "cmul-operation-graph-v1",
        "formula_version": FORMULA_ID,
        "name": str(candidate["metadata"].get("name", "joint_cmul")),
        "nodes": nodes,
    }
    validate_graph(graph)
    expected = candidate["metadata"].get("source_graph_sha256")
    if expected is not None and graph_sha256(graph) != expected:
        raise ValueError("joint candidate structure differs from its bound source graph")
    return graph


def implementation_from_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Create the analytic/RTL backend record from the joint candidate itself."""
    graph = graph_from_candidate(candidate)
    products = {node["id"] for node in graph["nodes"] if node["op"] == "multiply"}
    by_id = {node["id"]: node for node in candidate["nodes"]}
    drops = {node_id: int(by_id[node_id]["fixed_point"]["drop_lsb"])
             for node_id in products}
    modes = {by_id[node_id]["fixed_point"]["rounding"] for node_id in products}
    if len(modes) != 1:
        raise ValueError("cmul analytic backend currently requires one product rounding mode")
    # The current family lowerer implements one elastic output-register stage.
    # Reject unsupported scheduling instead of silently ignoring the IR.
    for node in candidate["nodes"]:
        expected_stage = 1 if node["op"] == "register" else 0
        if node["microarchitecture"]["pipeline_stage"] != expected_stage:
            raise ValueError("cmul backend does not yet lower this pipeline schedule")
        if node["microarchitecture"]["resource_group"] is not None:
            raise ValueError("cmul backend does not yet lower shared resource groups")
    return implementation_record(graph, drops, next(iter(modes)))


def evaluate_analytic(candidate: Mapping[str, Any]) -> dict[str, Any]:
    graph = graph_from_candidate(candidate)
    implementation = implementation_from_candidate(candidate)
    metrics = deepcopy(implementation["analytic_metrics"])
    metrics["quality_threshold_db"] = candidate["quality_contract"]["threshold"]
    metrics["quality_passed"] = (
        metrics["sqnr_db"] >= candidate["quality_contract"]["threshold"]
    )
    metrics["candidate_semantics"] = "approximate" if implementation["numeric_semantics"].startswith("approximate") else "exact"
    return metrics


def lower_rtl(candidate: Mapping[str, Any]) -> str:
    graph = graph_from_candidate(candidate)
    implementation = implementation_from_candidate(candidate)
    return lower_precision_rtl(graph, implementation)
