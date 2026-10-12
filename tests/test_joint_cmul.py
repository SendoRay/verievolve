"""Executable adapter checks for the first joint-design task family."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from cmul_graph import expert_direct_graph, expert_gauss_sum_recombine_graph  # noqa: E402
from joint_cmul import (  # noqa: E402
    candidate_from_graph,
    evaluate_analytic,
    graph_from_candidate,
    implementation_from_candidate,
    lower_rtl,
)
from joint_design_ir import quality_gate_passes, validate_candidate  # noqa: E402


def _candidate(graph, drops=4, threshold=60.0):
    product_ids = [node["id"] for node in graph["nodes"] if node["op"] == "multiply"]
    return candidate_from_graph(
        graph,
        multiply_drops={node_id: drops for node_id in product_ids},
        minimum_sqnr_db=threshold,
    )


@pytest.mark.parametrize("factory", [expert_direct_graph, expert_gauss_sum_recombine_graph])
def test_joint_candidate_roundtrips_structure_precision_and_rtl(factory):
    graph = factory()
    candidate = _candidate(graph)
    validation = validate_candidate(candidate)
    recovered = graph_from_candidate(candidate)
    implementation = implementation_from_candidate(candidate)
    metrics = evaluate_analytic(candidate)
    rtl = lower_rtl(candidate)

    assert validation["exact_formula_equality_required"] is False
    assert recovered["nodes"] == graph["nodes"]
    assert set(implementation["multiply_drops"].values()) == {4}
    assert metrics["quality_passed"] is True
    assert quality_gate_passes(candidate, metrics) is True
    assert "module top(" in rtl
    assert "approximate cmul precision implementation" in rtl


def test_nonuniform_product_precision_is_not_collapsed_to_one_parameter():
    graph = expert_direct_graph()
    products = [node["id"] for node in graph["nodes"] if node["op"] == "multiply"]
    drops = dict(zip(products, (0, 2, 4, 6)))
    candidate = candidate_from_graph(graph, multiply_drops=drops, rounding="trunc")
    implementation = implementation_from_candidate(candidate)
    assert implementation["multiply_drops"] == drops
    assert implementation["rounding_mode"] == "trunc"


def test_frozen_quality_contract_can_reject_an_approximate_candidate():
    candidate = _candidate(expert_direct_graph(), drops=8, threshold=200.0)
    metrics = evaluate_analytic(candidate)
    assert metrics["quality_passed"] is False
    assert quality_gate_passes(candidate, metrics) is False


@pytest.mark.parametrize("axis", ["pipeline", "resource_sharing"])
def test_backend_rejects_unimplemented_microarchitecture_axes(axis):
    candidate = _candidate(expert_direct_graph())
    changed = deepcopy(candidate)
    node = changed["nodes"][0]
    if axis == "pipeline":
        for scheduled in changed["nodes"]:
            scheduled["microarchitecture"]["pipeline_stage"] = 1
    else:
        node["microarchitecture"]["resource_group"] = "shared_multiplier"
    validate_candidate(changed)
    with pytest.raises(ValueError, match="does not yet lower"):
        implementation_from_candidate(changed)
