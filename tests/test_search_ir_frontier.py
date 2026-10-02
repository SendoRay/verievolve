import copy
import sys
from pathlib import Path

import numpy as np
import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.frontier import (
    engineering_hits,
    grid_values,
    hypervolume,
    paired_bootstrap,
)


def point(q, area):
    return {"Q": q, "area_um2": area}


def test_hypervolume_known_rectangles_and_physical_normalization():
    points = [point(2, 150), point(5, 100)]
    # (.2,1.5) 与 (.5,1) 到 (1,2) 的矩形并为 .4+.25。
    assert hypervolume(points, 10, 100) == pytest.approx(0.65)
    assert hypervolume([point(2, 100)], 10, 100) == pytest.approx(0.8)


def test_hypervolume_duplicates_dominated_points_and_order_are_irrelevant():
    points = [point(0.2, 1.5), point(0.5, 1.0), point(0.8, 1.7)]
    original = copy.deepcopy(points)
    assert hypervolume(points + [points[0]], 1, 1) == pytest.approx(0.65)
    assert hypervolume(list(reversed(points)), 1, 1) == pytest.approx(0.65)
    assert points == original


def test_hypervolume_excludes_roi_outliers_without_clipping():
    points = [point(0.5, 1), point(1.1, 0.1), point(0, 2.1)]
    assert hypervolume(points, 1, 1) == 0.5
    assert hypervolume([point(1.1, 0.1), point(0, 2.1)], 1, 1) == 0.0


def test_hypervolume_empty_zero_quality_and_reference_boundary():
    assert hypervolume([], 1, 1) == 0.0
    assert hypervolume([point(1, 0.1), point(0, 2)], 1, 1) == 0.0
    assert hypervolume([point(0, 0.5)], 1, 1) == 1.5


def test_grid_values_include_equal_boundaries_and_keep_missing_as_none():
    points = [point(0.25, 0.5), point(0.5, 0.25)]
    result = grid_values(points, 1, 1)
    assert result["quality_budgets"] == [0.25, 0.5, 1]
    assert result["area_budgets"] == [0.5, 0.75, 1, 1.25, 1.5, 2]
    assert result["min_area"] == [0.5, 0.25, 0.25]
    assert result["min_quality"] == [0.25] * 6
    empty = grid_values([], 1, 1)
    assert empty["min_area"] == [None] * 3
    assert empty["min_quality"] == [None] * 6
    partial = grid_values([point(0.75, 1.5)], 1, 1)
    assert partial["min_area"] == [None, None, 1.5]
    assert partial["min_quality"] == [None, None, None, None, 0.75, 0.75]


def test_grid_values_apply_each_budget_not_a_hidden_global_roi():
    result = grid_values([point(0.1, 3), point(2, 0.25)], 1, 1)
    assert result["min_area"] == [3] * 3
    assert result["min_quality"] == [2] * 6


@pytest.mark.parametrize(
    "bad",
    [
        point(float("nan"), 1),
        point(float("inf"), 1),
        point(-1, 1),
        point(True, 1),
        point("0.1", 1),
        point(0, float("inf")),
        point(0, 0),
        point(0, -1),
        point(0, False),
        {},
        None,
    ],
)
def test_invalid_points_are_rejected_in_every_entrypoint(bad):
    with pytest.raises(ValueError):
        hypervolume([bad], 1, 1)
    with pytest.raises(ValueError):
        grid_values([bad], 1, 1)
    with pytest.raises(ValueError):
        engineering_hits([point(0.1, 1)], [[bad]], 1, 1, 0.1, 0.1)


@pytest.mark.parametrize(
    "q_budget,A_ref",
    [(0, 1), (-1, 1), (float("nan"), 1), (True, 1), (1, 0), (1, float("inf"))],
)
def test_invalid_references_are_rejected_even_for_empty_points(q_budget, A_ref):
    with pytest.raises(ValueError):
        hypervolume([], q_budget, A_ref)
    with pytest.raises(ValueError):
        grid_values([], q_budget, A_ref)


def test_engineering_hits_require_all_baselines_at_the_same_grid():
    joint = [point(0.2, 1.5), point(0.8, 0.5)]
    first = [point(0.2, 1.8), point(0.8, 0.25)]
    second = [point(0.2, 1.25), point(0.8, 0.8)]
    assert engineering_hits(joint, [first], 1, 1, 0.125, 0.25)
    assert engineering_hits(joint, [second], 1, 1, 0.125, 0.25)
    # 分别在不同格点胜过两基线，不代表在同一格点同时胜过。
    assert engineering_hits(joint, [first, second], 1, 1, 0.125, 0.25) == []


def test_engineering_margin_equality_is_inclusive_and_described():
    hits = engineering_hits(
        [point(0.125, 0.75)], [[point(0.375, 1)]], 1, 1, 0.25, 0.25
    )
    area = next(h for h in hits if h["kind"] == "area" and h["budget"] == 0.5)
    assert area == {
        "kind": "area",
        "budget": 0.5,
        "joint": 0.75,
        "baselines": [1.0],
        "gaps": [0.25],
        "epsilon": 0.25,
    }
    quality = next(h for h in hits if h["kind"] == "quality" and h["budget"] == 1)
    assert quality["gaps"] == [0.25]


def test_empty_grid_is_not_infinite_improvement_and_zero_baselines_is_invalid():
    joint = [point(0.1, 0.5)]
    assert engineering_hits(joint, [[]], 1, 1, 0.1, 0.1) == []
    assert engineering_hits(joint, [[point(0.5, 1)], []], 1, 1, 0.1, 0.1) == []
    assert engineering_hits([], [[point(0.5, 1)]], 1, 1, 0.1, 0.1) == []
    with pytest.raises(ValueError, match="至少"):
        engineering_hits(joint, [], 1, 1, 0.1, 0.1)


@pytest.mark.parametrize("epsQ,epsA", [(0, 0.1), (0.1, 0), (-1, 0.1), (0.1, float("nan"))])
def test_invalid_engineering_margins_are_rejected(epsQ, epsA):
    with pytest.raises(ValueError):
        engineering_hits([], [[]], 1, 1, epsQ, epsA)


def test_bootstrap_matches_registered_rng_resamples_and_quantile_method():
    differences = np.array([-2.0, -0.5, 0.1, 1.0, 3.0])
    saved = differences.copy()
    rng = np.random.Generator(np.random.PCG64(271828))
    indices = rng.integers(0, 5, size=(10000, 5))
    expected = np.quantile(differences[indices].mean(axis=1), [0.025, 0.975], method="linear")
    result = paired_bootstrap(differences)
    assert result == paired_bootstrap(differences)
    assert result["mean"] == float(differences.mean())
    assert result["lower"] == float(expected[0])
    assert result["upper"] == float(expected[1])
    assert result["n"] == 5
    np.testing.assert_array_equal(differences, saved)
    assert set(result) == {"mean", "lower", "upper", "n"}


def test_bootstrap_all_zero_is_exact_and_does_not_change_global_rng():
    old = np.random.get_state()
    try:
        np.random.seed(123)
        expected_next = np.random.random()
        np.random.seed(123)
        assert paired_bootstrap([0.0] * 5) == {
            "mean": 0.0, "lower": 0.0, "upper": 0.0, "n": 5
        }
        assert np.random.random() == expected_next
    finally:
        np.random.set_state(old)


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")], [True], [[1, 2]]])
def test_bootstrap_rejects_empty_or_nonfinite_differences(values):
    with pytest.raises(ValueError):
        paired_bootstrap(values)
