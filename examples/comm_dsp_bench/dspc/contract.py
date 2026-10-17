"""实现契约：把通过候选级判定的原语程序冻结为 Lowering Agent 必须遵守的契约（FRAMEWORK_v5 §3.5）。

契约目录内容：
  program.py      冻结的原语程序（A 层 + B 层），即“算什么、承诺怎样造”的唯一依据
  contract.json   接口、时序、承诺、分段、暖机规则、哈希、测试向量清单
  CONTRACT.md     给 Lowering Agent 读的说明（协议、承诺、验收规则）
  vectors/<名>/   in.hex [inq.hex]、expected.txt：整数模型的逐样点参考输出

RTL 协议与 dspgen.rtl 相同（因此可直接进入同一 PPA 流程）：
  module top(clk, rst, in_valid, in_i[, in_q], out_valid, out_i[, out_q])；rst 同步高有效；
  每 in_period 个时钟送一个输入样点（in_valid 持续一个时钟）；第 k 次 out_valid 的输出必须等于参考输出第 k 个样点。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import analysis
from .interp import run
from .judge import inputs_for, load

N_RANDOM, N_EXTREME = 8192, 4096


def _extreme(bits: int, n: int, rng) -> np.ndarray:
    """极值序列：正负满量程交替、恒最大、恒最小、冲激、满量程随机符号，各占一段。"""
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    seg = n // 5
    parts = [np.tile([hi, lo], seg // 2 + 1)[:seg], np.full(seg, hi), np.full(seg, lo),
             np.where(np.arange(seg) % 97 == 0, hi, 0), rng.choice([lo, hi], size=n - 4 * seg)]
    return np.concatenate(parts).astype(np.int64)


def vector_sets(task, prog, seed: int = 20261016) -> dict:
    """测试向量：搜索场景、满量程随机、极值序列。返回 {名字: [输入码数组...]}，每个数组形状 (1, n)。"""
    rng = np.random.default_rng(seed)
    bits = task.interface["in_bits"]
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1))
    nin = len(prog.inputs)
    sets = {}
    for i in task.search_scenarios:
        sets[f"search{i}"] = [x[:1] for x in inputs_for(task, [i])]
    sets["random"] = [rng.integers(lo, hi, size=(1, N_RANDOM)) for _ in range(nin)]
    sets["extreme"] = [_extreme(bits, N_EXTREME, rng)[None, :] for _ in range(nin)]
    return sets


def _clock(task_name: str) -> float:
    from dspgen.contract import CONTRACTS
    c = CONTRACTS.get(task_name)
    return float(c.clock_ns) if c is not None else 2.0


def _warmup(prog) -> int:
    return max([c.get("warmup", 0) for c in prog.commits.values()] or [0])


def freeze(code: str, task_name: str, out_dir: Path, report: dict | None = None, seed: int = 20261016,
           only=None) -> dict:
    """冻结契约并写出参考向量。report：该候选的候选级判定报告（写入 contract.json 供追溯）。
    seed：随机与极值向量的种子；only：只生成指定的向量集（终验用新种子生成 agent 从未见过的向量）。"""
    from dspgen.task import get
    task = get(task_name)
    prog = load(code, task)
    out_dir = Path(out_dir)
    (out_dir / "vectors").mkdir(parents=True, exist_ok=True)
    (out_dir / "program.py").write_text(code)
    bits_in, bits_out = task.interface["in_bits"], task.interface["out_bits"]
    mask = (1 << bits_in) - 1
    sets = vector_sets(task, prog, seed=seed)
    if only:
        sets = {k: v for k, v in sets.items() if k in only}
    listing = {}
    for name, xs in sets.items():
        d = out_dir / "vectors" / name
        d.mkdir(parents=True, exist_ok=True)
        r = run(prog, xs, "fixed")
        y = np.atleast_2d(r.y)[0]
        sc = float(1 << (bits_out - 1))
        cols = [np.round(np.real(y) * sc).astype(np.int64)]
        if task.iface("out_kind") == "complex":
            cols.append(np.round(np.imag(y) * sc).astype(np.int64))
        (d / "in.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in xs[0][0]) + "\n")
        if len(xs) > 1:
            (d / "inq.hex").write_text("\n".join(f"{int(c) & mask:x}" for c in xs[1][0]) + "\n")
        (d / "expected.txt").write_text("\n".join(" ".join(str(int(c[k])) for c in cols)
                                                  for k in range(len(cols[0]))) + "\n")
        listing[name] = {"n_in": int(xs[0].shape[1]), "n_out": int(len(cols[0]))}
    st = analysis.g0(prog)
    scopes = sorted({n.scope for n in prog.nodes if n.scope})
    (out_dir / "graph.json").write_text(json.dumps(graph(prog), ensure_ascii=False))
    c = {"task": task_name,
         "interface": {"in_bits": bits_in, "out_bits": bits_out, "in_kind": task.iface("in_kind"),
                       "out_kind": task.iface("out_kind"), "in_period": task.iface("in_period"),
                       "out_rate": str(prog.out_rate), "top": "top"},
         "timing": {"ii": prog.iface.get("ii", task.iface("in_period")),
                    "latency_max": prog.iface.get("latency_max")},
         "commitments": prog.commits, "scopes": scopes, "warmup_outputs": _warmup(prog),
         "a_hash": prog.a_hash(), "b_hash": prog.b_hash(),
         "approx_points": len(st["approx_points"]), "vectors": listing,
         "saturation_possible": [{"node": x["node"], "fmt": x["fmt"], "scope": x["scope"]}
                                 for x in st["saturation_possible"]],
         "clock_ns": _clock(task_name),
         "candidate_report": {k: report[k] for k in ("verdict", "v", "constraints", "class") if k in report}
         if report else None}
    (out_dir / "contract.json").write_text(json.dumps(c, ensure_ascii=False, indent=1))
    (out_dir / "CONTRACT.md").write_text(contract_md(c))
    return c


def graph(prog) -> dict:
    """展开后的原语图：每个节点的运算、参数（常数与表项给出整数码）、格式、速率、分段、源码位置。"""
    nodes = []
    for i, n in enumerate(prog.nodes):
        p = {k: v for k, v in n.params.items() if k not in ("fn", "values", "value", "init")}
        nodes.append({"id": i, "op": n.op, "args": list(n.args), "fmt": str(n.fmt),
                      "rate": None if n.rate is None else str(n.rate), "scope": n.scope, "where": n.where, **p})
    return {"nodes": nodes, "inputs": prog.inputs, "outputs": prog.outputs,
            "format_note": "fmt 为 s<W>.<F>（有符号）或 u<W>.<F>：数值 = 整数码 × 2^-F；const/state 的 code、"
                           "lut/rom 的 codes 是整数码；state 的 next 指向其下一状态节点"}


def contract_md(c: dict) -> str:
    it, tm = c["interface"], c["timing"]
    cx_in, cx_out = it["in_kind"] == "complex", it["out_kind"] == "complex"
    ports = (f"input clk, input rst, input in_valid, input signed [{it['in_bits'] - 1}:0] in_i"
             + (f", input signed [{it['in_bits'] - 1}:0] in_q" if cx_in else "")
             + f", output out_valid, output signed [{it['out_bits'] - 1}:0] out_i"
             + (f", output signed [{it['out_bits'] - 1}:0] out_q" if cx_out else ""))
    valid_txt = ("每个时钟送一个输入样点（`in_valid` 在每个时钟沿都为高）；" if int(tm["ii"]) == 1 else
                 f"每 {tm['ii']} 个时钟送一个输入样点：`in_valid` 为**单拍脉冲**，其后 {int(tm['ii']) - 1} 个时钟为低；")
    com = "\n".join(f"- `{sc}`：" + "，".join(f"{k}={v}" for k, v in kw.items()) for sc, kw in c["commitments"].items()) \
        or "- （无。全部微结构由你选择）"
    return f"""# 实现契约：{c['task']}

你的任务：把 `program.py` 中冻结的原语程序实现为可综合的 Verilog，**逐位忠实**于它的定点解释，并尽量减小面积与功耗。
程序里允许的误差已经在设计阶段被判定为可接受；实现阶段**不允许任何误差**。

## 1. 接口与协议

```verilog
module top({ports});
```

- `rst` 同步、高有效。复位释放后，{valid_txt}输入流中间**没有空隙**，也不会反压。
  复位释放后的第一个有效输入对应输入样点 0；`in_valid` 为低时 `in_i` 的值无意义。
- 输出速率是输入样点率的 {it['out_rate']} 倍。只在有新输出样点时拉高 `out_valid`（单拍）。
- 第 k 次 `out_valid` 时的输出必须等于参考输出的第 k 个样点（前 {c['warmup_outputs']} 个输出不比较）。
- 输入结束后测试平台再运行 4096 个时钟：RTL 必须在此之前给出**全部**参考输出；多出的输出被忽略。
- 时序：目标时钟 {c['clock_ns']:g} ns，实现必须在该时钟下时序收敛（wns ≥ 0）才计入结果。{f"总延迟不超过 {tm['latency_max']} 个时钟。" if tm['latency_max'] else ""}

## 2. 语义的唯一依据

`program.py` 用原语写成（见 `PRIMITIVES.md`）；`graph.json` 是它展开后的原语图（每个节点的运算、格式、速率、分段，
常数与查表给出整数码），实现时以 `graph.json` 为准：**程序中的注释不保证准确**；量化后的系数**不保证对称**，
需要折叠对称抽头时请逐项核对整数码。你实现的是它的**定点解释**：每个信号是整数码 × 2^-F，
`q` 的舍入（round = 加半个 LSB 后向下取整；trunc = 向下取整）与溢出（sat = 饱和；wrap = 补码回绕）都必须逐位一致。
同速率的两个信号按样点序号配对；`delay` 是样点延迟（初值 0）；`decimate(x, r, phase)` 取第 m·r + phase 个样点。
时延对齐、有效信号、流水与存储方式由你决定，只要输出序列逐位一致。

可能饱和的量化点（区间分析，保守）：{', '.join(f"节点 {x['node']}（{x['scope'] or '-'}，{x['fmt']}）" for x in c.get('saturation_possible', [])) or '无'}。
其余 sat 量化点在任意输入码下都不会饱和，可以省去饱和逻辑。

调试：`./ve probe contract <节点号> [--set random]` 给出任意节点在某组向量上的逐样点参考值（整数码），不计预算。

## 3. 微结构承诺（必须遵守）

{com}

## 4. 分段标注

请在每个分段的寄存器上加属性 `(* ve_scope = "<分段名>" *)`（每个分段至少一个），分段名：{', '.join(c['scopes']) or '（无）'}。
有承诺的分段必须标注。被多个分段共用的资源标注为其中一个，并在 notes.md 中说明。标注用于把综合面积与关键路径回映到分段。

## 5. 验收（G3 一致性门）

工具 `conform` 在以下向量上逐位对拍：{', '.join(c['vectors'])}（搜索场景、满量程随机、极值序列）。
全部零失配、承诺满足、标注齐全才算通过；然后才进入综合 PPA。失配时报告首个失配样点。
"""
