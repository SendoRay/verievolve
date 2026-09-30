import json
import math
import sys
from pathlib import Path


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.ddc import prepare_witness_v1, run_witness_v1


def test_preflight_freezes_26_ncos_and_fixed_downstream_without_truth():
    manifest = prepare_witness_v1.build_preflight_manifest()
    assert manifest["status"] == "preflight-only; no chain truth"
    assert manifest["candidate_set"]["count"] == 26
    assert manifest["fixed_downstream"]["fir"]["name"] == "f1_c16"
    assert manifest["fixed_downstream"]["cmul"]["name"] == "c1_exact_rne"
    assert manifest["rtl_equivalence"]["pool_size"] == 26
    assert manifest["rtl_equivalence"]["all_pass"] is True
    assert manifest["truth_runner"]["allowed"] is False
    assert manifest["truth_runner"]["formal_entrypoint"].endswith("run_witness_v1.py truth")


def test_preflight_freezes_nco_only_nangate45_area_contract():
    manifest = prepare_witness_v1.build_preflight_manifest()
    area = manifest["synthesis_contract"]
    assert area["primary_scope"] == "NCO-only"
    assert area["primary_top_module"] == "nco_map"
    assert area["metric"].endswith("(um^2)")
    assert len(area["liberty"]["sha256"]) == 64
    assert len(area["script_sha256"]) == 64
    assert area["sdc"] is None
    assert area["timing_power_claims_allowed"] is False


def test_preflight_records_segments_sfdr_and_code_fingerprints():
    manifest = prepare_witness_v1.build_preflight_manifest()
    quality = manifest["quality_contract"]
    assert quality["measurement_segments"]["output_alignment_samples"] == 240
    assert quality["sfdr"]["n_samples"] == 2**16
    assert quality["sfdr"]["zero_pad_factor"] == 8
    assert len(manifest["reproducibility"]["code_sha256"]) >= 10


def test_preflight_q_calibration_and_threshold_are_exactly_defined():
    cal = prepare_witness_v1.exact_zero_q_calibration()
    assert cal["q_cal"] == 0.0
    assert math.isclose(cal["epsilon_q"], 0.1 * cal["q_budget"],
                        rel_tol=0.0, abs_tol=1e-20)
    assert 2.32e-6 < cal["epsilon_q"] < 2.34e-6


def test_checked_in_rtl_report_is_machine_readable_and_complete():
    report = json.loads(prepare_witness_v1.RTL_REPORT.read_text(encoding="utf-8"))
    assert report["schema_version"] == "nco-rtl-equiv-v1"
    assert len(report["results"]) == 26
    assert all(row["pass"] and row["mismatch"] == 0
               for row in report["results"].values())


def test_pair_selection_is_q_blind_and_obeys_three_db_limit():
    manifest = prepare_witness_v1.build_preflight_manifest()
    cfg = {x["name"]: x for x in manifest["candidate_set"]["candidates"]}
    rows = [
        {**cfg["v2_lut512near_b16"], "mcore_sqnr_db": 46.0},
        {**cfg["v2_cordic8_b16"], "mcore_sqnr_db": 47.0},
        {**cfg["v2_cordic12_b16"], "mcore_sqnr_db": 60.0},
    ]
    audit = run_witness_v1.select_v2_pair(rows, manifest)
    assert audit["q_blind"] is True
    assert {audit["selected"]["a"], audit["selected"]["b"]} == {
        "v2_lut512near_b16", "v2_cordic8_b16"}
    far = next(x for x in audit["complete_pair_table"]
               if {x["a"], x["b"]} == {
                   "v2_lut512near_b16", "v2_cordic12_b16"})
    assert far["status"] == "discard:delta-sqnr-over-3db"


def test_q_aggregation_uses_linear_max_and_reports_argmax():
    rows = [
        {"candidate": "a", "scenario": "s1", "split": "main", "fcw": 1,
         "q_aligned": 1e-5, "q_aligned_db": -50.0},
        {"candidate": "a", "scenario": "s2", "split": "main", "fcw": 2,
         "q_aligned": 2e-5, "q_aligned_db": -46.9897},
    ]
    got = run_witness_v1._aggregate(rows, "main")
    assert got == [{"candidate": "a", "Q": 2e-5, "Q_db": -46.9897,
                    "argmax_scenario": "s2", "argmax_fcw": 2,
                    "n_scenarios": 2}]


def test_decision_analysis_distinguishes_local_front_and_system_dominator():
    manifest = prepare_witness_v1.build_preflight_manifest()
    names = [x["name"] for x in manifest["candidate_set"]["candidates"]]
    local = {"rows": []}
    area = {"rows": []}
    main = []
    for i, cfg in enumerate(manifest["candidate_set"]["candidates"]):
        # a 是局部/面积前沿点，但 b 以相同面积和超过 epsilon_Q 的 Q 优势支配它。
        sqnr = 50.0 - i
        q = 1e-5 + i * 1e-8
        area_value = 1000.0 + i
        if i == 0:
            q = 2e-5
        elif i == 1:
            q = 1e-5
            area_value = 1000.0
        local["rows"].append({**cfg, "mcore_sqnr_db": sqnr,
                              "mcore_wce_lsb": 1.0 + i,
                              "mcore_last_bit_accuracy": 1.0 - i * 1e-6,
                              "sfdr_main_worst_db": 70.0 - i})
        area["rows"].append({"name": cfg["name"], "area_um2": area_value})
        main.append({"candidate": cfg["name"], "Q": q})
    report = run_witness_v1.analyze_main_decisions(main, local, area, manifest)
    witnesses = report["metrics"]["sqnr"]["pools"]["union26"]["decision_witnesses"]
    assert any(w["local_front_candidate"] == names[0]
               and w["system_dominator"] == names[1] for w in witnesses)
