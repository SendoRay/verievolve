"""批量运行 LLM 写程序搜索：规格 × 反馈档位 × 种子，并行进程。

python -m dspgraph.run_prog --out DIR --specs dev_r16_narrow,dev_r32_wide --modes verified \
    --seeds 0-2 --calls 20 --jobs 6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import llm
from . import llm_prog
from .rx_spec import DEV_SPECS, HELDOUT_SPECS, SPECS

PKG = Path(__file__).resolve().parent
SEED_PROGRAM = PKG / "seeds" / "naive.py"


def code_identity() -> dict:
    h = hashlib.sha256()
    for f in sorted(PKG.rglob("*.py")):
        h.update(f.relative_to(PKG).as_posix().encode())
        h.update(f.read_bytes())
    return {"dspgraph_sha256": h.hexdigest(),
            "seed_program_sha256": hashlib.sha256(SEED_PROGRAM.read_bytes()).hexdigest()}


def one(args):
    spec, mode, seed, calls, out, thinking, model, harness = args
    from . import rtl_judge
    rtl_judge.HARNESS.update(harness)
    d = Path(out) / f"{spec}__{mode}__s{seed}"
    try:
        return llm_prog.search(spec, llm.RX_FAMILY_TEXT, SEED_PROGRAM.read_text(), mode=mode,
                               calls=calls, seed=seed, log_dir=d, thinking=thinking,
                               model=model, max_repairs=2 if harness.get("repair") else 0)
    except Exception as e:  # 记录为运行失败，不中断其它任务
        return {"spec": spec, "mode": mode, "seed": seed, "run_error": repr(e)[:500]}


def parse_seeds(s):
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--specs", default="dev")
    ap.add_argument("--modes", default="scalar,metrics,verified")
    ap.add_argument("--seeds", default="0-2")
    ap.add_argument("--calls", type=int, default=20)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument("--model", default=llm.MODEL)
    ap.add_argument("--harness", default="v2", choices=["v1", "v2"],
                    help="v1：单次提交、位宽超限报错、无观测；v2：自动截位 + 编译修复回合 + 观测点")
    a = ap.parse_args(argv)
    if a.out.exists():
        sys.exit(f"refusing to overwrite {a.out}")
    a.out.mkdir(parents=True)
    specs = ([s.name for s in DEV_SPECS] if a.specs == "dev" else
             [s.name for s in HELDOUT_SPECS] if a.specs == "heldout" else a.specs.split(","))
    modes = a.modes.split(",")
    seeds = parse_seeds(a.seeds)
    manifest = {"schema": "dspgraph-llm-program-search-v1", "specs": {s: SPECS[s].to_dict() for s in specs},
                "modes": modes, "seeds": seeds, "calls_per_run": a.calls, "model": a.model, "harness": a.harness,
                "temperature": 0.8, "thinking": a.thinking, "code": code_identity(), "started": time.time(),
                "start_program": "seeds/naive.py (direct transcription of the formula)"}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    harness = ({"auto_narrow": True, "probes": True, "repair": True} if a.harness == "v2"
               else {"auto_narrow": False, "probes": False, "repair": False})
    tasks = [(s, m, sd, a.calls, str(a.out), a.thinking, a.model, harness)
             for sd in seeds for s in specs for m in modes]
    rows = []
    with ProcessPoolExecutor(a.jobs) as ex:
        for r in ex.map(one, tasks):
            rows.append({k: v for k, v in r.items() if k != "records"} |
                        {"n_records": len(r.get("records", []))})
            (a.out / "progress.json").write_text(json.dumps(rows, indent=1, default=str))
    (a.out / "runs.json").write_text(json.dumps(rows, indent=1, default=str))
    print(json.dumps(rows, indent=1, default=str))


if __name__ == "__main__":
    main()
