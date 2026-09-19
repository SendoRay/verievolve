#!/usr/bin/env python
"""E1 最终重判：两臂最终 Pareto 前沿统一用采样评估器（fresh-seed L2）重评。

- Arm S 前沿：直接取 checkpoint 指标（本就是采样口径），仍重评一次以对齐协议。
- Arm C 前沿：从 artifacts 的 params 重建 Verilog → 采样评估；
  同时记录 (cert_mean, sampled) 对 → 证书-实测验证散点（论文图 5.x）。

产出：experiments_e1/rejudge.json
"""
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
import os

os.environ.setdefault("COMMDSP_TASK", "cmul")  # 每任务运行前显式覆盖

import evaluator as base  # noqa: E402
from certfit import tpl_cmul, tpl_cordic, tpl_atan2, tpl_llr  # noqa: E402

_TPL = {"cmul": tpl_cmul, "cordic": tpl_cordic, "atan2": tpl_atan2, "llr": tpl_llr}

TASKS = ["cmul_w16_free", "cordic_sincos", "atan2_w16", "llr_64qam_snr20"]
OUT = BENCH / "experiments_e1"


def front_points(run_dir: Path):
    ckpts = sorted((run_dir / "checkpoints").glob("checkpoint_*"),
                   key=lambda p: int(p.name.split("_")[1]))
    if not ckpts:
        return []
    pts = []
    for pf in (ckpts[-1] / "programs").glob("*.json"):
        d = json.loads(pf.read_text())
        m = d.get("metrics", {})
        if m.get("combined_score", 0) > 0.5 and "precision" in m:
            pts.append({
                "prec_cert_or_sampled": float(m["precision"]),
                "area": float(m["area"]),
                "thr": float(m.get("throughput", 0)),
                "params": json.loads(d.get("artifacts", {}).get("params", "null"))
                if d.get("artifacts", {}).get("params") else None,
                "code": d.get("code", ""),
            })
    # 去重（按 precision/area）
    seen, uniq = set(), []
    for p in pts:
        key = (round(p["prec_cert_or_sampled"], 1), p["area"])
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def sample_eval(vfile: Path, task: str):
    os.environ["COMMDSP_TASK"] = task
    import importlib
    importlib.reload(base)
    r, err = base._simulate(str(vfile), base.FULL_SAMPLES,
                            int((base._load_task().get("timeouts", {}) or {}).get("L2_sim", 30)) + 10)
    if r is None:
        return None, err
    return r, None


def main():
    out = {"tasks": {}}
    for task in TASKS:
        fam = next((k for k in _TPL if task.startswith(k)), None)
        os.environ["COMMDSP_TASK"] = task
        import importlib
        importlib.reload(base)
        entry = {"rejudge": []}
        for arm in ["S", "C"]:
            rd = OUT / f"e1_{task}_arm{arm}_seed0"
            if not rd.exists():
                continue
            for pt in front_points(rd):
                if arm == "C" and pt["params"] is not None:
                    tpl = _TPL[fam]
                    ok, msg = tpl.validate(pt["params"])
                    if not ok:
                        continue
                    vtext = tpl.generate_verilog(pt["params"])
                    with tempfile_dir() as td:
                        vf = Path(td) / "design.v"
                        vf.write_text(vtext)
                        r, err = sample_eval(vf, task)
                else:
                    # Arm S：program code 存在 checkpoint，写临时 .v 采样重评
                    code = pt.get("code")
                    if not code:
                        continue
                    with tempfile_dir() as td:
                        vf = Path(td) / "design.v"
                        vf.write_text(code)
                        r, err = sample_eval(vf, task)
                if r is None:
                    entry["rejudge"].append({"arm": arm, "error": (err or "")[-200:]})
                    continue
                entry["rejudge"].append({
                    "arm": arm,
                    "prec_in_loop": pt["prec_cert_or_sampled"],
                    "sampled_sqnr": round(r["sqnr_db"], 3),
                    "sampled_thr": round(r["throughput"], 4),
                    "params": pt["params"],
                })
        out["tasks"][task] = entry
        n_ok = sum(1 for x in entry["rejudge"] if "sampled_sqnr" in x)
        print(f"{task}: {n_ok} designs re-judged")
    (OUT / "rejudge.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"-> {OUT / 'rejudge.json'}")


class tempfile_dir:
    def __enter__(self):
        import tempfile
        self.td = tempfile.TemporaryDirectory()
        return Path(self.td.name)

    def __exit__(self, *a):
        self.td.cleanup()


if __name__ == "__main__":
    main()
