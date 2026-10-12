"""Task-independent IR for joint structure, precision, and microarchitecture search.

The validator deliberately does *not* prove that a candidate is symbolically
equal to the reference formula.  It checks whether the proposal is a safe,
well-typed implementation graph.  Numerical acceptability is decided later by
the frozen ``quality_contract`` against independently measured metrics.  This
separation is what permits controlled approximate transformations.

Version 2 adds explicit constants and transaction-counted delays.  Version 1
remains accepted for read-only replay with its original operation set and
semantic hashes; new constructors should emit :data:`SCHEMA_VERSION`.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from typing import Any, Mapping


LEGACY_SCHEMA_VERSION = "verievolve-joint-design-v1"
SCHEMA_VERSION = "verievolve-joint-design-v2"
SUPPORTED_SCHEMA_VERSIONS = frozenset({LEGACY_SCHEMA_VERSION, SCHEMA_VERSION})
LEGACY_ALLOWED_OPS = frozenset({"add", "sub", "multiply", "register"})
ALLOWED_OPS = LEGACY_ALLOWED_OPS | {"constant", "delay"}
ROUNDING_MODES = frozenset({"rne", "trunc", "floor"})
OVERFLOW_MODES = frozenset({"sat", "wrap"})
QUALITY_DIRECTIONS = frozenset({"min", "max"})


class JointDesignValidationError(ValueError):
    """A stable, archivable rejection from the joint candidate validator."""

    def __init__(self, code: str, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.code = code
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def _fail(code: str, path: str, message: str) -> None:
    raise JointDesignValidationError(code, path, message)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def candidate_hash(candidate: Mapping[str, Any]) -> str:
    """Return semantic search identity, excluding descriptive metadata."""
    try:
        semantic = dict(candidate)
        semantic.pop("metadata", None)
        encoded = _canonical(semantic).encode()
    except (TypeError, ValueError) as exc:
        _fail("non_json_value", "$", f"candidate is not canonical JSON: {exc}")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.isidentifier() or len(value) > 64:
        _fail("identifier", path, "expected a Python-style identifier of at most 64 characters")
    return value


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("number", path, "expected a finite number")
    number = float(value)
    if not math.isfinite(number):
        _fail("number", path, "expected a finite number")
    return number


def _port(port: Any, path: str, *, output: bool) -> dict[str, Any]:
    if not isinstance(port, Mapping):
        _fail("port_type", path, "port must be an object")
    required = {"id", "width", "signed"} | ({"source"} if output else set())
    if set(port) != required:
        _fail("port_fields", path, f"fields must be exactly {sorted(required)}")
    port_id = _identifier(port["id"], f"{path}.id")
    width = port["width"]
    if type(width) is not int or not 1 <= width <= 128:
        _fail("port_width", f"{path}.width", "width must be an integer in [1,128]")
    if type(port["signed"]) is not bool:
        _fail("port_signed", f"{path}.signed", "signed must be boolean")
    result = {"id": port_id, "width": width, "signed": port["signed"]}
    if output:
        result["source"] = _identifier(port["source"], f"{path}.source")
    return result


def _fixed_point(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("fixed_point_type", path, "fixed_point must be an object")
    required = {"signed", "width", "frac", "rounding", "overflow", "drop_lsb"}
    if set(value) != required:
        _fail("fixed_point_fields", path, f"fields must be exactly {sorted(required)}")
    if type(value["signed"]) is not bool:
        _fail("fixed_point_signed", f"{path}.signed", "signed must be boolean")
    width, frac, drop = value["width"], value["frac"], value["drop_lsb"]
    if type(width) is not int or not 1 <= width <= 128:
        _fail("fixed_point_width", f"{path}.width", "width must be an integer in [1,128]")
    if type(frac) is not int or not 0 <= frac < width:
        _fail("fixed_point_frac", f"{path}.frac", "frac must be an integer in [0,width)")
    if type(drop) is not int or not 0 <= drop < width:
        _fail("fixed_point_drop", f"{path}.drop_lsb", "drop_lsb must be an integer in [0,width)")
    if value["rounding"] not in ROUNDING_MODES:
        _fail("fixed_point_rounding", f"{path}.rounding", f"expected one of {sorted(ROUNDING_MODES)}")
    if value["overflow"] not in OVERFLOW_MODES:
        _fail("fixed_point_overflow", f"{path}.overflow", f"expected one of {sorted(OVERFLOW_MODES)}")
    return dict(value)


def _microarchitecture(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("microarchitecture_type", path, "microarchitecture must be an object")
    required = {"pipeline_stage", "resource_group", "latency"}
    if set(value) != required:
        _fail("microarchitecture_fields", path, f"fields must be exactly {sorted(required)}")
    stage, latency, group = value["pipeline_stage"], value["latency"], value["resource_group"]
    if type(stage) is not int or not 0 <= stage <= 128:
        _fail("pipeline_stage", f"{path}.pipeline_stage", "pipeline_stage must be in [0,128]")
    if type(latency) is not int or not 0 <= latency <= 128:
        _fail("latency", f"{path}.latency", "latency must be in [0,128]")
    if group is not None and (not isinstance(group, str) or not group or len(group) > 64):
        _fail("resource_group", f"{path}.resource_group", "resource_group must be null or a nonempty string")
    return dict(value)


def _node_parameters(op: str, value: Any, path: str) -> dict[str, Any]:
    """Validate v2 state/value parameters without accepting ignored fields."""
    if not isinstance(value, Mapping):
        _fail("node_parameters_type", path, "parameters must be an object")
    if op == "constant":
        if set(value) != {"value"}:
            _fail("constant_parameters", path, "constant parameters must be exactly ['value']")
        if type(value["value"]) is not int:
            _fail("constant_value", f"{path}.value", "constant value must be an integer")
    elif op == "delay":
        required = {"cycles", "advance_on"}
        if set(value) != required:
            _fail("delay_parameters", path, f"delay parameters must be exactly {sorted(required)}")
        cycles = value["cycles"]
        if type(cycles) is not int or not 1 <= cycles <= 65535:
            _fail("delay_cycles", f"{path}.cycles", "cycles must be an integer in [1,65535]")
        if value["advance_on"] != "accepted_transaction":
            _fail("delay_advance", f"{path}.advance_on",
                  "delay must advance on accepted_transaction")
    elif value:
        _fail("unused_node_parameters", path, f"{op} does not define parameters")
    return dict(value)


def _quality_contract(value: Any) -> dict[str, Any]:
    path = "$.quality_contract"
    if not isinstance(value, Mapping):
        _fail("quality_contract_type", path, "quality_contract must be an object")
    required = {"metric", "direction", "threshold", "aggregation", "evaluation"}
    if set(value) != required:
        _fail("quality_contract_fields", path, f"fields must be exactly {sorted(required)}")
    if not isinstance(value["metric"], str) or not value["metric"]:
        _fail("quality_metric", f"{path}.metric", "metric must be a nonempty string")
    if value["direction"] not in QUALITY_DIRECTIONS:
        _fail("quality_direction", f"{path}.direction", "direction must be min or max")
    _finite_number(value["threshold"], f"{path}.threshold")
    if not isinstance(value["aggregation"], str) or not value["aggregation"]:
        _fail("quality_aggregation", f"{path}.aggregation", "aggregation must be nonempty")
    if not isinstance(value["evaluation"], str) or not value["evaluation"]:
        _fail("quality_evaluation", f"{path}.evaluation", "evaluation must identify the independent evaluator")
    return dict(value)


def validate_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structure and implementation semantics, never exact formula equality."""
    if not isinstance(candidate, Mapping):
        _fail("candidate_type", "$", "candidate must be an object")
    required = {
        "schema_version", "task", "inputs", "outputs", "nodes",
        "quality_contract", "metadata",
    }
    if set(candidate) != required:
        _fail("candidate_fields", "$", f"fields must be exactly {sorted(required)}")
    schema_version = candidate["schema_version"]
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        _fail("schema_version", "$.schema_version",
              f"expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    task = candidate["task"]
    if not isinstance(task, Mapping) or set(task) != {"task_id", "formula_id"}:
        _fail("task_fields", "$.task", "fields must be exactly ['formula_id','task_id']")
    for key in ("task_id", "formula_id"):
        if not isinstance(task[key], str) or not task[key]:
            _fail("task_value", f"$.task.{key}", f"{key} must be a nonempty string")
    if not isinstance(candidate["metadata"], Mapping):
        _fail("metadata_type", "$.metadata", "metadata must be an object")
    # Metadata is deliberately excluded from semantic deduplication, but it is
    # still archived with every proposal.  Validate the complete envelope so a
    # Python-only value (set, NaN, infinity, and so on) cannot make the archive
    # non-replayable merely because it is non-semantic.
    try:
        _canonical(candidate)
    except (TypeError, ValueError) as exc:
        _fail("non_json_value", "$", f"candidate is not canonical JSON: {exc}")
    candidate_hash(candidate)

    if not isinstance(candidate["inputs"], list) or not candidate["inputs"]:
        _fail("inputs", "$.inputs", "inputs must be a nonempty list")
    inputs = [_port(value, f"$.inputs[{index}]", output=False)
              for index, value in enumerate(candidate["inputs"])]
    if len({port["id"] for port in inputs}) != len(inputs):
        _fail("duplicate_id", "$.inputs", "input ids must be unique")

    nodes = candidate["nodes"]
    if not isinstance(nodes, list) or not nodes:
        _fail("nodes", "$.nodes", "nodes must be a nonempty list")
    known = {port["id"]: {"pipeline_stage": 0, "kind": "input"} for port in inputs}
    operation_counts: Counter[str] = Counter()
    approximate_nodes: list[str] = []
    resource_groups: dict[str, list[str]] = {}
    for index, node in enumerate(nodes):
        path = f"$.nodes[{index}]"
        if not isinstance(node, Mapping):
            _fail("node_type", path, "node must be an object")
        base_node = {"id", "op", "inputs", "fixed_point", "microarchitecture"}
        op = node.get("op")
        parameterized = schema_version == SCHEMA_VERSION and op in {"constant", "delay"}
        required_node = base_node | ({"parameters"} if parameterized else set())
        if set(node) != required_node:
            _fail("node_fields", path, f"fields must be exactly {sorted(required_node)}")
        node_id = _identifier(node["id"], f"{path}.id")
        if node_id in known:
            _fail("duplicate_id", f"{path}.id", "id duplicates an input or prior node")
        allowed_ops = LEGACY_ALLOWED_OPS if schema_version == LEGACY_SCHEMA_VERSION else ALLOWED_OPS
        if op not in allowed_ops:
            _fail("node_op", f"{path}.op", f"expected one of {sorted(allowed_ops)}")
        refs = node["inputs"]
        expected_arity = {"constant": 0, "delay": 1, "register": 1}.get(op, 2)
        if (not isinstance(refs, list) or len(refs) != expected_arity
                or not all(isinstance(ref, str) for ref in refs)):
            _fail("node_arity", f"{path}.inputs", f"{op} requires {expected_arity} input ids")
        if any(ref not in known for ref in refs):
            _fail("node_topology", f"{path}.inputs", "references must name inputs or prior nodes")
        fixed = _fixed_point(node["fixed_point"], f"{path}.fixed_point")
        micro = _microarchitecture(node["microarchitecture"], f"{path}.microarchitecture")
        parameters = _node_parameters(op, node["parameters"], f"{path}.parameters") \
            if parameterized else {}
        if op == "constant":
            value = parameters["value"]
            minimum = -(1 << (fixed["width"] - 1)) if fixed["signed"] else 0
            maximum = ((1 << (fixed["width"] - 1)) - 1
                       if fixed["signed"] else (1 << fixed["width"]) - 1)
            if not minimum <= value <= maximum:
                _fail("constant_range", f"{path}.parameters.value",
                      "constant value is not representable by fixed_point width/signed")
        latest_parent_stage = max(
            (known[ref]["pipeline_stage"] for ref in refs), default=0)
        if micro["pipeline_stage"] < latest_parent_stage:
            _fail("pipeline_order", f"{path}.microarchitecture.pipeline_stage",
                  "a node cannot be scheduled before one of its operands")
        if op == "register" and micro["latency"] < 1:
            _fail("register_latency", f"{path}.microarchitecture.latency",
                  "an explicit register must have positive latency")
        if op in {"constant", "delay"} and micro["latency"] != 0:
            _fail(f"{op}_latency", f"{path}.microarchitecture.latency",
                  f"{op} latency must be zero; delay history is specified by parameters.cycles")
        if fixed["drop_lsb"] > 0:
            approximate_nodes.append(node_id)
        if micro["resource_group"] is not None:
            resource_groups.setdefault(micro["resource_group"], []).append(node_id)
        known[node_id] = {"pipeline_stage": micro["pipeline_stage"], "kind": op}
        operation_counts[op] += 1

    if not isinstance(candidate["outputs"], list) or not candidate["outputs"]:
        _fail("outputs", "$.outputs", "outputs must be a nonempty list")
    outputs = [_port(value, f"$.outputs[{index}]", output=True)
               for index, value in enumerate(candidate["outputs"])]
    if len({port["id"] for port in outputs}) != len(outputs):
        _fail("duplicate_id", "$.outputs", "output ids must be unique")
    node_records = {node["id"]: node for node in nodes}
    for index, port in enumerate(outputs):
        if port["source"] not in known or known[port["source"]]["kind"] == "input":
            _fail("output_source", f"$.outputs[{index}].source", "output must bind to an operation node")
        source_format = node_records[port["source"]]["fixed_point"]
        if (port["width"], port["signed"]) != (source_format["width"], source_format["signed"]):
            _fail("output_format", f"$.outputs[{index}]",
                  "output width/signed must match its source node; make output conversion explicit")

    contract = _quality_contract(candidate["quality_contract"])
    return {
        "status": "valid_structure",
        "schema_version": schema_version,
        "candidate_sha256": candidate_hash(candidate),
        "task_id": task["task_id"],
        "formula_id": task["formula_id"],
        "operation_counts": dict(sorted(operation_counts.items())),
        "approximate_nodes": sorted(approximate_nodes),
        "pipeline_stages": sorted({node["microarchitecture"]["pipeline_stage"] for node in nodes}),
        "resource_groups": {name: members for name, members in sorted(resource_groups.items())},
        "quality_contract": contract,
        "semantic_status": "requires_independent_quality_evaluation",
        "exact_formula_equality_required": False,
    }


def quality_gate_passes(candidate: Mapping[str, Any], measured_metrics: Mapping[str, Any]) -> bool:
    """Apply only the candidate's frozen external quality gate to measured data."""
    validation = validate_candidate(candidate)
    if not isinstance(measured_metrics, Mapping):
        _fail("measured_metrics", "$metrics", "measured_metrics must be an object")
    contract = validation["quality_contract"]
    metric = contract["metric"]
    if metric not in measured_metrics:
        _fail("metric_missing", f"$metrics.{metric}", "required measured metric is absent")
    value = _finite_number(measured_metrics[metric], f"$metrics.{metric}")
    threshold = float(contract["threshold"])
    return value <= threshold if contract["direction"] == "min" else value >= threshold
