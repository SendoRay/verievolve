import copy
import json
import time
from pathlib import Path

import numpy as np
import pytest

from search_ir_dev_fixtures import make_candidate
from search_ir import pilot
from search_ir.canonicalize import candidate_hash
from search_ir.validate import IRValidationError, validate_candidate


def toy_record(candidate):
    return {"candidate": candidate, "candidate_hash": candidate_hash(candidate),
            "Q": 1e-6, "area_um2": 1.0}


def test_arm_rng_is_independent_and_schedule_order_does_not_change_stream():
    joint = pilot.ArmState(11, "joint")
    staged = pilot.ArmState(11, "staged")
    untouched = copy.deepcopy(staged.rng.bit_generator.state)
    joint.rng.random(30)
    assert staged.rng.bit_generator.state == untouched
    reference = np.random.Generator(np.random.PCG64(11))
    assert staged.rng.random() == reference.random()


def test_state_locks_after_six_attempts_and_retains_current_family_members():
    state = pilot.ArmState(11, "staged")
    for i, candidate in enumerate(pilot.development_candidates(), 1):
        state.update(toy_record(candidate), i)
    for i in range(4, 7):
        state.update(None, i)
    assert len(state.families) == 3
    original_order = list(state.families)
    candidate = copy.deepcopy(state.population[0]["candidate"])
    candidate["filter_decimator"]["coefficient_bits"] = 14
    improved = {**toy_record(candidate), "Q": 1e-7, "area_um2": 0.5}
    state.update(improved, 7)
    assert state.families == original_order
    assert improved["candidate_hash"] in {x["candidate_hash"] for x in state.population}
    assert len(state.population) <= 8
    json.dumps(state.snapshot(1e-5), allow_nan=False)


def fake_cache(tmp_path, monkeypatch):
    cache = pilot.AreaCache.__new__(pilot.AreaCache)
    cache.root = tmp_path
    cache.entries = {}
    library = b"cell (INV_X1) { area: 0.532; }"
    cache.contract = {
        "yosys": {"sha256": "yosys"}, "abc": {"sha256": "abc"},
        "liberty": {"sha256": pilot.synth._sha(library)},
        "script_sha256": "script", "timeout_seconds": 600,
    }
    for name in ("cache", "synthesis", "contracts"):
        (tmp_path / name).mkdir()
    (tmp_path / "synthesis/cells.lib").write_bytes(library)
    monkeypatch.setattr(pilot.synth, "_check_contract", lambda c: None)
    return cache


@pytest.mark.parametrize("remaining,expected", [(50, "global_deadline"), (800, "candidate_timeout")])
def test_global_deadline_is_not_censored_candidate_timeout(tmp_path, monkeypatch, remaining, expected):
    cache = fake_cache(tmp_path, monkeypatch)
    seen = []

    def timeout(directory, binding, contract, rtl, areas):
        seen.append(contract["timeout_seconds"])
        row = {"status": "failed", "process": {"timed_out": True, "wall_seconds": contract["timeout_seconds"]}}
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps(row))
        return row

    monkeypatch.setattr(pilot.synth, "run_job", timeout)
    result = cache.get(make_candidate(), 1, time.monotonic() + remaining)
    assert result["status"] == expected
    assert 0 < seen[0] <= min(remaining, 600)
    assert ("cost_sample_seconds" in result) is (expected == "candidate_timeout")
    assert not cache.entries


def test_successful_cache_hit_reuses_area_but_checks_source_identity(tmp_path, monkeypatch):
    cache = fake_cache(tmp_path, monkeypatch)
    calls = []

    def success(directory, binding, contract, rtl, areas):
        calls.append(1)
        directory.mkdir()
        row = {"status": "ok", "area_um2": 1.5, "binding": binding,
               "artifacts": {}, "process": {"timed_out": False, "wall_seconds": 0.1}}
        (directory / "result.json").write_text(json.dumps(row))
        return row

    monkeypatch.setattr(pilot.synth, "run_job", success)
    first = cache.get(make_candidate(), 1, time.monotonic() + 800)
    second = cache.get(make_candidate(), 2, time.monotonic() + 800)
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert len(calls) == 1 and second["area_um2"] == 1.5
    (tmp_path / "synthesis/job-0001/result.json").write_text("changed")
    with pytest.raises(Exception, match="漂移"):
        cache.get(make_candidate(), 3, time.monotonic() + 800)


class FakeQuality:
    def __init__(self, root, name, cases, max_attempts):
        self._attempts = 0

    def submit(self, raw):
        self._attempts += 1
        candidate = json.loads(raw)
        try:
            validate_candidate(candidate)
        except IRValidationError:
            return {"attempt_id": self._attempts, "status": "invalid_proposal", "candidate_hash": None}
        return {"attempt_id": self._attempts, "status": "ok", "candidate_hash": candidate_hash(candidate),
                "evaluation": {"Q_dev": 1e-6, "rows": [{"n_sat_mix": 0, "n_sat_fir": 0}]}}


@pytest.mark.parametrize("mode", ["ok", "global_deadline", "candidate_timeout", "infrastructure", "interrupt"])
def test_paired_driver_budget_and_failures_use_only_mock_evaluation(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(pilot, "PILOT_ROOT", tmp_path)
    monkeypatch.setattr(pilot, "_check_calibration", lambda _: {"mock": True})
    monkeypatch.setattr(pilot, "main_cases", lambda _: ["mock case, not a main waveform"])
    monkeypatch.setattr(pilot.synth, "build_contract", lambda: {"mock": True})
    monkeypatch.setattr(pilot, "DevRun", FakeQuality)

    class Cache:
        def __init__(self, *args):
            self.calls = 0

        def get(self, candidate, proposal_id, deadline):
            self.calls += 1
            if self.calls == 4 and mode == "infrastructure":
                raise RuntimeError("mock tool failure")
            if self.calls == 4 and mode == "interrupt":
                raise KeyboardInterrupt("mock cancellation")
            if self.calls == 4 and mode in ("global_deadline", "candidate_timeout"):
                return {"status": mode, "cache_hit": False, "wall_seconds": 600,
                        **({"cost_sample_seconds": 600} if mode == "candidate_timeout" else {})}
            return {"status": "ok", "cache_hit": True, "area_um2": 1.0}

    monkeypatch.setattr(pilot, "AreaCache", Cache)
    path = pilot.run_pilot("mock", Path("unused"))
    result = json.loads(path.read_text())
    if mode in ("ok", "candidate_timeout"):
        assert result["status"] == "pilot_completed" and result["budget_charged"] == 72
        assert len(result["trials"]) == 72
        for seed in (11, 29, 47):
            for arm in ("joint", "staged"):
                rows = [r for r in result["trials"] if r["seed"] == seed and r["arm"] == arm]
                assert [r["attempt"] for r in rows] == list(range(1, 13))
    else:
        assert result["status"] == "incomplete" and result["budget_charged"] == 4
        assert len(result["trials"]) == 4
        assert result["formal_budget_recommendation"] is None
    assert result["uncached_synthesis_costs"] == ([600] if mode == "candidate_timeout" else [])
    assert result["S"] == result["L"] == "N/A"
    with pytest.raises(FileExistsError):
        pilot.run_pilot("mock", Path("unused"))


def test_watch_exited_worker_does_not_poll_or_launch_anything(tmp_path):
    (tmp_path / "launch.json").write_text('{"pid":1}')
    (tmp_path / "exit.json").write_text('{"exit_code":0,"result_status":"pilot_completed"}')
    assert pilot.watch(tmp_path, 1)["status"] == "exited"


@pytest.mark.parametrize("changed", [None, "yosys", "abc", "liberty", "script"])
def test_initial_cache_cannot_relabel_history_under_new_toolchain(tmp_path, monkeypatch, changed):
    historical = tmp_path / "historical"
    historical.mkdir()
    library = tmp_path / "cells.lib"
    library.write_text("cell (INV_X1) { area: 0.532; }")
    contract = {"yosys": {"sha256": "old-y"}, "abc": {"sha256": "old-a"},
                "liberty": {"sha256": pilot._hash(library), "path": str(library)},
                "script_sha256": "old-script"}
    (historical / "manifest.json").write_text(json.dumps({"contract": contract}))
    configs = pilot.development_candidates()
    areas = {candidate_hash(c): 1.0 for c in configs}
    (historical / "results.json").write_text(json.dumps({"rows": [{"area_um2": 1.0} for c in configs]}))
    monkeypatch.setattr(pilot, "verified_areas", lambda *args: {"areas": areas})
    stored = []
    monkeypatch.setattr(pilot.AreaCache, "_store", lambda self, key, row, path: stored.append(key))
    current = copy.deepcopy(contract)
    if changed == "script":
        current["script_sha256"] = "different"
    elif changed:
        current[changed]["sha256"] = "different"
    target = tmp_path / "new"
    target.mkdir()
    if changed:
        with pytest.raises(Exception, match="不得重新标记"):
            pilot.AreaCache(target, current, historical)
        assert not stored
    else:
        pilot.AreaCache(target, current, historical)
        assert len(stored) == 3


def test_launcher_sets_package_cwd_without_relying_on_parent_sys_path(tmp_path, monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(pilot, "CAL_ROOT", tmp_path)
    popen = Mock(return_value=Mock(pid=12345))
    monkeypatch.setattr(pilot.subprocess, "Popen", popen)
    directory = pilot.launch("calibration", "launch-test")
    assert popen.call_args.kwargs["cwd"] == pilot.BENCH
    assert popen.call_args.kwargs["start_new_session"] is True
    assert "--launch-dir" in popen.call_args.args[0]
    assert (directory / "launch.json").is_file()
