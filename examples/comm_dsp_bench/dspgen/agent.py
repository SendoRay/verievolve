"""结构生成 agent：LLM 多轮调用工具（eval / probe / freqz），按数值反馈修改程序，直到达标后再继续减面积。

与链路无关：提示词由共用工具 agent_tool.py 的 spec / api / direct 输出拼成（规格、门槛与理想上限、干扰说明、原语与
定点约定、自动生成的直写程序作为“约定示例”），与 (d) Claude agent 看到的信息和工具逐字一致。
不出现任何具体结构名，不提供专家模板。另含“裸对话”用法（同一提示词去掉工具说明，一次写完）。

python -m dspgen.agent --task dev_r32_narrow --mode agent --k 3 --turns 12 --out DIR
python -m dspgen.agent --task dev_r32_narrow --mode bare  --k 3 --out DIR
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from dspgraph import llm
from .task import get

MODEL = "deepseek-v4-pro"
MARGIN = 0.3
MAX_OUT = 8000
API_RETRIES = 4


TOOL = str(Path(__file__).resolve().parent / "agent_tool.py")   # 与 (d) Claude agent 共用的同一工具


def tool(*args, timeout=600) -> str:
    try:
        pr = subprocess.run([sys.executable, "-I", "-W", "ignore", TOOL, *map(str, args)], capture_output=True,
                            text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"tool timeout {timeout}s"})
    out = pr.stdout.strip()
    if pr.returncode or not out:
        out += "\n" + pr.stderr.strip()[-1500:]
    return out


def base_prompt(t) -> str:
    return f"""你是数字通信硬件架构师。任务：用下面的原语写一个 Python 程序 build(g, spec)，实现规格描述的数学功能。
在满足全部指标的前提下，使硬件面积（area_um2_est）尽可能小。可以使用任何等价或近似的数学变换，只要指标达标。

【约束（裁判，不可修改）】
- 每个搜索场景：SNR ≥ snr_min_db（约为理想接收机上限 − 允许的实现损失），通带纹波 ≤ ripple_max_db。
- 测试信号含覆盖所有混叠频带的强阻塞；裁判自动搜索群时延、拟合一个复增益。
- 为了泛化，请保留至少 {MARGIN} dB 的 SNR 裕量（snr_margin_db ≥ {MARGIN}）。
- 程序中 spec 是对象，可读字段恰好是：{", ".join("spec." + k for k in vars(t.spec()))}
  （注意：接口位宽是 spec.input_bits / spec.output_bits，不是下面 interface 里的 in_bits / out_bits）。

【规格】
{tool("spec", t.name)}

【原语与约定】
{tool("api")}

【约定示例】下面是自动生成的直写设计，本身达标但面积很大。它展示了接口、位宽、增益和符号的正确约定。
```python
{tool("direct", t.name)}
```
"""


TOOLS = """【工具】你每一轮回答的最后一行必须是一个动作：ACTION: {...}（JSON）。可用动作：
- {"tool": "eval"}：评价当前程序：各搜索场景的 SNR 裕量、纹波、饱和、面积及逐段面积（g.scope 分段）。
- {"tool": "probe"}：对当前程序做单音扫描诊断：通带幅频（gain_db、pass_spread_db）、I/Q 符号（image_db）、混叠抑制（alias_rej_db）。
- {"tool": "freqz", "snippet": "<python 代码，可用 np、scipy、math，必须定义系数数组 h>", "rate": <该级相对输入的抽取倍率>}：
  系数的幅频响应摘要。
- {"tool": "submit"}：结束（系统取你所有 eval 中达标且裕量 ≥ 0.3 dB、面积最小的版本）。
回答中如果包含一个完整的 ```python 代码块，它就成为“当前程序”，动作作用于它；不包含代码块则沿用上一版。
每一轮先写简短分析（不超过 300 字）：上一轮数字说明了什么、这一轮改什么。工具调用次数有限：先保证达标，再减面积。"""


REMIND = ("\n下一步：先写简短分析；如要修改程序，给出含 def build 的完整 ```python 代码块（片段会被忽略）；"
          "回答最后一行写动作，例如 ACTION: {\"tool\": \"eval\"} 或 {\"tool\": \"probe\"} 或 "
          "{\"tool\": \"freqz\", \"snippet\": \"h = ...\", \"rate\": 1} 或 {\"tool\": \"submit\"}。")


def _parse(text):
    if not text:
        return None, None
    m = [c for c in re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S) if "def build(" in c]
    code = max(m, key=len) if m else None   # 只接受完整程序（含 def build）；片段不替换当前程序
    act = None
    a = re.findall(r"ACTION:\s*(\{.*\})", text)
    if a:
        try:
            act = json.loads(a[-1])
        except Exception:
            act = {"tool": "bad_json", "raw": a[-1][:200]}
    return code, act


def _gen(msgs, seed, max_out=MAX_OUT):
    llm.llm_client.INPUT_TOKEN_LIMIT = 400000
    llm.llm_client.OUTPUT_TOKEN_LIMIT = 64000
    for k in range(API_RETRIES + 1):
        r = llm.llm_client.generate(msgs, model=MODEL, api_base=llm.API_BASE, key_file=llm.KEY_FILE,
                                    max_output_tokens=max_out, timeout=900, temperature=0.7, seed=seed,
                                    extra_body={"thinking": {"type": "disabled"}})
        if r["status"] in ("ok", "truncated", "incomplete"):
            return r, k
        time.sleep(5 * (k + 1))
    return r, API_RETRIES + 1


def _trim(msgs):
    """较早的回答里只保留分析与动作，代码块替换为占位（最新一版程序总在最后的回答里或下面的提示里）。"""
    out = []
    pat = r"```(?:python)?\s*\n.*?```"
    keep = max((i for i, m in enumerate(msgs) if m["role"] == "assistant" and re.search(pat, m["content"], re.S)),
               default=-1)          # 保留最近一个含代码块的回答（即当前程序）
    for i, m in enumerate(msgs):
        if m["role"] == "assistant" and i != keep:
            m = dict(m, content=re.sub(r"```(?:python)?\s*\n.*?```", "```python\n# （较早版本，已省略）\n```",
                                       m["content"], flags=re.S))
        out.append(m)
    return out


def _eval_json(text):
    try:
        return json.loads(text[text.index("{"):])
    except Exception:
        return None


def _freqz(act, hfile: Path) -> str:
    """在独立进程中执行片段得到系数 h，写成 JSON，再调用共用工具的 freqz。"""
    code = ("import json, math, sys\nimport numpy as np\nimport scipy, scipy.signal\n" + act.get("snippet", "") +
            "\njson.dump([float(v) for v in np.asarray(h).ravel()], open(sys.argv[1], 'w'))\n")
    try:
        pr = subprocess.run([sys.executable, "-I", "-c", code, str(hfile)], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "freqz 片段超时"
    if pr.returncode:
        return "freqz 片段出错：" + pr.stderr.strip()[-800:]
    return tool("freqz", hfile, act.get("rate", 1))


def agent_run(task_name: str, variant: int, turns: int, out_dir: Path, seed: int = 0) -> dict:
    t = get(task_name)
    sysmsg = base_prompt(t) + "\n" + TOOLS
    user = (f"开始。这是 {variant + 1} 号独立尝试。先想清楚整体运算组织与面积预算，再写第一版程序并评价。")
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]
    cur, best, log = None, None, []
    t0 = time.time()
    used = 0
    while used < turns:
        r, retries = _gen(_trim(msgs), seed * 1000 + variant * 100 + used)
        text = r.get("text") or ""
        code, act = _parse(text)
        partial = bool(re.search(r"```(?:python)?\s*\n", text)) and code is None
        if code:
            cur = code
        rec = {"turn": used, "status": r["status"], "api_retries": retries, "usage": r["usage"],
               "action": act, "new_code": bool(code)}
        if r["status"] not in ("ok", "truncated", "incomplete"):
            rec["note"] = "api failed after retries"
            log.append(rec)
            break
        msgs.append({"role": "assistant", "content": text})
        if act and act.get("tool") == "submit":
            log.append(rec)
            break
        used += 1
        tname = (act or {}).get("tool")
        if cur is None and tname != "freqz":
            res_text = "还没有程序：请给出完整的 ```python 代码块"
        elif tname == "freqz":
            res_text = _freqz(act, out_dir / f"v{variant}_t{used}_h.json")
        else:
            if tname not in ("eval", "probe"):
                tname = "eval"
            vfile = out_dir / f"v{variant}_t{used}.py"
            vfile.write_text(cur)
            res_text = tool(tname, task_name, vfile)
            if (act or {}).get("tool") not in ("eval", "probe"):
                res_text = "（未识别到有效动作，已按 eval 执行）\n" + res_text
            if tname == "eval":
                ev = _eval_json(res_text)
                if ev is not None:
                    rec["eval"] = {"passed": ev.get("passed"), "margin": ev.get("snr_margin_db"),
                                   "area": ev.get("area_um2_est"), "path": str(vfile)}
                    if ev.get("passed") and ev.get("snr_margin_db", -1) >= MARGIN and \
                            (best is None or ev["area_um2_est"] < best["area"]):
                        best = {"area": ev["area_um2_est"], "margin": ev["snr_margin_db"], "path": str(vfile), "turn": used}
        if partial:
            res_text = "（注意：你给出的代码块不含 def build，不是完整程序，已忽略；以上结果针对上一版完整程序）\n" + res_text
        rec["tool"] = tname
        log.append(rec)
        status = f"（已用 {used}/{turns} 次工具调用；目前达标且余量≥{MARGIN} dB 的最小面积：" + \
                 (f"{best['area']:.0f}" if best else "无") + "）"
        msgs.append({"role": "user", "content": "工具结果：\n" + res_text[:8000] + "\n" + status + REMIND})
    rec = {"task": task_name, "variant": variant, "mode": "agent", "turns_used": used, "seconds": time.time() - t0,
           "best": best, "log": log}
    (out_dir / f"v{variant}_transcript.json").write_text(json.dumps(msgs, ensure_ascii=False, indent=1))
    return rec


def bare_run(task_name: str, variant: int, out_dir: Path, seed: int = 0) -> dict:
    t = get(task_name)
    sysmsg = base_prompt(t) + "\n【回答格式】先写“分析”一节（不超过 800 字），然后给出一个完整的 ```python 代码块。只有这一次机会。"
    msgs = [{"role": "system", "content": sysmsg},
            {"role": "user", "content": f"这是 {variant + 1} 号独立尝试。请给出你认为面积最小且达标的设计。"}]
    t0 = time.time()
    r, retries = _gen(msgs, seed * 1000 + variant * 100, max_out=16000)
    code, _ = _parse(r.get("text"))
    rec = {"task": task_name, "variant": variant, "mode": "bare", "status": r["status"], "api_retries": retries,
           "usage": r["usage"], "seconds": time.time() - t0, "best": None}
    if code:
        f = out_dir / f"v{variant}.py"
        f.write_text(code)
        res_text = tool("eval", task_name, f)
        ev = _eval_json(res_text) or {}
        rec["eval"] = {"passed": ev.get("passed"), "margin": ev.get("snr_margin_db"), "area": ev.get("area_um2_est"),
                       "error": ev.get("error") if "passed" not in ev else None}
        if ev.get("passed") and ev.get("snr_margin_db", -1) >= MARGIN:
            rec["best"] = {"area": ev["area_um2_est"], "margin": ev["snr_margin_db"], "path": str(f)}
    (out_dir / f"v{variant}_transcript.json").write_text(json.dumps(msgs + [{"role": "assistant", "content": r.get("text")}],
                                                                   ensure_ascii=False, indent=1))
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--mode", choices=["agent", "bare"], required=True)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    d = a.out / a.mode / a.task
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    import os
    for v in range(a.k):
        if os.environ.get("EH_BUDGET_START"):       # 预算守卫：累计花费超过上限则不再开始新的尝试
            from dspgraph.run_oe_grid import KEY
            import urllib.request
            req = urllib.request.Request("https://api.deepseek.com/user/balance",
                                         headers={"Authorization": "Bearer " + KEY.read_text().strip()})
            bal = None
            for _ in range(6):
                try:
                    bal = float(json.load(urllib.request.urlopen(req, timeout=30))["balance_infos"][0]["total_balance"])
                    break
                except Exception:
                    time.sleep(20)
            if bal is None:
                print("BALANCE UNAVAILABLE, stop before variant", v, flush=True)
                break
            if float(os.environ["EH_BUDGET_START"]) - bal > float(os.environ.get("EH_BUDGET_LIMIT", "20")):
                print("BUDGET STOP before variant", v, flush=True)
                break
        r = agent_run(a.task, v, a.turns, d, a.seed) if a.mode == "agent" else bare_run(a.task, v, d, a.seed)
        rows.append(r)
        (d / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        print(a.task, a.mode, v, r.get("best"), r.get("turns_used"), round(r["seconds"]), flush=True)
