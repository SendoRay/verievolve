import copy
import json

import numpy as np
import pytest

from search_ir_dev_fixtures import make_candidate, make_case
from search_ir import dev_run
from search_ir.dev_run import DevRun


def _read(path):
    return json.loads(path.read_text())


def test_end_to_end_fixture_run_persists_identity_and_counts_duplicates(tmp_path):
    run = DevRun(tmp_path, "smoke", [make_case()], max_attempts=2)
    raw = json.dumps(make_candidate())
    first, second = run.submit(raw), run.submit(raw)
    assert first["status"] == second["status"] == "ok"
    assert first["candidate_hash"] == second["candidate_hash"]
    assert first["attempt_id"] == 1 and second["attempt_id"] == 2
    manifest = _read(run.path / "manifest.json")
    assert manifest["context_sha256"] == first["context_sha256"]
    assert manifest["context"]["cache_enabled"] is False
    assert manifest["context"]["formal_truth_allowed"] is False
    assert manifest["context"]["sources"]
    assert _read(run.path / "result-0001.json") == first
    with np.load(run.path / "input-000.npz", allow_pickle=False) as data:
        np.testing.assert_array_equal(data["i12"], make_case().i12)
    events = [json.loads(line) for line in (run.path / "attempts.jsonl").read_text().splitlines()]
    assert [x["event"] for x in events] == ["attempt_started", "attempt_finished"] * 2
    assert sum(x["budget_units"] for x in events) == 2
    assert events[0]["raw_proposal"] == raw
    with pytest.raises(RuntimeError, match="预算"):
        run.submit(raw)


def test_invalid_json_is_recorded_before_parse_and_does_not_poison_next_attempt(tmp_path):
    run = DevRun(tmp_path, "invalid", [make_case()], max_attempts=5)
    invalid = ["{", '{"kind":"x","kind":"y"}', '{"value":NaN}', '{"value":1e999}']
    for raw in invalid:
        result = run.submit(raw)
        assert result["status"] == "invalid_proposal" and result["stage"] == "parse"
        assert result["candidate_hash"] is None
    assert run.submit(json.dumps(make_candidate()))["status"] == "ok"
    events = [json.loads(line) for line in (run.path / "attempts.jsonl").read_text().splitlines()]
    assert sum(x["budget_units"] for x in events) == 5


def test_invalid_schema_and_mask_failure_are_distinct(tmp_path):
    run = DevRun(tmp_path, "failures", [make_case()], max_attempts=2)
    invalid = make_candidate()
    invalid["mixer"]["product_drop"] = False
    result = run.submit(json.dumps(invalid))
    assert result["status"] == "invalid_proposal" and result["stage"] == "validate"
    result = run.submit(json.dumps(make_candidate(coefficient_bits=8)))
    assert result["status"] == "mask_failed"
    assert result["evaluation"]["Q_dev"] is None


def test_same_context_has_separate_run_identity_and_run_ids_cannot_be_reused(tmp_path):
    cases = [make_case()]
    first = DevRun(tmp_path, "first", cases, max_attempts=1)
    second = DevRun(tmp_path, "second", cases, max_attempts=1)
    a, b = _read(first.path / "manifest.json"), _read(second.path / "manifest.json")
    assert a["context_sha256"] == b["context_sha256"]
    assert a["run_id"] != b["run_id"]
    before = (first.path / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        DevRun(tmp_path, "first", cases, max_attempts=1)
    assert (first.path / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("run_id", ["../escape", ".", "a/b", "", "a" * 65])
def test_bad_run_id_cannot_escape_output_root(tmp_path, run_id):
    with pytest.raises(ValueError):
        DevRun(tmp_path, run_id, [make_case()], max_attempts=1)


def test_historical_output_root_is_forbidden():
    with pytest.raises(ValueError, match="历史"):
        DevRun(dev_run.BENCH / "experiments_system", "forbidden", [make_case()], max_attempts=1)


@pytest.mark.parametrize("target", ["manifest", "inputs", "context", "sources"])
def test_context_drift_fails_closed_and_is_recorded(tmp_path, monkeypatch, target):
    run = DevRun(tmp_path, "drift", [make_case()], max_attempts=2)
    if target == "manifest":
        with (run.path / "manifest.json").open("a") as f:
            f.write(" ")
    elif target == "inputs":
        with (run.path / "input-000.npz").open("ab") as f:
            f.write(b"drift")
    elif target == "context":
        original = dev_run.build_context

        def drift(cases):
            value = original(cases)
            value["quality"]["alignment"] = "changed"
            return value

        monkeypatch.setattr(dev_run, "build_context", drift)
    else:
        monkeypatch.setattr(dev_run, "_source_fingerprints", lambda: [])
    result = run.submit(json.dumps(make_candidate()))
    assert result["status"] == "evaluation_failed" and result["stage"] == "context"
    assert "evaluation" not in result
    with pytest.raises(RuntimeError, match="封闭"):
        run.submit(json.dumps(make_candidate()))


@pytest.mark.parametrize("fault", ["exception", "candidate", "cases", "post_context"])
def test_evaluation_failure_and_wrong_echo_cannot_be_reported_as_success(tmp_path, monkeypatch, fault):
    run = DevRun(tmp_path, "broken", [make_case()], max_attempts=1)
    original = dev_run.evaluate_candidate

    def broken(*args):
        if fault == "exception":
            raise RuntimeError("mock model failure")
        result = original(*args)
        if fault == "candidate":
            result["candidate_hash"] = "wrong"
        elif fault == "cases":
            result["rows"][0]["case_identity"]["fcw"] += 1
        else:
            with (run.path / "manifest.json").open("a") as f:
                f.write(" ")
        return result

    monkeypatch.setattr(dev_run, "evaluate_candidate", broken)
    result = run.submit(json.dumps(make_candidate()))
    assert result["status"] == "evaluation_failed"
    assert "evaluation" not in result
    assert _read(run.path / "result-0001.json") == result


def test_runtime_snapshots_caller_inputs(tmp_path):
    case = make_case()
    run = DevRun(tmp_path, "copy", [case], max_attempts=1)
    case.i12[:] = 0
    assert run.submit(json.dumps(make_candidate()))["status"] == "ok"


@pytest.mark.parametrize("fault", ["nan", "wrong_q", "missing", "duplicate"])
def test_run_boundary_validates_quality_and_complete_coverage(tmp_path, monkeypatch, fault):
    run = DevRun(tmp_path, "quality", [make_case("a"), make_case("b")], max_attempts=1)
    original = dev_run.evaluate_candidate

    def broken(*args):
        result = original(*args)
        if fault == "nan":
            result["rows"][0]["q_aligned"] = float("nan")
        elif fault == "wrong_q":
            result["Q_dev"] += 1
        elif fault == "missing":
            result["rows"].pop()
        else:
            result["rows"][1] = copy.deepcopy(result["rows"][0])
        return result

    monkeypatch.setattr(dev_run, "evaluate_candidate", broken)
    result = run.submit(json.dumps(make_candidate()))
    assert result["status"] == "evaluation_failed"
    assert "evaluation" not in result


@pytest.mark.parametrize("filename", ["candidate-0001.json", "result-0001.json"])
def test_artifact_collision_never_overwrites_and_seals_run(tmp_path, filename):
    run = DevRun(tmp_path, "collision", [make_case()], max_attempts=2)
    (run.path / filename).write_text("keep this")
    if filename.startswith("result"):
        with pytest.raises(FileExistsError):
            run.submit(json.dumps(make_candidate()))
    else:
        result = run.submit(json.dumps(make_candidate()))
        assert result["status"] == "evaluation_failed"
        assert result["stage"] == "persist_candidate"
    assert (run.path / filename).read_text() == "keep this"
    with pytest.raises(RuntimeError, match="封闭"):
        run.submit(json.dumps(make_candidate()))


def test_attempt_is_persisted_before_parser_is_called(tmp_path, monkeypatch):
    run = DevRun(tmp_path, "ordering", [make_case()], max_attempts=1)
    original = dev_run._strict_json

    def inspect(raw):
        events = (run.path / "attempts.jsonl").read_text().splitlines()
        assert len(events) == 1
        event = json.loads(events[0])
        assert event["event"] == "attempt_started" and event["budget_units"] == 1
        return original(raw)

    monkeypatch.setattr(dev_run, "_strict_json", inspect)
    assert run.submit(json.dumps(make_candidate()))["status"] == "ok"
