"""通用 OpenEvolve 批量运行：任务名 × 种子。起点由 Task 自动生成。
python -m dspgen.run_oe --out DIR --tasks duc_l8_wide,duc_l16_mid --seeds 0 --iters 120 --conc 3
"""
import argparse, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml
from dspgraph import llm
from dspgraph.run_oe_grid import KEY
from .prompt import system_prompt
from .task import get

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent.parent.parent


def run(args):
    name, seed, iters, out, model = args
    d = (Path(out) / f"{name}__s{seed}").resolve()
    d.mkdir(parents=True)
    t = get(name)
    (d / "start.py").write_text("# EVOLVE-BLOCK-START\n" + t.direct_start() + "# EVOLVE-BLOCK-END\n")
    cfg = {"max_iterations": iters, "checkpoint_interval": 20, "log_level": "INFO", "language": "python",
           "random_seed": seed,
           "llm": {"api_base": llm.API_BASE, "api_key": "${DEEPSEEK_API_KEY}", "primary_model": model,
                   "primary_model_weight": 1.0, "temperature": 0.7, "max_tokens": 8000, "timeout": 300, "retries": 1,
                   "extra_body": {"thinking": {"type": "disabled"}}},
           "prompt": {"system_message": system_prompt(t), "num_top_programs": 2, "num_diverse_programs": 1,
                      "include_artifacts": True, "use_template_stochasticity": True},
           "database": {"population_size": 40, "archive_size": 20, "num_islands": 2,
                        "feature_dimensions": ["area_log", "snr_margin"], "feature_bins": {"area_log": 8, "snr_margin": 6},
                        "elite_selection_ratio": 0.2, "exploration_ratio": 0.3, "exploitation_ratio": 0.7,
                        "random_seed": seed},
           "evaluator": {"cascade_evaluation": False, "timeout": 300, "parallel_evaluations": 2},
           "diff_based_evolution": True, "full_rewrite_probability": 0.0, "max_code_length": 30000}
    (d / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    env = dict(os.environ, DSPG_TASK=name, PYTHONWARNINGS="ignore", DEEPSEEK_API_KEY=KEY.read_text().strip())
    t0 = time.time()
    with open(d / "run.log", "w") as log:
        rc = subprocess.run([sys.executable, str(ROOT / "openevolve-run.py"), str(d / "start.py"),
                             str(PKG / "oe_eval.py"), "--config", str(d / "config.yaml"), "--output", str(d),
                             "--iterations", str(iters)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    return {"task": name, "seed": seed, "rc": rc, "seconds": time.time() - t0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--iters", type=int, default=120)
    ap.add_argument("--conc", type=int, default=3)
    ap.add_argument("--model", default=llm.MODEL)
    a = ap.parse_args()
    if a.out.exists():
        sys.exit(f"refusing to overwrite {a.out}")
    a.out.mkdir(parents=True)
    tasks = [(n, int(s), a.iters, str(a.out), a.model) for s in a.seeds.split(",") for n in a.tasks.split(",")]
    (a.out / "manifest.json").write_text(json.dumps({"tasks": a.tasks, "seeds": a.seeds, "iters": a.iters,
                                                    "model": a.model, "started": time.time()}, indent=1))
    with ThreadPoolExecutor(a.conc) as ex:
        rows = list(ex.map(run, tasks))
    (a.out / "runs.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
