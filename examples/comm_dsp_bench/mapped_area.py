"""Auditable Nangate45 mapped-cell area for one synthesizable RTL design.

The reported value is the sum of mapped cell counts times Liberty ``area``.
This module does not run static timing analysis and makes no timing or power
claim.
"""

from __future__ import annotations

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
from typing import Iterable


BENCH = Path(__file__).resolve().parent
DEFAULT_LIBERTY = BENCH / "pdk/NangateOpenCellLibrary_typical.lib"
NANGATE45_LIBERTY_SHA256 = "8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1"


class MappedAreaError(RuntimeError):
    """An incomplete, inconsistent, or unbound synthesis result."""


def canonical_json(value) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def file_identity(path: Path) -> dict:
    resolved = Path(path).resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256_bytes(resolved.read_bytes())}


def write_new_json(path: Path, value) -> None:
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(canonical_json(value) + "\n")


def task_ports(task: dict) -> dict[str, tuple[str, int]]:
    """Return the exact top-level port contract derived from a task card."""
    ports: dict[str, tuple[str, int]] = {
        "clk": ("input", 1),
        "rst_n": ("input", 1),
        "in_valid": ("input", 1),
        "in_ready": ("output", 1),
        "out_valid": ("output", 1),
        "out_ready": ("input", 1),
    }
    try:
        groups = (
            ("input", task["io_protocol"]["inputs"]),
            ("output", task["io_protocol"]["outputs"]),
        )
    except (KeyError, TypeError) as exc:
        raise MappedAreaError(f"invalid task I/O protocol: {exc}") from exc
    for direction, entries in groups:
        if not isinstance(entries, list):
            raise MappedAreaError("task input/output declarations must be lists")
        for entry in entries:
            try:
                name, width = entry["name"], entry["width"]
            except (KeyError, TypeError) as exc:
                raise MappedAreaError(f"invalid task port: {exc}") from exc
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name)
                or type(width) is not int
                or not 1 <= width <= 4096
                or name in ports
            ):
                raise MappedAreaError(f"invalid or duplicate task port {name!r}")
            ports[name] = (direction, width)
    return ports


def liberty_areas(text: str) -> dict[str, float]:
    """Parse cell areas from the frozen Nangate Liberty snapshot."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    starts = list(
        re.finditer(r'\bcell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{', text)
    )
    areas: dict[str, float] = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        found = re.search(r"\barea\s*:\s*([^;]+);", text[match.end() : end])
        if found is None:
            raise MappedAreaError(f"library cell {match[1]} has no area")
        area = float(found[1])
        if not math.isfinite(area) or area < 0 or match[1] in areas:
            raise MappedAreaError("invalid or duplicate library cell area")
        areas[match[1]] = area
    if not areas:
        raise MappedAreaError("no cell areas found in Liberty")
    return areas


def _tool(name: str, version_args: list[str]) -> dict:
    executable = shutil.which(name)
    if executable is None:
        raise MappedAreaError(f"tool not found: {name}")
    identity = file_identity(Path(executable))
    try:
        process = subprocess.run(
            [identity["path"], *version_args],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MappedAreaError(f"cannot identify {name}: {exc}") from exc
    identity["version"] = (process.stdout + process.stderr).strip()
    if not identity["version"]:
        raise MappedAreaError(f"{name} returned no version")
    return identity


def synthesis_script(abc_path: str, top: str = "top") -> str:
    if (
        not Path(abc_path).is_absolute()
        or any(char in abc_path for char in ('"', "\n", "\r", "\\"))
        or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", top)
    ):
        raise MappedAreaError("unsafe ABC path or top module")
    return "\n".join(
        [
            "read_liberty -lib cells.lib",
            "read_verilog -sv design.v",
            f"hierarchy -check -top {top}",
            f"synth -top {top} -flatten -noabc",
            "dffunmap",
            "dfflibmap -liberty cells.lib",
            f'abc -exe "{abc_path}" -liberty cells.lib',
            "clean",
            "delete t:$scopeinfo",
            "check -mapped -assert",
            f"tee -o stat.json stat -json -liberty cells.lib -top {top}",
            "write_json mapped.json",
            "",
        ]
    )


def build_contract(
    task: dict,
    *,
    liberty: Path = DEFAULT_LIBERTY,
    timeout_seconds: float = 600,
    source_files: Iterable[Path] = (),
) -> dict:
    """Freeze task ports, tools, scripts, library, and runner source identity."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise MappedAreaError("timeout must be a finite positive number")
    liberty = Path(liberty)
    if not liberty.is_file():
        raise MappedAreaError(f"Nangate45 Liberty not found: {liberty}")
    liberty_identity = file_identity(liberty)
    if liberty_identity["sha256"] != NANGATE45_LIBERTY_SHA256:
        raise MappedAreaError(
            "the area metric accepts only the frozen Nangate45 typical Liberty snapshot"
        )
    liberty_text = liberty.read_text(encoding="utf-8")
    required_metadata = (
        "library (NangateOpenCellLibrary)",
        "default_operating_conditions : typical",
        "nom_process",
        "nom_temperature",
        "nom_voltage",
    )
    if any(item not in liberty_text for item in required_metadata):
        raise MappedAreaError("frozen Liberty metadata is incomplete")
    yosys = _tool("yosys", ["-V"])
    abc = _tool("yosys-abc", ["-c", "version"])
    top = task.get("dut_module", "top")
    script = synthesis_script(abc["path"], top)
    sources = [Path(__file__), *map(Path, source_files)]
    source_ids = [file_identity(path) for path in sorted(set(sources))]
    ports = task_ports(task)
    return {
        "schema_version": "mapped-cell-area-v1",
        "metric": "Nangate45 mapped cell area",
        "top": top,
        "flatten": True,
        "expected_ports": {name: list(value) for name, value in ports.items()},
        "task_sha256": digest(task),
        "yosys": yosys,
        "abc": abc,
        "liberty": liberty_identity,
        "library_name": "NangateOpenCellLibrary",
        "operating_conditions": "typical",
        "nominal_process": 1.0,
        "nominal_voltage_v": 1.1,
        "nominal_temperature_c": 25.0,
        "area_unit": "um^2",
        "script": script,
        "script_sha256": sha256_bytes(script.encode("utf-8")),
        "runner_sources": source_ids,
        "timeout_seconds": float(timeout_seconds),
        "sdc": None,
        "timing": "unverified",
        "power": "unverified",
        "area_crosscheck": {
            "primary": "sum(mapped JSON cell count * Liberty area)",
            "stat_relative_tolerance": 5e-6,
            "stat_absolute_tolerance_um2": 1e-6,
        },
    }


def contract_cache_identity(contract: dict) -> dict:
    return {
        "schema_version": contract["schema_version"],
        "top": contract["top"],
        "expected_ports": contract["expected_ports"],
        "task_sha256": contract["task_sha256"],
        "yosys_sha256": contract["yosys"]["sha256"],
        "abc_sha256": contract["abc"]["sha256"],
        "liberty_sha256": contract["liberty"]["sha256"],
        "script_sha256": contract["script_sha256"],
        "runner_sources": contract["runner_sources"],
    }


def area_cache_key(source: str, task: dict, contract: dict) -> str:
    return digest(
        {
            "rtl_sha256": sha256_bytes(source.encode("utf-8")),
            "task_sha256": digest(task),
            "contract": contract_cache_identity(contract),
        }
    )


def validate_contract(contract: dict, task: dict) -> None:
    if contract["task_sha256"] != digest(task):
        raise MappedAreaError("task identity changed")
    if contract["expected_ports"] != {
        name: list(value) for name, value in task_ports(task).items()
    }:
        raise MappedAreaError("task port contract changed")
    for key in ("yosys", "abc", "liberty"):
        current = file_identity(Path(contract[key]["path"]))
        if current["sha256"] != contract[key]["sha256"]:
            raise MappedAreaError(f"{key} identity changed")
    for source in contract["runner_sources"]:
        if file_identity(Path(source["path"]))["sha256"] != source["sha256"]:
            raise MappedAreaError("runner source identity changed")
    script = synthesis_script(contract["abc"]["path"], contract["top"])
    if script != contract["script"] or sha256_bytes(script.encode()) != contract["script_sha256"]:
        raise MappedAreaError("synthesis script identity changed")


def validate_mapped_result(
    stat: dict,
    netlist: dict,
    areas: dict[str, float],
    expected_ports: dict[str, tuple[str, int]],
    *,
    top_name: str = "top",
) -> dict:
    """Cross-check a fully flattened mapped JSON netlist against Yosys stat."""
    try:
        top = netlist["modules"][top_name]
        module_stat = stat["modules"].get(f"\\{top_name}", stat["modules"].get(top_name))
        if module_stat is None:
            raise MappedAreaError("top module missing from stat")
        ports = {
            name: (port["direction"], len(port["bits"]))
            for name, port in top["ports"].items()
        }
        if ports != expected_ports:
            raise MappedAreaError("mapped top ports differ from task contract")
        if top.get("memories"):
            raise MappedAreaError("mapped netlist still contains memories")
        if str(top.get("attributes", {}).get("blackbox", "0")) not in ("0", ""):
            raise MappedAreaError("top is a blackbox")
        cells = top["cells"]
        types = Counter(cell["type"] for cell in cells.values())
        if not types:
            raise MappedAreaError("mapped netlist is empty")
        if any(name.startswith("$") or name not in areas for name in types):
            raise MappedAreaError("generic, unknown, or blackbox cell remains")
        counts = module_stat["num_cells_by_type"]
        if any(type(value) is not int or value <= 0 for value in counts.values()):
            raise MappedAreaError("invalid stat cell count")
        if (
            type(module_stat["num_cells"]) is not int
            or dict(types) != counts
            or module_stat["num_cells"] != sum(types.values())
        ):
            raise MappedAreaError("stat and mapped JSON cell counts disagree")
        stat_area = module_stat["area"]
        if type(stat_area) not in (int, float) or not math.isfinite(stat_area) or stat_area <= 0:
            raise MappedAreaError("stat area is not finite and positive")
        summed = math.fsum(areas[name] * count for name, count in types.items())
        if not math.isclose(stat_area, summed, rel_tol=5e-6, abs_tol=1e-6):
            raise MappedAreaError("stat area differs from Liberty cell-area sum")
        normalized = {
            "ports": {
                name: {key: value for key, value in port.items() if key != "attributes"}
                for name, port in top["ports"].items()
            },
            "cells": sorted(
                [
                    {
                        "type": cell["type"],
                        "parameters": cell.get("parameters", {}),
                        "port_directions": cell["port_directions"],
                        "connections": cell["connections"],
                    }
                    for cell in cells.values()
                ],
                key=canonical_json,
            ),
        }
        return {
            "area_um2": summed,
            "stat_reported_area_um2": float(stat_area),
            "library_area_sum_um2": summed,
            "num_cells": sum(types.values()),
            "cells_by_type": dict(sorted(types.items())),
            "stat_top_sha256": digest(module_stat),
            "netlist_semantic_sha256": digest(normalized),
            "normalized_netlist": normalized,
            "timing": "unverified",
            "power": "unverified",
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise MappedAreaError(f"invalid mapped result: {exc}") from exc


def run_process(command: list[str], cwd: Path, timeout: float) -> dict:
    """Run a tool in a new process group and kill the group on timeout."""
    started = time.monotonic()
    with (cwd / "stdout.log").open("xb") as stdout, (cwd / "stderr.log").open(
        "xb"
    ) as stderr:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
    return {
        "returncode": process.returncode,
        "timed_out": timed_out,
        "wall_seconds": time.monotonic() - started,
    }


def run_job(
    directory: Path,
    source: str,
    task: dict,
    contract: dict,
    *,
    binding: dict | None = None,
) -> dict:
    """Run one new synthesis job, retaining every input, log, and output."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    rtl_sha = sha256_bytes(source.encode("utf-8"))
    fixed_binding = {
        **(binding or {}),
        "rtl_sha256": rtl_sha,
        "task_sha256": digest(task),
        "contract_sha256": digest(contract),
        "area_cache_key": area_cache_key(source, task, contract),
    }
    result = {
        "status": "failed",
        "area_um2": None,
        "binding": fixed_binding,
        "timing": "unverified",
        "power": "unverified",
    }
    stage = "identity"
    try:
        write_new_json(directory / "started.json", fixed_binding)
        validate_contract(contract, task)
        (directory / "design.v").write_text(source, encoding="utf-8")
        (directory / "task.json").write_text(canonical_json(task) + "\n", encoding="utf-8")
        (directory / "run.ys").write_text(contract["script"], encoding="utf-8")
        (directory / "cells.lib").write_bytes(Path(contract["liberty"]["path"]).read_bytes())
        write_new_json(directory / "contract.json", contract)
        snapshots = {
            "design.v": rtl_sha,
            "task.json": sha256_bytes((directory / "task.json").read_bytes()),
            "run.ys": contract["script_sha256"],
            "cells.lib": contract["liberty"]["sha256"],
            "contract.json": sha256_bytes((directory / "contract.json").read_bytes()),
        }
        stage = "process"
        process = run_process(
            [contract["yosys"]["path"], "-T", "-s", "run.ys"],
            directory,
            contract["timeout_seconds"],
        )
        result["process"] = process
        if process["timed_out"]:
            result["status"] = "timeout"
            raise MappedAreaError("synthesis timed out")
        if process["returncode"] != 0:
            raise MappedAreaError("synthesis process returned nonzero")
        stage = "mapped_result"
        stat = json.loads((directory / "stat.json").read_text(encoding="utf-8"))
        netlist = json.loads((directory / "mapped.json").read_text(encoding="utf-8"))
        areas = liberty_areas((directory / "cells.lib").read_text(encoding="utf-8"))
        expected = {name: tuple(value) for name, value in contract["expected_ports"].items()}
        validated = validate_mapped_result(
            stat, netlist, areas, expected, top_name=contract["top"]
        )
        normalized = validated.pop("normalized_netlist")
        write_new_json(directory / "normalized_netlist.json", normalized)
        stage = "identity"
        validate_contract(contract, task)
        for filename, expected_sha in snapshots.items():
            if sha256_bytes((directory / filename).read_bytes()) != expected_sha:
                raise MappedAreaError(f"job input changed during synthesis: {filename}")
        result.update(status="ok", **validated)
        artifact_names = (
            "design.v",
            "task.json",
            "run.ys",
            "cells.lib",
            "contract.json",
            "stdout.log",
            "stderr.log",
            "stat.json",
            "mapped.json",
            "normalized_netlist.json",
        )
        result["artifacts"] = {
            name: sha256_bytes((directory / name).read_bytes()) for name in artifact_names
        }
    except Exception as exc:
        result.update(stage=stage, error_type=type(exc).__name__, error=str(exc))
    write_new_json(directory / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    import yaml

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("task", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--liberty", type=Path, default=DEFAULT_LIBERTY)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    task = yaml.safe_load(args.task.read_text(encoding="utf-8"))
    contract = build_contract(task, liberty=args.liberty, timeout_seconds=args.timeout)
    result = run_job(args.output, args.source.read_text(encoding="utf-8"), task, contract)
    print(canonical_json(result))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
