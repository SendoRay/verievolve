"""方法二的唯一入口（讨论归纳 §5.0）：verdict(程序, 任务, 层级) → 报告。报告原样反馈给 agent。

指标来源：原语携带的信息（记录的类型化数据流图，静态推导）或工具计算（仿真、扫频、RTL 对拍、综合、STA）。
指标角色：约束（决定合格）、目标（面积、功耗）、诊断（其余全部）。

可接受判据（一条规则）：实现带来的额外误差功率不超过系统允许误差功率的 p 倍（契约给定，默认 0.1）。
  接收链：SNR ≥ SNR_ideal − 10·log10(1+p)（任务门槛 snr_min_db 按此设定）；
  发射链：EVM ≤ EVM_std + 10·log10 p；
  混叠抑制（链路 A 扫频）：rej ≥ 单个干扰相对期望信号的功率 + SNR_ideal + 10·log10(1/p)。
裕量与判定（一条规则）：slack = 指标 − 门槛（越大越好）。搜索阶段 FEASIBLE 要求每个约束 min slack ≥ 裕量 m；
  终验 VERIFIED 要求留出与统计复核场景上 min slack ≥ 0 且硬约束（RTL 一致、时序收敛）满足。
  缺口 v = Σ max(0, m − min slack) / 单位尺度。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

DB_MARGIN = 0.3
RIPPLE_MARGIN_FRAC = 0.2


def _contract(task_name):
    from .contract import CONTRACTS
    return CONTRACTS.get(task_name)


def _p(c):
    return (c.envelope or {}).get("impl_budget_p", 0.1) if c is not None else 0.1


def _margins(c):
    m = getattr(c, "margins", None) or {}
    return m.get("db", c.safety_margin_db if c is not None else DB_MARGIN), m.get("ripple_frac", RIPPLE_MARGIN_FRAC)


def quality_constraints(rows, c, source, ripple: bool = True) -> list:
    """由逐场景打分得到质量约束（SNR/EVM 与纹波）。rows：task.score 的输出列表。
    ripple=False：纹波改由无噪声扫频给出（线性响应的性质），场景中的纹波估计只作诊断。"""
    mdb, mrip = _margins(c)
    out = []
    w = min(rows, key=lambda r: r["snr_db"] - r["snr_min_db"])
    out.append({"name": "snr", "source": source, "unit": "dB", "value": w["snr_db"], "threshold": w["snr_min_db"],
                "slack": w["snr_db"] - w["snr_min_db"], "margin": mdb, "scale": 1.0, "worst_scenario": w["scenario"]})
    rip = [r for r in rows if r.get("ripple_max_db") is not None] if ripple else []
    if rip:
        w = max(rip, key=lambda r: r["ripple_db"] - r["ripple_max_db"])
        out.append({"name": "ripple", "source": source, "unit": "dB", "value": w["ripple_db"],
                    "threshold": w["ripple_max_db"], "slack": w["ripple_max_db"] - w["ripple_db"],
                    "margin": mrip * w["ripple_max_db"], "scale": w["ripple_max_db"], "worst_scenario": w["scenario"]})
    return out


def alias_requirement(task, c) -> float | None:
    """rej ≥ 单个干扰相对期望信号的功率 + SNR_ideal + 10·log10(1/p)，取搜索场景中最严的一个。"""
    p = task.params
    if "blocker_rel_db" not in p or "fcw" not in p or getattr(task, "base", None):   # 反向规格任务以 USRP 为门槛
        return None
    req = -1e9
    for i in task.search_scenarios:
        sc = task.scene(i)
        n_blk = max(1, len(sc.get("blocker_offsets", ())))
        dense = task.stimulus == "tones_with_dense_blockers"
        per = p["blocker_rel_db"] + (10 * math.log10(3.0) - 10 * math.log10(n_blk) if dense else 0.0)
        req = max(req, per + sc["ceiling_db"] + 10 * math.log10(1.0 / _p(c)))
    return req


def static_diagnostics(code, task_name) -> dict:
    """由原语携带的信息推导：取值范围（区间分析）、局部量化噪声、资源。"""
    from .record import build, export
    from .symbolic import ranges
    g, _, _ = build(code, task_name)
    ex = export(g)
    noise = []
    for n in g.rec_nodes:
        if n["op"] != "q":
            continue
        y = g.rec_sigs[n["out"]["sig"]]
        a = g.rec_sigs[n["args"][0]["sig"]] if isinstance(n["args"][0], dict) else None
        if a is None or a.lin is None or a.F <= y.F:
            continue                       # 没有丢弃精度的重量化点不产生量化噪声
        v = np.asarray(y.v, dtype=np.float64)[:1] / 2.0 ** y.F
        rms2 = float(np.mean(v ** 2))
        lsb = 2.0 ** (-y.F)
        noise.append({"scope": n["scope"], "node": n["id"], "w": y.w, "f": y.f,
                      "local_sqnr_db": round(10 * math.log10(max(rms2, 1e-300) / (lsb * lsb / 12)), 2)})
    noise.sort(key=lambda r: r["local_sqnr_db"])
    if getattr(g, "rtl_numerics", False):        # 时钟域设计构造时的数值是占位，局部量化噪声无意义
        noise = [{"note": "含时钟域：数值来自 RTL 仿真，构造时无真实取值，不报告局部量化噪声"}]
    r = ranges(code, task_name)
    return {"ir": {"nodes": ex["summary"]["nodes"], "ops": ex["summary"]["ops"], "semantic_hash": ex["semantic_hash"],
                   "clock_domain": ex["summary"]["clock_domain"]},
            "local_quant_noise_weakest": noise[:8],
            "ranges": {"summary": r["summary"],
                       "data_path_flags": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()
                                            if k in ("scope", "op", "ovf", "status", "headroom_bits")}
                                           for f in r["flags"] if f["status"] != "control_modular"][:12],
                       "note": r["note"]}}


def _gap(cons):
    return sum(max(0.0, k["margin"] - k["slack"]) / k["scale"] for k in cons)


def search(code: str, task_name: str, sweep: bool = True) -> dict:
    """搜索阶段：搜索场景上的质量约束 + 链路 A 的扫频约束 + 静态诊断。"""
    from .task import evaluate_program, get
    t, c = get(task_name), _contract(task_name)
    r = evaluate_program(code, task_name)
    if not r.get("valid"):
        return {"verdict": "BROKEN", "error": r.get("error")}
    q = r["quality"]
    req = alias_requirement(t, c) if sweep else None
    cons = quality_constraints(q["scenarios"], c, "sim:search", ripple=req is None)
    diag = {"area_per_scope": r["area_per_scope"], "saturation": q.get("saturation"),
            "per_scenario": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()
                              if k in ("scenario", "snr_db", "snr_min_db", "ripple_db", "max_abs_err_lsb",
                                       "worst_bins", "outputs", "needed", "shift_diagnosis")} for s in q["scenarios"]]}
    if req is not None:
        from .symbolic import sweep as do_sweep
        env = (c.envelope if c is not None else {}) or {}
        sw = do_sweep(code, task_name, nf=128, amp_pass=env.get("desired_peak", 0.05), amp_stop=env.get("peak", 0.9))
        cons.append({"name": "alias_rejection", "source": "sweep", "unit": "dB",
                     "value": sw["worst_alias_rejection_db"], "threshold": req,
                     "slack": sw["worst_alias_rejection_db"] - req, "margin": 1.0, "scale": 1.0,
                     "worst_scenario": f"f_in={sw['worst_alias_input_freq']:.5f}",
                     **({"note": "测得的抑制接近测量噪声底：瓶颈是实现的噪声或杂散（量化、NCO/CORDIC 误差），不是滤波器漏过"}
                        if sw.get("floor_limited") else {})})
        rmax = t.tolerance.get("ripple_max_db")
        if rmax is not None:
            _, mrip = _margins(c)
            cons.append({"name": "ripple", "source": "sweep", "unit": "dB", "value": sw["passband_ripple_db"],
                         "threshold": rmax, "slack": rmax - sw["passband_ripple_db"], "margin": mrip * rmax,
                         "scale": rmax, "worst_scenario": "passband sweep"})
        diag["sweep"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in sw.items()
                         if k in ("worst_leak_any_output_freq_db", "stopband_points", "measurement_floor_db",
                                  "floor_limited")}
    try:
        diag.update(static_diagnostics(code, task_name))
    except Exception as e:                       # 诊断失败不影响判定
        diag["static_error"] = f"{type(e).__name__}: {e}"
    for k in cons:
        k["ok"] = k["slack"] >= k["margin"]
    v = _gap(cons)
    return {"verdict": "FEASIBLE" if all(k["ok"] for k in cons) else "OPEN", "v": round(v, 4),
            "constraints": [_round(k) for k in cons], "objectives": {"area_est": round(float(r["area"]), 1)},
            "diagnostics": diag}


def hidden(code: str, task_name: str, has_sweep: bool, n_stat: int = 30) -> dict:
    """L2：留出场景（加固集）与统计复核场景上的质量约束，要求 min slack ≥ 0。"""
    from scipy.stats import beta
    from .task import evaluate_program, get
    t, c = get(task_name), _contract(task_name)
    sets = {"holdout": list(t.holdout_scenarios), "stat": list(range(100, 100 + n_stat))}
    rows = {}
    for name, idx in sets.items():
        rows[name] = []
        try:
            for k in range(0, len(idx), 10):
                rows[name] += evaluate_program(code, task_name, scenarios=idx[k:k + 10])["quality"]["scenarios"]
        except (KeyError, IndexError):          # 场景库不支持任意编号
            rows.pop(name)
    allr = [r for v in rows.values() for r in v]
    cons = quality_constraints(allr, c, "sim:" + "+".join(rows), ripple=not has_sweep)
    for k in cons:
        k["ok"] = k["slack"] >= 0
    fails = sum(r["snr_db"] < r["snr_min_db"] or (not has_sweep and r.get("ripple_max_db") is not None
                                                 and r["ripple_db"] > r["ripple_max_db"]) for r in allr)
    return {"ok": all(k["ok"] for k in cons), "constraints": [_round(k) for k in cons],
            "per_set_min_snr_slack": {n: round(min(r["snr_db"] - r["snr_min_db"] for r in v), 4) for n, v in rows.items()},
            "scenarios": len(allr), "failures": fails,
            "fail_prob_upper_95": float(beta.ppf(0.95, fails + 1, len(allr) - fails)) if fails < len(allr) else 1.0}


def final(code: str, task_name: str, prog_path: Path, n_stat: int = 30) -> dict:
    """终验：L1（搜索数据集）+ L2（隐藏数据集）+ L3（RTL 对拍、门级对拍、目标时钟下 PPA 与仿真功耗）。"""
    from .task import get
    from .rtl import crosscheck
    from . import ppa_sta
    t, c = get(task_name), _contract(task_name)
    rep = search(code, task_name)
    if rep["verdict"] == "BROKEN":
        return rep
    sweep_cons = [k for k in rep["constraints"] if k["source"] == "sweep"]
    h = hidden(code, task_name, bool(sweep_cons), n_stat)
    clk = c.clock_ns if c is not None else 2.0
    n = t.n_in() if hasattr(t, "frame_outputs") else min(16000, t.n_in())
    rtl = crosscheck(code, task_name, scenario=t.search_scenarios[0], n_in=n)
    p = ppa_sta.evaluate_program_vcd(task_name, Path(prog_path), period_ns=clk, fast=True, n_in=n)
    gate = p.get("gate_vs_model") or {}
    hard = [{"name": "rtl_equiv", "source": "rtl", "ok": bool(rtl.get("passed")),
             "detail": {k: rtl.get(k) for k in ("mismatches", "compared")}},
            {"name": "gate_equiv", "source": "gate-sim", "ok": gate.get("mismatches") == 0, "detail": gate},
            {"name": "timing", "source": "sta", "ok": p.get("status") == "ok" and (p.get("wns_ns") or -1) >= 0,
             "detail": {"clock_ns": clk, "wns_ns": p.get("wns_ns"), "fmax_mhz": p.get("fmax_mhz")}}]
    ok = rep["verdict"] == "FEASIBLE" and h["ok"] and all(x["ok"] for x in hard) and all(k["slack"] >= 0 for k in sweep_cons)
    reasons = ([f"搜索数据集未达 FEASIBLE（缺口 v={rep['v']}）"] if rep["verdict"] != "FEASIBLE" else []) + \
              [f"{k['name']}：隐藏数据集未通过" for k in h["constraints"] if not k["ok"]] + \
              [x["name"] for x in hard if not x["ok"]]
    return {"verdict": "VERIFIED" if ok else "REJECTED", "reject_reasons": reasons, "search": rep, "hidden": h,
            "hard": hard,
            "objectives": {"area_um2": p.get("area_um2"), "power_mw": (p.get("power_vcd") or {}).get("total_mw"),
                           "fmax_mhz": p.get("fmax_mhz"), "cells": p.get("cells"),
                           "area_est": rep["objectives"]["area_est"]}}


def _round(k):
    return {a: (round(b, 4) if isinstance(b, float) else b) for a, b in k.items()}


# ---------------------------------------------------------------------------
# 直写 Verilog（方法一消融）：同一套约束、同样的数据集与 PPA 流程
# ---------------------------------------------------------------------------
def vsearch(vtext: str, task_name: str, sweep: bool = False) -> dict:
    from . import vlog
    from .task import get
    t, c = get(task_name), _contract(task_name)
    try:
        q = vlog.evaluate(vtext, task_name)["quality"]
    except Exception as e:
        return {"verdict": "BROKEN", "error": str(e)[-1500:]}
    req = alias_requirement(t, c) if sweep else None
    cons = quality_constraints(q["scenarios"], c, "sim:search", ripple=req is None)
    if req is not None:
        from .symbolic import sweep as do_sweep
        env = (c.envelope if c is not None else {}) or {}
        sw = do_sweep(None, task_name, nf=48, per_band=3, amp_pass=env.get("desired_peak", 0.05),
                      amp_stop=env.get("peak", 0.9), runner=lambda xb: vlog.simulate_inputs(vtext, task_name, xb))
        rmax = t.tolerance.get("ripple_max_db")
        cons.append({"name": "alias_rejection", "source": "sweep", "unit": "dB", "value": sw["worst_alias_rejection_db"],
                     "threshold": req, "slack": sw["worst_alias_rejection_db"] - req, "margin": 1.0, "scale": 1.0,
                     "worst_scenario": f"f_in={sw['worst_alias_input_freq']:.5f}"})
        if rmax is not None:
            _, mrip = _margins(c)
            cons.append({"name": "ripple", "source": "sweep", "unit": "dB", "value": sw["passband_ripple_db"],
                         "threshold": rmax, "slack": rmax - sw["passband_ripple_db"], "margin": mrip * rmax,
                         "scale": rmax, "worst_scenario": "passband sweep"})
    for k in cons:
        k["ok"] = k["slack"] >= k["margin"]
    return {"verdict": "FEASIBLE" if all(k["ok"] for k in cons) else "OPEN", "v": round(_gap(cons), 4),
            "constraints": [_round(k) for k in cons],
            "diagnostics": {"per_scenario": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()
                                              if k in ("scenario", "snr_db", "snr_min_db", "ripple_db", "outputs",
                                                       "needed", "shift_diagnosis")} for s in q["scenarios"]]}}


def vfinal(vtext: str, task_name: str) -> dict:
    from scipy.stats import beta
    from . import vlog, ppa_sta
    from .task import get
    t, c = get(task_name), _contract(task_name)
    rep = vsearch(vtext, task_name, sweep=True)
    if rep["verdict"] == "BROKEN":
        return rep
    has_sweep = any(k["source"] == "sweep" for k in rep["constraints"])
    rows = []
    for idx in list(t.holdout_scenarios) + list(range(100, 130)):
        try:
            rows.append(t.score(idx, vlog.simulate(vtext, task_name, [idx])[idx]))
        except (KeyError, IndexError):
            pass
    hcons = quality_constraints(rows, c, "sim:holdout+stat", ripple=not has_sweep)
    for k in hcons:
        k["ok"] = k["slack"] >= 0
    fails = sum(not k for k in [r["snr_db"] >= r["snr_min_db"] for r in rows])
    clk = c.clock_ns if c is not None else 2.0
    p = ppa_sta.evaluate_verilog_vcd(vtext, task_name, scenario=t.search_scenarios[0], period_ns=clk, fast=True,
                                     n_in=t.n_in() if hasattr(t, "frame_outputs") else min(16000, t.n_in()))
    timing = p.get("status") == "ok" and (p.get("wns_ns") or -1) >= 0
    ok = rep["verdict"] == "FEASIBLE" and all(k["ok"] for k in hcons) and timing
    reasons = ([f"搜索数据集未达 FEASIBLE（缺口 v={rep['v']}）"] if rep["verdict"] != "FEASIBLE" else []) + \
              [f"{k['name']}：隐藏数据集未通过" for k in hcons if not k["ok"]] + ([] if timing else ["timing"])
    return {"verdict": "VERIFIED" if ok else "REJECTED", "reject_reasons": reasons, "search": rep, "hidden_constraints": [_round(k) for k in hcons],
            "statistics": {"scenarios": len(rows), "failures": fails,
                           "fail_prob_upper_95": float(beta.ppf(0.95, fails + 1, len(rows) - fails)) if rows and fails < len(rows) else 1.0},
            "timing": {"ok": timing, "wns_ns": p.get("wns_ns"), "fmax_mhz": p.get("fmax_mhz")},
            "objectives": {"area_um2": p.get("area_um2"), "power_mw": (p.get("power_vcd") or {}).get("total_mw")}}


# ---------------------------------------------------------------------------
# agent 可见视图（F2）：隐藏数据集只给通过/未通过，数值写到工作区外的旁路记录
# ---------------------------------------------------------------------------
SIDECAR = Path("/Users/chengzhy/verievolve_agent_ws/.hidden")


def sidecar(ws: Path, kind: str, rec: dict):
    import json
    import time
    SIDECAR.mkdir(parents=True, exist_ok=True)
    with (SIDECAR / f"{Path(ws).resolve().name}.jsonl").open("a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "kind": kind, **rec}, ensure_ascii=False, default=str) + "\n")


def public(res: dict) -> dict:
    """终验结果中 agent 可见的部分：判定、拒绝原因（不含隐藏集数值）、硬约束、目标、搜索数据集报告。"""
    out = {k: res.get(k) for k in ("verdict", "reject_reasons", "objectives", "error") if k in res}
    if "hidden" in res:
        out["hidden"] = {"ok": res["hidden"]["ok"]}
    if "hidden_constraints" in res:
        out["hidden"] = {"ok": all(k["ok"] for k in res["hidden_constraints"])}
    if "hard" in res:
        out["hard"] = [{"name": h["name"], "ok": h["ok"]} | ({"detail": h["detail"]} if h["name"] == "timing" else {})
                       for h in res["hard"]]
    if "timing" in res:
        out["timing"] = res["timing"]
    if "search" in res:
        out["search"] = res["search"]
    return out
