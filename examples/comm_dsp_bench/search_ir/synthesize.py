"""固定开发候选的 full-DDC mapped cell area；不是正式搜索或 PPA 评价。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

import numpy as np
import scipy

from chains.ddc import candidates, ref_chain

from .canonicalize import candidate_hash, canonical_json
from .dev_fixtures import development_candidates
from .lower_bittrue import resolve_fir_coefficients
from .lower_rtl import lower_ddc_rtl
from .validate import validate_candidate


BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parent.parent
LIBERTY = BENCH / "pdk/NangateOpenCellLibrary_typical.lib"
OUTPUT_ROOT = BENCH / "experiments_search/stage_c"
EXPECTED_PORTS = {
    "clk": ("input", 1), "rst_n": ("input", 1),
    "in_valid": ("input", 1), "in_ready": ("output", 1),
    "fcw": ("input", 32), "i_in": ("input", 12), "q_in": ("input", 12),
    "y_re": ("output", 16), "y_im": ("output", 16),
    "out_valid": ("output", 1), "out_ready": ("input", 1),
}


class SynthesisError(RuntimeError):
    """任何缺失、未映射或身份不一致都不能产生有效面积。"""


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value) -> str:
    return _sha(_json(value).encode("utf-8"))


def _write_new(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(_json(value) + "\n")


def _file(path: Path) -> dict:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": _sha(resolved.read_bytes())}


def _sources() -> list[dict]:
    paths = [
        *Path(__file__).parent.glob("*.py"),
        *(BENCH / "chains/ddc" / name for name in (
            "spec.py", "fixed_chain.py", "ref_chain.py", "scenarios.py",
            "candidates.py", "rtl_gen.py",
        )),
        BENCH / "certfit/tpl_cordic.py", BENCH / "design_gen.py",
    ]
    return [_file(path) for path in sorted(set(paths))]


_LOADED_SOURCES = _sources()


def _tool(name: str, version_args: list[str]) -> dict:
    executable = shutil.which(name)
    if executable is None:
        raise SynthesisError(f"找不到 {name}")
    identity = _file(Path(executable))
    proc = subprocess.run([identity["path"], *version_args], capture_output=True,
                          text=True, timeout=30, check=True)
    identity["version"] = (proc.stdout + proc.stderr).strip()
    if not identity["version"]:
        raise SynthesisError(f"{name} 未返回版本")
    return identity


def synthesis_script(abc_path: str) -> str:
    if not Path(abc_path).is_absolute() or any(x in abc_path for x in ('"', '\n', '\r', '\\')):
        raise SynthesisError("ABC 必须使用可安全引用的绝对路径")
    return "\n".join([
        "read_liberty -lib ../cells.lib",
        "read_verilog -sv design.v",
        "hierarchy -check -top top",
        "synth -top top -flatten -noabc",
        "dffunmap",
        "dfflibmap -liberty ../cells.lib",
        f'abc -exe "{abc_path}" -liberty ../cells.lib',
        "clean",
        # flatten 的来源元数据不是逻辑单元；其他未映射 cell 仍由 check 拒绝。
        "delete t:$scopeinfo",
        "check -mapped -assert",
        "tee -o stat.json stat -json -liberty ../cells.lib -top top",
        "write_json mapped.json",
        "",
    ])


def build_contract() -> dict:
    if _sources() != _LOADED_SOURCES:
        raise SynthesisError("源码在导入后改变，请使用新进程")
    yosys = _tool("yosys", ["-V"])
    abc = _tool("yosys-abc", ["-c", "version"])
    script = synthesis_script(abc["path"])
    return {
        "schema_version": "search-ir-full-ddc-synthesis-v1",
        "scope": "fixed development candidates; full-DDC mapped cell area",
        "top": "top", "flatten": True,
        "expected_ports": EXPECTED_PORTS,
        "fcw": "programmable input; not constant-folded per scenario",
        "yosys": yosys, "abc": abc, "liberty": _file(LIBERTY),
        "corner": "Nangate45 typical, 1.1V, 25C", "area_unit": "um^2",
        "script": script, "script_sha256": _sha(script.encode()),
        "sources": _LOADED_SOURCES,
        "environment": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__},
        "sdc": None, "timing_power_claims_allowed": False,
        "microarchitecture_search": False,
        "cache_enabled": False, "resume_enabled": False,
        "timeout_seconds": 600,
        "area_crosscheck": {
            "primary": "sum of JSON top cell counts times Liberty cell areas",
            "stat_relative_tolerance": 5e-6, "stat_absolute_tolerance_um2": 1e-6,
            "reason": "allow finite textual precision in Yosys stat, not physical variation",
        },
        "repeat_hash_definition": (
            "sorted top port/cell connectivity, types and parameters; excludes instance names, "
            "source attributes and wire labels; retains Yosys signal IDs; not an equivalence proof"
        ),
    }


def liberty_areas(text: str) -> dict[str, float]:
    """仅解析冻结 Nangate Liberty 的 cell/area，不实现通用 Liberty 解析器。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    starts = list(re.finditer(r'\bcell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{', text))
    areas = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        found = re.search(r"\barea\s*:\s*([^;]+);", text[match.end():end])
        if found is None:
            raise SynthesisError(f"库单元 {match[1]} 缺少面积")
        area = float(found[1])
        if not math.isfinite(area) or area < 0 or match[1] in areas:
            raise SynthesisError("库单元面积无效或名称重复")
        areas[match[1]] = area
    if not areas:
        raise SynthesisError("未找到 Nangate cell area")
    return areas


def validate_mapped_result(stat: dict, netlist: dict, areas: dict[str, float]) -> dict:
    """以 JSON top.cells 为计数来源，并与 stat/Liberty 交叉核对。"""
    try:
        top = netlist["modules"]["top"]
        module_stat = stat["modules"]["\\top"]
        ports = {name: (port["direction"], len(port["bits"]))
                 for name, port in top["ports"].items()}
        if ports != EXPECTED_PORTS or top.get("memories"):
            raise SynthesisError("top 接口漂移或存在未映射 memory")
        cells = top["cells"]
        types = Counter(cell["type"] for cell in cells.values())
        if not types or any(name not in areas or name.startswith("$") for name in types):
            raise SynthesisError("存在通用单元、未知 blackbox 或空网表")
        counts = module_stat["num_cells_by_type"]
        if any(type(v) is not int or v <= 0 for v in counts.values()):
            raise SynthesisError("stat 单元计数无效")
        if (type(module_stat["num_cells"]) is not int
                or dict(types) != counts or module_stat["num_cells"] != sum(types.values())):
            raise SynthesisError("stat 与 JSON 网表单元计数不一致")
        area = module_stat["area"]
        if type(area) not in (int, float) or not math.isfinite(area) or area <= 0:
            raise SynthesisError("面积必须是有限正数")
        summed = math.fsum(areas[name] * count for name, count in types.items())
        if not math.isclose(area, summed, rel_tol=5e-6, abs_tol=1e-6):
            raise SynthesisError("stat 面积与实际库单元面积之和不一致")
        normalized = {
            "ports": {name: {k: v for k, v in p.items() if k != "attributes"}
                      for name, p in top["ports"].items()},
            "cells": sorted([
                {"type": c["type"], "parameters": c.get("parameters", {}),
                 "port_directions": c["port_directions"], "connections": c["connections"]}
                for c in cells.values()
            ], key=_json),
        }
        return {
            "area_um2": summed, "stat_reported_area_um2": float(area),
            "library_area_sum_um2": summed,
            "num_cells": sum(types.values()), "cells_by_type": dict(sorted(types.items())),
            "stat_top": module_stat, "stat_top_sha256": _digest(module_stat),
            "normalized_netlist": normalized, "netlist_semantic_sha256": _digest(normalized),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise SynthesisError(f"映射结果字段无效: {exc}") from exc


def _run_process(command: list[str], cwd: Path, timeout: int) -> dict:
    """超时清理本次综合的整个进程组，防止 ABC 遗留。"""
    started = time.monotonic()
    with (cwd / "stdout.log").open("xb") as stdout, (cwd / "stderr.log").open("xb") as stderr:
        proc = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                start_new_session=True)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        except BaseException:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise
    return {"returncode": proc.returncode, "timed_out": timed_out,
            "wall_seconds": time.monotonic() - started}


def _check_contract(contract: dict) -> None:
    for key in ("yosys", "abc", "liberty"):
        current = _file(Path(contract[key]["path"]))
        if current["sha256"] != contract[key]["sha256"]:
            raise SynthesisError(f"{key} 身份漂移")
    if _sources() != contract["sources"]:
        raise SynthesisError("生成/综合源码身份漂移")
    if contract["script"] != synthesis_script(contract["abc"]["path"]):
        raise SynthesisError("综合脚本与固定模板不一致")
    if _sha(contract["script"].encode()) != contract["script_sha256"]:
        raise SynthesisError("综合脚本摘要不一致")


def run_job(directory: Path, binding: dict, contract: dict, rtl: str, areas: dict) -> dict:
    directory.mkdir(exist_ok=False)
    result = {"binding": binding, "status": "failed", "area_um2": None}
    stage = "identity"
    try:
        _write_new(directory / "started.json", binding)
        _check_contract(contract)
        if _digest(contract) != binding["contract_sha256"]:
            raise SynthesisError("contract 与预注册摘要不一致")
        if _sha(rtl.encode()) != binding["rtl_sha256"]:
            raise SynthesisError("RTL 与预注册摘要不一致")
        if _sha((directory.parent / "cells.lib").read_bytes()) != contract["liberty"]["sha256"]:
            raise SynthesisError("Liberty 快照身份漂移")
        (directory / "design.v").write_text(rtl, encoding="utf-8")
        (directory / "run.ys").write_text(contract["script"], encoding="utf-8")
        stage = "process"
        process = _run_process([contract["yosys"]["path"], "-T", "-s", "run.ys"],
                               directory, contract["timeout_seconds"])
        result["process"] = process
        if process["timed_out"] or process["returncode"] != 0:
            raise SynthesisError("综合超时或进程非零退出；不消费任何残留面积")
        stage = "mapped_result"
        stat = json.loads((directory / "stat.json").read_text())
        mapped = json.loads((directory / "mapped.json").read_text())
        validated = validate_mapped_result(stat, mapped, areas)
        normalized = validated.pop("normalized_netlist")
        _write_new(directory / "normalized_netlist.json", normalized)
        stage = "identity"
        _check_contract(contract)
        if _sha((directory.parent / "cells.lib").read_bytes()) != contract["liberty"]["sha256"]:
            raise SynthesisError("执行期间 Liberty 快照发生漂移")
        for filename, expected in (("design.v", binding["rtl_sha256"]),
                                   ("run.ys", contract["script_sha256"])):
            if _sha((directory / filename).read_bytes()) != expected:
                raise SynthesisError(f"执行文件 {filename} 发生漂移")
        result.update({"status": "ok", **validated,
                       "artifacts": {name: _sha((directory / name).read_bytes()) for name in (
                           "design.v", "run.ys", "stdout.log", "stderr.log", "stat.json",
                           "mapped.json", "normalized_netlist.json",
                       )}})
    except Exception as exc:
        result.update({"stage": stage, "error_type": type(exc).__name__, "error": str(exc)})
    _write_new(directory / "result.json", result)
    return result


def _run_root(run_id: str, output_root: Path) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError("非法 run_id")
    root = Path(output_root) / run_id
    if root.resolve().is_relative_to((BENCH / "experiments_system").resolve()):
        raise ValueError("禁止写入历史 witness 产物目录")
    return root


def prepare_smoke(run_id: str, output_root: Path = OUTPUT_ROOT) -> Path:
    """一次冻结全部任务；允许调度尚未开始的任务，不恢复或重试失败任务。"""
    root = _run_root(run_id, output_root)
    contract = build_contract()
    configs = development_candidates()
    frozen = []
    for candidate in configs:
        validate_candidate(candidate)
        hq = resolve_fir_coefficients(candidate["filter_decimator"])
        mask = candidates.check_fir_mask(hq, ref_chain.prototype_taps())
        if not mask["legal"]:
            raise SynthesisError("预注册开发候选 FIR mask 失败，不缩小候选集")
        rtl = lower_ddc_rtl(candidate)
        frozen.append({"candidate": json.loads(canonical_json(candidate)),
                       "candidate_hash": candidate_hash(candidate), "rtl_sha256": _sha(rtl.encode()),
                       "hq": hq.tolist(), "hq_sha256": _sha(hq.astype("<i8").tobytes()), "fir_mask": mask})
    manifest = {"schema_version": "search-ir-stage-c-v1", "run_id": run_id,
                "contract": contract, "contract_sha256": _digest(contract),
                "candidates": frozen, "attempt_candidate_indices": [0, 1, 2, 0],
                "repeat_interpretation": "single-host reproducibility check only; not epsilon_A"}
    root.mkdir(parents=True, exist_ok=False)
    with (root / "cells.lib").open("xb") as handle:
        handle.write(Path(contract["liberty"]["path"]).read_bytes())
    _write_new(root / "manifest.json", manifest)
    for index, item in enumerate(frozen):
        (root / f"candidate-{index:02d}.v").write_text(
            lower_ddc_rtl(item["candidate"]), encoding="utf-8"
        )
    _write_new(root / "manifest_identity.json", {"sha256": _sha((root / "manifest.json").read_bytes())})
    return root


def run_next_job(run_id: str, output_root: Path = OUTPUT_ROOT) -> Path:
    """单次只执行下一个未开始任务，便于保持每次工具调用的时限；禁止失败重试。"""
    root = _run_root(run_id, output_root)
    if (root / "results.json").exists():
        raise SynthesisError("运行已结束；不能复用该 run_id")
    manifest_sha = _sha((root / "manifest.json").read_bytes())
    if manifest_sha != json.loads((root / "manifest_identity.json").read_text())["sha256"]:
        raise SynthesisError("运行 manifest 漂移")
    manifest = json.loads((root / "manifest.json").read_text())
    contract = manifest["contract"]
    if _digest(contract) != manifest["contract_sha256"]:
        raise SynthesisError("contract 摘要不一致")
    rows = []
    for attempt, index in enumerate(manifest["attempt_candidate_indices"], 1):
        item = manifest["candidates"][index]
        binding = {"run_id": run_id, "attempt_id": attempt,
                   "candidate_hash": item["candidate_hash"], "rtl_sha256": item["rtl_sha256"],
                   "contract_sha256": manifest["contract_sha256"], "manifest_sha256": manifest_sha}
        job_dir = root / f"job-{attempt:02d}"
        if job_dir.exists():
            if not (job_dir / "result.json").is_file():
                raise SynthesisError("已有任务未结束，不能并发调度或恢复中断任务")
            expected_result = json.loads((root / f"job-{attempt:02d}.identity.json").read_text())["sha256"]
            if _sha((job_dir / "result.json").read_bytes()) != expected_result:
                raise SynthesisError("前序任务结果发生漂移")
            row = json.loads((job_dir / "result.json").read_text())
            for name, digest in row.get("artifacts", {}).items():
                if _sha((job_dir / name).read_bytes()) != digest:
                    raise SynthesisError("前序综合产物发生漂移")
            if row["binding"] != binding or row["status"] != "ok":
                raise SynthesisError("前序任务失败或身份不一致，拒绝后续调度")
            rows.append(row)
            continue
        rtl = (root / f"candidate-{index:02d}.v").read_text()
        areas = liberty_areas((root / "cells.lib").read_text())
        row = run_job(job_dir, binding, contract, rtl, areas)
        _write_new(root / f"job-{attempt:02d}.identity.json",
                   {"sha256": _sha((job_dir / "result.json").read_bytes())})
        rows.append(row)
        print(f"[{row['status']}] job-{attempt:02d} {item['candidate_hash'][:12]} area={row['area_um2']}", flush=True)
        if row["status"] != "ok" or attempt == 4:
            return _finish_summary(root, manifest_sha, rows)
        return job_dir / "result.json"
    raise SynthesisError("全部任务已有结果，不能重复执行")


def _finish_summary(root: Path, manifest_sha: str, rows: list[dict]) -> Path:
    repeat = None
    if len(rows) == 4 and all(row["status"] == "ok" for row in rows):
        fields = ("area_um2", "cells_by_type", "stat_top_sha256", "netlist_semantic_sha256")
        repeat = {key: rows[0][key] == rows[3][key] for key in fields}
        repeat["all_equal"] = all(repeat.values())
    summary = {"schema_version": "search-ir-stage-c-results-v1", "manifest_sha256": manifest_sha,
               "status": "ok" if repeat and repeat["all_equal"] else "incomplete_or_mismatch",
               "rows": rows, "repeat": repeat, "formal_gate_passed": False,
               "note": "fixed development full-DDC mapped cell area; no quality-area benefit claim"}
    _write_new(root / "results.json", summary)
    return root / "results.json"


def run_smoke(run_id: str, output_root: Path = OUTPUT_ROOT) -> Path:
    root = prepare_smoke(run_id, output_root)
    while not (root / "results.json").exists():
        run_next_job(run_id, output_root)
    return root / "results.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--next-job", action="store_true")
    args = parser.parse_args(argv)
    if args.prepare_only:
        print(prepare_smoke(args.run_id))
        return 0
    path = run_next_job(args.run_id) if args.next_job else run_smoke(args.run_id)
    print(path)
    return 0 if json.loads(path.read_text())["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
