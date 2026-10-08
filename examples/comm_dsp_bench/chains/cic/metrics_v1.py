"""CIC witness 冻结局部指标与链级判定辅助函数。"""

from __future__ import annotations

import math

import numpy as np

from chains.cic.gen_candidates_v1 import eq21_gain
from chains.ddc.metrics import aligned_impl_error


Q_BUDGET = (10 ** (0.10 / 10.0) - 1.0) / (10 ** (30.0 / 10.0))
EPSILON_Q = 0.1 * Q_BUDGET
P_REF_LOCAL = 0.5


def local_metrics(row: dict) -> dict:
    R, N = int(row["R"]), int(row["N"])
    B = [int(x) for x in row["B"]]
    norm2 = float((1 << 22) * (R ** (2 * N)))
    sources: list[dict] = []
    previous = 0
    for j, current in enumerate(B, 1):
        if current > previous:
            gain = eq21_gain(R, N, j)
            base_variance = gain * float(1 << (2 * current)) / 12.0
            sources.append({
                "source_j": j,
                "kind": "lock_pruning",
                "B": current,
                "G": gain,
                "normalized_error_power": base_variance / norm2,
            })
        previous = current
    if int(row["B_fmt"]) > B[-1]:
        b_fmt = int(row["B_fmt"])
        sources.append({
            "source_j": 2 * N + 1,
            "kind": "output_format",
            "B": b_fmt,
            "G": 1,
            "normalized_error_power": float(1 << (2 * b_fmt)) / 12.0 / norm2,
        })
    total = sum(x["normalized_error_power"] for x in sources)
    exact = total == 0.0
    total_snr = None if exact else 10.0 * math.log10(P_REF_LOCAL / total)
    worst_stage = None if exact else min(
        10.0 * math.log10(P_REF_LOCAL / x["normalized_error_power"])
        for x in sources
    )
    return {
        "name": row["name"],
        "R": R,
        "N": N,
        "hogenauer_predicted_snr_db": total_snr,
        "worst_stage_sqnr_db": worst_stage,
        "total_cumulative_pruning_bits": B[-1],
        "exact_under_local_model": exact,
        "predicted_error_power": total,
        "sources": sources,
    }


def exact_zero_q_calibration() -> dict:
    code = np.arange(256, dtype=np.int64) - 128
    y = (code + 1j * code[::-1]) / float(1 << 15)
    result = aligned_impl_error(y, y.copy(), 64, y_des_ref=y)
    if result["err_aligned"] != 0.0:
        raise RuntimeError(f"CIC q_cal is not exact zero: {result}")
    return {
        "q_cal": 0.0,
        "q_budget": Q_BUDGET,
        "epsilon_q": max(0.0, EPSILON_Q),
        "kind": "exact-representable-identical-reference",
    }


def _metric_value(row: dict, field: str, higher_is_better: bool) -> float:
    value = row[field]
    if value is None:
        return math.inf if higher_is_better else -math.inf
    return float(value)


def analyze_order(local_rows: list[dict], aggregates: list[dict],
                  epsilon_q: float, pruning_tolerance_bits: int = 0) -> dict:
    local = {row["name"]: row for row in local_rows}
    q = {row["candidate"]: float(row["Q"]) for row in aggregates}
    specs = {
        "hogenauer_predicted_snr_db": {"higher": True, "epsilon": 0.10},
        "worst_stage_sqnr_db": {"higher": True, "epsilon": 0.10},
        "total_cumulative_pruning_bits": {
            "higher": False, "epsilon": float(pruning_tolerance_bits)
        },
    }
    report: dict = {"epsilon_Q": epsilon_q, "metrics": {}}
    for metric, rule in specs.items():
        per_r = {}
        for R in (2, 4):
            names = sorted(name for name, row in local.items() if row["R"] == R)
            strict, collapse = [], []
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    va = _metric_value(local[a], metric, rule["higher"])
                    vb = _metric_value(local[b], metric, rule["higher"])
                    qa, qb = q[a], q[b]
                    if math.isinf(va) and math.isinf(vb):
                        delta = 0.0
                    else:
                        delta = va - vb
                    eps = rule["epsilon"]
                    local_winner = None
                    if rule["higher"]:
                        if delta > eps:
                            local_winner = a
                        elif delta < -eps:
                            local_winner = b
                    else:
                        if delta < -eps:
                            local_winner = a
                        elif delta > eps:
                            local_winner = b
                    if local_winner is not None:
                        loser = b if local_winner == a else a
                        if q[local_winner] > q[loser] + epsilon_q:
                            strict.append({
                                "local_winner": local_winner,
                                "chain_winner": loser,
                                "local_winner_value": local[local_winner][metric],
                                "chain_winner_value": local[loser][metric],
                                "q_local_winner": q[local_winner],
                                "q_chain_winner": q[loser],
                            })
                    elif abs(qa - qb) > epsilon_q:
                        collapse.append({
                            "a": a, "b": b,
                            "local_a": local[a][metric], "local_b": local[b][metric],
                            "q_a": qa, "q_b": qb,
                        })
            per_r[f"R{R}"] = {
                "strict_reversals": strict,
                "collapses": collapse,
                "n_strict": len(strict),
                "n_collapse": len(collapse),
            }
        report["metrics"][metric] = {**rule, "by_R": per_r}
    return report
