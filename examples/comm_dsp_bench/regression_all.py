#!/usr/bin/env python
"""106 实例全量回归：逐实例闭环（复制 task.yaml → 评估基线 → 汇总报告）

基线 = .family_baselines/<family>/<instance>/initial_program.v（朴素起点，
验证「任务卡 + golden + 激励 + 基线」四件套闭环，不是进化结果）。

用法:
  python regression_all.py --family llr          # 只跑某族
  python regression_all.py --filter qpsk,16qam   # 实例名包含任一子串
  python regression_all.py --jobs 4              # 并行度（默认 4）
  python regression_all.py --list                # 只列实例不跑

输出: regression_report.json / regression_report.md（覆盖写）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

BENCH = Path(__file__).resolve().parent
TASKS_GEN = BENCH / "tasks_gen"
BASELINES = BENCH / ".family_baselines"
TASKS = BENCH / "tasks"
PY = sys.executable
EVAL_TIMEOUT = 900  # 单实例上限（秒）：仿真 + 双口径综合

# tasks/ 下的精任务与既有抽样（不删不动）
PERMANENT = {"cmul", "cordic_sincos", "fir", "nco",
             "atan2_w16", "cmul_w16_free", "crc16_step1", "fir_t16_c25_sym",
             "llr_64qam_snr20", "mfilt_L63", "nco_p24_t256"}


def iter_instances(family=None, substrings=None):
    for fam_dir in sorted(TASKS_GEN.iterdir()):
        if family and fam_dir.name != family:
            continue
        for inst_dir in sorted(d for d in fam_dir.iterdir() if (d / "task.yaml").exists()):
            if substrings and not any(s in inst_dir.name for s in substrings):
                continue
            yield fam_dir.name, inst_dir.name, inst_dir


def eval_one(fam: str, inst: str, inst_dir: Path) -> dict:
    """单实例闭环：临时复制 task.yaml → 子进程评估 → 清理"""
    t0 = time.time()
    tmp = TASKS / inst
    created = False
    if inst not in PERMANENT:
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        created = True
    # 同步最新 task.yaml（PERMANENT 实例仅更新 yaml，不动其他文件）
    shutil.copy(inst_dir / "task.yaml", tmp / "task.yaml")
    prog = BASELINES / fam / inst / "initial_program.v"
    if not prog.exists():
        return {"instance": inst, "family": fam, "ok": False,
                "error_type": "missing_baseline", "error": str(prog), "secs": 0.0}
    env = dict(os.environ, COMMDSP_TASK=inst)
    rec = {"instance": inst, "family": fam}
    try:
        p = subprocess.run(
            [PY, str(BENCH / "evaluator.py"), str(prog)],
            capture_output=True, text=True, timeout=EVAL_TIMEOUT, env=env,
        )
        out = p.stdout
        # 解析 evaluator 的 metrics:/artifacts: JSON 块
        try:
            m = out.split("metrics:", 1)[1].split("artifacts:", 1)[0]
            a = out.split("artifacts:", 1)[1]
            rec["metrics"] = json.loads(m)
            rec["artifacts"] = json.loads(a)
            rec["ok"] = (rec["metrics"].get("combined_score", 0.0) > 0.0
                          and float(rec.get("artifacts", {}).get("smoke_sqnr_db", "0") or 0) >= 20.0
                          ) or rec["metrics"].get("precision", 0.0) >= 20.0
            if not rec["ok"]:
                rec["error_type"] = rec["artifacts"].get("error_type", "zero_score")
                rec["error"] = rec["artifacts"].get("error_message", "")[:300]
        except (IndexError, json.JSONDecodeError):
            rec["ok"] = False
            rec["error_type"] = "evaluator_parse_fail"
            rec["error"] = (out + p.stderr)[-500:]
    except subprocess.TimeoutExpired:
        rec["ok"] = False
        rec["error_type"] = "regression_timeout"
        rec["error"] = f"evaluator exceeded {EVAL_TIMEOUT}s"
    finally:
        if created and tmp.exists():
            shutil.rmtree(tmp)
    rec["secs"] = round(time.time() - t0, 1)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default=None)
    ap.add_argument("--filter", default=None, help="逗号分隔子串（实例名包含即选中）")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    substrings = args.filter.split(",") if args.filter else None

    insts = list(iter_instances(args.family, substrings))
    print(f"instances: {len(insts)}")
    if args.list or not insts:
        for fam, name, _ in insts:
            print(f"  {fam}/{name}")
        return

    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(eval_one, fam, name, d): (fam, name)
                for fam, name, d in insts}
        for fut in as_completed(futs):
            rec = fut.result()
            results.append(rec)
            tag = "OK " if rec["ok"] else "FAIL"
            met = rec.get("metrics", {})
            prec = met.get("precision", "?")
            area = met.get("area", "?")
            um2 = met.get("area_um2", "?")
            print(f"[{tag}] {rec['instance']:<24} prec={prec} area={area} "
                  f"um2={um2} ({rec['secs']}s)"
                  + ("" if rec["ok"] else f"  err={rec.get('error_type')}: {rec.get('error', '')[:120]}"))

    results.sort(key=lambda r: (r["family"], r["instance"]))
    (BENCH / "regression_report.json").write_text(json.dumps(results, indent=1))

    # 汇总
    n_ok = sum(1 for r in results if r["ok"])
    fams = {}
    for r in results:
        f = fams.setdefault(r["family"], {"n": 0, "ok": 0, "prec": [], "area": [], "um2": []})
        f["n"] += 1
        if r["ok"]:
            f["ok"] += 1
            f["prec"].append(r["metrics"].get("precision", 0.0))
            f["area"].append(r["metrics"].get("area", 0.0))
            if "area_um2" in r["metrics"]:
                f["um2"].append(r["metrics"]["area_um2"])
    lines = ["# 106 实例全量回归报告（基线闭环）", "",
             f"- 总实例: {len(results)}，通过: {n_ok}，失败: {len(results) - n_ok}", ""]
    lines += ["| 族 | 实例 | 通过 | 精度中位 | 面积中位(LUT) | ASIC 中位(μm²) |",
              "|---|---|---|---|---|---|"]
    for fam in sorted(fams):
        f = fams[fam]
        prec = sorted(f["prec"])[len(f["prec"]) // 2] if f["prec"] else None
        area = sorted(f["area"])[len(f["area"]) // 2] if f["area"] else None
        um2 = sorted(f["um2"])[len(f["um2"]) // 2] if f["um2"] else None
        lines.append(f"| {fam} | {f['n']} | {f['ok']} | "
                     f"{prec if prec is not None else '-'} | "
                     f"{area if area is not None else '-'} | "
                     f"{um2 if um2 is not None else '-'} |")
    fails = [r for r in results if not r["ok"]]
    if fails:
        lines += ["", "## 失败清单", ""]
        for r in fails:
            lines.append(f"- `{r['instance']}` [{r.get('error_type')}] {r.get('error', '')[:200]}")
    (BENCH / "regression_report.md").write_text("\n".join(lines) + "\n")
    print(f"\nreport: regression_report.md / .json  ({n_ok}/{len(results)} ok)")


if __name__ == "__main__":
    main()
