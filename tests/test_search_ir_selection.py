import copy
import math

import numpy as np
import pytest

from search_ir_dev_fixtures import make_candidate
from search_ir.canonicalize import candidate_hash
from search_ir.selection import family_key, lock_families, main_archive, ranked, tournament, truncate


def record(i, q, area, kind="lut"):
    candidate = make_candidate(kind)
    if kind == "compose":
        candidate["nco"]["coarse"]["phase_bits"] = 8 + i
    else:
        candidate["nco"]["phase_bits"] = 8 + i
    return {"candidate": candidate, "candidate_hash": candidate_hash(candidate), "Q": q, "area_um2": area}


def test_exact_pareto_ranks_and_crowding_preserve_extremes():
    values = [record(i, q, a) for i, (q, a) in enumerate([(1, 4), (2, 3), (3, 2), (4, 1), (4, 4)])]
    snapshot = copy.deepcopy(values)
    result = ranked(values)
    front = [x for x in result if x["rank"] == 0]
    assert len(front) == 4
    assert result[-1]["rank"] == 1
    chosen = truncate(values, capacity=2)
    assert {x["Q"] for x in chosen} == {1, 4}
    assert values == snapshot


def test_ties_have_zero_crowding_and_stable_hash_order():
    values = [record(i, 1, 1) for i in range(5)]
    first = ranked(values)
    second = ranked(list(reversed(values)))
    assert first == second
    assert all(x["rank"] == 0 and x["crowding"] == 0 for x in first)
    assert [x["candidate_hash"] for x in first] == sorted(x["candidate_hash"] for x in values)


def test_duplicate_semantics_ignore_metadata_but_reject_different_scores():
    a = record(0, 1, 1)
    b = copy.deepcopy(a)
    b["candidate"]["metadata"] = {"label": "different label"}
    assert len(ranked([a, b])) == 1
    b["Q"] = 2
    with pytest.raises(ValueError, match="conflicting"):
        ranked([a, b])


@pytest.mark.parametrize("q,area", [(math.nan, 1), (1, math.inf), (-1, 1), (1, 0), (True, 1)])
def test_nonfinite_or_invalid_objectives_never_enter_selection(q, area):
    with pytest.raises(ValueError):
        ranked([record(0, q, area)])


def test_family_key_excludes_numeric_parameters_but_not_structure():
    a = make_candidate()
    b = copy.deepcopy(a)
    b["nco"]["depth"] = 1024
    b["filter_decimator"]["coefficient_bits"] = 12
    assert family_key(a) == family_key(b)
    b["nco"]["interpolation"] = "nearest"
    assert family_key(a) != family_key(b)


def test_truncation_protects_one_current_member_of_each_locked_family():
    values = [record(0, 1, 1), record(1, 2, 2, "cordic"), record(2, 10, 10, "compose")]
    families = lock_families(values)
    improved = record(3, 0.1, 0.5)
    chosen = truncate([*values, improved], capacity=3, families=families)
    assert {family_key(x["candidate"]) for x in chosen} == set(families)
    assert improved["candidate_hash"] in {x["candidate_hash"] for x in chosen}
    assert values[0]["candidate_hash"] not in {x["candidate_hash"] for x in chosen}


def test_tournament_respects_family_and_independent_rng():
    population = [record(0, 1, 1), record(1, 2, 2, "cordic")]
    family = family_key(population[1]["candidate"])
    a = np.random.Generator(np.random.PCG64(11))
    b = np.random.Generator(np.random.PCG64(11))
    assert tournament(population, a) == tournament(population, b)
    assert tournament(population, a, family)["candidate_hash"] == population[1]["candidate_hash"]
    assert tournament([population[0]], a)["candidate_hash"] == population[0]["candidate_hash"]


def test_final_archive_excludes_over_budget_but_search_can_keep_it():
    values = [record(0, 1, 5), record(1, 20, 1)]
    assert len(truncate(values)) == 2
    assert [r["Q"] for r in main_archive(values, 10)] == [1]
    assert main_archive(values, 0.5) == []
