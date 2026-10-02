"""两臂共享的确定性非支配排序、crowding 与结构族锁定。"""

from __future__ import annotations

import copy
import json
import math
from typing import Mapping, Sequence

from .canonicalize import candidate_hash, canonical_json
from .validate import validate_candidate


FIELDS = ("candidate", "candidate_hash", "Q", "area_um2")


def family_key(candidate: Mapping) -> str:
    """只锁 primitive 类和组合拓扑；表深、级数和定点参数不进入族键。"""
    validate_candidate(candidate)

    def shape(node):
        result = {"kind": node["kind"]}
        if node["kind"] == "phasor_compose":
            result.update(coarse=shape(node["coarse"]), residual=shape(node["residual"]))
        elif node["kind"] == "lut_sincos":
            result["interpolation"] = node["interpolation"]
        return result

    return json.dumps({"nco": shape(candidate["nco"]), "fir": candidate["filter_decimator"]["kind"]},
                      sort_keys=True, separators=(",", ":"))


def _unique(records: Sequence[Mapping]) -> list[dict]:
    by_hash = {}
    for record in records:
        value = {key: copy.deepcopy(record[key]) for key in FIELDS}
        validate_candidate(value["candidate"])
        value["candidate"] = json.loads(canonical_json(value["candidate"]))
        if candidate_hash(value["candidate"]) != value["candidate_hash"]:
            raise ValueError("candidate hash mismatch")
        for key in ("Q", "area_um2"):
            number = value[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ValueError("selection requires finite numeric objectives")
        if value["Q"] < 0 or value["area_um2"] <= 0:
            raise ValueError("invalid quality/area")
        old = by_hash.get(value["candidate_hash"])
        if old is not None and old != value:
            raise ValueError("conflicting duplicate candidate")
        by_hash[value["candidate_hash"]] = value
    return [by_hash[key] for key in sorted(by_hash)]


def _dominates(a: dict, b: dict) -> bool:
    return (a["Q"] <= b["Q"] and a["area_um2"] <= b["area_um2"]
            and (a["Q"] < b["Q"] or a["area_um2"] < b["area_um2"]))


def ranked(records: Sequence[Mapping]) -> list[dict]:
    """返回独立副本；rank/crowding仅用于内部选择，不作为数值实验结果。"""
    values = _unique(records)
    outgoing = [[] for _ in values]
    incoming = [0 for _ in values]
    for i, a in enumerate(values):
        for j in range(i + 1, len(values)):
            b = values[j]
            if _dominates(a, b):
                outgoing[i].append(j)
                incoming[j] += 1
            elif _dominates(b, a):
                outgoing[j].append(i)
                incoming[i] += 1
    front = [i for i, count in enumerate(incoming) if count == 0]
    level = 0
    result = []
    while front:
        distances = {i: 0.0 for i in front}
        for field in ("Q", "area_um2"):
            ordered = sorted(front, key=lambda i: (values[i][field], values[i]["candidate_hash"]))
            low, high = values[ordered[0]][field], values[ordered[-1]][field]
            if high == low:
                continue
            distances[ordered[0]] = distances[ordered[-1]] = math.inf
            for pos in range(1, len(ordered) - 1):
                distances[ordered[pos]] += (values[ordered[pos + 1]][field]
                                           - values[ordered[pos - 1]][field]) / (high - low)
        next_front = []
        for i in front:
            result.append({**values[i], "rank": level, "crowding": distances[i]})
            for j in outgoing[i]:
                incoming[j] -= 1
                if incoming[j] == 0:
                    next_front.append(j)
        front = next_front
        level += 1
    return sorted(result, key=lambda r: (r["rank"], -r["crowding"], r["candidate_hash"]))


def truncate(records: Sequence[Mapping], capacity: int = 8,
             families: Sequence[str] | None = None) -> list[dict]:
    if type(capacity) is not int or capacity < 1:
        raise ValueError("capacity must be positive")
    allowed = None if families is None else list(families)
    if allowed is not None:
        if not allowed or len(set(allowed)) != len(allowed) or len(allowed) > capacity:
            raise ValueError("invalid locked families")
        records = [r for r in records if family_key(r["candidate"]) in allowed]
    ordered = ranked(records)
    chosen = set()
    if allowed is not None:
        for family in allowed:
            members = [r for r in ordered if family_key(r["candidate"]) == family]
            if not members:
                raise ValueError("locked family has no member")
            chosen.add(members[0]["candidate_hash"])
    for record in ordered:
        if len(chosen) >= capacity:
            break
        chosen.add(record["candidate_hash"])
    return [r for r in ordered if r["candidate_hash"] in chosen]


def lock_families(history: Sequence[Mapping], max_families: int = 3) -> list[str]:
    if type(max_families) is not int or max_families < 1:
        raise ValueError("max_families must be positive")
    families = []
    for record in ranked(history):
        key = family_key(record["candidate"])
        if key not in families:
            families.append(key)
        if len(families) == max_families:
            break
    return families


def tournament(population: Sequence[Mapping], rng, family: str | None = None) -> dict:
    eligible = [r for r in population if family is None or family_key(r["candidate"]) == family]
    ordered = ranked(eligible)
    if not ordered:
        raise ValueError("no eligible parent")
    if len(ordered) == 1:
        return ordered[0]
    indices = rng.choice(len(ordered), size=2, replace=False)
    return ordered[min(int(i) for i in indices)]


def main_archive(history: Sequence[Mapping], q_budget: float) -> list[dict]:
    if isinstance(q_budget, bool) or not math.isfinite(q_budget) or q_budget <= 0:
        raise ValueError("invalid q_budget")
    validated = _unique(history)
    return [r for r in ranked([r for r in validated if r["Q"] <= q_budget]) if r["rank"] == 0]
