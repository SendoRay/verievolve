"""Contract tests for the generic joint algorithm/precision/microarchitecture IR.

The first adapter is ``cmul_w16``, but the IR itself must remain task agnostic.
These tests intentionally build raw JSON-shaped dictionaries: an LLM proposal
must be valid without first passing through a task-specific Python constructor.
"""

import copy
import json
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from joint_design_ir import (  # noqa: E402
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    JointDesignValidationError,
    candidate_hash,
    quality_gate_passes,
    validate_candidate,
)


def _fixed_point(width, frac, *, drop_lsb=0, rounding="rne", overflow="wrap"):
    return {
        "signed": True,
        "width": width,
        "frac": frac,
        "rounding": rounding,
        "overflow": overflow,
        "drop_lsb": drop_lsb,
    }


def _microarchitecture(stage, group, *, latency=1):
    return {
        "pipeline_stage": stage,
        "resource_group": group,
        "latency": latency,
    }


def _node(
    node_id,
    op,
    inputs,
    fixed_point,
    *,
    stage,
    resource_group,
    latency=1,
):
    return {
        "id": node_id,
        "op": op,
        "inputs": inputs,
        "fixed_point": fixed_point,
        "microarchitecture": _microarchitecture(
            stage, resource_group, latency=latency
        ),
    }


def _envelope(nodes, *, task_id="cmul_w16", formula_id="complex_multiply"):
    return {
        "schema_version": "verievolve-joint-design-v1",
        "task": {"task_id": task_id, "formula_id": formula_id},
        "inputs": [
            {"id": name, "width": 16, "signed": True}
            for name in ("a", "b", "c", "d")
        ],
        # Output IDs bind the public ports to graph nodes with the same IDs.
        "outputs": [
            {"id": "y_re", "source": "y_re", "width": 33, "signed": True},
            {"id": "y_im", "source": "y_im", "width": 33, "signed": True},
        ],
        "nodes": nodes,
        "quality_contract": {
            "metric": "worst_output_mse_lsb2",
            "direction": "min",
            "threshold": 4.0,
            "aggregation": "max_over_outputs",
            "evaluation": "integer_domain_exact",
        },
        "metadata": {
            "label": "not part of candidate identity",
            "provenance": {"author": "test", "generation": 0},
        },
    }


def direct_candidate():
    # Four distinct product precisions deliberately exercise per-node precision.
    products = [
        ("ac", "a", "c", 0),
        ("bd", "b", "d", 1),
        ("ad", "a", "d", 2),
        ("bc", "b", "c", 3),
    ]
    nodes = [
        _node(
            node_id,
            "multiply",
            [left, right],
            _fixed_point(32 - drop, 30 - drop, drop_lsb=drop),
            stage=0,
            resource_group=f"mul_{node_id}",
        )
        for node_id, left, right, drop in products
    ]
    nodes.extend(
        [
            _node(
                "y_re",
                "sub",
                ["ac", "bd"],
                _fixed_point(33, 27),
                stage=1,
                resource_group="add_real",
            ),
            _node(
                "y_im",
                "add",
                ["ad", "bc"],
                _fixed_point(33, 27),
                stage=1,
                resource_group="add_imag",
            ),
        ]
    )
    return _envelope(nodes)


def gauss_candidate():
    nodes = [
        _node(
            "sum_ab",
            "add",
            ["a", "b"],
            _fixed_point(17, 15),
            stage=0,
            resource_group="preadd_left",
        ),
        _node(
            "sum_cd",
            "add",
            ["c", "d"],
            _fixed_point(17, 15),
            stage=0,
            resource_group="preadd_right",
        ),
        _node(
            "p_ac",
            "multiply",
            ["a", "c"],
            _fixed_point(32, 30, drop_lsb=0),
            stage=0,
            resource_group="mul_edge",
        ),
        _node(
            "p_bd",
            "multiply",
            ["b", "d"],
            _fixed_point(31, 29, drop_lsb=1),
            stage=0,
            resource_group="mul_edge",
        ),
        _node(
            "p_sum",
            "multiply",
            ["sum_ab", "sum_cd"],
            _fixed_point(32, 28, drop_lsb=2),
            stage=1,
            resource_group="mul_sum",
        ),
        _node(
            "y_re",
            "sub",
            ["p_ac", "p_bd"],
            _fixed_point(33, 28),
            stage=1,
            resource_group="recombine_real",
        ),
        _node(
            "im_partial",
            "sub",
            ["p_sum", "p_ac"],
            _fixed_point(33, 28),
            stage=2,
            resource_group="recombine_imag",
        ),
        _node(
            "y_im",
            "sub",
            ["im_partial", "p_bd"],
            _fixed_point(33, 28),
            stage=3,
            resource_group="recombine_imag",
        ),
    ]
    return _envelope(nodes)


@pytest.mark.parametrize("factory", [direct_candidate, gauss_candidate])
def test_direct_and_gauss_are_valid_joint_json_candidates(factory):
    candidate = factory()
    # Round-trip through JSON so the contract cannot depend on Python-only types.
    raw_json_candidate = json.loads(json.dumps(candidate))
    validate_candidate(raw_json_candidate)


def test_validator_is_generic_instead_of_hard_coded_to_cmul_w16():
    candidate = {
        "schema_version": "verievolve-joint-design-v1",
        "task": {"task_id": "scalar_sum_w8", "formula_id": "x_plus_y"},
        "inputs": [
            {"id": "x", "width": 8, "signed": True},
            {"id": "y", "width": 8, "signed": True},
        ],
        "outputs": [{"id": "z", "source": "z", "width": 9, "signed": True}],
        "nodes": [
            _node(
                "z",
                "add",
                ["x", "y"],
                _fixed_point(9, 4),
                stage=0,
                resource_group="adder_0",
            )
        ],
        "quality_contract": {
            "metric": "max_abs_error_lsb",
            "direction": "min",
            "threshold": 1.0,
            "aggregation": "max_over_outputs",
            "evaluation": "exhaustive_integer_domain",
        },
        "metadata": {},
    }
    validate_candidate(candidate)


def test_each_multiply_can_choose_an_independent_drop_and_resource_binding():
    candidate = direct_candidate()
    products = [node for node in candidate["nodes"] if node["op"] == "multiply"]
    assert [node["fixed_point"]["drop_lsb"] for node in products] == [0, 1, 2, 3]
    assert len({node["fixed_point"]["width"] for node in products}) == 4
    assert len({node["microarchitecture"]["resource_group"] for node in products}) == 4
    validate_candidate(candidate)


def test_pipeline_placement_is_per_node_and_part_of_candidate_identity():
    candidate = gauss_candidate()
    stages = {
        node["id"]: node["microarchitecture"]["pipeline_stage"]
        for node in candidate["nodes"]
    }
    assert stages == {
        "sum_ab": 0,
        "sum_cd": 0,
        "p_ac": 0,
        "p_bd": 0,
        "p_sum": 1,
        "y_re": 1,
        "im_partial": 2,
        "y_im": 3,
    }
    validate_candidate(candidate)

    moved_pipeline = copy.deepcopy(candidate)
    next(node for node in moved_pipeline["nodes"] if node["id"] == "y_re")[
        "microarchitecture"
    ]["pipeline_stage"] = 2
    validate_candidate(moved_pipeline)
    assert candidate_hash(candidate) != candidate_hash(moved_pipeline)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["nodes"].__setitem__(1, copy.deepcopy(c["nodes"][0])),
        lambda c: c["nodes"][0]["inputs"].__setitem__(0, "does_not_exist"),
        lambda c: c["nodes"][0].__setitem__("op", "python_eval"),
        lambda c: c["nodes"][0]["inputs"].__setitem__(0, "y_re"),
        lambda c: c["outputs"][0].__setitem__("source", "unbound_output"),
    ],
    ids=[
        "duplicate-node-id",
        "undefined-input",
        "unknown-operation",
        "cycle-or-forward-reference",
        "unbound-output",
    ],
)
def test_structurally_invalid_graphs_are_rejected(mutate):
    candidate = direct_candidate()
    mutate(candidate)
    with pytest.raises(JointDesignValidationError):
        validate_candidate(candidate)


@pytest.mark.parametrize(
    "field,value",
    [
        ("width", 0),
        ("width", True),
        ("frac", -1),
        ("frac", 33),
        ("rounding", "stochastic_unseeded"),
        ("overflow", "undefined"),
        ("drop_lsb", -1),
        ("drop_lsb", 32),
    ],
)
def test_invalid_fixed_point_descriptions_are_rejected(field, value):
    candidate = direct_candidate()
    candidate["nodes"][0]["fixed_point"][field] = value
    with pytest.raises(JointDesignValidationError):
        validate_candidate(candidate)


@pytest.mark.parametrize("field,value", [("width", 32), ("signed", False)])
def test_output_port_format_must_match_its_bound_graph_node(field, value):
    candidate = direct_candidate()
    candidate["outputs"][0][field] = value
    with pytest.raises(JointDesignValidationError):
        validate_candidate(candidate)


def test_formula_mismatch_is_not_a_structural_validation_error():
    candidate = direct_candidate()
    # This is not exact complex multiplication: real = ac + bd.  It is still a
    # well-formed approximate proposal and must reach deterministic evaluation.
    y_re = next(node for node in candidate["nodes"] if node["id"] == "y_re")
    y_re["op"] = "add"
    validate_candidate(candidate)

    assert quality_gate_passes(
        candidate, {"worst_output_mse_lsb2": 3.999}
    ) is True
    assert quality_gate_passes(
        candidate, {"worst_output_mse_lsb2": 4.001}
    ) is False


def test_quality_gate_reads_the_declared_metric_and_includes_the_boundary():
    candidate = direct_candidate()
    assert quality_gate_passes(candidate, {"worst_output_mse_lsb2": 4.0}) is True
    with pytest.raises(JointDesignValidationError):
        quality_gate_passes(candidate, {"some_other_metric": 0.0})


def _reverse_mapping_order(value):
    if isinstance(value, dict):
        return {
            key: _reverse_mapping_order(value[key])
            for key in reversed(list(value.keys()))
        }
    if isinstance(value, list):
        return [_reverse_mapping_order(item) for item in value]
    return value


def test_canonical_hash_ignores_mapping_order_and_nonsemantic_metadata():
    candidate = direct_candidate()
    reordered = _reverse_mapping_order(candidate)
    reordered["metadata"] = {
        "label": "renamed after evaluation",
        "provenance": {"generation": 99, "author": "another-run"},
    }
    assert candidate_hash(candidate) == candidate_hash(reordered)


@pytest.mark.parametrize("semantic_axis", ["precision", "microarchitecture"])
def test_canonical_hash_changes_for_joint_design_axes(semantic_axis):
    candidate = direct_candidate()
    changed = copy.deepcopy(candidate)
    if semantic_axis == "precision":
        changed["nodes"][0]["fixed_point"]["drop_lsb"] = 1
    else:
        changed["nodes"][0]["microarchitecture"]["resource_group"] = "shared_mul"
    assert candidate_hash(candidate) != candidate_hash(changed)


@pytest.mark.parametrize("bad_metadata", [{"not_json": {1, 2}}, {"not_json": float("inf")}])
def test_metadata_must_contain_only_strict_json_values(bad_metadata):
    candidate = direct_candidate()
    candidate["metadata"] = bad_metadata
    with pytest.raises(JointDesignValidationError):
        validate_candidate(candidate)


def _v2_constant_delay_candidate():
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "task": {"task_id": "accepted_delay", "formula_id": "scaled_previous_x"},
        "inputs": [{"id": "x", "width": 16, "signed": True}],
        "outputs": [{"id": "y", "source": "y", "width": 32, "signed": True}],
        "nodes": [
            {
                "id": "x_prev",
                "op": "delay",
                "inputs": ["x"],
                "parameters": {"cycles": 1, "advance_on": "accepted_transaction"},
                "fixed_point": _fixed_point(16, 0, rounding="trunc"),
                "microarchitecture": _microarchitecture(0, None, latency=0),
            },
            {
                "id": "gain",
                "op": "constant",
                "inputs": [],
                "parameters": {"value": -79},
                "fixed_point": _fixed_point(16, 15, drop_lsb=2, rounding="trunc"),
                "microarchitecture": _microarchitecture(0, None, latency=0),
            },
            _node(
                "y", "multiply", ["x_prev", "gain"],
                _fixed_point(32, 15, rounding="trunc"),
                stage=0, resource_group=None, latency=0,
            ),
        ],
        "quality_contract": {
            "metric": "sqnr_db", "direction": "max", "threshold": 60.0,
            "aggregation": "mean_squared_error",
            "evaluation": "integer_domain_exact",
        },
        "metadata": {},
    }
    return candidate


def test_legacy_v1_candidate_remains_read_only_valid_with_stable_identity():
    candidate = direct_candidate()
    assert candidate["schema_version"] == LEGACY_SCHEMA_VERSION
    validation = validate_candidate(candidate)
    assert validation["schema_version"] == LEGACY_SCHEMA_VERSION
    assert candidate_hash(candidate) == "406130703556fdd5ef48936b5ff62588d7282f4b90a33e40b37e70eeececfd0e"


def test_legacy_v1_rejects_v2_operations_and_parameters():
    candidate = direct_candidate()
    candidate["nodes"][0] = copy.deepcopy(_v2_constant_delay_candidate()["nodes"][1])
    with pytest.raises(JointDesignValidationError):
        validate_candidate(candidate)


def test_v2_constant_and_accepted_transaction_delay_are_valid_and_hashed():
    candidate = _v2_constant_delay_candidate()
    validation = validate_candidate(candidate)
    assert validation["schema_version"] == SCHEMA_VERSION
    assert validation["operation_counts"] == {
        "constant": 1, "delay": 1, "multiply": 1}
    assert validation["approximate_nodes"] == ["gain"]

    changed_constant = copy.deepcopy(candidate)
    changed_constant["nodes"][1]["parameters"]["value"] = -78
    changed_delay = copy.deepcopy(candidate)
    changed_delay["nodes"][0]["parameters"]["cycles"] = 2
    assert candidate_hash(candidate) != candidate_hash(changed_constant)
    assert candidate_hash(candidate) != candidate_hash(changed_delay)


@pytest.mark.parametrize(
    "node_index,mutation,error_code",
    [
        (1, lambda node: node["parameters"].__setitem__("extra", 1), "constant_parameters"),
        (1, lambda node: node["parameters"].__setitem__("value", 1.5), "constant_value"),
        (1, lambda node: node["parameters"].__setitem__("value", 40000), "constant_range"),
        (1, lambda node: node["inputs"].append("x"), "node_arity"),
        (1, lambda node: node["microarchitecture"].__setitem__("latency", 1), "constant_latency"),
        (0, lambda node: node["parameters"].__setitem__("cycles", 0), "delay_cycles"),
        (0, lambda node: node["parameters"].__setitem__("cycles", True), "delay_cycles"),
        (0, lambda node: node["parameters"].__setitem__("advance_on", "clock_cycle"), "delay_advance"),
        (0, lambda node: node["parameters"].__setitem__("ignored", 1), "delay_parameters"),
        (0, lambda node: node["microarchitecture"].__setitem__("latency", 1), "delay_latency"),
    ],
)
def test_v2_constant_delay_invalid_parameters_are_rejected(node_index, mutation, error_code):
    candidate = _v2_constant_delay_candidate()
    mutation(candidate["nodes"][node_index])
    with pytest.raises(JointDesignValidationError) as caught:
        validate_candidate(candidate)
    assert caught.value.code == error_code


def test_v2_existing_ops_reject_parameters_instead_of_ignoring_them():
    candidate = _v2_constant_delay_candidate()
    candidate["nodes"][2]["parameters"] = {"value": 123}
    with pytest.raises(JointDesignValidationError) as caught:
        validate_candidate(candidate)
    assert caught.value.code == "node_fields"
