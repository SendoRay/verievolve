"""同三份固定 DDC 的 36 主场景接入验证；不运行搜索或 held-out。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from chains.ddc import candidates, fixed_chain, ref_chain, scenarios, spec

from .canonicalize import candidate_hash, canonical_json
from .dev_fixtures import development_candidates
from .dev_run import DevRun, THRESHOLD_SOURCE
from .evaluate import EvaluationError, aggregate_rows, prepare_case
from .lower_bittrue import resolve_fir_coefficients
from .lower_rtl import lower_ddc_rtl
from .synthesize import liberty_areas, synthesis_script, validate_mapped_result


BENCH = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = BENCH / "experiments_search/stage_d"
DEFAULT_AREA_RUN = BENCH / "experiments_search/stage_c/dev-full-ddc-v2-20261001"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _write_new(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def _main_view(manifest: dict) -> dict:
    selected = [row for row in manifest["scenarios"] if row["split"] == "main"]
    frequencies = {f"{row['f_off_mhz']:.3f}" for row in selected}
    return {
        **{key: value for key, value in manifest.items() if key not in ("scenarios", "fcw")},
        "scenarios": selected,
        "fcw": {key: value for key, value in manifest["fcw"].items() if key in frequencies},
    }


def frozen_main_definition() -> dict:
    """只比较已知主场景规格，不读取 held-out/stress 的数值结果。"""
    original = json.loads(THRESHOLD_SOURCE.read_text())["scenario_manifest"]
    expected = _main_view(original)
    actual = _main_view(spec.export_witness_manifest())
    if actual != expected or len(actual["scenarios"]) != 36:
        raise EvaluationError("主场景规格或完整长度与冻结 preflight 不一致")
    keys = [row["key"] for row in actual["scenarios"]]
    if len(set(keys)) != 36 or len(actual["fcw"]) != 9:
        raise EvaluationError("主场景 key/FCW 覆盖错误")
    return actual


def verified_areas(root: Path, configs: list[dict]) -> dict:
    """关联已有全链综合；核对已记录的依赖，不因后来新增无关文件修改历史清单。"""
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    result = json.loads((root / "results.json").read_text())
    manifest_sha = _sha(root / "manifest.json")
    if (result["status"] != "ok" or result["manifest_sha256"] != manifest_sha
            or json.loads((root / "manifest_identity.json").read_text())["sha256"] != manifest_sha):
        raise EvaluationError("面积结果未完成或 manifest 身份不一致")
    contract = manifest["contract"]
    if (_digest(contract) != manifest["contract_sha256"] or contract["top"] != "top"
            or contract["flatten"] is not True or contract["area_unit"] != "um^2"
            or contract["scope"] != "fixed development candidates; full-DDC mapped cell area"):
        raise EvaluationError("不匹配的全链综合口径")
    if (contract["script"] != synthesis_script(contract["abc"]["path"])
            or hashlib.sha256(contract["script"].encode()).hexdigest() != contract["script_sha256"]):
        raise EvaluationError("不匹配的综合脚本")
    for record in [*contract["sources"], contract["yosys"], contract["abc"], contract["liberty"]]:
        if _sha(Path(record["path"])) != record["sha256"]:
            raise EvaluationError("已记录的综合源码/工具/库发生漂移")
    if _sha(root / "cells.lib") != contract["liberty"]["sha256"]:
        raise EvaluationError("面积库快照不一致")
    frozen = manifest["candidates"]
    if len(configs) != 3 or len(frozen) != 3 or manifest["attempt_candidate_indices"] != [0, 1, 2, 0]:
        raise EvaluationError("面积不是固定的三候选加一次重复")
    for cfg, item in zip(configs, frozen):
        rtl_sha = hashlib.sha256(lower_ddc_rtl(cfg).encode()).hexdigest()
        if (candidate_hash(cfg) != item["candidate_hash"] or rtl_sha != item["rtl_sha256"]
                or canonical_json(cfg) != canonical_json(item["candidate"])):
            raise EvaluationError("候选或实际 RTL 与已有面积身份不匹配")
        hq = resolve_fir_coefficients(cfg["filter_decimator"])
        mask = candidates.check_fir_mask(hq, ref_chain.prototype_taps())
        if (hq.tolist() != item["hq"]
                or hashlib.sha256(hq.astype("<i8").tobytes()).hexdigest() != item["hq_sha256"]
                or mask != item["fir_mask"] or mask["legal"] is not True):
            raise EvaluationError("实际 FIR 系数或 mask 与面积 manifest 不一致")
    rows = result["rows"]
    if len(rows) != 4 or not result["repeat"]["all_equal"]:
        raise EvaluationError("面积四任务覆盖或重复检查不完整")
    lib_areas = liberty_areas((root / "cells.lib").read_text())
    areas = {}
    for attempt, (index, row) in enumerate(zip([0, 1, 2, 0], rows), 1):
        job = root / f"job-{attempt:02d}"
        item = frozen[index]
        expected_binding = {
            "attempt_id": attempt, "candidate_hash": item["candidate_hash"],
            "contract_sha256": manifest["contract_sha256"], "manifest_sha256": manifest_sha,
            "rtl_sha256": item["rtl_sha256"], "run_id": manifest["run_id"],
        }
        if row["binding"] != expected_binding or row["status"] != "ok":
            raise EvaluationError("面积任务身份不一致或失败")
        if json.loads((job / "result.json").read_text()) != row:
            raise EvaluationError("汇总面积与逐任务结果不一致")
        if _sha(job / "result.json") != json.loads((root / f"job-{attempt:02d}.identity.json").read_text())["sha256"]:
            raise EvaluationError("逐任务结果摘要不一致")
        if row["process"]["returncode"] != 0 or row["process"]["timed_out"]:
            raise EvaluationError("失败进程不能贡献面积")
        if set(row["artifacts"]) != {
            "design.v", "run.ys", "stdout.log", "stderr.log", "stat.json",
            "mapped.json", "normalized_netlist.json",
        }:
            raise EvaluationError("综合产物清单不完整")
        if (_sha(job / "design.v") != item["rtl_sha256"]
                or _sha(job / "run.ys") != contract["script_sha256"]):
            raise EvaluationError("实际执行的 RTL/脚本未绑定到冻结输入")
        for name, digest in row["artifacts"].items():
            if Path(name).name != name or _sha(job / name) != digest:
                raise EvaluationError("综合产物摘要不一致")
        checked = validate_mapped_result(json.loads((job / "stat.json").read_text()),
                                        json.loads((job / "mapped.json").read_text()), lib_areas)
        for key in ("area_um2", "cells_by_type", "stat_top_sha256", "netlist_semantic_sha256"):
            if checked[key] != row[key]:
                raise EvaluationError("重新核对的面积/网表与记录不一致")
            if attempt == 4 and row[key] != rows[0][key]:
                raise EvaluationError("重复综合不一致")
        areas[item["candidate_hash"]] = row["area_um2"]
    return {"areas": areas, "source": str(root), "manifest_sha256": manifest_sha,
            "results_sha256": _sha(root / "results.json"), "scope": contract["scope"]}


def main_cases(definition: dict) -> list:
    cases = []
    scene_list = spec.build_witness_scenarios("main")
    if len(scene_list) != 36:
        raise EvaluationError("必须完整覆盖 36 个主场景")
    for scene, record in zip(scene_list, definition["scenarios"]):
        if any(record[key] != value for key, value in asdict(scene).items()):
            raise EvaluationError("生成场景与冻结记录不一致")
        sd = scenarios.generate_scenario(scene)
        i12, q12 = fixed_chain.adc_quantize(sd.x_adc)
        case = prepare_case(record["key"], i12, q12, spec.fcw_of(scene.f_off_mhz),
                            sd.desired, scenarios.measure_start_out(sd.n_pre))
        cases.append(case)
    return cases


def summarize_candidate(evaluation: dict, expected_ids: list[str], area: float) -> dict:
    if evaluation["status"] != "ok" or evaluation["fir_mask"]["legal"] is not True:
        raise EvaluationError("候选未完成质量评价或 FIR mask 失败")
    q = aggregate_rows(evaluation["rows"], expected_ids)
    if q != evaluation["Q_dev"]:
        raise EvaluationError("Q_dev 与完整主场景聚合不一致")
    worst = max(evaluation["rows"], key=lambda row: row["q_aligned"])
    n_mix = sum(row["n_sat_mix"] for row in evaluation["rows"])
    n_fir = sum(row["n_sat_fir"] for row in evaluation["rows"])
    return {
        "candidate_hash": evaluation["candidate_hash"], "Q_main_observed": q,
        "n_scenarios": len(expected_ids), "argmax_case": worst["case_id"],
        "argmax_fcw": worst["case_identity"]["fcw"], "area_um2": area,
        "n_sat_mix": n_mix, "n_sat_fir_retained": n_fir,
        "observed_saturation": n_mix != 0 or n_fir != 0,
        "saturation_scope": evaluation["saturation_scope"],
        "formal_deployment_feasibility": "pending",
    }


def run_validation(run_id: str, area_root: Path = DEFAULT_AREA_RUN,
                   output_root: Path = OUTPUT_ROOT) -> Path:
    """前置条件：调用者已确认 C 独立复核通过；此入口不代替审查签字。"""
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError("非法 run_id")
    root = Path(output_root) / run_id
    if root.resolve().is_relative_to((BENCH / "experiments_system").resolve()):
        raise ValueError("不得写入历史 witness 目录")
    configs = development_candidates()
    definition = frozen_main_definition()
    area = verified_areas(area_root, configs)
    manifest = {
        "schema_version": "search-ir-fixed-main-validation-v1", "run_id": run_id,
        "candidates": [json.loads(canonical_json(c)) for c in configs],
        "main_definition": definition, "area_source": area,
        "preflight_sha256": _sha(THRESHOLD_SOURCE), "adapter_sha256": _sha(Path(__file__)),
        "max_attempts": 3, "expected_evaluations": 108,
        "formal_search_allowed": False, "heldout_accessed": False,
        "S": "N/A", "L": "N/A",
    }
    root.mkdir(parents=True, exist_ok=False)
    _write_new(root / "validation_manifest.json", manifest)
    manifest_sha = _sha(root / "validation_manifest.json")
    rows = []
    status = "failed"
    error = None
    try:
        cases = main_cases(definition)
        expected_ids = [record["key"] for record in definition["scenarios"]]
        if [case.case_id for case in cases] != expected_ids:
            raise EvaluationError("生成主场景的覆盖或顺序不一致")
        run = DevRun(root, "quality", cases, max_attempts=3)
        for config in configs:
            envelope = run.submit(json.dumps(config))
            if envelope["status"] != "ok":
                raise EvaluationError(f"主场景评价失败，见 quality/result-{envelope['attempt_id']:04d}.json")
            evaluation = envelope["evaluation"]
            row = summarize_candidate(evaluation, expected_ids, area["areas"][candidate_hash(config)])
            rows.append(row)
            print(f"[main] {row['candidate_hash'][:12]} Q={row['Q_main_observed']:.9g} saturation={row['observed_saturation']}", flush=True)
            if row["observed_saturation"]:
                raise EvaluationError("主场景观察域发生饱和，暂停后续推进")
        if (_sha(Path(__file__)) != manifest["adapter_sha256"]
                or _sha(THRESHOLD_SOURCE) != manifest["preflight_sha256"]
                or _sha(root / "validation_manifest.json") != manifest_sha
                or frozen_main_definition() != definition
                or verified_areas(area_root, configs) != area):
            raise EvaluationError("验证期间上下文身份漂移")
        status = "fixed_candidates_validated"
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    result = {"schema_version": manifest["schema_version"], "status": status,
              "manifest_sha256": manifest_sha, "rows": rows, "error": error,
              "quality_manifest_sha256": _sha(root / "quality/manifest.json") if (root / "quality/manifest.json").is_file() else None,
              "formal_search_allowed": False, "S": "N/A", "L": "N/A"}
    _write_new(root / "results.json", result)
    return root / "results.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--area-run", type=Path, default=DEFAULT_AREA_RUN)
    args = parser.parse_args(argv)
    path = run_validation(args.run_id, args.area_run)
    print(path)
    return 0 if json.loads(path.read_text())["status"] == "fixed_candidates_validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
