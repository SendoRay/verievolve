from copy import deepcopy
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples/comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from fir_decim_graph import (  # noqa: E402
    expert_direct_graph,
    expert_polyphase_graph,
    expert_symmetric_preadd_graph,
    graph_sha256,
)
from joint_design_ir import SCHEMA_VERSION, candidate_hash, validate_candidate  # noqa: E402
from joint_fir import (  # noqa: E402
    candidate_from_graph,
    evaluate_analytic,
    graph_from_candidate,
    lower_rtl,
)
import run_m5_fir_nonuniform_precision as frozen_precision  # noqa: E402


EXPERTS = (
    (expert_direct_graph, 16),
    (expert_polyphase_graph, 16),
    (expert_symmetric_preadd_graph, 8),
)


def _candidate(factory, *, drop=0, threshold=60.0, **kwargs):
    graph = factory()
    products = [node["id"] for node in graph["nodes"]
                if node["op"] == "constant_multiply"]
    return candidate_from_graph(
        graph,
        coefficient_drops={node_id: drop for node_id in products},
        minimum_sqnr_db=threshold,
        **kwargs,
    )


@pytest.mark.parametrize("factory,multiplies", EXPERTS)
def test_expert_structures_round_trip_and_lower(factory, multiplies):
    source = factory()
    candidate = _candidate(factory)
    validation = validate_candidate(candidate)
    assert candidate["schema_version"] == SCHEMA_VERSION
    assert candidate["inputs"] == [{"id": "x", "width": 16, "signed": True}]
    assert validation["operation_counts"]["multiply"] == multiplies
    assert validation["operation_counts"]["constant"] == multiplies
    assert validation["operation_counts"]["delay"] == 15
    assert all(
        node["parameters"]["advance_on"] == "accepted_transaction"
        for node in candidate["nodes"] if node["op"] == "delay"
    )
    assert graph_sha256(graph_from_candidate(candidate)) == graph_sha256(source)

    metrics = evaluate_analytic(candidate)
    assert metrics["candidate_semantics"] == "exact"
    assert metrics["mse"]["numerator"] == 0
    assert metrics["sqnr_db"] == 999.0
    assert metrics["quality_passed"] is True

    rtl = lower_rtl(candidate)
    assert "module top(" in rtl
    assert "input wire signed [15:0] x" in rtl
    assert "k_p0" not in rtl
    assert "assign in_ready = !out_valid || out_ready;" in rtl
    assert "accepted_count >= 5'd15 && phase == 1'b1" in rtl
    assert rtl.count(" * 40'sd") + rtl.count(" * -40'sd") == multiplies


def test_nonuniform_coefficient_precision_is_semantic_and_analytic():
    graph = expert_symmetric_preadd_graph()
    products = [node["id"] for node in graph["nodes"]
                if node["op"] == "constant_multiply"]
    drops = {node_id: (4 if index in {1, 4, 6} else 0)
             for index, node_id in enumerate(products)}
    candidate = candidate_from_graph(
        graph, coefficient_drops=drops, minimum_sqnr_db=60.0)
    exact = _candidate(expert_symmetric_preadd_graph)
    assert candidate_hash(candidate) != candidate_hash(exact)
    assert set(validate_candidate(candidate)["approximate_nodes"]) == {
        f"k_{products[1]}", f"k_{products[4]}", f"k_{products[6]}"}

    metrics = evaluate_analytic(candidate)
    assert metrics["candidate_semantics"] == "approximate"
    assert metrics["mse"]["numerator"] > 0
    assert metrics["effective_impulse_response"] != metrics["delta_impulse_response"]
    assert metrics["quality_passed"] == (metrics["sqnr_db"] >= 60.0)
    rtl = lower_rtl(candidate)
    assert "40'sd128" in rtl  # abs(-136) with four coefficient bits cleared


def test_symmetric_analytic_result_matches_frozen_independent_model():
    graph = expert_symmetric_preadd_graph()
    products = [node for node in graph["nodes"] if node["op"] == "constant_multiply"]
    drops = (0, 4, 2, 6, 0, 2, 4, 0)
    candidate = candidate_from_graph(
        graph,
        coefficient_drops={node["id"]: drop for node, drop in zip(products, drops)},
    )
    measured = evaluate_analytic(candidate)
    coefficients = tuple(
        frozen_precision.quantize(node["coefficient"], drop)
        for node, drop in zip(products, drops)
    )
    independent = frozen_precision.candidate_from_coefficients(coefficients)
    assert measured["mse"] == independent["mse"]
    assert measured["sqnr_db"] == independent["sqnr_db"]


def test_quality_gate_can_reject_an_approximate_candidate():
    candidate = _candidate(expert_symmetric_preadd_graph, drop=6, threshold=200.0)
    metrics = evaluate_analytic(candidate)
    assert metrics["sqnr_db"] < 200.0
    assert metrics["quality_passed"] is False


def test_backend_rejects_unimplemented_pipeline_schedule():
    graph = expert_symmetric_preadd_graph()
    products = [node["id"] for node in graph["nodes"]
                if node["op"] == "constant_multiply"]
    # A coherent extra arithmetic stage is legal in the generic IR, while the
    # current FIR shell intentionally does not pretend to implement it.
    stages = {
        node["id"]: (2 if node["op"] == "register" else 1)
        for node in graph["nodes"]
        if node["op"] in {"add", "sub", "constant_multiply", "register"}
    }
    candidate = candidate_from_graph(
        graph,
        coefficient_drops={node_id: 0 for node_id in products},
        pipeline_stages=stages,
    )
    with pytest.raises(ValueError, match="pipeline schedule"):
        evaluate_analytic(candidate)
    with pytest.raises(ValueError, match="pipeline schedule"):
        lower_rtl(candidate)


def test_backend_rejects_unimplemented_resource_sharing():
    graph = expert_direct_graph()
    products = [node["id"] for node in graph["nodes"]
                if node["op"] == "constant_multiply"]
    candidate = candidate_from_graph(
        graph,
        coefficient_drops={node_id: 0 for node_id in products},
        resource_groups={products[0]: "shared_multiplier"},
    )
    with pytest.raises(ValueError, match="shared resource groups"):
        lower_rtl(candidate)


def test_graph_tampering_fails_exact_source_validation():
    candidate = _candidate(expert_symmetric_preadd_graph)
    tampered = deepcopy(candidate)
    multiply = next(node for node in tampered["nodes"] if node["op"] == "multiply")
    multiply["inputs"][0] = "d1"
    with pytest.raises(ValueError):
        graph_from_candidate(tampered)


def test_constructor_requires_a_precision_decision_for_every_multiplier():
    graph = expert_direct_graph()
    products = [node["id"] for node in graph["nodes"]
                if node["op"] == "constant_multiply"]
    with pytest.raises(ValueError, match="every and only"):
        candidate_from_graph(graph, coefficient_drops={node_id: 0 for node_id in products[:-1]})
