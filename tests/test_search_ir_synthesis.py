import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from search_ir_dev_fixtures import make_candidate
from search_ir import synthesize as synth


def mapped_fixture():
    ports = {}
    index = 2
    for name, (direction, width) in synth.EXPECTED_PORTS.items():
        ports[name] = {"direction": direction, "bits": list(range(index, index + width))}
        index += width
    cells = {
        "generated_name": {"type": "INV_X1", "parameters": {},
                           "port_directions": {"A": "input", "ZN": "output"},
                           "connections": {"A": [2], "ZN": [3]}, "attributes": {"src": "tmp/a.v:1"}},
    }
    stat = {"modules": {"\\top": {"num_cells": 1, "num_cells_by_type": {"INV_X1": 1}, "area": 0.532}}}
    netlist = {"modules": {"top": {"ports": ports, "cells": cells}}}
    return stat, netlist, {"INV_X1": 0.532}


def test_stat_area_and_cell_counts_are_cross_checked_with_json_netlist():
    stat, netlist, areas = mapped_fixture()
    result = synth.validate_mapped_result(stat, netlist, areas)
    assert result["area_um2"] == 0.532
    assert result["cells_by_type"] == {"INV_X1": 1}
    assert result["library_area_sum_um2"] == 0.532
    changed = copy.deepcopy(netlist)
    cell = changed["modules"]["top"]["cells"].pop("generated_name")
    cell["attributes"]["src"] = "other/path.v:999"
    changed["modules"]["top"]["cells"]["different_instance_name"] = cell
    same = synth.validate_mapped_result(stat, changed, areas)
    assert result["netlist_semantic_sha256"] == same["netlist_semantic_sha256"]
    cell["connections"]["A"] = [4]
    different = synth.validate_mapped_result(stat, changed, areas)
    assert result["netlist_semantic_sha256"] != different["netlist_semantic_sha256"]


@pytest.mark.parametrize("fault", ["nan", "negative", "zero", "missing_area", "wrong_area", "count", "generic", "unknown", "memory", "fcw"])
def test_rejects_incomplete_or_inconsistent_mapping(fault):
    stat, netlist, areas = mapped_fixture()
    top = stat["modules"]["\\top"]
    if fault == "nan":
        top["area"] = float("nan")
    elif fault == "negative":
        top["area"] = -1
    elif fault == "zero":
        top["area"] = 0
    elif fault == "missing_area":
        del top["area"]
    elif fault == "wrong_area":
        top["area"] += 1
    elif fault == "count":
        top["num_cells_by_type"]["INV_X1"] = 2
    elif fault in ("generic", "unknown"):
        netlist["modules"]["top"]["cells"]["generated_name"]["type"] = "$add" if fault == "generic" else "CUSTOM"
    elif fault == "memory":
        netlist["modules"]["top"]["memories"] = {"rom": {}}
    else:
        del netlist["modules"]["top"]["ports"]["fcw"]
    with pytest.raises(synth.SynthesisError):
        synth.validate_mapped_result(stat, netlist, areas)


def fake_contract_and_binding(tmp_path):
    abc = "/absolute/abc"
    script = synth.synthesis_script(abc)
    library = b"cell (INV_X1) { area : 0.532; }"
    (tmp_path / "cells.lib").write_bytes(library)
    rtl = "module top; endmodule\n"
    contract = {"yosys": {"path": "/absolute/yosys"}, "abc": {"path": abc},
                "timeout_seconds": 600, "liberty": {"sha256": synth._sha(library)},
                "script": script, "script_sha256": synth._sha(script.encode())}
    binding = {"rtl_sha256": synth._sha(rtl.encode()), "contract_sha256": synth._digest(contract)}
    return contract, binding, rtl


@pytest.mark.parametrize("outcome", ["nonzero", "timeout", "missing", "drift"])
def test_failed_process_or_inputs_never_produce_area(tmp_path, monkeypatch, outcome):
    contract, binding, rtl = fake_contract_and_binding(tmp_path)
    monkeypatch.setattr(synth, "_check_contract", lambda c: None)

    def process(command, directory, timeout):
        assert command[0] == "/absolute/yosys" and timeout == 600
        stat, netlist, _ = mapped_fixture()
        if outcome != "missing":
            (directory / "stat.json").write_text(json.dumps(stat))
            (directory / "mapped.json").write_text(json.dumps(netlist))
        if outcome == "drift":
            (directory / "design.v").write_text("changed")
        return {"returncode": 1 if outcome == "nonzero" else 0,
                "timed_out": outcome == "timeout", "wall_seconds": 0.1}

    monkeypatch.setattr(synth, "_run_process", process)
    result = synth.run_job(tmp_path / "job", binding, contract, rtl, {"INV_X1": 0.532})
    assert result["status"] == "failed" and result["area_um2"] is None
    assert (tmp_path / "job/result.json").is_file()
    with pytest.raises(FileExistsError):
        synth.run_job(tmp_path / "job", binding, contract, rtl, {"INV_X1": 0.532})


def test_timeout_cleans_process_group_and_keeps_logs(tmp_path, monkeypatch):
    process = Mock(pid=12345, returncode=-9)
    process.wait.side_effect = [synth.subprocess.TimeoutExpired("yosys", 600), None]
    popen = Mock(return_value=process)
    kill = Mock()
    monkeypatch.setattr(synth.subprocess, "Popen", popen)
    monkeypatch.setattr(synth.os, "killpg", kill)
    result = synth._run_process(["/absolute/yosys"], tmp_path, 600)
    assert popen.call_args.kwargs["start_new_session"] is True
    kill.assert_called_once_with(12345, synth.signal.SIGKILL)
    assert result["timed_out"] is True and result["returncode"] == -9
    assert (tmp_path / "stdout.log").exists() and (tmp_path / "stderr.log").exists()


def test_absolute_abc_path_is_the_one_used_in_script():
    text = synth.synthesis_script("/opt/tools/yosys-abc")
    assert 'abc -exe "/opt/tools/yosys-abc"' in text
    assert "write_json mapped.json" in text and "stat -json" in text
    assert "-flatten" in text and "check -mapped -assert" in text
    with pytest.raises(synth.SynthesisError):
        synth.synthesis_script("yosys-abc")


def test_liberty_area_parser_uses_cell_scopes():
    text = '/* cell (FAKE) { area: 99; } */ cell (INV_X1) { area : 0.532; pin(A){} } cell (BUF_X1) { area: 1.064; }'
    assert synth.liberty_areas(text) == {"INV_X1": 0.532, "BUF_X1": 1.064}
    with pytest.raises(synth.SynthesisError):
        synth.liberty_areas("cell (MISSING) { pin (A) {} }")


@pytest.mark.parametrize("fail_first,repeat_drift", [(False, False), (True, False), (False, True)])
def test_all_candidates_are_frozen_before_jobs_and_failures_stop_run(tmp_path, monkeypatch, fail_first, repeat_drift):
    contract, _, _ = fake_contract_and_binding(tmp_path)
    contract["liberty"]["path"] = str(tmp_path / "cells.lib")
    monkeypatch.setattr(synth, "build_contract", lambda: contract)
    seen = []

    def job(directory, binding, actual_contract, rtl, areas):
        manifest = json.loads((directory.parent / "manifest.json").read_text())
        assert len(manifest["candidates"]) == 3
        assert all(c["hq"] and c["fir_mask"]["legal"] for c in manifest["candidates"])
        assert manifest["attempt_candidate_indices"] == [0, 1, 2, 0]
        assert binding["manifest_sha256"] == synth._sha((directory.parent / "manifest.json").read_bytes())
        seen.append(binding["candidate_hash"])
        result = {"binding": binding, "status": "failed" if fail_first else "ok",
                "area_um2": None if fail_first else 1.0, "cells_by_type": {"INV_X1": 1},
                "stat_top_sha256": "same",
                "netlist_semantic_sha256": "changed" if repeat_drift and len(seen) == 4 else "same"}
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps(result))
        return result

    monkeypatch.setattr(synth, "run_job", job)
    path = synth.run_smoke("fixed", tmp_path / "out")
    result = json.loads(path.read_text())
    assert len(seen) == (1 if fail_first else 4)
    if not fail_first:
        assert seen[0] == seen[3]
        assert result["repeat"]["area_um2"] is True
        assert result["repeat"]["all_equal"] is (not repeat_drift)
    assert result["status"] == ("ok" if not fail_first and not repeat_drift else "incomplete_or_mismatch")
    assert result["formal_gate_passed"] is False
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        synth.run_smoke("fixed", tmp_path / "out")
    assert path.read_bytes() == before


def test_scopeinfo_cleanup_does_not_disable_mapped_check():
    lines = synth.synthesis_script("/absolute/abc").splitlines()
    assert "delete t:$scopeinfo" in lines
    assert lines.index("delete t:$scopeinfo") < lines.index("check -mapped -assert")
    assert not any(line.startswith("delete t:$") and line != "delete t:$scopeinfo" for line in lines)


def test_incremental_dispatch_cannot_retry_started_jobs(tmp_path, monkeypatch):
    contract, _, _ = fake_contract_and_binding(tmp_path)
    contract["liberty"]["path"] = str(tmp_path / "cells.lib")
    monkeypatch.setattr(synth, "build_contract", lambda: contract)
    root = synth.prepare_smoke("started", tmp_path / "out")
    (root / "job-01").mkdir()
    with pytest.raises(synth.SynthesisError, match="未结束"):
        synth.run_next_job("started", tmp_path / "out")
    assert not (root / "job-02").exists()
