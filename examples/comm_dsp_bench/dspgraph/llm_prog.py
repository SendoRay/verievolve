"""LLM 写 build 程序的搜索循环（命题 2、3）。

LLM 的输入：数学公式、规格、原语 API（由 sdf.Graph 的签名与文档自动生成）、
当前最好程序及其反馈、最近几次尝试的想法与反馈。
LLM 的输出：一句想法 + 一段完整 Python 程序 build(g, spec)。
数学变换（等价与近似）全部发生在这段程序里；系统只编译、打分、诊断。

反馈三档：
  scalar   ：是否合法、是否达标、代理面积
  metrics  ：+ 各场景 SNR/门槛/纹波、逐段面积、饱和计数、错误信息（含行号）
  verified ：+ 确定性诊断（加宽全部量化点重跑：结构受限 / 精度受限及主导段）
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
from pathlib import Path

from . import judge
from . import llm as llm_base
from .rtl_judge import evaluate_program
from .rx_spec import SPECS
from .sdf import Graph

llm_client = llm_base.llm_client
FEEDBACK_MODES = ("scalar", "metrics", "verified")
THINKING = {False: {"thinking": {"type": "disabled"}},
            True: {"thinking": {"type": "enabled"}},
            "low": {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
            "budget": {"thinking": {"type": "enabled", "budget_tokens": 8000}}}
PRIMS = ("input", "const", "counter", "add", "sub", "neg", "mul", "scale", "shift", "q", "bits",
         "mux", "lut", "reg", "delay_line", "delay", "integrate", "decimate", "mac", "scope", "probe",
         "output")


def api_doc() -> str:
    lines = []
    for name in PRIMS:
        fn = getattr(Graph, name)
        sig = str(inspect.signature(fn)).replace("self, ", "").replace("(self)", "()")
        doc = " ".join((inspect.getdoc(fn) or "").split())
        lines.append(f"- g.{name}{sig}: {doc}")
    return "\n".join(lines)


GENERAL = """定点与时序约定（编译器自动处理时钟对齐，你只写样点级数学）：
- 信号是有符号定点数：w 位总宽、f 位小数（数值 = 整数码 × 2^-f）。sig.w、sig.f 可读。
- add/sub 自动对齐小数点并扩 1 位；mul 位宽相加；位宽只在 g.q() 处裁剪。任何信号宽度不得超过 62 位。
- 每个信号属于一个速率域；decimate 进入更慢的域；不同速率域的信号不能直接组合。
- 面积代价：通用乘法器(mul、mac share>1)最贵；常数乘(scale、mac share=1)按移位加数计价，
  零系数免费；查表按存储位计价；延迟线、积分器按寄存器位计价。
- 可用模块：np(numpy)、scipy(含 scipy.signal)、math。程序在构造时可以做任意离线计算（例如设计滤波器系数）。
- 用 `with g.scope("名字"):` 给电路分段，面积与诊断会按段汇报。
- 用 g.probe("名字", i, q) 观测中间信号（不产生硬件）；在提供验证信息的反馈中会报告各观测点的
  带内 SNR、带外残留、增益与时延，可用于定位是哪一级出了问题。
- 若程序报错（Python 异常或构造规则错误），会立即把错误返回给你修复，修复也计入调用次数。

API 语义要点（只是原语用法，不是设计建议）：
- 相位/时间索引：g.counter(step, bits) 在输入速率给出 n·step mod 2^bits；g.bits 取其高位作查表地址。
- 输入速率的信号（如计数器）要在抽取后的速率使用，先对它做同样的 g.decimate(sig, r, phase)。
- g.delay_line(x, n)[j] 是 x[k-j]；g.delay(x, k) 是 x[k-k0]（k0=k）。
- g.decimate(v, r, p) 的第 m 个输出是 v[m·r+p]；同一来源、同一 r 的不同 p 可直接相加。
- 常数必须用 g.const(value, w, f) 包装，或用 g.scale/g.mac 乘常数；不能把 Python 数直接传给 add/sub/mux。
- 输出前用 g.q(x, output_bits, output_bits-1) 得到接口格式；g.shift(x, k) 乘 2^k 用于增益调整。"""


def system_prompt(spec, family_text: str) -> str:
    return f"""你是数字通信硬件架构师。任务：写一段 Python 程序 build(g, spec)，用下面的原语搭出实现给定数学功能的
硬件。在满足全部指标的前提下，使硬件面积尽可能小。你可以使用任何等价变换或近似变换（改变运算顺序、
多级分解、多相、利用对称、零系数、查表镜像、截短位宽、分时复用等），不要求与理想数学逐位相等，
只要求指标达标。

【数学功能】
{family_text}

【规格】（spec 对象的字段可在程序中直接读取）
{json.dumps(spec_view(spec), ensure_ascii=False, indent=1)}

【原语】
{api_doc()}

{GENERAL}

【评分】裁判只看输入输出：把冻结测试信号（通带内 24 个复音 + 3 个落在混叠频带的强阻塞音）送入你的
电路，对照理想基带期望信号计算 SNR（自动搜索群时延，只拟合一个复增益；混叠、通带失真、量化噪声全部算误差）
和通带纹波。每个场景都必须 SNR ≥ 门槛且纹波 ≤ 上限。输出样点数必须满足 input_rate/{spec.r_total}。

【回答格式】先一行 `IDEA: <本次的主要改动与理由>`，然后给出一个完整的 ```python 代码块（只定义 build，
可附辅助函数）。不要省略任何代码。"""


def spec_view(spec) -> dict:
    return {"r_total(总抽取)": spec.r_total, "fs_out(输出率,相对输入)": spec.fs_out,
            "passband(通带边缘,相对输入率)": spec.passband, "f_if(中频)": spec.f_if,
            "fcw(32位相位字=round(f_if*2^32))": spec.fcw,
            "input_bits": spec.input_bits, "output_bits": spec.output_bits,
            "ripple_max_db": spec.ripple_max_db,
            "各测试场景SNR门槛dB": [round(judge.snr_min(spec, i), 2) for i in judge.SEARCH_SCENARIOS],
            "理想接收机SNR上限dB": [round(judge.scene(spec, i).ceiling_db, 2) for i in judge.SEARCH_SCENARIOS], "blocker_rel_db(阻塞音相对期望信号)": spec.blocker_rel_db}


def _r(x, n=2):
    return round(float(x), n)


def feedback(r: dict, mode: str) -> dict:
    if not r.get("valid"):
        if mode == "scalar":
            return {"合法": False}
        return {"合法": False, "错误": r["error"]}
    q = r["quality"]
    fb = {"合法": True, "达标": q["passed"], "面积": _r(r["area"], 0)}
    if mode == "scalar":
        return fb
    fb["各场景"] = [{"SNR": _r(s["snr_db"]), "门槛": _r(s["snr_min_db"]), "纹波": _r(s["ripple_db"], 3),
                   "纹波上限": s["ripple_max_db"],
                   **({"拟合增益dB": _r(s["gain_db"]), "拟合群时延(输入样点)": _r(s["delay_in"], 1)}
                      if "gain_db" in s else {}),
                   **({} if s.get("valid_output", True) else
                      {"输出样点不足": f"{s['outputs']}/{s['needed']}"})}
                  for s in q["scenarios"]]
    fb["逐段面积"] = {k: _r(v, 0) for k, v in sorted(r["area_per_scope"].items(), key=lambda kv: -kv[1])}
    if q.get("saturation"):
        fb["饱和次数(按段)"] = q["saturation"]
    if r.get("notes"):
        fb["编译提示"] = r["notes"]
    if mode == "verified" and r.get("diagnosis"):
        d = r["diagnosis"]
        msg = {"structure_limited": "结构受限：把全部量化点加宽 4 位后 SNR 几乎不变，瓶颈在滤波/混叠/失真/相位分辨率等结构，加位宽无效",
               "precision_limited": "精度受限：加宽全部量化点后达标，应在主导段增加位宽",
               "both": "结构与精度都受限：加宽后有改善但仍不达标",
               "too_few_outputs": "输出样点数不足（抽取倍率或输出有效信号有误）",
               "undetermined": "诊断未能完成"}[d["kind"]]
        v = {"结论": msg, "最差场景": d["worst_scenario"]}
        k = next((k for k in d if k.startswith("snr_if_all_quantizers")), None)
        if k:
            v["全部量化点加宽4位后的SNR"] = _r(d[k])
        if d.get("snr_gain_db_if_only_this_scope_widened"):
            v["只加宽该段的SNR增益dB"] = {s: _r(x) for s, x in d["snr_gain_db_if_only_this_scope_widened"].items()}
            v["主导段"] = d.get("dominant_scope")
        fb["经验证的原因"] = v
    if mode == "verified" and r.get("probes"):
        fb["观测点(场景0)"] = {k: ({kk: (_r(vv) if isinstance(vv, float) else vv) for kk, vv in x.items()})
                           for k, x in r["probes"].items()}
    elif mode == "verified" and q["passed"]:
        worst = min(q["scenarios"], key=lambda s: s["snr_db"] - s["snr_min_db"])
        fb["经验证的原因"] = {"结论": f"达标，最小 SNR 裕量 {_r(worst['snr_db'] - worst['snr_min_db'])} dB；"
                                    f"面积最大的段是 {max(r['area_per_scope'], key=r['area_per_scope'].get)}"}
    return fb


def parse(text: str):
    if not text:
        return None, None
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    code = max(m, key=len) if m else None
    idea = re.search(r"IDEA:\s*(.*)", text)
    return code, (idea.group(1).strip()[:300] if idea else None)


def search(spec_name: str, family_text: str, init_code: str, *, mode: str, calls: int, seed: int,
           log_dir: Path, temperature: float = 0.8, history_k: int = 5, thinking=False,
           model: str | None = None, max_repairs: int = 2) -> dict:
    assert mode in FEEDBACK_MODES
    spec = SPECS[spec_name]
    sysmsg = system_prompt(spec, family_text)
    log_dir.mkdir(parents=True, exist_ok=True)
    seen: dict = {}
    hist, recs = [], []
    t_start = time.time()

    def judge(code, tag):
        h = hashlib.sha256(code.encode()).hexdigest()
        if h in seen:
            return seen[h] | {"duplicate": True}
        r = evaluate_program(code, spec_name, diagnose=(mode == "verified"))
        r["hash"] = h
        seen[h] = r
        return r

    r0 = judge(init_code, "init")
    best = (init_code, r0) if r0.get("valid") and r0["quality"]["passed"] else None
    last = (init_code, r0)
    hist.append({"想法": "起点：照公式直写（整周期查表混频 + 单级长低通 + 抽取）", "反馈": feedback(r0, mode)})
    cost = 0.0
    c = 0
    while c < calls:
        user = {}
        if best:
            user["当前最优程序(达标且面积最小)"] = {"code": best[0], "反馈": feedback(best[1], mode)}
        else:
            user["尚无达标程序"] = True
        if not best or last[0] != best[0]:
            user["上一次尝试的程序"] = {"code": last[0], "反馈": feedback(last[1], mode)}
        user["最近尝试(想法与反馈)"] = hist[-history_k:]
        user["剩余调用次数"] = calls - c
        user["要求"] = ("在保持达标的前提下进一步减小面积（若尚未达标，先修改使其达标）。"
                      "可以基于当前最优程序修改，也可以换成完全不同的结构；给出一个与以往不同的完整程序。")
        messages = [{"role": "system", "content": sysmsg},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]
        repairs = 0
        while True:
            t0 = time.time()
            resp = llm_client.generate(messages, model=model or llm_base.MODEL, api_base=llm_base.API_BASE,
                                       key_file=llm_base.KEY_FILE, max_output_tokens=8000, timeout=600,
                                       temperature=temperature, seed=seed * 1000 + c,
                                       extra_body=THINKING[thinking])
            cst = llm_client.calculate_cost(resp["usage"], llm_base.TARIFF)
            cost += float(cst.get("estimated_cost") or 0.0)
            code, idea = parse(resp.get("text"))
            rec = {"call": c, "repair": repairs, "provider_status": resp["status"],
                   "llm_seconds": time.time() - t0, "usage": resp["usage"], "cost": cst, "idea": idea}
            c += 1
            r = None
            if code is None:
                rec["outcome"] = "no_code" if resp["status"] == "ok" else resp["status"]
                err = ("回答中没有完整的 python 代码块" if resp["status"] != "truncated"
                       else "回答被截断（程序过长）")
            else:
                r = judge(code, f"call{c}")
                rec["outcome"] = ("duplicate" if r.get("duplicate") else "invalid" if not r.get("valid")
                                  else "passed" if r["quality"]["passed"] else "failed")
                rec.update(hash=r["hash"], area=r.get("area"), error=r.get("error"))
                if r.get("valid"):
                    rec.update(snr_margin_db=r["quality"]["snr_margin_db"], ripple_db=r["quality"]["ripple_db"],
                               diagnosis_kind=(r.get("diagnosis") or {}).get("kind"),
                               primitives=r["stats"]["primitives"])
                (log_dir / f"call_{c - 1:03d}.py").write_text(code)
                err = None if r.get("valid") else json.dumps(r["error"], ensure_ascii=False)
            rec["best_area_so_far"] = best[1]["area"] if best else None
            recs.append(rec)
            (log_dir / f"call_{c - 1:03d}.json").write_text(json.dumps(rec | {"raw_text": resp.get("text")},
                                                                       ensure_ascii=False, indent=1, default=str))
            if err is not None and repairs < max_repairs and c < calls and resp["status"] in ("ok", "truncated"):
                # 编译修复回合：错误当场返回（所有反馈档位相同）
                messages = messages + [{"role": "assistant", "content": resp.get("text") or ""},
                                       {"role": "user", "content": f"程序未能构造：{err}。请修复并重新给出完整程序"
                                                                   f"（先一行 IDEA，再一个完整 python 代码块）。"}]
                repairs += 1
                continue
            if r is None:
                hist.append({"想法": idea, "反馈": {"合法": False, "错误": err}})
            else:
                hist.append({"想法": idea, "反馈": feedback(r, mode)})
                last = (code, r)
                if r.get("valid") and r["quality"]["passed"] and (best is None or r["area"] < best[1]["area"]):
                    best = (code, r)
                    recs[-1]["best_area_so_far"] = r["area"]
            break
    out = {"spec": spec_name, "mode": mode, "seed": seed, "calls": calls, "records": recs,
           "init": {"area": r0.get("area"), "passed": bool(r0.get("valid") and r0["quality"]["passed"])},
           "best_area": best[1]["area"] if best else None,
           "best_hash": best[1]["hash"] if best else None,
           "estimated_cost_usd": cost, "seconds": time.time() - t_start}
    if best:
        (log_dir / "best.py").write_text(best[0])
    (log_dir / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return out
