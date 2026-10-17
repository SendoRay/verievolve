"""工作区生成：设计工作区（外环，设计 Agent）与实现工作区（内环，Lowering Agent）。

设计工作区内容：TASK.md（输入三项 F/Q/I、规则、命令、预算）、PRIMITIVES.md、start.py（语义直写起点）、
.ws.json（任务、变体、预算）、ve（工具入口）。
变体（同一工具链、同一输入、同一预算，每次只改一项；见 FRAMEWORK_v5 §7.3）：
  full   完整方法
  exact  零误差对照（E1）：只允许相对父节点逐位等价的修改（T1），即不允许在 A 层引入新的近似
  score  反馈消融（E5）：判定只返回状态与一个标量分数
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
DEFAULT_BUDGET = {"verdict": 150, "lower": 40, "ppa": 20, "final": 3}


def _ve(ws: Path) -> None:
    (ws / "ve").write_text(f"#!/bin/sh\nPYTHONPATH={BENCH} exec python3 -W ignore -m dspc.tool \"$@\"\n")
    os.chmod(ws / "ve", 0o755)


def task_md(task_name: str, variant: str, budget: dict) -> str:
    from dspgen.contract import CONTRACTS
    from dspgen.task import get
    t, c = get(task_name), CONTRACTS.get(task_name)
    it = t.interface
    p = (c.envelope or {}).get("impl_budget_p", 0.1) if c else 0.1
    clock = c.clock_ns if c else 2.0
    params = ", ".join(f"spec.{k} = {v!r}" for k, v in t.params.items())
    exact = ("\n> **本工作区为零误差对照变体**：只接受相对父节点**逐位等价**（T1）的修改，即不允许引入新的近似；"
             "可以改结构（如多相分解、交织）与微结构承诺，不能改精度或换成近似结构。\n" if variant == "exact" else "")
    return f"""# 设计任务：{t.name}
{exact}
## 输入（三项）

**公式 F**：{t.description}
参数：{params}

**质量指标 Q**：{c.scoring if c else '见判定报告'}
输入类：{c.input_class if c else ''}
可接受判据：实现带来的额外误差功率不超过系统允许误差功率的 p = {p:g} 倍（门槛由此推出，判定报告中的 threshold 即门槛）。

**接口 I**：输入 {it['in_bits']} 位{'复数' if t.iface('in_kind') == 'complex' else '实数'}，
每 {t.iface('in_period')} 个时钟一个输入样点；输出 {it['out_bits']} 位{'复数' if t.iface('out_kind') == 'complex' else '实数'}；
目标时钟 {clock:g} ns。

## 你做什么

你是**设计 Agent**：用 `PRIMITIVES.md` 中的原语写 `build(g, spec)` 程序，决定“算什么”（结构与精度，A 层）
和“承诺怎样造”（折叠、资源、流水，B 层）。**误差只能经由近似点（q、const、lut）进入**，是否可接受由系统判定。
你不写 Verilog：通过判定的候选会冻结为契约，由 Lowering Agent 实现为 RTL，再做真实综合，PPA 反馈给你。

目标：在满足全部约束及裕量的前提下，使真实面积尽可能小；同等面积下功耗越低越好；必须在目标时钟下时序收敛。

## 命令（在本目录执行）

```
./ve api                                   # 原语参考
./ve archive add <prog.py> [--parent dNNN] --action REWRITE|TUNE --claim equiv|precision|structure --note "..."
                                           # 登记候选并做候选级判定（G0 静态 → G1 变换核实 → G2 容差门）
./ve archive show                          # 档案、前沿与调度提示
./ve archive impl <dNNN> <rtl.v>           # （由实现环调用）登记一个实现：一致性检查 + 真实综合
./ve archive final <dNNN>                  # 终验：隐藏场景 + 新向量一致性 + 门级对拍 + 时序，只返回通过与否
```

`start.py` 是语义直写起点（理想解释即公式，PPA 很差）。判定报告给出：约束表（值、门槛、松弛、裕量）、
变换类别（T1 逐位等价 / T2 理想等价即只改精度 / T3 结构近似）、**结构余量与精度余量**（理想解释与定点解释的质量）
以及据此的修改粒度建议，还有近似点噪声清单。

## 预算（工具层强制执行，超额调用直接拒绝）

候选级判定 {budget.get('verdict')} 次；实现（一致性检查）{budget.get('lower')} 次；真实综合 {budget.get('ppa')} 次；
终验 {budget.get('final')} 次。

## 规则

- 只在本目录内读写，不查看本目录以外的任何文件。
- 在 `notes/plan.md` 写分析与路线；最终在 `notes/summary.md` 写明结构、PPA、裕量。
"""


def make_design_ws(task_name: str, root: Path, variant: str = "full", budget: dict | None = None) -> Path:
    from .direct import direct_start
    from .docs import PRIMITIVES_MD
    from dspgen.task import get
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    budget = budget or dict(DEFAULT_BUDGET)
    (root / ".ws.json").write_text(json.dumps({"task": task_name, "variant": variant, "budget": budget},
                                              ensure_ascii=False))
    (root / "TASK.md").write_text(task_md(task_name, variant, budget))
    (root / "PRIMITIVES.md").write_text(PRIMITIVES_MD)
    (root / "start.py").write_text(direct_start(get(task_name)))
    (root / "notes").mkdir(exist_ok=True)
    _ve(root)
    return root


LOWERING_PROMPT = """你是 Lowering Agent（RTL 实现智能体）。在当前目录把冻结的实现契约实现为可综合 Verilog `top.v`，
逐位忠实于契约中原语程序的定点解释，并在此基础上尽量减小面积。

先读 contract/CONTRACT.md（接口、协议、承诺、验收）、contract/PRIMITIVES.md（原语语义）、contract/program.py 与
contract/graph.json（展开后的原语图，常数与表项给出整数码；以它为准，不要自己重新推导系数）。

工具：`./ve conform contract top.v [--sets random]` 一致性检查（预算 {lower} 次）；`./ve ppa contract top.v` 真实综合（预算 {ppa} 次）。
你也可以用 dspc.interp.run(prog, inputs, 'fixed', keep='all') 拿到任意中间节点的逐位参考值来定位错误（不计预算）。

规则：顶层模块 top；不得修改 contract/；不得把 contract/vectors/ 中的数据以任何形式嵌入 RTL（之后会用新的随机向量复核）；
必须遵守契约中的微结构承诺；有承诺的分段加 (* ve_scope = "<分段名>" *) 标注。推荐写 Python 生成脚本产生 top.v。
完成后在 notes.md 写明：一致性结果、PPA、调用次数、遇到的错误类型、契约文档中不清楚的地方。
"""


def make_lower_ws(design_ws: Path, cid: str, k: int, budget: dict | None = None) -> Path:
    """为设计节点 cid 准备第 k 个实现工作区（契约来自设计工作区的 contracts/<cid>/）。"""
    import shutil
    design_ws = Path(design_ws)
    budget = budget or {"lower": 25, "ppa": 6}
    src = design_ws / "contracts" / cid
    if not (src / "contract.json").exists():
        raise FileNotFoundError(f"{src} 不存在：先对 {cid} 运行 ./ve archive impl 或 freeze")
    ws = design_ws / "lowering" / f"{cid}_{k:02d}"
    ws.mkdir(parents=True, exist_ok=True)
    if not (ws / "contract").exists():
        shutil.copytree(src, ws / "contract")
    task = json.loads((design_ws / ".ws.json").read_text())["task"]
    (ws / ".ws.json").write_text(json.dumps({"task": task, "budget": budget}, ensure_ascii=False))
    (ws / "PROMPT.md").write_text(LOWERING_PROMPT.format(**budget))
    _ve(ws)
    return ws
