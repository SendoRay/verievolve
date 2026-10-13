"""初始化：LLM 只看规格（公式、接口、指标、容差、原语说明），写出 K 个参数化结构程序。
提示词不出现任何具体结构名，也不提供专家模板。编译失败时把错误返回，允许修复若干轮。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from dspgraph import llm
from .prompt import api_doc, interface_text
from .space_tune import read_space
from .task import evaluate_program, get

GEN_RULES = """【任务】请先充分思考：在满足指标的前提下，什么样的运算组织能使硬件面积最小。然后写出一个**参数化**的完整程序：
- 程序开头用字面量写出 SPACE = {参数名: [允许取值, ...]}（每个参数 3–12 个候选值，按大小排序），
  以及 P = {参数名: 当前取值}（必须属于 SPACE）。参数可以包括结构参数（例如级数、各级倍率、滤波器长度、阶数）、
  数值精度（各处位宽、系数位数）和复用因子。build(g, spec) 只通过 P 读取这些参数。
- 系统会在你声明的 SPACE 内自动做参数搜索，所以请把你不确定的选择都做成参数，并给出合理范围；
  但程序结构本身（运算如何组织）要由你决定并写清楚。
- 可以在构造时用 numpy/scipy 做任意离线计算（例如设计滤波器系数）。
【回答格式】先写“分析”一节（不超过 800 字）：估算所需的抑制量与噪声预算、各处运算速率，比较两三种可能的运算组织并说明选择理由；
然后一行 IDEA: <结构思路>，最后给出一个完整的 ```python 代码块。"""


def gen_prompt(t, variant: int, k_total: int) -> list:
    sc = [t.scene(i) for i in t.search_scenarios]
    view = dict(t.params)
    view.update({"各测试场景SNR门槛dB": [round(s["snr_min_db"], 2) for s in sc],
                 "纹波上限dB": t.tolerance["ripple_max_db"]})
    sysmsg = f"""你是数字通信硬件架构师。目标：用下面的原语写出实现给定数学功能的硬件程序 build(g, spec)，
在满足全部指标的前提下使硬件面积尽可能小。可以使用任何等价或近似变换。

【数学功能】
{t.description}

【接口】{interface_text(t)}

【规格参数】（程序中以 spec.<名字> 读取；另有 spec.input_bits、spec.output_bits）
{json.dumps(view, ensure_ascii=False, indent=1)}

【原语】
{api_doc()}

【评分】冻结测试信号送入电路，对照理想参考计算 SNR（自动搜索群时延、只拟合一个复增益；失真、混叠、量化噪声都算误差）
与通带纹波；每个场景都必须 SNR ≥ 门槛且纹波 ≤ 上限。面积按所用原语的硬件代价计算（乘法器最贵、常数乘按移位加计价、
寄存器按位计价、查找表按存储位计价）。

{GEN_RULES}"""
    user = (f"这是 {k_total} 个独立方案中的第 {variant + 1} 个。请给出你认为面积最小的设计"
            + ("；与常见做法相比，可以尝试不同的运算组织。" if variant > 0 else "。"))
    return [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]


def parse(text):
    if not text:
        return None, None
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    idea = re.search(r"IDEA:\s*(.*)", text)
    return (max(m, key=len) if m else None), (idea.group(1).strip()[:300] if idea else None)


def generate(task_name: str, k: int, repairs: int, model: str, thinking: bool, out_dir: Path, seed: int = 0) -> list:
    t = get(task_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    llm.llm_client.OUTPUT_TOKEN_LIMIT = 64000
    results = []
    for v in range(k):
        msgs = gen_prompt(t, v, k)
        rec = {"variant": v, "calls": []}
        code = None
        for attempt in range(repairs + 1):
            t0 = time.time()
            r = llm.llm_client.generate(msgs, model=model, api_base=llm.API_BASE, key_file=llm.KEY_FILE,
                                        max_output_tokens=40000 if thinking else 16000, timeout=1800,
                                        temperature=0.8, seed=seed * 100 + v * 10 + attempt,
                                        extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}})
            code, idea = parse(r.get("text"))
            call = {"attempt": attempt, "status": r["status"], "seconds": time.time() - t0, "usage": r["usage"],
                    "idea": idea}
            err = None
            if code is None:
                err = "回答中没有完整的 python 代码块"
            elif read_space(code) is None:
                err = "程序开头必须用字面量写出 SPACE 与 P 两个字典（P 的键都在 SPACE 中）"
            else:
                e = evaluate_program(code, task_name)
                call["eval"] = {"valid": e.get("valid"), "error": e.get("error"),
                                "passed": e.get("quality", {}).get("passed"),
                                "margin": e.get("quality", {}).get("snr_margin_db"), "area": e.get("area")}
                if not e.get("valid"):
                    err = json.dumps(e["error"], ensure_ascii=False)
            call["error"] = err
            rec["calls"].append(call)
            if code:
                (out_dir / f"v{v}_a{attempt}.py").write_text(code)
            if err is None:
                break
            msgs = msgs + [{"role": "assistant", "content": r.get("text") or ""},
                           {"role": "user", "content": f"程序未能通过：{err}。请修复并给出完整程序（IDEA 一行 + 完整 python 代码块）。"}]
        rec["compiled"] = rec["calls"][-1]["error"] is None
        rec["final_code_path"] = str(out_dir / f"v{v}_a{len(rec['calls']) - 1}.py") if rec["compiled"] else None
        results.append(rec)
        (out_dir / "structgen.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    return results
