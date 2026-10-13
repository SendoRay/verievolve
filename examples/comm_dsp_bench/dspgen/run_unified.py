"""VeriEvolve 统一系统的一次运行：初始种群 = 直写起点 + K 个 LLM 从规格生成的参数化结构程序；
外层 diff 变异与整程序重写按固定比例混用；内层在候选声明的参数空间内做确定性搜索。

python -m dspgen.run_unified --out DIR --tasks a,b --seed 0 --iters 120 --seeds-dir DIR_WITH_structgen --conc 3
"""
import argparse, asyncio, json, os, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from dspgraph import llm
from dspgraph.run_oe_grid import KEY
from .prompt import system_prompt
from .task import get

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent.parent.parent
REWRITE_P = 0.25
INNER = 8
MARGIN = 0.3


def child(task, seed, iters, d: Path, seed_codes):
    sys.path.insert(0, str(ROOT))
    from openevolve.config import load_config
    from openevolve.controller import OpenEvolve
    from openevolve.database import Program
    cfg = load_config(str(d / "config.yaml"))
    oe = OpenEvolve(initial_program_path=str(d / "start.py"), evaluation_file=str(PKG / "oe_eval.py"),
                    config=cfg, output_dir=str(d))

    async def go():
        codes = [oe.initial_program_code] + ["# EVOLVE-BLOCK-START\n" + c + "# EVOLVE-BLOCK-END\n" for c in seed_codes]
        for k, code in enumerate(codes):
            pid = str(uuid.uuid4())
            m = await oe.evaluator.evaluate_program(code, pid)
            oe.database.add(Program(id=pid, code=code, language=cfg.language, metrics=m, iteration_found=0),
                            target_island=k % cfg.database.num_islands)
            art = oe.evaluator.get_pending_artifacts(pid)
            if art:
                oe.database.store_artifacts(pid, art)
            print(f"seed {k}: {m}", flush=True)
        await oe.run(iterations=iters)
    asyncio.run(go())


def run(args):
    name, seed, iters, out, seeds_dir = args
    d = (Path(out) / f"{name}__s{seed}").resolve()
    d.mkdir(parents=True)
    t = get(name)
    (d / "start.py").write_text("# EVOLVE-BLOCK-START\n" + t.direct_start() + "# EVOLVE-BLOCK-END\n")
    sg = json.loads((Path(seeds_dir) / name / "structgen.json").read_text())
    seed_codes = [Path(r["final_code_path"]).read_text() for r in sg if r.get("compiled")]
    cfg = {"max_iterations": iters, "checkpoint_interval": 20, "log_level": "INFO", "language": "python",
           "random_seed": seed,
           "llm": {"api_base": llm.API_BASE, "api_key": "${DEEPSEEK_API_KEY}", "primary_model": llm.MODEL,
                   "primary_model_weight": 1.0, "temperature": 0.7, "max_tokens": 8000, "timeout": 300, "retries": 1,
                   "extra_body": {"thinking": {"type": "disabled"}}},
           "prompt": {"system_message": system_prompt(t) + "\n程序可以用字面量 SPACE/P 字典声明参数及其取值范围，"
                      "系统会在该范围内自动搜索参数；你只需要关注结构。",
                      "num_top_programs": 2, "num_diverse_programs": 1, "include_artifacts": True,
                      "use_template_stochasticity": True},
           "database": {"population_size": 40, "archive_size": 20, "num_islands": 2,
                        "feature_dimensions": ["area_log", "snr_margin"], "feature_bins": {"area_log": 8, "snr_margin": 6},
                        "elite_selection_ratio": 0.2, "exploration_ratio": 0.3, "exploitation_ratio": 0.7,
                        "random_seed": seed},
           "evaluator": {"cascade_evaluation": False, "timeout": 900, "parallel_evaluations": 2},
           "diff_based_evolution": True, "full_rewrite_probability": REWRITE_P, "max_code_length": 40000}
    (d / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    env = dict(os.environ, DSPG_TASK=name, PYTHONWARNINGS="ignore", DEEPSEEK_API_KEY=KEY.read_text().strip(),
               DSPG_INNER_SPACE=str(INNER), DSPG_MARGIN_DB=str(MARGIN), DSPG_INNER_LOG=str(d / "inner_evals.log"))
    (d / "seeds.json").write_text(json.dumps({"n_structgen_seeds": len(seed_codes)}))
    import subprocess
    t0 = time.time()
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); from dspgen.run_unified import child; "
            "import json; child(%r, %d, %d, __import__('pathlib').Path(%r), json.load(open(%r)))"
            % (str(PKG.parent), str(ROOT), name, seed, iters, str(d), str(d / "seed_codes.json")))
    (d / "seed_codes.json").write_text(json.dumps(seed_codes))
    with open(d / "run.log", "w") as log:
        rc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    return {"task": name, "seed": seed, "rc": rc, "seconds": time.time() - t0, "n_seeds": len(seed_codes)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--iters", type=int, default=120)
    ap.add_argument("--seeds-dir", required=True)
    ap.add_argument("--conc", type=int, default=3)
    a = ap.parse_args()
    if a.out.exists():
        sys.exit(f"refusing to overwrite {a.out}")
    a.out.mkdir(parents=True)
    (a.out / "manifest.json").write_text(json.dumps({"tasks": a.tasks, "seed": a.seed, "iters": a.iters,
        "rewrite_probability": REWRITE_P, "inner_budget": INNER, "margin_db": MARGIN, "seeds_dir": a.seeds_dir,
        "started": time.time()}, indent=1))
    with ThreadPoolExecutor(a.conc) as ex:
        rows = list(ex.map(run, [(n, a.seed, a.iters, str(a.out), a.seeds_dir) for n in a.tasks.split(",")]))
    (a.out / "runs.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
