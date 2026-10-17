"""任务契约（声明式数据）与 agent 工作区生成。

契约 = 任务（公式、接口、指标、场景，见 Task）+ 设计边界 + 输入类声明 + 验收集/加固集划分 + 安全裕量 + 硬件约束 + 预算。
它是数据而不是代码：新增一个设计任务只需登记一份 Contract，工作区（CONTRACT.md、spec.json、原语与构造函数库文档、
直写起点）由 make_workspace 自动生成，保证不同任务、不同运行之间的条件一致、可复现。

四个边界（讨论归纳 §5.3）：
  var  可变子图：允许搜索/改写的部分（当前整条链）
  ctx  冻结上下文：保持不变的前后级
  obs  质量观测点：在哪里计算系统指标
  cost 计价范围：哪些部分计入 PPA
加固集（留出场景）不写进工作区，agent 不可见，只在终验时使用。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .task import get

TOOL = Path(__file__).resolve().parent / "agent_tool.py"

# 原语分层（讨论归纳 §4.3）：判据是“决策全部可见、机制全部隐藏”
CORE_RTL = ("const", "add", "sub", "mul", "bits", "mux", "lut", "reg", "ram")
CORE_DSP = ("q", "shift", "delay", "decimate", "interpolate", "gather", "clock", "state", "close", "sample")
CORE_IO = ("input", "output")
CONVENIENCE = {   # 编译器直接支持以提高可读性，但语义上可由核心原语组合；列出等价组合，避免把设计决策藏进黑盒
    "neg": "等价于 sub(const(0), x)",
    "scale": "等价于常数 × mul；当前固定用 CSD 移位加实现。若想共享移位加项（多常数乘法共享），可以用 shift + add 自己写",
    "integrate": "等价于 state + add + q(ovf='wrap') 的累加反馈",
    "counter": "等价于 state + add + q(ovf='wrap') 的相位/序号累加",
    "delay_line": "等价于 n 个 delay；当前用寄存器实现",
    "mac": "等价于若干 scale/mul + add；share>1 时等价于 clock + counter + mux + mul + state 的分时复用",
}
TOOLS = ("scope", "probe")


@dataclass
class Contract:
    task: str
    goal: str                                   # 一句话目标
    input_class: str                            # 输入类声明（幅度、分布），终验与证明都以此为准
    scoring: str                                # 指标如何计算（给 agent 看的说明）
    boundaries: dict = field(default_factory=lambda: {"var": "整条链", "ctx": "无", "obs": "链路输出端",
                                                      "cost": "整条链"})
    safety_margin_db: float = 0.3
    clock_ns: float = 2.0
    objective: str = "在满足全部约束的前提下，使硬件面积尽可能小；同等面积下功耗越低越好。"
    budget: dict = field(default_factory=lambda: {"eval": 150, "ppa": 12, "final": 3})
    convention_note: str = ""                   # 直写起点的说明
    extra_constraints: tuple = ()
    envelope: dict = field(default_factory=dict)   # 输入包络的数值形式（例如 peak、desired_peak、blocker_rel_db）
    variant: str = "full"                        # full / flat（无档案）/ score（只给分数）/ verilog（直写 Verilog）

    def to_json(self) -> dict:
        t = get(self.task)
        d = asdict(self)
        d.update(search_scenarios=list(t.search_scenarios), holdout_scenarios=list(t.holdout_scenarios),
                 tolerance=t.tolerance, interface=t.interface)
        return d


def primitives_doc() -> str:
    from .prompt import api_doc
    from dspgraph.llm_prog import GENERAL
    lines = api_doc().splitlines()
    by = {}
    for ln in lines:
        name = ln.split("(")[0].replace("- g.", "").strip()
        by[name] = ln

    def sect(title, names, note=None):
        out = [f"## {title}"]
        for n in names:
            if n in by:
                out.append(by[n] + (f"  【{note[n]}】" if note and n in note else ""))
        return out

    parts = ["# 原语说明", "",
             "核心原语分三类：RTL 字级运算（与 Verilog 的字级运算一一对应）、DSP 语义（定点量化、样本延迟、速率域、反馈、",
             "帧与时钟域；编译器据此自动生成时延对齐、使能与 valid）、接口。便利原语可由核心原语组合，列出了等价写法。",
             "任何结构（FIR、CIC、FFT 蝶形、NCO、CORDIC 等）都应由这些原语组合而成；构造函数库 LIBRARY.md 给出了几个",
             "可直接复制、也可修改的组合示例。", ""]
    parts += sect("核心原语：RTL 字级运算", CORE_RTL) + [""]
    parts += sect("核心原语：DSP 语义", CORE_DSP) + [""]
    parts += sect("核心原语：接口", CORE_IO) + [""]
    parts += sect("便利原语（可由核心原语组合）", list(CONVENIENCE), CONVENIENCE) + [""]
    parts += sect("工具（不产生硬件）", TOOLS) + [""]
    parts += ["## 定点与时序约定", GENERAL]
    return "\n".join(parts)


LIBRARY = '''# 构造函数库（可直接复制进你的程序，也可以修改；它们只是核心原语的组合，不是黑盒）

```python
def cmp_lt(g, a, b):
    """a < b 时为 1（1 位无符号）：取 a − b 的符号位。"""
    d = g.sub(a, b)
    return g.bits(d, d.w - 1, d.w - 1)

def vmax(g, a, b):
    return g.mux(cmp_lt(g, a, b), b, a)

def vmin(g, a, b):
    return g.mux(cmp_lt(g, a, b), a, b)

def vabs(g, x):
    return g.mux(g.bits(x, x.w - 1, x.w - 1), g.neg(x), x)

def cadd(g, a, b):            # 复数用 (re, im) 二元组表示
    return g.add(a[0], b[0]), g.add(a[1], b[1])

def csub(g, a, b):
    return g.sub(a[0], b[0]), g.sub(a[1], b[1])

def cmul(g, a, b):            # 4 个实乘法；也可以改写成 3 乘法形式
    return (g.sub(g.mul(a[0], b[0]), g.mul(a[1], b[1])),
            g.add(g.mul(a[0], b[1]), g.mul(a[1], b[0])))

def cmul_const(g, a, c, bits=16):   # 乘复常数 c（Python complex），用移位加实现
    return (g.sub(g.scale(a[0], c.real, bits), g.scale(a[1], c.imag, bits)),
            g.add(g.scale(a[0], c.imag, bits), g.scale(a[1], c.real, bits)))

def mul_j(g, a, sign=+1):     # 乘 ±j：只交换实虚部并取负，不产生乘法器
    return (g.neg(a[1]), a[0]) if sign > 0 else (a[1], g.neg(a[0]))

def bfly2(g, a, b):           # 基 2 蝶形：(a + b, a − b)
    return cadd(g, a, b), csub(g, a, b)
```
'''


BUDGET_TXT = "由工具强制执行：评价类调用（eval、veval、vsweep、archive add）合计 {E} 次；PPA 类调用（ppa、ppa --vcd、vppa）合计 {P} 次；终验（final、vfinal、archive verify）{F} 次。observe 与 rtl 不计入。超额的调用会被拒绝。终验约 3–5 分钟，会用到你看不到的留出场景与统计复核场景，只返回通过与否。"


def _commands(c: Contract) -> str:
    t = get(c.task)
    bud = c.budget
    T = TOOL
    head = f"## 命令（在本目录下执行）\n```\nT={T}\n"
    if c.variant == "verilog":
        return (head +
                f"python3 -W ignore $T veval  {t.name} <设计.v>          # 搜索场景上的约束表（秒级）\n"
                f"python3 -W ignore $T vsweep {t.name} <设计.v>          # 同上，另加全频带扫频约束（较慢）\n"
                f"python3 -W ignore $T vppa   {t.name} <设计.v> {c.clock_ns:g} [--vcd]   # 真实综合 + OpenSTA\n"
                f"python3 -W ignore $T vfinal {t.name} <设计.v>          # 终验：隐藏数据集 + 扫频 + 目标时钟下 PPA\n```\n"
                "设计是一个 Verilog 文件，顶层模块名 top，端口与 `direct_start.v` 相同（含时钟、复位与 valid 约定）。\n\n"
                "## 预算\n" + BUDGET_TXT.format(E=bud["eval"], P=bud["ppa"], F=bud["final"]) + "\n\n"
                "## 工作方式\n1. 先在 `notes/plan.md` 写分析。\n2. 候选存为 `cand/cNN.v` 并用 veval 评价。\n"
                "3. 最终设计复制为 `final.v`，用 vfinal 终验，在 `notes/summary.md` 写明结构、PPA、裕量与路线。\n"
                "4. 在 `notes/tool_feedback.md` 写下工具问题。\n\n")
    if c.variant == "flat":
        return (head +
                f"python3 -W ignore $T eval    {t.name} <程序.py>        # 判定报告：约束表、目标、诊断（秒级）\n"
                f"python3 -W ignore $T observe {t.name} <程序.py> o.json # 导出 g.probe 观测点的逐样点值\n"
                f"python3 -W ignore $T rtl     {t.name} <程序.py>        # RTL 与整数模型对拍\n"
                f"python3 -W ignore $T ppa     {t.name} <程序.py> {c.clock_ns:g} [--vcd]   # 真实综合 + OpenSTA\n"
                f"python3 -W ignore $T final   {t.name} <程序.py>        # 终验：隐藏数据集 + RTL/门级对拍 + PPA\n```\n\n"
                "## 预算\n" + BUDGET_TXT.format(E=bud["eval"], P=bud["ppa"], F=bud["final"]) + "\n\n"
                "## 工作方式\n1. 先在 `notes/plan.md` 写分析。\n2. 候选存为 `cand/cNN.py` 并用 eval 评价。\n"
                "3. 最终设计复制为 `final.py`，用 final 终验，在 `notes/summary.md` 写明结构、PPA、裕量与路线。\n"
                "4. 在 `notes/tool_feedback.md` 写下工具问题。\n\n")
    txt = COMMANDS_FULL.format(t=t, c=c, bud=bud, TOOL=T,
                               budget_txt=BUDGET_TXT.format(E=bud["eval"], P=bud["ppa"], F=bud["final"]))
    if c.variant == "score":
        txt = txt.replace("# 判定报告：约束（值/门槛/松弛/裕量/来源）、目标（代理面积）、诊断（秒级）",
                          "# 判定（FEASIBLE/OPEN/BROKEN）、一个标量分数（≥0 即满足全部约束及裕量）与代理面积（秒级）")
    return txt


def contract_md(c: Contract) -> str:
    t = get(c.task)
    m = c.safety_margin_db
    cons = [f"1. **质量**：{c.scoring}",
            f"2. **可接受判据**：实现带来的额外误差功率不超过系统允许误差功率的 p = {c.envelope.get('impl_budget_p', 0.1):g} 倍"
            "（质量门槛按此推出，eval 报告中的 threshold 即门槛）。",
            f"3. **裕量**：搜索阶段每个约束的松弛量（指标 − 门槛）都要不小于其安全裕量（dB 类 {m:g} dB，纹波为上限的 20%），"
            "候选才是 FEASIBLE；终验时在你看不到的留出与统计复核场景上松弛量须不小于 0。",
            f"4. **时序**：目标时钟 {c.clock_ns:g} ns，最终设计必须时序收敛（wns ≥ 0）。",
            "5. **正确性**：RTL 与逐位整数模型、门级网表与整数模型都必须零失配（终验自动检查）。"]
    cons += [f"{i + 6}. {x}" for i, x in enumerate(c.extra_constraints)]
    b = c.boundaries
    bud = c.budget
    commands = _commands(c)
    return f"""# 任务契约：{t.name}

## 目标
{c.goal}

{'写一个可综合的 Verilog 设计（顶层 top）' if c.variant == 'verilog' else '用 `PRIMITIVES.md` 中的原语写一个 Python 程序 `build(g, spec)`'}，实现 `spec.json` 描述的数学功能。
**{c.objective}** 可以使用任何等价或近似的数学变换和任何运算组织方式，只要约束满足。

## 设计边界
- 可变部分：{b['var']}；冻结上下文：{b['ctx']}；质量观测点：{b['obs']}；计价范围：{b['cost']}。

## 输入类声明
{c.input_class}
设计只需对这一类输入正确；但不得依赖搜索场景的具体数据（终验使用同一类输入的其他随机实例）。

## 约束（裁判，不可修改）
{chr(10).join(cons)}

## 约定示例
`direct_start{'.v' if c.variant == 'verilog' else '.py'}` 是自动生成的直写设计。{c.convention_note}

{commands}## 边界
- 只在本目录内读写；不要查看或搜索本目录以外的任何文件（包括仓库中的其他程序、模板、源码或实验结果），
  评价只通过上面的命令进行。
- 不需要写 Verilog，编译器会自动生成。
"""


def spec_json(c: Contract) -> dict:
    t = get(c.task)
    d = {"name": t.name, "description": t.description, "params": t.params, "interface": t.interface,
         "tolerance": t.tolerance, "scoring": c.scoring, "input_class": c.input_class,
         "safety_margin_db": c.safety_margin_db, "clock_ns": c.clock_ns, "boundaries": c.boundaries}
    if not hasattr(t, "frame_outputs"):
        sc = [t.scene(i) for i in t.search_scenarios]
        d["snr_min_db"] = [round(s["snr_min_db"], 2) for s in sc]
        d["ideal_ceiling_db"] = [round(s["ceiling_db"], 2) for s in sc]
    return d


def make_workspace(c: Contract, root: Path, variant: str | None = None) -> Path:
    import dataclasses
    if variant:
        c = dataclasses.replace(c, variant=variant)
    t = get(c.task)
    root = Path(root)
    for sub in ("notes",):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "CONTRACT.md").write_text(contract_md(c))
    (root / "spec.json").write_text(json.dumps(spec_json(c), ensure_ascii=False, indent=1, default=str))
    if c.variant == "verilog":
        from .task import run_program
        r = run_program(t.direct_start(), c.task, list(t.search_scenarios)[:1], want_verilog=True, timeout=900)
        (root / "direct_start.v").write_text(r["verilog"])
    else:
        (root / "PRIMITIVES.md").write_text(primitives_doc())
        (root / "LIBRARY.md").write_text(LIBRARY)
        (root / "direct_start.py").write_text(t.direct_start())
    (root / ".contract.json").write_text(json.dumps(c.to_json(), ensure_ascii=False, indent=1, default=str))
    return root


COMMANDS_FULL = """## 命令（在本目录下执行）
```
T={TOOL}
python3 -W ignore $T eval    {t.name} <程序.py>        # 判定报告：约束（值/门槛/松弛/裕量/来源）、目标（代理面积）、诊断（秒级）
python3 -W ignore $T observe {t.name} <程序.py> o.json # 导出 g.probe 观测点的逐样点值，用来和你自己的数学模型对照
python3 -W ignore $T rtl     {t.name} <程序.py>        # 生成 Verilog 并与逐位整数模型对拍
python3 -W ignore $T ppa     {t.name} <程序.py> {c.clock_ns:g} [--vcd]   # 真实综合 + OpenSTA：面积、wns、fmax、功耗（--vcd 用门级仿真翻转率）
python3 -W ignore $T freqz   <系数.json> <倍率>          # 系数幅频响应
python3 -W ignore $T archive add {t.name} <程序.py> --action REWRITE|TUNE --claim equiv|math|approx --parent cNNN --note "改了什么"
python3 -W ignore $T archive show                       # 可行前沿、近可行前沿、调度提示
python3 -W ignore $T archive verify {t.name} cNNN       # 终验：留出场景 + 统计复核 + RTL 对拍 + PPA
```
`eval` 报告的约束来自两类来源：工具计算（场景仿真 sim、全频带扫频 sweep）与原语携带的信息（诊断中的取值范围、
局部量化噪声、资源）。诊断只给你参考，不参与判定。代理面积（area_est）只用于快速比较；最终以 `ppa` / `verify` 的真实面积为准。

## 预算
{budget_txt}

## 工作方式
1. 先在 `notes/plan.md` 写下分析：运算量、各处可用的时钟周期数、数值误差预算，比较几种运算组织。
2. 每个有意义的候选都用 `archive add` 登记：REWRITE 表示改了结构、分解或数据流，TUNE 表示只改位宽、截位、参数。
   同时声明变换类别：equiv（与父节点逐位等价，例如插流水、分时复用；框架会逐位核实，通过则质量直接继承父节点）、
   math（数学等价但定点不同，例如多相分解、换基数；框架做数值检验）、approx（近似变换）。报告里有相对父节点的变化量。
   不达标的候选也会保留在近可行前沿上，可以作为后续修改的父节点。`archive show` 会在调参停滞时提示改结构。
3. 选定的设计用 `archive verify` 终验（会用到你看不到的留出场景），通过的标为 VERIFIED。
4. 最优的 VERIFIED 设计复制为 `final.py`，在 `notes/summary.md` 写明结构、PPA、裕量、尝试过的路线。
5. **工具反馈**：在 `notes/tool_feedback.md` 写下使用原语和工具时遇到的问题：缺了什么原语或工具、哪些报错难以理解、
   哪些语义不清楚、哪些地方浪费了评价次数。请具体，这会用来改进框架。

"""


# ---------------------------------------------------------------------------
# 登记的契约
# ---------------------------------------------------------------------------
CONTRACTS: dict = {}


def _desired_peak(task_name: str) -> float:
    """链路 A 类任务：期望信号（输入端，相对满量程）在各场景上的最大峰值。"""
    import numpy as np
    t = get(task_name)
    pk = 0.0
    for i in tuple(t.search_scenarios) + tuple(t.holdout_scenarios):
        tt = np.arange(0, 20000)
        pk = max(pk, float(np.max(np.abs(np.real(t.scene(i)["clean"].at(tt))))))
    return pk


def _ddc(name):
    t = get(name)
    p = t.params
    dp = _desired_peak(name)
    strong = p.get("blocker_rel_db", 0) >= 40
    blk = ("一个窄带调制干扰，功率比期望信号高 {:g} dB，位于会折入通带的混叠带".format(p["blocker_rel_db"]) if strong else
           "覆盖全部会折入通带的混叠带的多个干扰音，总功率比期望信号高 {:g} dB".format(p["blocker_rel_db"]))
    return Contract(
        task=name,
        goal=t.description,
        input_class=(f"实数输入，{t.interface['in_bits']} 位有符号码；期望信号为中频 f_if 附近 ±passband 内的多音，"
                     f"峰值最高 {dp:.3f} 满量程；干扰为{blk}；总信号峰值不超过 0.9 满量程。"),
        scoring=("三个约束：(a) 每个场景链路输出的带内 SNR（自动搜索群时延并拟合一个复增益）≥ 理想接收机在同一输入上的 SNR − "
                 f"{t.tolerance['snr_loss_db']:.3f} dB；(b) 通带纹波（全频带扫频测得）≤ {t.tolerance['ripple_max_db']:g} dB；"
                 "(c) 折入通带的混叠抑制（全频带扫频，覆盖所有会折入通带的频率）≥ 单个干扰相对期望信号的功率 + 理想 SNR + 10 dB。"),
        safety_margin_db=0.3, clock_ns=2.0,
        convention_note="它展示了接口、位宽、增益和符号的正确约定（不保证达标，也不考虑面积）。",
        envelope={"peak": 0.9, "desired_peak": round(dp, 4), "blocker_rel_db": p["blocker_rel_db"]},
    )


def _register_ddc():
    from dspgraph.rx_spec import DEV_SPECS
    for sp in DEV_SPECS:
        CONTRACTS[sp.name] = _ddc(sp.name)
    for n in ("real_r32_narrow", "real_r64_wide", "usrpq_dev_r32_narrow", "usrpq_real_r32_narrow"):
        CONTRACTS[n] = _ddc(n)
    for n in ("usrpq_dev_r32_narrow", "usrpq_real_r32_narrow"):
        CONTRACTS[n].scoring = ("每个场景计算链路输出的带内 SNR（自动搜索群时延并拟合一个复增益），要求 SNR 不低于该场景给定的门槛"
                                "（eval 输出的 snr_min_db），且通带纹波不高于给定上限；")


def _ofdm_tx(name, qam, evm):
    sym = "任意复数" if qam == 0 else f"{qam}QAM 符号"
    cls = ("每个子载波的实部、虚部独立地在 ±√1.5 上均匀分布（单位平均功率，不限于星座点）"
           if qam == 0 else f"每个子载波独立、等概率取 {qam}QAM 星座点（单位平均功率）")
    return Contract(
        task=name,
        goal=f"每个 OFDM 符号输入 52 个子载波上的{sym}，输出 64 点 IDFT 加 16 点循环前缀，共 80 个复样点。",
        input_class=f"{cls}，乘 in_scale=0.5 后量化为 12 位有符号码；空闲槽输入为 0。",
        scoring=(f"EVM 按每符号全部 80 个输出样点（含循环前缀）与理想浮点 IDFT 的时域误差计算，"
                 f"EVM_dB = 10·log10(Σ|y−ref|²/Σ|ref|²)，要求 EVM ≤ −{evm:g} dB（eval 输出的 snr_db 即 −EVM_dB）；"
                 "逐样点精确对齐，不搜时延、不拟合增益。"),
        safety_margin_db=0.5, clock_ns=2.5,
        convention_note=("它本身达标（EVM 约 −55 dB，只剩输出舍入误差），但用 12,176 个常系数乘法，代理面积约 741 万。"
                         "它展示了接口、输入槽顺序、输出顺序（先 b[48..63] 再 b[0..63]）、缩放和 gather 用法的正确约定。"),
        extra_constraints=("**接口**：每 4 个时钟一个输入槽；输出每符号 80 个样点，由 out_valid 标记。",),
    )


for _n, _q, _e in (("ofdm_tx64_q64", 64, 35), ("ofdm_tx64_q256", 256, 42),
                   ("ofdm_tx64_q1024", 1024, 45), ("ofdm_tx64_q4096", 4096, 48), ("ofdm_tx64_gen", 0, 45)):
    CONTRACTS[_n] = _ofdm_tx(_n, _q, _e)


def stat_check(code: str, task: str, n: int = 30, start: int = 100, conf: float = 0.95) -> dict:
    """统计复核：在 n 个新随机场景（编号 start.. ，agent 不可见）上复测，给出失败概率的 Clopper–Pearson 上界。"""
    from scipy.stats import beta
    from .task import evaluate_program
    idx = list(range(start, start + n))
    fails, worst, worst_rip, bad = 0, float("inf"), 0.0, []
    for k in range(0, n, 10):
        r = evaluate_program(code, task, scenarios=idx[k:k + 10])
        if not r.get("valid"):
            return {"error": r.get("error")}
        for s in r["quality"]["scenarios"]:
            worst = min(worst, s["snr_db"] - s["snr_min_db"])
            worst_rip = max(worst_rip, s.get("ripple_db") or 0.0)
            if not s["passed"]:
                fails += 1
                why = []
                if s["snr_db"] < s["snr_min_db"]:
                    why.append(f"SNR {s['snr_db']:.2f} < {s['snr_min_db']:.2f}")
                if s.get("ripple_max_db") is not None and (s.get("ripple_db") or 0) > s["ripple_max_db"]:
                    why.append(f"纹波 {s['ripple_db']:.3f} > {s['ripple_max_db']:.3f} dB")
                bad.append({"scenario": s["scenario"], "reason": "；".join(why) or "输出无效"})
    ub = float(beta.ppf(conf, fails + 1, n - fails)) if fails < n else 1.0
    return {"scenarios": n, "failures": fails, "worst_margin_db": worst, "worst_ripple_db": worst_rip,
            "failed": bad[:10], f"fail_prob_upper_{int(conf * 100)}": ub}


def finalize(c: Contract, prog: Path, vcd: bool = True, n_stat: int = 30) -> dict:
    """终验：搜索场景 + 加固集（留出场景与统计复核，agent 不可见）+ RTL 对拍 + 目标时钟下的 PPA（仿真功耗）。"""
    import os
    os.environ.setdefault("VERIEVOLVE_STA", "/Users/chengzhy/verievolve_thirdparty/OpenSTA/build/sta")
    from .task import evaluate_program
    from .rtl import crosscheck
    from . import ppa_sta
    t = get(c.task)
    code = Path(prog).read_text()
    out = {"task": c.task, "program": str(prog), "contract": c.to_json()}
    rs = evaluate_program(code, c.task)
    rh = evaluate_program(code, c.task, scenarios=list(t.holdout_scenarios))
    def brief(r):
        if not r.get("valid"):
            return {"valid": False, "error": r.get("error")}
        q = r["quality"]
        return {"valid": True, "passed": q["passed"], "margin_db": q["snr_margin_db"],
                "per_scenario": [(s["scenario"], s["snr_db"]) for s in q["scenarios"]], "area_est": r["area"]}
    out["search"] = brief(rs)
    out["holdout"] = brief(rh)
    try:
        out["stat"] = stat_check(code, c.task, n=n_stat)
    except (KeyError, IndexError) as e:            # 场景库不支持任意编号的任务
        out["stat"] = {"error": f"scenario library does not support extra scenarios: {e}"}
    n = t.n_in() if hasattr(t, "frame_outputs") else 4000
    out["rtl"] = crosscheck(code, c.task, scenario=t.search_scenarios[0], n_in=n)
    out["ppa"] = (ppa_sta.evaluate_program_vcd(c.task, Path(prog), period_ns=c.clock_ns, fast=True) if vcd
                  else ppa_sta.evaluate_program(c.task, Path(prog), period_ns=c.clock_ns, fast=True))
    p = out["ppa"]
    checks = {
        "search_margin": bool(out["search"].get("passed") and out["search"].get("margin_db", -1) >= c.safety_margin_db),
        "holdout": bool(out["holdout"].get("passed")),
        "stat": out["stat"].get("failures", 1) == 0,
        "rtl": bool(out["rtl"].get("passed")),
        "timing": p.get("status") == "ok" and (p.get("wns_ns") if p.get("wns_ns") is not None else -1) >= 0,
    }
    out["checks"] = checks
    out["accept"] = all(checks.values())
    out["reject_reasons"] = [k for k, v in checks.items() if not v]
    return out


_register_ddc()


if __name__ == "__main__":
    import sys
    name, out = sys.argv[1], sys.argv[2]
    print(make_workspace(CONTRACTS[name], Path(out), sys.argv[3] if len(sys.argv) > 3 else None))
