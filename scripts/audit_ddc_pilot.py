#!/usr/bin/env python3
"""只读审计完成的 DDC pilot；不运行新候选或推断 S0/S1。"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

BENCH = Path(__file__).resolve().parents[1] / "examples/comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.pilot import ArmState, area_key
from search_ir.synthesize import liberty_areas, validate_mapped_result
from search_ir.canonicalize import canonical_json
from search_ir.provenance import verify_source_record


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def audit(root):
    root = Path(root)
    result, manifest = read(root / "results.json"), read(root / "manifest.json")
    assert result["status"] == "pilot_completed"
    assert result["manifest_sha256"] == digest(root / "manifest.json")
    assert len(result["trials"]) == result["budget_charged"] == 72
    assert result["S"] == result["L"] == "N/A" and manifest["formal_search"] is False
    contract = manifest["contract"]
    for record in contract["sources"]:
        verify_source_record(record)
    for record in (contract["yosys"], contract["abc"], contract["liberty"]):
        assert digest(record["path"]) == record["sha256"], record["path"]
    assert len(manifest["main_definition"]["scenarios"]) == 36
    assert all(s["split"] == "main" for s in manifest["main_definition"]["scenarios"])
    budget = manifest["draft"]["evaluation"]["q_budget"]
    initial = [row["candidate"] for row in manifest["draft"]["initial_candidates"]]
    states = {(seed, arm): ArmState(seed, arm, initial, "legacy_v1")
              for seed in (11, 29, 47) for arm in ("joint", "staged")}
    seen_sources, cache_keys = set(), set()
    quality_rows, mutations, area_hits = 0, 0, 0
    cost_samples = []
    areas = liberty_areas(Path(contract["liberty"]["path"]).read_text())
    for i, (trial, scheduled) in enumerate(zip(result["trials"], manifest["draft"]["schedule"]), 1):
        assert trial == read(root / f"trials/{i:04d}.json")
        assert trial["proposal_id"] == i
        assert all(trial[k] == v for k, v in scheduled.items())
        key = (trial["seed"], trial["arm"])
        state = states[key]
        proposal = read(root / f"proposals/{i:04d}.json")
        assert proposal["rng_before"] == state.rng.bit_generator.state
        generated = state.candidate(trial["attempt"], trial["phase"])
        assert all(generated[k] == proposal[k] for k in generated), (i, "proposal replay")
        assert state.rng.bit_generator.state == trial["rng_after"]
        quality_dir = root / "quality" / f"{key[0]}-{key[1]}"
        q = read(quality_dir / f"result-{trial['attempt']:04d}.json")
        assert q["attempt_id"] == trial["quality_attempt_id"] == trial["attempt"]
        assert q["candidate_hash"] == trial["candidate_hash"]
        qm = read(quality_dir / "manifest.json")
        assert q["context_sha256"] == qm["context_sha256"]
        if proposal["error"] is None:
            actual_candidate = read(quality_dir / f"candidate-{trial['attempt']:04d}.json")
            assert canonical_json(actual_candidate) == canonical_json(proposal["candidate"])
            mutations += bool(proposal.get("parent_hash"))
        if q["status"] == "ok":
            ev = q["evaluation"]
            assert len(ev["rows"]) == 36
            assert [r["case_identity"] for r in ev["rows"]] == qm["context"]["cases"]
            assert ev["Q_dev"] == max(r["q_aligned"] for r in ev["rows"]) == trial["Q"]
            assert all(np.isfinite(r["q_aligned"]) and r["q_aligned"] >= 0 for r in ev["rows"])
            assert all(r["n_samples"] == 6400 for r in ev["rows"])
            quality_rows += len(ev["rows"])
        record = None
        if trial["status"] == "ok":
            ev = q["evaluation"]
            assert not any(r["n_sat_mix"] or r["n_sat_fir"] for r in ev["rows"])
            area = trial["area"]
            source = Path(area["source_result"])
            rtl = (source.parent / "design.v").read_text()
            assert area["cache_key"] == area_key(proposal["candidate"], rtl, contract)
            assert digest(source) == area["source_sha256"]
            raw = read(source)
            assert raw["status"] == "ok" and raw["area_um2"] == area["area_um2"]
            assert raw["binding"]["candidate_hash"] == trial["candidate_hash"]
            if str(source) not in seen_sources:
                for name, value in raw["artifacts"].items():
                    assert digest(source.parent / name) == value
                checked = validate_mapped_result(read(source.parent / "stat.json"),
                                                read(source.parent / "mapped.json"), areas)
                for name in ("area_um2", "cells_by_type", "stat_top_sha256", "netlist_semantic_sha256"):
                    assert checked[name] == raw[name]
                seen_sources.add(str(source))
            cache_keys.add(area["cache_key"])
            area_hits += area["cache_hit"]
            if not area["cache_hit"]:
                cost_samples.append(area["wall_seconds"])
            record = {"candidate": proposal["candidate"], "candidate_hash": trial["candidate_hash"],
                      "Q": trial["Q"], "area_um2": area["area_um2"]}
        elif trial["status"] == "candidate_timeout":
            cost_samples.append(600.0)
        else:
            assert trial["status"] in ("invalid_proposal", "mask_failed", "saturation_failed")
        state.update(record, trial["attempt"])
        assert state.snapshot(budget) == read(root / f"states/{i:04d}.json"), (i, "state replay")
    summaries = []
    for (seed, arm), state in states.items():
        qdir = root / "quality" / f"{seed}-{arm}"
        ledger = [json.loads(line) for line in (qdir / "attempts.jsonl").read_text().splitlines()]
        starts = [r for r in ledger if r["event"] == "attempt_started"]
        ends = [r for r in ledger if r["event"] == "attempt_finished"]
        assert [r["attempt_id"] for r in starts] == list(range(1, 13))
        assert [r["attempt_id"] for r in ends] == list(range(1, 13))
        assert sum(r["budget_units"] for r in ledger) == 12
        assert result["arms"][f"{seed}-{arm}"] == state.snapshot(budget)
        qm = read(qdir / "manifest.json")
        for item in qm["inputs"]:
            assert digest(qdir / item["path"]) == item["sha256"]
        trials = [t for t in result["trials"] if t["seed"] == seed and t["arm"] == arm]
        archive = result["arms"][f"{seed}-{arm}"]["main_archive"]
        best = min(archive, key=lambda r: r["area_um2"])
        summaries.append({"seed": seed, "arm": arm, "statuses": dict(Counter(t["status"] for t in trials)),
                          "unique_valid_candidates": len(state.history), "main_front_size": len(archive),
                          "min_area_within_budget": best["area_um2"], "quality_at_min_area": best["Q"],
                          "candidate_hash": best["candidate_hash"]})
    assert cost_samples == result["uncached_synthesis_costs"]
    p90 = float(np.quantile(cost_samples, 0.9, method="higher"))
    assert p90 == result["p90_seconds"]
    recommended = 64 if len(cost_samples) >= 10 and p90 <= 90 else 32
    assert recommended == result["formal_budget_recommendation"]
    differences = []
    for seed in (11, 29, 47):
        j = next(r for r in summaries if r["seed"] == seed and r["arm"] == "joint")
        s = next(r for r in summaries if r["seed"] == seed and r["arm"] == "staged")
        differences.append({"seed": seed, "joint_minus_staged_area": j["min_area_within_budget"] - s["min_area_within_budget"],
                            "joint_area_improvement_percent": 100 * (s["min_area_within_budget"] - j["min_area_within_budget"]) / s["min_area_within_budget"]})
    improvements = [r["joint_area_improvement_percent"] for r in differences]
    return {
        "source": str(root.resolve()), "result_sha256": digest(root / "results.json"),
        "manifest_sha256": digest(root / "manifest.json"), "audit_script_sha256": digest(__file__),
        "audit": {"charged": 72, "rng_and_state_replays": 72, "valid_mutation_replays": mutations,
                  "quality_case_rows": quality_rows, "area_sources_checked": len(seen_sources)},
        "statuses": dict(Counter(t["status"] for t in result["trials"])),
        "area_cache_hits": area_hits, "unique_area_keys": len(cache_keys),
        "uncached_syntheses": len(cost_samples), "p90_seconds": p90,
        "cost_mean_seconds": float(np.mean(cost_samples)), "cost_max_seconds": max(cost_samples),
        "wall_hours": result["wall_seconds"] / 3600, "formal_budget_recommendation": recommended,
        "raw_table": summaries, "paired_area_descriptions": differences,
        "joint_improvement_mean_percent": float(np.mean(improvements)),
        "joint_improvement_sample_std_percent": float(np.std(improvements, ddof=1)),
        "S": "N/A", "L": "N/A", "note": "pilot descriptions only; no held-out, no significance or S decision",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.run), ensure_ascii=False, indent=2, allow_nan=False))
