#!/usr/bin/env python3
"""Audit archived hierarchical M4 calls and frozen-v2 evidence bindings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_m4_cordic_2x2_pilot as protocol
import run_m4_hierarchical_pilot as experiment


BENCH = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def audit_task(root: Path, task: str, seed_count: int) -> dict:
    spec = experiment.TASKS[task]
    task_root = root / task
    manifest_path = task_root / "manifest.json"
    results_path = task_root / "results.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    require(manifest["status"] == "complete", f"{task}: task manifest incomplete")
    require(manifest["results_sha256"] == protocol.sha(results_path), f"{task}: results hash mismatch")
    require(len(results["runs"]) == seed_count * 4, f"{task}: wrong run count")

    rows, areas, _, provenance = experiment.load_frozen_task(spec)
    require(provenance == manifest["source_provenance"], f"{task}: source provenance changed")
    for key in ("source_manifest", "candidate_rows", "area_cache"):
        path = BENCH / provenance[key]
        require(path.exists(), f"{task}: missing source file {path}")
        require(
            protocol.sha(path) == provenance[key + "_sha256"],
            f"{task}: source hash mismatch for {key}",
        )

    call_artifacts = []
    for run in results["runs"]:
        label = f"{task}:{run['proposer']}:{run['fitness']}:{run['seed']}"
        require(run["status"] == "complete", f"{label}: incomplete")
        require(run["new_candidate_evaluations"] == 8, f"{label}: wrong evaluation budget")
        require(len(run["evaluations"]) == 8, f"{label}: wrong evaluation list length")
        require(len(run["visited_indices"]) == 9, f"{label}: wrong visited length")
        require(
            len(set(run["visited_indices"])) == len(run["visited_indices"]),
            f"{label}: repeated candidate",
        )
        recomputed = spec.terminal(run["visited_indices"], rows, areas)
        require(recomputed == run["terminal"], f"{label}: terminal result changed")
        if run["proposer"] != "deepseek_hierarchical_action":
            require(not run.get("calls"), f"{label}: non-LLM run has calls")
            continue
        require(len(run["calls"]) == 8, f"{label}: wrong LLM call count")
        for call, evaluation in zip(run["calls"], run["evaluations"]):
            step = call["step"]
            call_root = task_root / "llm_calls" / f"{run['fitness']}-seed-{run['seed']}" / f"step-{step:02d}"
            request_path = call_root / "request.json"
            response_path = call_root / "response.json"
            record_path = call_root / "record.json"
            require(request_path.exists(), f"{label}: missing request step {step}")
            require(response_path.exists(), f"{label}: missing response step {step}")
            require(record_path.exists(), f"{label}: missing record step {step}")
            request = json.loads(request_path.read_text(encoding="utf-8"))
            response = json.loads(response_path.read_text(encoding="utf-8"))
            record = json.loads(record_path.read_text(encoding="utf-8"))
            require(record == call, f"{label}: archived record differs from results step {step}")
            require(record["status"] == response["status"], f"{label}: response status mismatch")
            require(
                record["expanded_candidate_index"] == evaluation["candidate_index"],
                f"{label}: expansion binding mismatch step {step}",
            )
            require(
                record["executed_action"] == evaluation["executed_action"],
                f"{label}: action binding mismatch step {step}",
            )
            user = json.loads(request["messages"][1]["content"])
            require(
                all("candidate_index" not in item for item in user["action_menu"]),
                f"{label}: candidate id leaked in action menu step {step}",
            )
            require(
                all("candidate_index" not in item for item in user["evaluated"]),
                f"{label}: candidate id leaked in feedback step {step}",
            )
            call_artifacts.append(
                {
                    "fitness": run["fitness"],
                    "seed": run["seed"],
                    "step": step,
                    "status": record["status"],
                    "proposed_action": record["proposed_action"],
                    "executed_action": record["executed_action"],
                    "fallback_reason": record["fallback_reason"],
                    "expanded_candidate_index": record["expanded_candidate_index"],
                    "request": str(request_path.relative_to(BENCH)),
                    "request_sha256": protocol.sha(request_path),
                    "response": str(response_path.relative_to(BENCH)),
                    "response_sha256": protocol.sha(response_path),
                    "record": str(record_path.relative_to(BENCH)),
                    "record_sha256": protocol.sha(record_path),
                }
            )
    expected_calls = seed_count * 2 * experiment.NEW_EVALUATIONS
    require(len(call_artifacts) == expected_calls, f"{task}: wrong archived call count")
    accounting = results["summary"]["llm_accounting"]
    require(accounting["recorded_calls"] == expected_calls, f"{task}: summary call mismatch")
    budget = results["summary"]["budget_audit"]
    require(budget["all_runs_complete"], f"{task}: budget audit incomplete")
    require(budget["all_runs_exactly_eight_new_candidates"], f"{task}: budget mismatch")
    require(budget["unique_candidate_violations"] == 0, f"{task}: uniqueness violation")
    return {
        "status": "pass",
        "task_manifest": str(manifest_path.relative_to(BENCH)),
        "task_manifest_sha256": protocol.sha(manifest_path),
        "results": str(results_path.relative_to(BENCH)),
        "results_sha256": protocol.sha(results_path),
        "source_provenance": provenance,
        "run_count": len(results["runs"]),
        "llm_call_count": len(call_artifacts),
        "all_runs_exactly_eight_unique_new_candidates": True,
        "terminal_recomputation": "exact match",
        "call_artifacts": call_artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    root_manifest_path = root / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text(encoding="utf-8"))
    require(root_manifest["status"] == "complete", "root manifest incomplete")
    require(
        root_manifest["runner_sha256"] == protocol.sha(Path(experiment.__file__)),
        "runner identity mismatch",
    )
    tasks = {
        task: audit_task(root, task, root_manifest["seed_count"])
        for task in root_manifest["tasks"]
    }
    for task, record in tasks.items():
        require(
            root_manifest["task_manifest_sha256"][task] == record["task_manifest_sha256"],
            f"{task}: root-to-task manifest hash mismatch",
        )
    output = {
        "schema_version": "m4-hierarchical-artifact-audit-v1",
        "status": "pass",
        "root_manifest": str(root_manifest_path.relative_to(BENCH)),
        "root_manifest_sha256": protocol.sha(root_manifest_path),
        "runner": str(Path(experiment.__file__).resolve().relative_to(BENCH)),
        "runner_sha256": protocol.sha(Path(experiment.__file__)),
        "verifier_sha256": protocol.sha(Path(__file__)),
        "total_runs": sum(record["run_count"] for record in tasks.values()),
        "total_llm_calls": sum(record["llm_call_count"] for record in tasks.values()),
        "tasks": tasks,
    }
    protocol.write_json(root / "artifact_audit.json", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
