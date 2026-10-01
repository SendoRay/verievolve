import copy
import json

import pytest

from search_ir_dev_fixtures import make_case
from search_ir import validate_main as vm
from search_ir.dev_fixtures import development_candidates
from search_ir.evaluate import EvaluationError, evaluate_candidate


def test_main_definition_is_exactly_the_frozen_grid():
    definition = vm.frozen_main_definition()
    assert len(definition["scenarios"]) == 36 and len(definition["fcw"]) == 9
    assert all(row["split"] == "main" for row in definition["scenarios"])
    assert definition["n_sym"] == 1600


def test_main_definition_drift_is_rejected(monkeypatch):
    original = vm.spec.export_witness_manifest

    def changed():
        doc = original()
        doc["n_sym"] += 1
        return doc

    monkeypatch.setattr(vm.spec, "export_witness_manifest", changed)
    with pytest.raises(EvaluationError, match="规格或完整长度"):
        vm.frozen_main_definition()


@pytest.mark.parametrize("fault", ["missing", "duplicate", "bad_q"])
def test_summary_never_renames_partial_quality_as_main(fault):
    result = evaluate_candidate(development_candidates()[0], [make_case("a"), make_case("b")])
    if fault == "missing":
        result["rows"].pop()
    elif fault == "duplicate":
        result["rows"][1] = copy.deepcopy(result["rows"][0])
    else:
        result["Q_dev"] += 1
    with pytest.raises(EvaluationError):
        vm.summarize_candidate(result, ["a", "b"], 1.0)


def test_summary_reports_saturation_without_inventing_formal_feasibility():
    result = evaluate_candidate(development_candidates()[0], [make_case("a")])
    result["rows"][0]["n_sat_fir"] = 2
    summary = vm.summarize_candidate(result, ["a"], 1.0)
    assert summary["observed_saturation"] is True
    assert summary["formal_deployment_feasibility"] == "pending"
    assert summary["n_sat_fir_retained"] == 2


@pytest.mark.parametrize("fault", [None, "missing", "saturation", "identity"])
def test_wrapper_lifecycle_with_synthetic_cases_only(tmp_path, monkeypatch, fault):
    # 36 个短合成 case 只检验接线；这里不生成任何正式波形。
    definition = vm.frozen_main_definition()
    configs = development_candidates()
    area = {"areas": {vm.candidate_hash(c): 1.0 for c in configs}, "source": "mock"}
    calls = []

    def areas(*args):
        calls.append(1)
        if fault == "identity" and len(calls) > 1:
            return {**area, "source": "drift"}
        return copy.deepcopy(area)

    def cases(_):
        selected = definition["scenarios"][:-1] if fault == "missing" else definition["scenarios"]
        return [make_case(record["key"]) for record in selected]

    monkeypatch.setattr(vm, "verified_areas", areas)
    monkeypatch.setattr(vm, "main_cases", cases)
    if fault == "saturation":
        original = vm.summarize_candidate

        def saturated(*args):
            row = original(*args)
            row["observed_saturation"] = True
            return row

        monkeypatch.setattr(vm, "summarize_candidate", saturated)
    path = vm.run_validation("mock", output_root=tmp_path)
    result = json.loads(path.read_text())
    assert result["formal_search_allowed"] is False and result["S"] == "N/A"
    assert result["status"] == ("fixed_candidates_validated" if fault is None else "failed")
    if fault is None:
        assert len(result["rows"]) == 3
        assert all(r["n_scenarios"] == 36 for r in result["rows"])
    if fault == "saturation":
        assert len(result["rows"]) == 1
        assert not (path.parent / "quality/result-0002.json").exists()
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        vm.run_validation("mock", output_root=tmp_path)
    assert path.read_bytes() == before


has_c_artifacts = pytest.mark.skipif(
    not (vm.DEFAULT_AREA_RUN / "results.json").is_file(),
    reason="仅在本地已存在 C 产物时做只读证据链回归，不生成替代面积",
)


@has_c_artifacts
def test_actual_c_area_chain_is_read_only_and_matches_all_three_candidates():
    result = vm.verified_areas(vm.DEFAULT_AREA_RUN, development_candidates())
    assert len(result["areas"]) == 3
    assert all(area > 0 for area in result["areas"].values())


@has_c_artifacts
@pytest.mark.parametrize("fault", ["candidate", "rtl", "source"])
def test_area_identity_mismatch_is_rejected(fault, monkeypatch):
    configs = development_candidates()
    if fault == "candidate":
        configs[0]["nco"]["phase_bits"] = 10
    elif fault == "rtl":
        monkeypatch.setattr(vm, "lower_ddc_rtl", lambda _: "wrong RTL")
    else:
        original = vm._sha

        def changed(path):
            return "0" * 64 if path.name == "synthesize.py" else original(path)

        monkeypatch.setattr(vm, "_sha", changed)
    with pytest.raises(EvaluationError, match="身份不匹配|发生漂移"):
        vm.verified_areas(vm.DEFAULT_AREA_RUN, configs)
