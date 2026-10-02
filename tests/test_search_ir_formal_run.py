import copy
import json
from pathlib import Path

import pytest

from search_ir_dev_fixtures import make_case, make_candidate
from search_ir import formal_run as formal


def test_numeric_context_has_formal_scope_and_detects_snapshot_drift(tmp_path, monkeypatch):
    case = make_case("one")
    monkeypatch.setattr(formal, "_cases", lambda *args: [case])
    context = formal.NumericContext(tmp_path / "numeric", "main", {"scenarios": [{"key": "one"}]})
    assert context.context["formal_truth_allowed"] is True
    raw, source = context.score(make_candidate(), "one")
    assert raw["status"] == "ok" and Path(source["path"]).exists()
    (context.path / "input-000.npz").write_bytes(b"changed")
    with pytest.raises(Exception, match="快照漂移"):
        context.score(make_candidate(), "two")


def test_numeric_context_rejects_case_coverage_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(formal, "_cases", lambda *args: [make_case("wrong")])
    with pytest.raises(Exception, match="覆盖"):
        formal.NumericContext(tmp_path / "bad", "main", {"scenarios": [{"key": "expected"}]})


def test_formal_schedule_has_exactly_32_attempts_per_seed_arm():
    rows = formal.schedule(("joint", "staged"))
    assert len(rows) == 320
    for seed in formal.SEEDS:
        for arm in ("joint", "staged"):
            assert [r["attempt"] for r in rows if r["seed"] == seed and r["arm"] == arm] == list(range(1, 33))
    assert len(formal.schedule(("cost-first",))) == 160


@pytest.mark.parametrize("scenario", ["S0", "S1", "insufficient_common", "deadline", "error"])
def test_formal_lifecycle_uses_mock_scores_and_respects_stop_rule(tmp_path, monkeypatch, scenario):
    monkeypatch.setattr(formal, "OUTPUT", tmp_path / "out")
    for name in ("PROTOCOL", "VERIFIER", "PILOT_AUDIT"):
        path = tmp_path / name
        path.write_text("mock")
        monkeypatch.setattr(formal, name, path)
    verification = tmp_path / "verification"
    verification.mkdir()
    (verification / "manifest.json").write_text("{}")
    (verification / "report.json").write_text("{}")
    monkeypatch.setattr(formal, "VERIFICATION", verification)
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "results.json").write_text("{}")
    monkeypatch.setattr(formal, "PILOT", pilot)
    monkeypatch.setattr(formal.synth, "build_contract", lambda: {"mock": True})
    monkeypatch.setattr(formal, "_ready", lambda _: {"path": "mock", "sha256": "mock"})
    monkeypatch.setattr(formal, "_calibration_record", lambda _: {"path": "mock", "sha256": "mock"})
    monkeypatch.setattr(formal, "_split_definition", lambda split: {"mock": split})
    monkeypatch.setattr(formal, "_guard", lambda *args: None)
    calls = {"heldout": 0, "main": 0, "area": 0, "proof": 0}

    class Numeric:
        def __init__(self, directory, split, definition):
            self.path, self.split = directory, split
            directory.mkdir()
            (directory / "manifest.json").write_text("{}")
        def score(self, candidate, label):
            calls[self.split] += 1
            if self.split == "heldout":
                phase = self.path.parent
                assert (phase / "archive_lock.json").is_file()
                ledger = [json.loads(line) for line in (phase / "ledger.jsonl").read_text().splitlines()]
                starts = [r for r in ledger if r["event"] == "attempt_started"]
                assert len(starts) == (320 if phase.name == "joint-staged" else 160)
            return {"status": "ok", "Q_dev": 1e-6, "rows": [{"n_sat_mix": 0, "n_sat_fir": 0}]}, {"mock": True}

    class Cache:
        def __init__(self, root, contract):
            self.warm_index = []
        def get(self, candidate, proposal_id, deadline):
            calls["area"] += 1
            if scenario == "deadline":
                return {"status": "global_deadline"}
            if scenario == "error":
                raise RuntimeError("mock infrastructure error")
            return {"status": "ok", "cache_hit": True, "area_um2": 1.0}

    class Checks:
        def __init__(self, directory):
            self.tools = {}
        def verify(self, *args):
            calls["proof"] += 1
            return {"mock": True}

    monkeypatch.setattr(formal, "NumericContext", Numeric)
    monkeypatch.setattr(formal, "WarmAreaCache", Cache)
    monkeypatch.setattr(formal, "RTLChecks", Checks)
    if scenario in ("S1", "insufficient_common"):
        monkeypatch.setattr(formal, "comparison", lambda *args: {"necessary_pass": True, "bootstrap": {"lower": 0.1}})
        hits = iter([[{"mock": True}]] * 5 if scenario == "S1" else [[{"mock": True}], [], [], [], []])
        monkeypatch.setattr(formal, "engineering_hits", lambda *args: next(hits))
    path = formal.execute("test")
    result = json.loads(path.read_text())
    first = json.loads((path.parent / "joint-staged/main_results.json").read_text())
    if scenario in ("deadline", "error"):
        assert result["status"] == "inconclusive" and result["S"] == "N/A"
        assert first["charged"] == 1
        assert calls["heldout"] == 0
        assert not (path.parent / "cost-first").exists()
    else:
        expected_s = "S0" if scenario == "insufficient_common" else scenario
        assert result["status"] == "formal_completed" and result["S"] == expected_s
        assert first["charged"] == 320
        assert all(len([t for t in first["trials"] if t["seed"] == seed and t["arm"] == arm]) == 32
                   for seed in formal.SEEDS for arm in ("joint", "staged"))
        if scenario == "S0":
            assert not (path.parent / "cost-first").exists()
            assert result["cost_first"].startswith("not-run")
        else:
            second = json.loads((path.parent / "cost-first/main_results.json").read_text())
            assert second["charged"] == 160
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        formal.execute("test")
    assert path.read_bytes() == original


has_pilot = pytest.mark.skipif(not (formal.PILOT / "results.json").exists(), reason="需要已有pilot，仅检查只读来源")


@has_pilot
def test_warm_cache_imports_all_and_only_audited_successes(tmp_path):
    contract = copy.deepcopy(json.loads((formal.PILOT / "manifest.json").read_text())["contract"])
    contract["sources"] = formal.synth._sources()
    cache = formal.WarmAreaCache(tmp_path, contract)
    assert len(cache.entries) == 37 and len(cache.warm_index) == 37
    assert all(entry["row"]["status"] == "ok" for entry in cache.entries.values())


@has_pilot
def test_history_calibration_accepts_added_modules_not_changed_sources():
    contract = copy.deepcopy(json.loads((formal.PILOT / "manifest.json").read_text())["contract"])
    contract["sources"] = formal.synth._sources()
    record = formal._calibration_record(contract)
    assert record["epsilon_A_um2"] == formal.EPS_A
