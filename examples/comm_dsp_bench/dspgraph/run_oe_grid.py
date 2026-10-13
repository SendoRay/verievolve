"""批量运行 OpenEvolve（LLM diff 进化）：规格 × 反馈档位 × 种子，限制并发。

python -m dspgraph.run_oe_grid --out DIR --specs dev --modes verified --seeds 0 --iters 200 --conc 3
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import llm, llm_prog
from .rx_spec import DEV_SPECS, HELDOUT_SPECS, SPECS

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent.parent.parent
KEY = Path(__file__).resolve().parent.parent / ".api_key_deepseek"


B1_PROMPT = """你是数字通信硬件架构师。任务：直接修改一个 Verilog 设计（顶层模块 top），在满足全部指标的前提下使
硬件面积尽可能小。可以使用任何等价或近似变换（多级抽取、多相、利用对称、零系数、查表镜像、截短位宽、分时复用等），
只要求指标达标。

【数学功能】
{family}

【规格】（spec 对象的字段可在 @py 指令中读取）
{spec}

【设计格式】
- 顶层模块 top，端口固定：input clk, rst, in_valid, input signed [input_bits-1:0] in_i,
  output out_valid, output signed [output_bits-1:0] out_i, out_q。输入每个时钟一个样点（in_valid 恒为 1），
  out_valid 为 1 的周期输出一个复基带样点，输出速率必须是 input_rate/r_total。
- 离线计算：在注释里写 `// @py <Python 语句>`（可用 np、scipy、math、spec），
  `// @hex <文件名> <位宽> <表达式>` 把整数列表写成文件供 $readmemh 读取，正文中 `{{{{表达式}}}}` 会被替换为数值。
- 用 iverilog 仿真（注意：组合 always @(*) 对数组元素不敏感，读数组的长运算请放在时钟块里），
  面积由 Yosys 映射到 Nangate45 标准单元得到（μm²）。

【评分】裁判只看输入输出：冻结测试信号（通带内 24 个复音 + 覆盖全部混叠频带的阻塞音）送入设计，对照理想基带期望
信号计算 SNR（自动搜索群时延，只拟合一个复增益）和通带纹波；每个场景都必须 SNR ≥ 门槛且纹波 ≤ 上限。

【回答格式】按要求给出对当前设计的修改。优先做有针对性的改动并保持设计达标；每次改动要有明确的面积收益理由。"""


STRUCT_NOTE = ("\n【本轮限制】当前程序的参数（P_ 字典中的阶数、抽头数、位宽、复用因子等）已经由参数搜索调到最优，"
               "单纯修改参数不会被接受。请提出结构或算法层面的变换（改变运算组织、级的划分与类型、"
               "滤波实现方式、混频方式、数值表示、共享方式等），等价或近似均可，只要指标达标且面积更小。\n")


def config(spec: str, seed: int, iters: int, model: str, struct_only: bool = False,
           knowledge: bool = False, b1: bool = False) -> dict:
    sm = llm_prog.system_prompt(SPECS[spec], llm.RX_FAMILY_TEXT).split("【回答格式】")[0]
    if b1:
        sm = B1_PROMPT.format(family=llm.RX_FAMILY_TEXT,
                              spec=json.dumps(llm_prog.spec_view(SPECS[spec]), ensure_ascii=False, indent=1))
    if knowledge:
        sm += "\n" + (PKG / "knowledge_multirate.txt").read_text() + "\n"
    if struct_only:
        sm += STRUCT_NOTE
    if not b1:
        sm += "【回答格式】按要求给出对当前程序的修改。优先做有针对性的改动并保持程序达标；每次改动要有明确的面积收益理由。"
    return {"max_iterations": iters, "checkpoint_interval": 20, "log_level": "INFO",
            "language": "verilog" if b1 else "python",
            "random_seed": seed,
            "llm": {"api_base": llm.API_BASE, "api_key": "${DEEPSEEK_API_KEY}", "primary_model": model,
                    "primary_model_weight": 1.0, "temperature": 0.7, "max_tokens": 8000, "timeout": 300,
                    "retries": 1, "extra_body": {"thinking": {"type": "disabled"}}},
            "prompt": {"system_message": sm, "num_top_programs": 2, "num_diverse_programs": 1,
                       "include_artifacts": True, "use_template_stochasticity": True},
            "database": {"population_size": 40, "archive_size": 20, "num_islands": 2,
                         "feature_dimensions": ["area_log", "snr_margin"],
                         "feature_bins": {"area_log": 8, "snr_margin": 6}, "elite_selection_ratio": 0.2,
                         "exploration_ratio": 0.3, "exploitation_ratio": 0.7, "random_seed": seed},
            "evaluator": {"cascade_evaluation": False, "timeout": 2400 if b1 else 300, "parallel_evaluations": 2},
            "diff_based_evolution": True, "full_rewrite_probability": 0.0, "max_code_length": 30000}


def run(task):
    spec, mode, seed, iters, out, model, start, struct_only, knowledge, b1 = task
    d = (Path(out) / f"{spec}__{mode}__s{seed}").resolve()
    d.mkdir(parents=True, exist_ok=False)
    cfg = d / "config.yaml"
    cfg.write_text(yaml.safe_dump(config(spec, seed, iters, model, struct_only, knowledge, b1), allow_unicode=True, sort_keys=False))
    env = dict(os.environ, DSPG_SPEC=spec, DSPG_MODE=mode, PYTHONWARNINGS="ignore",
               DEEPSEEK_API_KEY=KEY.read_text().strip())
    for k in ("DSPG_MARGIN_DB", "DSPG_INNER_TUNE", "DSPG_TUNE_KEYS"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    env["DSPG_INNER_LOG"] = str(d / "inner_evals.log")
    if struct_only:
        env["DSPG_STRUCT_ONLY_SEED"] = str(PKG / f"seeds/expert_{spec}_oe.py")
    t0 = time.time()
    with open(d / "run.log", "w") as log:
        rc = subprocess.run([sys.executable, str(ROOT / "openevolve-run.py"), str(PKG / ("seeds/naive_verilog_oe.v" if b1 else
                                        "seeds/naive_oe.py" if start == "naive" else
                                        f"seeds/expert03_{spec}_oe.py" if start == "expert03" else
                                        f"seeds/expert_{spec}_oe.py")),
                             str(PKG / ("oe_eval_verilog.py" if b1 else "oe_eval.py")), "--config", str(cfg), "--output", str(d),
                             "--iterations", str(iters)], cwd=ROOT, env=env, stdout=log,
                            stderr=subprocess.STDOUT).returncode
    return {"spec": spec, "mode": mode, "seed": seed, "rc": rc, "seconds": time.time() - t0}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--specs", default="dev")
    ap.add_argument("--modes", default="verified")
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--conc", type=int, default=3)
    ap.add_argument("--model", default=llm.MODEL)
    ap.add_argument("--start", default="naive", choices=["naive", "expert", "expert03"])
    ap.add_argument("--struct-only", action="store_true")
    ap.add_argument("--knowledge", action="store_true")
    ap.add_argument("--b1", action="store_true", help="B1 对照：LLM 直接写 Verilog")
    a = ap.parse_args(argv)
    if a.out.exists():
        sys.exit(f"refusing to overwrite {a.out}")
    a.out.mkdir(parents=True)
    specs = ([s.name for s in DEV_SPECS] if a.specs == "dev" else
             [s.name for s in HELDOUT_SPECS] if a.specs == "heldout" else a.specs.split(","))
    seeds = [int(x) for x in a.seeds.split(",")]
    modes = a.modes.split(",")
    (a.out / "manifest.json").write_text(json.dumps(
        {"schema": "dspgraph-oe-grid-v1", "specs": specs, "modes": modes, "seeds": seeds,
         "iterations": a.iters, "model": a.model, "start_program": a.start, "struct_only": a.struct_only, "knowledge": a.knowledge, "b1": a.b1,
         "evaluator": "dspgraph/oe_eval.py", "started": time.time()}, indent=1))
    tasks = [(s, m, sd, a.iters, str(a.out), a.model, a.start, a.struct_only, a.knowledge, a.b1)
             for sd in seeds for m in modes for s in specs]
    with ThreadPoolExecutor(a.conc) as ex:
        rows = list(ex.map(run, tasks))
    (a.out / "runs.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
