#!/usr/bin/env python3
"""Run the bounded M4 hierarchical-action proposer pilot for FIR and NCO.

The LLM never names a candidate.  It selects one task-level action, and a
frozen deterministic executor expands that action to the first legal,
unvisited typed neighbor.  Invalid or exhausted actions are normalized to a
recorded deterministic fallback and still consume exactly one search
evaluation (but no extra LLM call).  The non-LLM comparator is a UCB1 policy
over the identical action set and uses the identical expansion executor.

Candidate truth, terminal protocols, and mapped areas are read from the
immutable FIR/NCO formal-v2 artifacts.  This runner does not generate RTL or
rerun synthesis.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import time
from typing import Callable

import run_m4_cordic_2x2_pilot as protocol
import run_m4_fir_2x2 as fir_v2
import run_m4_nco_2x2_pilot as nco_v2
from rotation_llm_client import calculate_cost, generate


BENCH = Path(__file__).resolve().parent
FIR_SOURCE = BENCH / "experiments_m4/fir_2x2_v2_20261009"
NCO_SOURCE = BENCH / "experiments_m4/nco_2x2_pilot_v2_20261009"
OUTPUTS = {
    "smoke": BENCH / "experiments_m4/hierarchical_smoke_v1_20261009",
    "formal": BENCH / "experiments_m4/hierarchical_pilot_v1_20261009",
}
KEY_FILE = Path(
    "/Users/chengzhy/verievolve/examples/comm_dsp_bench/.api_key_deepseek"
)
NEW_EVALUATIONS = 8
MODEL = "deepseek-flash"
TEMPERATURE = 0.4


@dataclass(frozen=True)
class TaskSpec:
    name: str
    source: Path
    seeds: tuple[int, ...]
    initial_index: int
    actions: tuple[str, ...]
    action_descriptions: dict[str, str]
    rows_file: str
    classify_edge: Callable[[dict, dict], str]
    make_graph: Callable[[list[dict]], dict[int, list[int]]]
    exposed_record: Callable[[int, str, list[dict], list[float]], dict]
    exposed_objectives: Callable[[int, str, list[dict], list[float]], tuple]
    terminal: Callable[[list[int], list[dict], list[float]], dict]
    primary_utility: Callable[[dict], float | None]
    primary_name: str


def classify_fir_edge(parent: dict, child: dict) -> str:
    changed = [key for key in ("structure", "coef_frac", "rounding") if parent[key] != child[key]]
    if changed == ["structure"]:
        return "switch_architecture"
    if changed == ["rounding"]:
        return "change_rounding"
    if changed == ["coef_frac"]:
        return "increase_precision" if child["coef_frac"] > parent["coef_frac"] else "decrease_precision"
    raise ValueError(f"unclassified FIR edge: {parent} -> {child}")


def classify_nco_edge(parent: dict, child: dict) -> str:
    if parent["algo"] != child["algo"]:
        return "switch_architecture"
    if parent["algo"] == "cordic":
        if child["stages"] != parent["stages"]:
            return "increase_precision" if child["stages"] > parent["stages"] else "decrease_precision"
    else:
        if child["phase_bits"] != parent["phase_bits"]:
            return "increase_precision" if child["phase_bits"] > parent["phase_bits"] else "decrease_precision"
        if child["depth"] != parent["depth"]:
            return "increase_table_capacity" if child["depth"] > parent["depth"] else "decrease_table_capacity"
        if child["order"] != parent["order"]:
            return "change_interpolation"
    raise ValueError(f"unclassified NCO edge: {parent} -> {child}")


def normalized_hypervolume(
    indices: list[int], points: dict[int, tuple[float, float]], error_ref: float, area_ref: float
) -> float:
    unique = sorted({points[index] for index in indices})
    front = [
        point
        for point in unique
        if not any(protocol.dominates(other, point) for other in unique)
    ]
    front.sort()
    total = 0.0
    previous_area = area_ref
    for error, area in front:
        if area < previous_area:
            total += (error_ref - error) * (previous_area - area)
            previous_area = area
    return total / (error_ref * area_ref)


def nco_terminal(visited: list[int], rows: list[dict], areas: list[float]) -> dict:
    """Extend the unchanged v2 terminal record with an always-defined HV."""
    result = nco_v2.terminal(visited, rows, areas)
    points = {
        index: (row["heldout_error_power_lsb2"], areas[index])
        for index, row in enumerate(rows)
    }
    error_ref = max(point[0] for point in points.values()) * 1.05
    area_ref = max(areas) * 1.05
    result.update(
        heldout_hypervolume=normalized_hypervolume(visited, points, error_ref, area_ref),
        global_heldout_hypervolume=normalized_hypervolume(
            list(range(len(rows))), points, error_ref, area_ref
        ),
        heldout_hypervolume_reference={
            "error_lsb2": error_ref,
            "area_um2": area_ref,
            "rule": "1.05 * frozen 20-candidate pool maxima",
        },
    )
    return result


TASKS = {
    "fir": TaskSpec(
        name="fir",
        source=FIR_SOURCE,
        seeds=fir_v2.SEEDS,
        initial_index=fir_v2.INITIAL_INDEX,
        actions=("switch_architecture", "increase_precision", "decrease_precision", "change_rounding"),
        action_descriptions={
            "switch_architecture": "switch direct versus symmetric-preadd structure",
            "increase_precision": "increase coefficient fractional precision by one legal level",
            "decrease_precision": "decrease coefficient fractional precision by one legal level",
            "change_rounding": "switch coefficient rounding mode",
        },
        rows_file="candidate_pool.json",
        classify_edge=classify_fir_edge,
        make_graph=fir_v2.adjacency,
        exposed_record=fir_v2.exposed_record,
        exposed_objectives=fir_v2.exposed_objectives,
        terminal=fir_v2.terminal,
        primary_utility=lambda terminal: terminal["heldout_hypervolume"],
        primary_name="heldout_hypervolume",
    ),
    "nco": TaskSpec(
        name="nco",
        source=NCO_SOURCE,
        seeds=nco_v2.SEEDS,
        initial_index=nco_v2.INITIAL_INDEX,
        actions=(
            "switch_architecture",
            "increase_precision",
            "decrease_precision",
            "increase_table_capacity",
            "decrease_table_capacity",
            "change_interpolation",
        ),
        action_descriptions={
            "switch_architecture": "switch LUT versus CORDIC structure",
            "increase_precision": "increase phase bits or CORDIC stages by one legal level",
            "decrease_precision": "decrease phase bits or CORDIC stages by one legal level",
            "increase_table_capacity": "increase LUT depth by one legal level",
            "decrease_table_capacity": "decrease LUT depth by one legal level",
            "change_interpolation": "switch nearest-neighbor versus linear interpolation",
        },
        rows_file="candidate_snapshot.json",
        classify_edge=classify_nco_edge,
        make_graph=nco_v2.adjacency,
        exposed_record=nco_v2.exposed_record,
        exposed_objectives=nco_v2.exposed_objectives,
        terminal=nco_terminal,
        primary_utility=lambda terminal: terminal["heldout_hypervolume"],
        primary_name="heldout_hypervolume",
    ),
}


def parse_action(text: str | None) -> str | None:
    if not text:
        return None
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.S | re.I)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    action = value.get("action") if isinstance(value, dict) else None
    return action if isinstance(action, str) else None


def load_frozen_task(spec: TaskSpec) -> tuple[list[dict], list[float], dict[int, list[int]], dict]:
    source_manifest_path = spec.source / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    rows_path = spec.source / spec.rows_file
    rows_payload = json.loads(rows_path.read_text(encoding="utf-8"))
    rows = rows_payload["rows"]
    area_path = spec.source / "area_cache.json"
    area_cache = json.loads(area_path.read_text(encoding="utf-8"))
    expected_rows_sha = protocol.sha(rows_path)
    source_sha_field = "candidate_source_sha256" if spec.name == "fir" else "candidate_snapshot_sha256"
    if source_manifest[source_sha_field] != expected_rows_sha:
        raise RuntimeError(f"{spec.name} source manifest candidate identity mismatch")
    if area_cache["candidate_source_sha256"] != expected_rows_sha:
        raise RuntimeError(f"{spec.name} area cache candidate identity mismatch")
    if source_manifest["area_cache_sha256"] != protocol.sha(area_path):
        raise RuntimeError(f"{spec.name} source manifest area identity mismatch")
    if len(rows) != 20 or len(area_cache["rows"]) != len(rows):
        raise RuntimeError(f"{spec.name} frozen pool is not 20 complete candidates")
    by_index = {entry["candidate_index"]: entry for entry in area_cache["rows"]}
    if set(by_index) != set(range(len(rows))):
        raise RuntimeError(f"{spec.name} area indices are incomplete")
    for index, row in enumerate(rows):
        entry = by_index[index]
        if entry["status"] != "ok" or entry["params"] != row["params"]:
            raise RuntimeError(f"{spec.name} area binding mismatch at candidate {index}")
    graph = spec.make_graph(rows)
    for parent, neighbors in graph.items():
        for child in neighbors:
            action = spec.classify_edge(rows[parent]["params"], rows[child]["params"])
            if action not in spec.actions:
                raise RuntimeError(f"{spec.name} edge has action outside frozen set")
    provenance = {
        "source_manifest": str(source_manifest_path.relative_to(BENCH)),
        "source_manifest_sha256": protocol.sha(source_manifest_path),
        "candidate_rows": str(rows_path.relative_to(BENCH)),
        "candidate_rows_sha256": expected_rows_sha,
        "area_cache": str(area_path.relative_to(BENCH)),
        "area_cache_sha256": protocol.sha(area_path),
        "area_contract_sha256": area_cache["contract_sha256"],
    }
    return rows, [by_index[index]["area_um2"] for index in range(len(rows))], graph, provenance


def action_candidates(
    spec: TaskSpec,
    visited: list[int],
    rows: list[dict],
    graph: dict[int, list[int]],
) -> dict[str, list[dict]]:
    """Return every legal unvisited neighbor, frozen by earliest parent then params."""
    result: dict[str, dict[int, dict]] = {action: {} for action in spec.actions}
    visited_set = set(visited)
    for parent_order, parent in enumerate(visited):
        for candidate in graph[parent]:
            if candidate in visited_set:
                continue
            action = spec.classify_edge(rows[parent]["params"], rows[candidate]["params"])
            proposal = {
                "candidate_index": candidate,
                "parent_index": parent,
                "parent_visit_order": parent_order,
            }
            prior = result[action].get(candidate)
            if prior is None or (parent_order, parent) < (
                prior["parent_visit_order"],
                prior["parent_index"],
            ):
                result[action][candidate] = proposal
    ordered: dict[str, list[dict]] = {}
    for action in spec.actions:
        ordered[action] = sorted(
            result[action].values(),
            key=lambda item: (
                item["parent_visit_order"],
                protocol.canonical(rows[item["candidate_index"]]["params"]),
                item["candidate_index"],
            ),
        )
    return ordered


def normalize_and_expand(
    spec: TaskSpec,
    proposed_action: str | None,
    visited: list[int],
    action_counts: dict[str, int],
    rows: list[dict],
    graph: dict[int, list[int]],
) -> dict:
    candidates = action_candidates(spec, visited, rows, graph)
    available = [action for action in spec.actions if candidates[action]]
    if not available:
        raise RuntimeError(f"{spec.name} graph exhausted before evaluation budget")
    fallback_reason = None
    if proposed_action not in spec.actions:
        fallback_reason = "invalid_or_unparseable_action"
    elif not candidates[proposed_action]:
        fallback_reason = "action_has_no_legal_unvisited_neighbor"
    if fallback_reason is None:
        executed_action = proposed_action
    else:
        executed_action = min(
            available, key=lambda action: (action_counts[action], spec.actions.index(action))
        )
    expanded = candidates[executed_action][0]
    return {
        "proposed_action": proposed_action,
        "executed_action": executed_action,
        "fallback_reason": fallback_reason,
        "candidate_index": expanded["candidate_index"],
        "parent_index": expanded["parent_index"],
        "available_actions": available,
        "remaining_candidates_by_action": {
            action: len(candidates[action]) for action in spec.actions
        },
        "executor_rule": "earliest visited parent, then canonical candidate params, then candidate index",
    }


def pareto_archive(
    indices: list[int], spec: TaskSpec, fitness: str, rows: list[dict], areas: list[float]
) -> list[int]:
    objectives = {index: spec.exposed_objectives(index, fitness, rows, areas) for index in indices}
    return [
        index
        for index in indices
        if not any(protocol.dominates(objectives[other], objectives[index]) for other in indices)
    ]


def archive_reward(
    before: list[int],
    candidate: int,
    spec: TaskSpec,
    fitness: str,
    rows: list[dict],
    areas: list[float],
) -> float:
    old_archive = pareto_archive(before, spec, fitness, rows, areas)
    new_archive = pareto_archive(before + [candidate], spec, fitness, rows, areas)
    candidate_objective = spec.exposed_objectives(candidate, fitness, rows, areas)
    dominated = sum(
        protocol.dominates(candidate_objective, spec.exposed_objectives(old, fitness, rows, areas))
        for old in old_archive
    )
    return (float(candidate in new_archive) + dominated) / (len(old_archive) + 1.0)


def ucb_action(
    spec: TaskSpec,
    available: list[str],
    counts: dict[str, int],
    rewards: dict[str, list[float]],
    priority: dict[str, int],
    step: int,
) -> tuple[str, dict]:
    untried = [action for action in available if counts[action] == 0]
    if untried:
        chosen = min(untried, key=lambda action: priority[action])
        return chosen, {"policy": "untried_action", "ucb_scores": {}}
    scores = {
        action: statistics.fmean(rewards[action])
        + math.sqrt(2.0 * math.log(step) / counts[action])
        for action in available
    }
    chosen = min(available, key=lambda action: (-scores[action], priority[action]))
    return chosen, {"policy": "ucb1", "ucb_scores": scores}


def feedback_for_prompt(
    index: int, order: int, spec: TaskSpec, fitness: str, rows: list[dict], areas: list[float]
) -> dict:
    record = dict(spec.exposed_record(index, fitness, rows, areas))
    record.pop("candidate_index", None)
    return {"evaluation_order": order, "params": rows[index]["params"], **record}


def build_messages(
    spec: TaskSpec,
    seed: int,
    step: int,
    fitness: str,
    visited: list[int],
    history: list[dict],
    available: dict[str, list[dict]],
    rows: list[dict],
    areas: list[float],
) -> list[dict]:
    metric = (
        "Boolean quality verdict plus strict Nangate45 mapped area"
        if fitness == "boolean"
        else "continuous analytic numerical error/SQNR plus strict Nangate45 mapped area"
    )
    action_menu = [
        {
            "action": action,
            "meaning": spec.action_descriptions[action],
            "legal_unvisited_neighbor_count": len(available[action]),
        }
        for action in spec.actions
    ]
    return [
        {
            "role": "system",
            "content": (
                f"Choose one high-level {spec.name.upper()} hardware search action. "
                "Do not choose or invent a candidate id. A deterministic executor will expand the action "
                "to one legal unvisited candidate. Balance numerical quality and mapped area using only "
                "the observations supplied. Return only JSON: {\"action\": string, \"reason\": string}."
            ),
        },
        {
            "role": "user",
            "content": protocol.canonical(
                {
                    "experiment_seed_label": seed,
                    "step": step,
                    "feedback_policy": metric,
                    "evaluated": [
                        feedback_for_prompt(index, order, spec, fitness, rows, areas)
                        for order, index in enumerate(visited)
                    ],
                    "prior_actions": [
                        {
                            "step": item["step"],
                            "proposed_action": item["proposed_action"],
                            "executed_action": item["executed_action"],
                            "fallback_reason": item["fallback_reason"],
                        }
                        for item in history
                    ],
                    "action_menu": action_menu,
                }
            ),
        },
    ]


def run_nonllm(
    spec: TaskSpec,
    seed: int,
    fitness: str,
    rows: list[dict],
    areas: list[float],
    graph: dict[int, list[int]],
) -> dict:
    rng = random.Random(seed)
    shuffled = list(spec.actions)
    rng.shuffle(shuffled)
    priority = {action: order for order, action in enumerate(shuffled)}
    counts = {action: 0 for action in spec.actions}
    rewards = {action: [] for action in spec.actions}
    visited = [spec.initial_index]
    evaluations = []
    for step in range(1, NEW_EVALUATIONS + 1):
        candidates = action_candidates(spec, visited, rows, graph)
        available = [action for action in spec.actions if candidates[action]]
        proposed, decision = ucb_action(spec, available, counts, rewards, priority, step)
        expansion = normalize_and_expand(spec, proposed, visited, counts, rows, graph)
        candidate = expansion["candidate_index"]
        reward = archive_reward(visited, candidate, spec, fitness, rows, areas)
        repeated = counts[proposed] > 0
        visited.append(candidate)
        counts[expansion["executed_action"]] += 1
        rewards[expansion["executed_action"]].append(reward)
        evaluations.append(
            {
                "step": step,
                **expansion,
                "proposal_repeated": repeated,
                "action_decision": decision,
                "archive_reward": reward,
                "params": rows[candidate]["params"],
                "exposed": spec.exposed_record(candidate, fitness, rows, areas),
            }
        )
    return {
        "status": "complete",
        "proposer": "ucb1_action",
        "fitness": fitness,
        "seed": seed,
        "initial_index": spec.initial_index,
        "new_candidate_evaluations": len(evaluations),
        "action_priority": shuffled,
        "evaluations": evaluations,
        "visited_indices": visited,
        "terminal": spec.terminal(visited, rows, areas),
    }


def run_llm(
    spec: TaskSpec,
    seed: int,
    fitness: str,
    rows: list[dict],
    areas: list[float],
    graph: dict[int, list[int]],
    output: Path,
) -> dict:
    visited = [spec.initial_index]
    evaluations = []
    calls = []
    counts = {action: 0 for action in spec.actions}
    proposed_counts = {action: 0 for action in spec.actions}
    for step in range(1, NEW_EVALUATIONS + 1):
        candidates = action_candidates(spec, visited, rows, graph)
        messages = build_messages(spec, seed, step, fitness, visited, evaluations, candidates, rows, areas)
        call_dir = output / spec.name / "llm_calls" / f"{fitness}-seed-{seed}" / f"step-{step:02d}"
        protocol.write_json(call_dir / "request.json", {"messages": messages, "provider_seed": None})
        response = generate(
            messages,
            model=MODEL,
            api_base="https://api.deepseek.com",
            key_file=None,
            max_output_tokens=256,
            timeout=180,
            temperature=TEMPERATURE,
            seed=None,
            extra_body={"thinking": {"type": "disabled"}},
        )
        proposed = parse_action(response.get("text")) if response["status"] == "ok" else None
        expansion = normalize_and_expand(spec, proposed, visited, counts, rows, graph)
        repeated = proposed in proposed_counts and proposed_counts.get(proposed, 0) > 0
        if proposed in proposed_counts:
            proposed_counts[proposed] += 1
        candidate = expansion["candidate_index"]
        reward = archive_reward(visited, candidate, spec, fitness, rows, areas)
        visited.append(candidate)
        counts[expansion["executed_action"]] += 1
        cost = calculate_cost(response["usage"], protocol.TARIFF)
        call_record = {
            "step": step,
            "status": response["status"],
            "proposed_action": proposed,
            "executed_action": expansion["executed_action"],
            "fallback_reason": expansion["fallback_reason"],
            "proposal_repeated": repeated,
            "expanded_candidate_index": candidate,
            "usage": response["usage"],
            "elapsed_seconds": response["elapsed_seconds"],
            "error": response["error"],
            "cost": cost,
        }
        protocol.write_json(call_dir / "response.json", response)
        protocol.write_json(call_dir / "record.json", call_record)
        calls.append(call_record)
        evaluations.append(
            {
                "step": step,
                **expansion,
                "proposal_repeated": repeated,
                "archive_reward": reward,
                "params": rows[candidate]["params"],
                "exposed": spec.exposed_record(candidate, fitness, rows, areas),
            }
        )
    return {
        "status": "complete",
        "proposer": "deepseek_hierarchical_action",
        "fitness": fitness,
        "seed": seed,
        "initial_index": spec.initial_index,
        "new_candidate_evaluations": len(evaluations),
        "evaluations": evaluations,
        "calls": calls,
        "visited_indices": visited,
        "terminal": spec.terminal(visited, rows, areas),
    }


def summarize(spec: TaskSpec, runs: list[dict], expected_seeds: tuple[int, ...]) -> dict:
    output = {}
    for proposer in ("ucb1_action", "deepseek_hierarchical_action"):
        for fitness in ("boolean", "numerical"):
            members = [
                run for run in runs if run["proposer"] == proposer and run["fitness"] == fitness
            ]
            utilities = [spec.primary_utility(run["terminal"]) for run in members]
            output[f"{proposer}:{fitness}"] = {
                "complete": sum(run["status"] == "complete" for run in members),
                "paired_seeds_expected": len(expected_seeds),
                spec.primary_name + "s": utilities,
                "global_best_hits": sum(
                    run["terminal"]["hit_global_min_feasible_area"] for run in members
                ),
                "mean_architecture_class_coverage": (
                    statistics.fmean(
                        run["terminal"]["architecture_class_coverage"] for run in members
                    )
                    if spec.name == "fir" and members
                    else None
                ),
            }
    calls = [call for run in runs for call in run.get("calls", [])]
    reported = [call for call in calls if call["usage"].get("reported")]
    evaluations = [item for run in runs for item in run["evaluations"]]
    llm_evaluations = [
        item
        for run in runs
        if run["proposer"] == "deepseek_hierarchical_action"
        for item in run["evaluations"]
    ]
    output["llm_accounting"] = {
        "recorded_calls": len(calls),
        "api_ok_calls": sum(call["status"] == "ok" for call in calls),
        "repeated_action_proposals": sum(call["proposal_repeated"] for call in calls),
        "fallback_expansions": sum(call["fallback_reason"] is not None for call in calls),
        "invalid_or_failed_action_calls": sum(
            call["fallback_reason"] == "invalid_or_unparseable_action" for call in calls
        ),
        "exhausted_action_calls": sum(
            call["fallback_reason"] == "action_has_no_legal_unvisited_neighbor" for call in calls
        ),
        "reported_input_tokens": sum(call["usage"].get("input_tokens") or 0 for call in reported),
        "reported_output_tokens": sum(call["usage"].get("output_tokens") or 0 for call in reported),
        "reported_cache_tokens": sum(call["usage"].get("cache_tokens") or 0 for call in reported),
        "estimated_cost_usd_for_reported_usage": math.fsum(
            call["cost"]["estimated_cost"]
            for call in calls
            if call["cost"]["estimated_cost"] is not None
        ),
        "recorded_call_elapsed_seconds": math.fsum(call["elapsed_seconds"] for call in calls),
    }
    output["budget_audit"] = {
        "runs": len(runs),
        "all_runs_complete": all(run["status"] == "complete" for run in runs),
        "all_runs_exactly_eight_new_candidates": all(
            run["new_candidate_evaluations"] == NEW_EVALUATIONS for run in runs
        ),
        "unique_candidate_violations": sum(
            len(run["visited_indices"]) != len(set(run["visited_indices"])) for run in runs
        ),
        "total_new_candidate_evaluations": len(evaluations),
        "llm_new_candidate_evaluations": len(llm_evaluations),
    }
    interactions = []
    for seed in expected_seeds:
        by_cell = {
            (run["proposer"], run["fitness"]): run
            for run in runs
            if run["seed"] == seed
        }
        required = {
            ("ucb1_action", "boolean"),
            ("ucb1_action", "numerical"),
            ("deepseek_hierarchical_action", "boolean"),
            ("deepseek_hierarchical_action", "numerical"),
        }
        if not required.issubset(by_cell):
            continue
        utility = {cell: spec.primary_utility(by_cell[cell]["terminal"]) for cell in required}
        value = (
            utility[("deepseek_hierarchical_action", "numerical")]
            - utility[("ucb1_action", "numerical")]
            - utility[("deepseek_hierarchical_action", "boolean")]
            + utility[("ucb1_action", "boolean")]
        )
        interactions.append({"seed": seed, "value": value})
    output["interaction"] = {
        "definition": (
            "(hierarchical LLM numerical - UCB numerical) - "
            f"(hierarchical LLM Boolean - UCB Boolean), using {spec.primary_name}; higher is favorable"
        ),
        "complete_paired_seeds": interactions,
        "mean": statistics.fmean(item["value"] for item in interactions) if interactions else None,
    }
    return output


def write_readme(output: Path, mode: str, task_summaries: dict) -> None:
    lines = [
        f"# M4 hierarchical action proposer {mode}",
        "",
        "DeepSeek selects only a generic hardware action. A frozen executor expands it to a legal unvisited typed neighbor. Repeated valid actions remain valid while another neighbor exists; invalid or exhausted actions use a recorded least-used deterministic fallback without spending an extra evaluation.",
        "",
        "The non-LLM comparator is UCB1 over the same actions and uses the same expansion rule. Every cell has exactly eight new-candidate evaluations. FIR and NCO terminal truth and strict Nangate45 area identities are inherited unchanged from their formal v2 artifacts; no RTL generation or synthesis is performed here.",
        "",
    ]
    for task, summary in task_summaries.items():
        lines.extend([f"## {task.upper()}", ""])
        for cell in (
            "ucb1_action:boolean",
            "ucb1_action:numerical",
            "deepseek_hierarchical_action:boolean",
            "deepseek_hierarchical_action:numerical",
        ):
            item = summary[cell]
            lines.append(
                f"- `{cell}`: {item['complete']}/{item['paired_seeds_expected']} complete; "
                f"{task_summaries[task].get('primary_name', '')}{item.get(TASKS[task].primary_name + 's')}"
            )
        lines.extend(
            [
                "",
                f"Interaction records: {summary['interaction']['complete_paired_seeds']}; mean {summary['interaction']['mean']}.",
                f"LLM accounting: {summary['llm_accounting']}.",
                "",
            ]
        )
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")


def run_task(
    spec: TaskSpec,
    output: Path,
    seed_count: int,
    phase: str,
) -> tuple[dict, dict]:
    rows, areas, graph, provenance = load_frozen_task(spec)
    task_dir = output / spec.name
    task_dir.mkdir(parents=True, exist_ok=True)
    results_path = task_dir / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {"runs": []}
    seeds = spec.seeds[:seed_count]
    existing = {(run["proposer"], run["fitness"], run["seed"]) for run in results["runs"]}
    started = time.monotonic()
    for seed in seeds:
        if phase in ("nonllm", "all"):
            for fitness in ("boolean", "numerical"):
                key = ("ucb1_action", fitness, seed)
                if key not in existing:
                    results["runs"].append(run_nonllm(spec, seed, fitness, rows, areas, graph))
                    existing.add(key)
                    results["summary"] = summarize(spec, results["runs"], seeds)
                    protocol.write_json(results_path, results)
        if phase in ("llm", "all"):
            for fitness in ("boolean", "numerical"):
                key = ("deepseek_hierarchical_action", fitness, seed)
                if key not in existing:
                    results["runs"].append(
                        run_llm(spec, seed, fitness, rows, areas, graph, output)
                    )
                    existing.add(key)
                    results["summary"] = summarize(spec, results["runs"], seeds)
                    protocol.write_json(results_path, results)
    results["summary"] = summarize(spec, results["runs"], seeds)
    results["last_driver_invocation_wall_seconds"] = time.monotonic() - started
    protocol.write_json(results_path, results)
    task_manifest = {
        "schema_version": "m4-hierarchical-action-pilot-v1",
        "status": "complete" if results["summary"]["budget_audit"]["all_runs_complete"] else "partial",
        "task": spec.name,
        "seeds": list(seeds),
        "new_candidate_evaluations_per_cell_seed": NEW_EVALUATIONS,
        "proposers": ["deepseek_hierarchical_action", "ucb1_action"],
        "fitnesses": ["boolean", "numerical"],
        "actions": [
            {"action": action, "meaning": spec.action_descriptions[action]}
            for action in spec.actions
        ],
        "executor_rule": "all typed neighbors of all visited candidates; selected action expands earliest visited parent, then canonical candidate params, then index",
        "fallback_rule": "invalid or exhausted action -> least executed available action, then frozen action order; same search evaluation, no extra LLM call",
        "nonllm_policy": "UCB1 on Pareto-archive survival/dominance reward; untried actions first in seed-shuffled priority",
        "terminal_protocol": "unchanged imported formal-v2 terminal function and frozen row truth",
        "interaction_primary": (
            "held-out normalized MSE-area hypervolume; reference is 1.05 times the frozen "
            "20-candidate maxima, so utility remains defined when no strict-feasible candidate is visited"
        ),
        "source_provenance": provenance,
        "results_sha256": protocol.sha(results_path),
    }
    protocol.write_json(task_dir / "manifest.json", task_manifest)
    return results, task_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    parser.add_argument("--phase", choices=("nonllm", "llm", "all"), default="all")
    parser.add_argument("--tasks", nargs="+", choices=tuple(TASKS), default=list(TASKS))
    parser.add_argument("--seeds", type=int, choices=(1, 2, 3))
    args = parser.parse_args()
    seed_count = args.seeds if args.seeds is not None else (1 if args.mode == "smoke" else 3)
    if args.mode == "smoke" and seed_count != 1:
        raise RuntimeError("smoke mode is frozen to one seed")
    output = OUTPUTS[args.mode]
    output.mkdir(parents=True, exist_ok=True)
    if args.phase in ("llm", "all"):
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if not key or any(character.isspace() for character in key):
            raise RuntimeError("DeepSeek key file is missing or invalid")
        os.environ["DEEPSEEK_API_KEY"] = key
    task_summaries = {}
    task_manifests = {}
    for task in args.tasks:
        results, manifest = run_task(TASKS[task], output, seed_count, args.phase)
        task_summaries[task] = results["summary"]
        task_manifests[task] = manifest
    root_manifest = {
        "schema_version": "m4-hierarchical-fir-nco-pilot-v1",
        "mode": args.mode,
        "status": (
            "complete"
            if all(item["status"] == "complete" for item in task_manifests.values())
            else "partial"
        ),
        "created_date": "2026-10-09",
        "tasks": args.tasks,
        "seed_count": seed_count,
        "phase": args.phase,
        "runner_sha256": protocol.sha(Path(__file__)),
        "model": {
            "name": MODEL,
            "temperature": TEMPERATURE,
            "provider_seed": None,
            "thinking": "disabled",
            "automatic_retry": False,
            "tariff": protocol.TARIFF,
        },
        "task_manifest_sha256": {
            task: protocol.sha(output / task / "manifest.json") for task in args.tasks
        },
    }
    protocol.write_json(output / "manifest.json", root_manifest)
    write_readme(output, args.mode, task_summaries)
    return 0 if root_manifest["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
