import copy
import json
from pathlib import Path

import pytest

from search_ir_dev_fixtures import make_candidate
from search_ir.canonicalize import candidate_hash
from search_ir.formal_state import FormalState
from search_ir.selection import family_key


def record(kind="lut", q=1e-6, area=1.0):
    candidate = make_candidate(kind)
    return {"candidate": candidate, "candidate_hash": candidate_hash(candidate), "Q": q, "area_um2": area}


def test_budget32_locks_at_16_not_6_and_rotates_from_17():
    state = FormalState(101, "staged", budget=32)
    for i, kind in enumerate(("lut", "cordic", "compose"), 1):
        state.update(record(kind), i)
    for i in range(4, 16):
        state.update(None, i)
        assert state.families is None
    state.update(None, 16)
    assert len(state.families) == 3
    assert state.phase(16) == "structure" and state.phase(17) == "numeric"
    proposal = state.candidate(17)
    assert proposal["parent_hash"] in state.history
    assert family_key(state.history[proposal["parent_hash"]]["candidate"]) == state.families[0]
    state.update(None, 17)
    second = state.candidate(18)
    assert family_key(state.history[second["parent_hash"]]["candidate"]) == state.families[1]


def test_cost_first_rotates_targets_without_using_quality_for_ranking():
    left = FormalState(101, "cost-first", budget=32)
    right = FormalState(101, "cost-first", budget=32)
    for i, kind in enumerate(("lut", "cordic", "compose"), 1):
        left.update(record(kind, q=i*1e-6, area=float(i)), i)
        right.update(record(kind, q=(4-i)*1e-6, area=float(i)), i)
    assert [left.quality_target(i) / left.q_budget for i in (4, 5, 6, 7)] == [0.25, 0.5, 1.0, 0.25]
    assert left.candidate(4) == right.candidate(4)


def test_cost_first_no_eligible_parent_is_not_a_free_seed():
    state = FormalState(101, "cost-first", budget=32)
    for i, kind in enumerate(("lut", "cordic", "compose"), 1):
        state.update(record(kind, q=1.0), i)
    with pytest.raises(ValueError, match="no eligible parent"):
        state.candidate(4)
    assert len(state.history) == 3


def test_state_rejects_wrong_attempt_order_or_phase():
    state = FormalState(101, "joint")
    with pytest.raises(ValueError):
        state.candidate(2)
    with pytest.raises(ValueError):
        state.candidate(1, "mixed")
    with pytest.raises(ValueError):
        state.update(record(), 2)


PILOT = Path(__file__).resolve().parents[1] / "examples/comm_dsp_bench/experiments_search/pilot/paired-pilot-v2-20261002"


@pytest.mark.skipif(not (PILOT / "results.json").exists(), reason="需要已有pilot产物；仅做只读回放")
def test_budget12_reproduces_all_72_saved_pilot_transitions():
    result = json.loads((PILOT / "results.json").read_text())
    manifest = json.loads((PILOT / "manifest.json").read_text())
    q_budget = manifest["draft"]["evaluation"]["q_budget"]
    states = {(seed, arm): FormalState(seed, arm, budget=12, q_budget=q_budget)
              for seed in (11, 29, 47) for arm in ("joint", "staged")}
    for trial in result["trials"]:
        index = trial["proposal_id"]
        stored = json.loads((PILOT / f"proposals/{index:04d}.json").read_text())
        state = states[(trial["seed"], trial["arm"])]
        assert state.rng.bit_generator.state == stored["rng_before"]
        proposal = state.candidate(trial["attempt"], trial["phase"])
        assert all(proposal[key] == stored[key] for key in proposal)
        rec = None
        if trial["status"] == "ok":
            rec = {"candidate": stored["candidate"], "candidate_hash": trial["candidate_hash"],
                   "Q": trial["Q"], "area_um2": trial["area"]["area_um2"]}
        state.update(rec, trial["attempt"])
        snapshot = json.loads((PILOT / f"states/{index:04d}.json").read_text())
        assert state.snapshot(q_budget) == snapshot
    for key, state in states.items():
        assert state.snapshot(q_budget) == result["arms"][f"{key[0]}-{key[1]}"]
