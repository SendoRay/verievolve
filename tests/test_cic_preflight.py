import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.cic import prepare_witness_v1
from chains.cic.gen_candidates_v1 import expand


def test_scenario_manifest_is_complete_and_has_no_illegal_blocker():
    manifest = prepare_witness_v1.build_scenario_manifest()
    assert manifest["counts"] == {
        "R2_heldout": 12, "R2_main": 18, "R2_stress": 6,
        "R4_heldout": 12, "R4_main": 18, "R4_stress": 6,
    }
    assert manifest["heldout_rule"]["grids_khz"] == {
        "R2": [225.0, 275.0, 375.0, 425.0],
        "R4": [187.5, 202.5, 232.5, 244.0],
    }
    assert all(row["blocker_hz"] is None or 169_000 < row["blocker_hz"] < 1_000_000
               for row in manifest["rows"])


def test_equivalence_scan_only_merges_semantically_safe_classes():
    scan = prepare_witness_v1.scan_equivalence(expand())
    assert scan["input_count"] == 28
    assert scan["deduplicated_count"] == 23
    classes = [set(x["members"]) for x in scan["classes"]]
    assert {"comp_H_R2N3", "comp_U0_R2N3", "comp_RND_R2N3"} in classes
    assert {"comp_H_R2N4", "comp_U0_R2N4", "comp_RND_R2N4"} in classes
    assert {"comp_H_R4N3", "comp_U0_R4N3"} in classes
    # wrap/sat 不因有限 trace 相同而合并。
    for cls in classes:
        assert not ({"comp_H_R4N4", "comp_O_R4N4"} <= cls)


def test_preflight_contains_fingerprints_and_keeps_formal_execution_locked():
    manifest = prepare_witness_v1.build_preflight_manifest()
    assert manifest["status"] == "awaiting user second freeze; chain q forbidden"
    assert manifest["protocol"]["sha256"] == (
        "aa6a54ecaef931f131108437aacfbc6803922dd3e46bfc450e3c0f4cacb25174"
    )
    assert manifest["candidate_set"]["generated_count"] == 28
    assert len(manifest["deduplicated_pool"]) == 23
    assert manifest["formal_execution"]["allowed"] is False
    assert "chain q" in manifest["formal_execution"]["forbidden_metrics"]
    assert len(manifest["reproducibility"]["code_sha256"]) == 6


def test_checked_in_manifest_matches_the_builder_when_present():
    path = prepare_witness_v1.OUT
    if not path.exists():
        return
    checked = json.loads(path.read_text())
    fresh = prepare_witness_v1.build_preflight_manifest()
    # git dirty 状态可因测试运行环境变化；其余内容必须逐字一致。
    checked["reproducibility"]["git"] = fresh["reproducibility"]["git"]
    assert checked == fresh
