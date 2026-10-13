"""通用 LLM 提议器：提示词由积木库 schema 与规格自动生成，对任何链族通用。

反馈三档（命题 3）：
  scalar   ：只给“是否合法 / 是否达标 / 代理面积”
  metrics  ：全部指标数值、门槛、逐块面积、非法原因
  verified ：metrics + 经确定性重算验证的失败原因（误差来源占比、主导量化块、
             结构不足或系数量化、饱和位置、指标裕量）
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from .core import REGISTRY, catalog

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))
import rotation_llm_client as llm_client  # noqa: E402

# 旧客户端的保守输入上限（8000）是为单算子短提示设定的；本框架提示含积木库与历史，
# 放宽到 48000（远低于提供方上下文上限），其余请求校验保持不变。
llm_client.INPUT_TOKEN_LIMIT = 48000
llm_client.OUTPUT_TOKEN_LIMIT = 24000

KEY_FILE = Path(__file__).resolve().parent.parent / ".api_key_deepseek"
MODEL = "deepseek-flash"
API_BASE = "https://api.deepseek.com"
TARIFF = {"currency": "USD", "input_per_million": 0.3, "cache_input_per_million": 0.006,
          "output_per_million": 1.2, "label": "frozen_peak_tariff_dspgraph_v1"}
FEEDBACK_MODES = ("scalar", "metrics", "verified")


def system_prompt(spec, family_text: str) -> str:
    return f"""你是数字通信硬件架构师。目标：从数学功能出发，组合积木库中的模块，给出满足系统指标、
硬件面积尽量小的完整实现方案。你可以同时选择算法结构（模块组合、抽取分配、滤波器类型与长度、
阶数、是否补偿）、数值精度（各级位宽、舍入、剪枝、增益定标）和微架构（乘法器折叠复用）。
允许任何满足指标的近似实现，不要求与理想数学完全等价。

【数学功能】
{family_text}

【规格】
{json.dumps(spec_view(spec), ensure_ascii=False, indent=1)}

【积木库】（type、输入输出类型、参数及取值范围、角色：structure/precision/micro）
{json.dumps(catalog(), ensure_ascii=False, separators=(',', ':'))}

【方案格式】只输出一个 JSON 对象：
{{"idea": "<一句话说明本次修改及理由>", "plan": {{"blocks": [{{"type": "...", "params": {{...}}}}, ...]}}}}
规则：第一个模块必须接受实数输入（real）；之后均为复数（complex）；所有 rate 参数（decim）的乘积
必须等于 {spec.r_total}；最后一个模块的 out_bits 必须等于 {spec.output_bits}；未给出的参数取默认值。
面积由逐块硬件代价估计；每次提交都会被完整验证并消耗一次评价预算。"""


def spec_view(spec) -> dict:
    return {"总抽取倍率": spec.r_total, "输出采样率(相对输入)": spec.fs_out,
            "通带边缘(相对输入率)": spec.passband, "中频(相对输入率)": spec.f_if,
            "ADC位宽": spec.input_bits, "输出位宽": spec.output_bits,
            "通带纹波上限dB": spec.ripple_max_db, "折入通带混叠抑制下限dB": spec.alias_min_db,
            "系统SNR下限dB(含阻塞混叠/纹波/量化)": spec.snr_min_db,
            "理想接收机SNR上限dB": round(spec.snr_min_db + spec.impl_loss_db, 3),
            "阻塞音相对期望信号dB": spec.blocker_rel_db}


def diagnose(q: dict, spec, area_per_block: dict) -> list[str]:
    """由确定性归因结果生成的失败/裕量说明（每句都对应可复核的数值）。"""
    out = []
    att = q.get("attribution")
    for v in q["violations"]:
        m = v["metric"]
        if m == "snr_db" and att:
            sh = att["error_share"]
            top = sorted(sh.items(), key=lambda kv: -kv[1])[:3]
            out.append(f"SNR {v['value']:.2f} < {v['limit']:.2f} dB。误差来源占比："
                       + "，".join(f"{k}={s:.0%}" for k, s in top)
                       + f"。若全部算术理想，SNR={att['snr_if_all_arithmetic_ideal_db']:.2f} dB。")
            if att["snr_if_all_arithmetic_ideal_db"] < spec.snr_min_db:
                out.append("即使算术理想也不达标：瓶颈在滤波结构（混叠/纹波/阻塞泄漏），提高位宽无效。")
            else:
                out.append(f"算术量化是瓶颈，最主要的是 {att['dominant_arithmetic_block']}。")
        if m == "alias_rejection_db" and att:
            au = att["alias_rejection_unquantized_db"]
            if au < spec.alias_min_db:
                out.append(f"混叠抑制 {v['value']:.1f} dB 不足且未量化系数时也只有 {au:.1f} dB："
                           f"结构不足（需更强滤波：更多抽头/阶数或改变抽取分配）。最差频点 "
                           f"{q['worst_alias_freq']:.5f}，各块在该频点衰减(dB)："
                           f"{json.dumps({k: round(x, 1) for k, x in att['block_attenuation_at_worst_alias_db'].items()})}")
            else:
                out.append(f"混叠抑制 {v['value']:.1f} dB 不足，但未量化系数时为 {au:.1f} dB："
                           f"系数量化导致，增加对应块 coef_bits。")
        if m == "ripple_db" and att:
            ru = att["ripple_unquantized_db"]
            out.append(f"纹波 {v['value']:.3f} dB 超限（未量化 {ru:.3f} dB）："
                       + ("结构/补偿问题（例如 CIC 下垂未补偿或通带过宽）。" if ru > spec.ripple_max_db
                          else "系数量化导致。"))
    if q.get("saturation"):
        out.append(f"出现饱和：{json.dumps(q['saturation'])}，相应块的 gain_shift 过大或位宽不足。")
    if q["passed"]:
        out.append(f"达标。裕量：SNR +{q['snr_db'] - spec.snr_min_db:.2f} dB，混叠 "
                   f"+{q['alias_rejection_db'] - spec.alias_min_db:.1f} dB，纹波余 "
                   f"{spec.ripple_max_db - q['ripple_db']:.3f} dB。面积最大的块："
                   + ", ".join(f"{k}={v:.0f}" for k, v in
                               sorted(area_per_block.items(), key=lambda kv: -kv[1])[:2]))
    return out


def feedback(r: dict, spec, mode: str) -> dict:
    if not r.get("valid"):
        if mode == "scalar":
            return {"合法": False}
        return {"合法": False, "原因": r.get("error")}
    if "quality" not in r:
        return {"合法": True, "说明": "预算耗尽，未评价"}
    q = r["quality"]
    fb = {"合法": True, "达标": q["passed"], "代理面积": round(r["area"], 1)}
    if mode == "scalar":
        return fb
    fb["指标"] = {"snr_db": round(q["snr_db"], 3), "alias_rejection_db": round(q["alias_rejection_db"], 2),
                "ripple_db": round(q["ripple_db"], 4)}
    fb["违反"] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in x.items()}
                for x in q["violations"]]
    fb["逐块面积"] = {k: round(v) for k, v in r["area_per_block"].items()}
    if mode == "verified":
        fb["验证后的原因"] = diagnose(q, spec, r["area_per_block"])
    return fb


def parse_plan(text: str):
    if not text:
        return None, None
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    s = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        obj = json.loads(s)
    except Exception:
        return None, None
    if isinstance(obj, dict) and "plan" in obj:
        return obj.get("plan"), obj.get("idea")
    if isinstance(obj, dict) and "blocks" in obj:
        return obj, None
    return None, None


def _compact(plan) -> str:
    return json.dumps(plan, ensure_ascii=False, separators=(",", ":"))


def llm_search(ev, spec, family_text: str, *, seed: int, mode: str, calls: int,
               temperature: float = 0.8, log_dir: Path | None = None, history_k: int = 6) -> dict:
    assert mode in FEEDBACK_MODES
    sysmsg = system_prompt(spec, family_text)
    hist, records = [], []
    best = None
    cost_total = 0.0
    for c in range(calls):
        user = {"已用评价": ev.used, "剩余调用": calls - c}
        if best:
            user["当前最优（达标、面积最小）"] = {"plan": best["plan"],
                                          "反馈": feedback(best, spec, mode)}
        user["最近尝试"] = hist[-history_k:]
        user["要求"] = "提出一个新的、尚未尝试过的方案，力求在达标前提下进一步降低面积。只输出 JSON。"
        messages = [{"role": "system", "content": sysmsg},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]
        t0 = time.time()
        resp = llm_client.generate(messages, model=MODEL, api_base=API_BASE, key_file=KEY_FILE,
                                   max_output_tokens=3000, timeout=180, temperature=temperature,
                                   seed=seed * 1000 + c,
                                   extra_body={"thinking": {"type": "disabled"}})
        cost = llm_client.calculate_cost(resp["usage"], TARIFF)
        cost_total += float(cost.get("estimated_cost") or 0.0)
        plan, idea = parse_plan(resp.get("text"))
        rec = {"call": c, "status": resp["status"], "seconds": time.time() - t0,
               "usage": resp["usage"], "cost": cost, "idea": idea, "plan": plan}
        if plan is None:
            rec["outcome"] = "parse_error" if resp["status"] == "ok" else resp["status"]
            hist.append({"方案": None, "反馈": {"合法": False, "原因": "输出无法解析为 JSON 方案"}})
        else:
            r = ev(plan, attribution=(mode == "verified"), tag=f"llm_{mode}")
            if r.get("cache_hit"):
                rec["outcome"] = "duplicate"
            else:
                rec["outcome"] = ("invalid" if not r.get("valid") else
                                  "passed" if r.get("quality", {}).get("passed") else "failed")
            rec["eval"] = {k: r.get(k) for k in ("hash", "area", "eval_index", "valid", "error")}
            if r.get("quality"):
                rec["eval"]["quality"] = {k: r["quality"][k] for k in
                                          ("snr_db", "alias_rejection_db", "ripple_db", "passed")}
            hist.append({"想法": idea, "方案": plan, "反馈": feedback(r, spec, mode)})
            if r.get("valid") and r.get("quality", {}).get("passed"):
                if best is None or r["area"] < best["area"]:
                    best = r
        records.append(rec)
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / f"call_{c:03d}.json").write_text(json.dumps(
                rec | {"raw_text": resp.get("text")}, ensure_ascii=False, indent=1, default=str))
        if ev.exhausted():
            break
    return {"best": best, "plan": best["plan"] if best else None, "records": records,
            "estimated_cost_usd": cost_total}


RX_FAMILY_TEXT = ("实数 ADC 输入 x[n]（采样率 1）中，中频 f_if 处有带宽 ±passband 的期望信号，"
                  "另有若干阻塞音。要求输出复基带 y[m] = (h * (x·e^{-j2π f_if n}))[m·R]，"
                  "即混频到零频、低通滤波并抽取 R 倍；h 为任意满足通带纹波与混叠抑制要求的低通。"
                  "系统 SNR 在冻结场景上相对理想基带期望信号测量。")
