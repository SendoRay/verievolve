#!/usr/bin/env python3
"""生成 CIC witness 第二次冻结所需的预检 manifest。

本入口只展开冻结候选、运行逐位等价扫描并物化场景清单。它不生成链级参考，
不调用 ``aligned_impl_error``，也不计算局部指标或任何 q。
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


BENCH = Path(__file__).resolve().parent.parent.parent
ROOT = BENCH.parent.parent
sys.path.insert(0, str(BENCH))

from chains.cic.bittrue import run_iq
from chains.cic.gen_candidates_v1 import expand, static_checks


PROTOCOL = ROOT / "thesis" / "CONTRACT_CIC_WITNESS_v1.md"
OUT = BENCH / "experiments_system" / "cic_witness_v1" / "preflight_manifest.json"
FS_IN_HZ = 2_000_000
MAIN_GRIDS_KHZ = {
    2: [200.0, 250.0, 300.0, 350.0, 400.0, 450.0],
    4: [180.0, 195.0, 210.0, 225.0, 240.0, 248.0],
}
# 四个 held-out 点在第二次冻结时显式确认。规则取主网格第 1、2、4、5 个间隔的中点，
# 覆盖两端且不与 main 重合；正式 q 运行前仍由用户冻结整个 manifest。
HELDOUT_GAP_INDEXES = (0, 1, 3, 4)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _seed(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") >> 1


def _blocker_hz(R: int, g_khz: float) -> float:
    fs_out = FS_IN_HZ / R
    return fs_out - g_khz * 1000.0 if R == 2 else fs_out + g_khz * 1000.0


def _scenario(split: str, R: int, anchor_g: float, kind: str,
              blocker_g: float | None, rel_db: float | None) -> dict:
    raw = {
        "version": "cic-scenario-v1-preflight",
        "split": split,
        "R": R,
        "anchor_g_khz": anchor_g,
        "kind": kind,
        "blocker_g_khz": blocker_g,
        "blocker_rel_db": rel_db,
        "awgn_snr_db": 30.0,
    }
    key = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return {
        **raw,
        "blocker_hz": None if blocker_g is None else _blocker_hz(R, blocker_g),
        "seed": _seed(key),
        "scenario_key": key,
    }


def build_scenario_manifest() -> dict:
    rows: list[dict] = []
    heldout_grids: dict[int, list[float]] = {}
    for R, main in MAIN_GRIDS_KHZ.items():
        held = [(main[i] + main[i + 1]) / 2.0 for i in HELDOUT_GAP_INDEXES]
        heldout_grids[R] = held
        for split, grid in (("main", main), ("heldout", held)):
            for i, g in enumerate(grid):
                g_next = grid[i + 1] if i + 1 < len(grid) else grid[i - 1]
                rows.append(_scenario(split, R, g, "clean", None, None))
                rows.append(_scenario(split, R, g, "alias_at_g", g, -3.0))
                rows.append(_scenario(split, R, g, "alias_at_g_next", g_next, -3.0))
        for g in main:
            rows.append(_scenario("stress", R, g, "alias_at_g", g, 6.0))
    counts = defaultdict(int)
    for row in rows:
        counts[f"R{row['R']}_{row['split']}"] += 1
        fb = row["blocker_hz"]
        if fb is not None and not (169_000.0 < fb < FS_IN_HZ / 2):
            raise RuntimeError(f"invalid blocker frequency: {row}")
    return {
        "version": "cic-scenario-v1-preflight",
        "status": "materialized for user second freeze; no q evaluated",
        "signal": {
            "kind": "QPSK with RRC pulse shaping",
            "symbol_rate_hz": 250_000.0,
            "rrc_beta": 0.35,
            "fs_in_hz": FS_IN_HZ,
            "adc": "signed 12-bit Q1.11, half-up quantization, sat12",
            "awgn_snr_db": 30.0,
            "n_warmup_symbols": 64,
            "n_measure_symbols": 1600,
        },
        "heldout_rule": {
            "description": "midpoints of main-grid gaps 1, 2, 4, and 5",
            "gap_indexes_zero_based": list(HELDOUT_GAP_INDEXES),
            "grids_khz": {f"R{R}": grid for R, grid in heldout_grids.items()},
        },
        "counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def equivalence_traces() -> dict[str, tuple[list[int], list[int]]]:
    """不含质量含义的固定整数压力输入；每条 trace 之间复位状态。"""
    n = 256
    impulse_i = [0] * n
    impulse_q = [0] * n
    impulse_i[:8] = [2047, -2048, 1, -1, 1024, -1024, 3, -3]
    impulse_q[:8] = [-2048, 2047, -1, 1, -1024, 1024, -3, 3]
    alternating_i = [2047 if k % 2 == 0 else -2048 for k in range(n)]
    alternating_q = [1023 if k % 3 else -1024 for k in range(n)]
    dc_i = [2047] * n
    dc_q = [-2048] * n
    # 独立、固定的整数 LCG；只用于覆盖舍入边界，不是实验随机 seed。
    state = 0x13579BDF
    prng_i: list[int] = []
    prng_q: list[int] = []
    for _ in range(n):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        prng_i.append((state & 0xFFF) - 2048)
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        prng_q.append((state & 0xFFF) - 2048)
    return {
        "impulse_edges": (impulse_i, impulse_q),
        "alternating_extrema": (alternating_i, alternating_q),
        "dc_extrema": (dc_i, dc_q),
        "fixed_lcg": (prng_i, prng_q),
    }


def _rounding_is_active(row: dict) -> bool:
    B = row["B"]
    internal_drop = B[0] > 0 or any(B[i] > B[i - 1] for i in range(1, len(B)))
    output_drop = row["B_fmt"] > B[-1]
    return internal_drop or output_drop


def _semantic_key(row: dict) -> dict:
    # 舍入模式仅在至少一个右移发生时有语义；overflow 始终保留，不能因有限 trace
    # 未触发事件而把 wrap/sat 合并。
    return {
        "R": row["R"],
        "N": row["N"],
        "B": row["B"],
        "B_fmt": row["B_fmt"],
        "overflow": row["overflow"],
        "rounding": row["rounding"] if _rounding_is_active(row) else "inactive",
    }


def scan_equivalence(rows: list[dict]) -> dict:
    traces = equivalence_traces()
    results: dict[str, dict] = {}
    for row in rows:
        stream: list[list[int]] = []
        trace_events: dict[str, dict] = {}
        for trace_name, (i_codes, q_codes) in traces.items():
            got = run_iq(row, i_codes, q_codes)
            stream.extend([[i, q] for i, q in zip(got["i"], got["q"])])
            trace_events[trace_name] = got["events"]
        results[row["name"]] = {
            "output_sha256": _json_sha(stream),
            "n_output_iq": len(stream),
            "semantic_key": _semantic_key(row),
            "semantic_sha256": _json_sha(_semantic_key(row)),
            "events": trace_events,
        }

    by_semantic: dict[str, list[str]] = defaultdict(list)
    by_trace: dict[str, list[str]] = defaultdict(list)
    for name, result in results.items():
        by_semantic[result["semantic_sha256"]].append(name)
        by_trace[result["output_sha256"]].append(name)

    classes: list[dict] = []
    for semantic_hash, names in sorted(by_semantic.items()):
        hashes = {results[name]["output_sha256"] for name in names}
        if len(hashes) != 1:
            raise RuntimeError(f"semantic-equivalent candidates disagree bitwise: {names}")
        ordered = sorted(names)
        classes.append({
            "representative": ordered[0],
            "members": ordered,
            "semantic_sha256": semantic_hash,
            "output_sha256": next(iter(hashes)),
            "merge_reason": "same operational semantics and same frozen-trace bitstream",
        })

    collisions = []
    for output_hash, names in sorted(by_trace.items()):
        semantic_hashes = {results[name]["semantic_sha256"] for name in names}
        if len(names) > 1 and len(semantic_hashes) > 1:
            collisions.append({
                "output_sha256": output_hash,
                "members": sorted(names),
                "action": "kept separate: finite-trace equality is not a semantic proof",
            })
    return {
        "trace_suite": {
            "names": list(traces),
            "length_per_trace": {name: len(v[0]) for name, v in traces.items()},
            "reset_between_traces": True,
            "contains_no_chain_q": True,
        },
        "candidate_results": results,
        "classes": classes,
        "representatives": [x["representative"] for x in classes],
        "input_count": len(rows),
        "deduplicated_count": len(classes),
        "trace_collisions_kept_separate": collisions,
    }


def _git_identity() -> dict:
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          text=True, capture_output=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                           text=True, capture_output=True, check=True).stdout
    return {"head": head, "working_tree_dirty": bool(dirty)}


def build_preflight_manifest() -> dict:
    rows = expand()
    # static_checks 的 blocker 诊断来自 Python tuple；在构造边界先规范成 JSON
    # 原生类型，保证内存结果与落盘后重新读取的结果逐字一致。
    checks = json.loads(json.dumps(static_checks(rows)))
    if checks["problems"]:
        raise RuntimeError(f"candidate static checks failed: {checks['problems']}")
    files = [
        PROTOCOL,
        BENCH / "chains/cic/gen_candidates_v1.py",
        BENCH / "chains/cic/bittrue.py",
        BENCH / "chains/cic/prepare_witness_v1.py",
        ROOT / "tests/test_cic_hogenauer.py",
        ROOT / "tests/test_cic_bittrue.py",
        ROOT / "tests/test_cic_preflight.py",
    ]
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise RuntimeError(f"preflight fingerprint files missing: {missing}")
    equivalence = scan_equivalence(rows)
    return {
        "schema_version": "cic-witness-preflight-v1",
        "status": "awaiting user second freeze; chain q forbidden",
        "protocol": {
            "path": str(PROTOCOL.relative_to(ROOT)),
            "sha256": _sha256(PROTOCOL),
            "first_freeze_approved": "2026-10-04",
        },
        "candidate_set": {
            "generated_count": len(rows),
            "static_checks": checks,
            "rows": rows,
        },
        "equivalence_scan": equivalence,
        "deduplicated_pool": equivalence["representatives"],
        "scenario_manifest": build_scenario_manifest(),
        "reproducibility": {
            "code_sha256": {str(p.relative_to(ROOT)): _sha256(p) for p in files[1:]},
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "git": _git_identity(),
        },
        "formal_execution": {
            "allowed": False,
            "forbidden_metrics": ["chain q", "local metric ranking", "reversal decision"],
            "remaining_gate": "user approval of this exact preflight manifest",
        },
    }


def main() -> int:
    manifest = build_preflight_manifest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"[cic preflight] generated={manifest['candidate_set']['generated_count']}, "
          f"deduplicated={len(manifest['deduplicated_pool'])}")
    print("[cic preflight] chain q not computed; formal execution locked")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
