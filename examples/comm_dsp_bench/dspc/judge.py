"""候选级判定（方法二上半段）：G0 静态检查 → G1 变换核实 → G2 容差门。全部在整数模型上做，不写 RTL。

质量约束、门槛、裕量与缺口沿用 dspgen.verdict 的口径（与 v4 结果一致）：
  SNR ≥ SNR_ideal − 10·log10(1 + p)；DDC 另有扫频的混叠抑制与通带纹波；slack = 指标 − 门槛；
  FEASIBLE 要求每个约束 slack ≥ 裕量；缺口 v = Σ max(0, 裕量 − slack) / 单位尺度。

双重解释的诊断（FRAMEWORK_v5 §4.3）：同一候选的理想解释给出“结构本身能达到的质量”，
定点解释给出“实际实现的质量”，据此建议 REWRITE（结构是瓶颈）或 TUNE（精度是瓶颈 / 还有余量）。
"""
from __future__ import annotations

import math
import traceback
from fractions import Fraction

import numpy as np

from . import analysis, lib
from .fixtype import ContractError
from .interp import run
from .prog import Prog

T2_REL_DB = -100.0          # 理想解释一致的门限（相对误差功率）
MAX_SHIFT_OUT = 16          # 父子比对允许的整体延迟差（输出样点）


# ---------------------------------------------------------------------- 程序加载
def task_prog(task) -> Prog:
    """按任务接口生成一个空的原语程序构造器。"""
    in_p, out_p = task.iface("in_period"), task.iface("out_period")
    if out_p is None:                       # 帧任务：硬件上 out_valid 不规则，样点级上每帧输出数 / 每帧输入数
        out_rate = Fraction(task.frame_outputs, task.frame_inputs)
    else:
        out_rate = Fraction(in_p, out_p)
    return Prog(in_bits=task.interface["in_bits"], out_bits=task.interface["out_bits"],
                in_kind=task.iface("in_kind"), out_kind=task.iface("out_kind"),
                out_rate=out_rate, in_period=in_p, spec=task.spec())


def load(code: str, task) -> Prog:
    """执行候选程序的 build(g, spec)，返回构造好的原语程序。"""
    import scipy
    import scipy.signal  # noqa: F401
    g = task_prog(task)
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "lib": lib, "__name__": "candidate"}
    exec(compile(code, "<candidate>", "exec"), env)
    if "build" not in env:
        raise ContractError("structure", "program must define build(g, spec)")
    env["build"](g, g.spec)
    if g.outputs is None:
        raise ContractError("structure", "build() never called g.output(...)")
    return g


def broken(e: Exception) -> dict:
    if isinstance(e, ContractError):
        return {"verdict": "BROKEN", "error": e.as_dict()}
    tb = traceback.extract_tb(e.__traceback__)
    line = next((f"line {f.lineno}" for f in reversed(tb) if f.filename == "<candidate>"), None)
    return {"verdict": "BROKEN", "error": {"code": "exception", "message": f"{type(e).__name__}: {e}",
                                           "where": line}}


def inputs_for(task, idxs) -> list:
    x = [np.stack([task.scene(i)["x_codes"] for i in idxs])]
    if task.iface("in_kind") == "complex":
        x.append(np.stack([task.scene(i)["xq_codes"] for i in idxs]))
    return x


# ---------------------------------------------------------------------- G1 变换核实
def _codes(y, bits):
    s = float(1 << (bits - 1))
    return np.round(np.asarray(y) * s)


def _best_shift(a, b, warm, D=MAX_SHIFT_OUT):
    """在 |d| ≤ D 的整体延迟内找使两序列误差最小的对齐。返回 (d, 误差功率, 参考功率)。"""
    best = None
    n = min(a.shape[-1], b.shape[-1])
    for d in range(-D, D + 1):
        lo, hi = warm + max(0, d), n - max(0, -d)
        if hi - lo < 16:
            continue
        x, y = a[..., lo:hi], b[..., lo - d:hi - d]
        e = float(np.mean(np.abs(x - y) ** 2))
        if best is None or e < best[1]:
            best = (d, e, float(np.mean(np.abs(x) ** 2)))
    return best


def g1(child: Prog, parent: Prog | None, task, claim: str | None, xs, warm: int) -> dict:
    """判定实际变换类别（agent 声明的 claim 只作对照）：

    T1 逐位等价：定点解释的输出逐位相同（含只改 B 层的情形）→ 继承父节点全部质量结论；
    T2 理想等价：理想解释相同、定点不同 → 只改了精度（位宽、截位、系数位数、查表大小）或做了数学等价的重排，
       结构余量与父节点相同，只需重测定点质量；
    T3 结构近似：理想解释改变 → 结构本身变了（换滤波器、FIR 换 CIC 等），两种解释都要重测。
    claim：equiv（T1）/ precision 或 math（T2）/ structure 或 approx（T3）。"""
    if parent is None:
        return {"actual": None, "declared": claim, "note": "root"}
    if child.a_hash() == parent.a_hash():
        return {"actual": "T1", "declared": claim, "by": "construction",
                "note": "只改了 B 层承诺或分段：整数模型不变，直接继承父节点的质量结论"}
    bits = task.interface["out_bits"]
    yc, yp = run(child, xs, "fixed").y, run(parent, xs, "fixed").y
    d, e, _ = _best_shift(_codes(yc, bits), _codes(yp, bits), warm)
    if e == 0.0:
        out = {"actual": "T1", "by": "bit-exact", "output_shift": d}
    else:
        ic, ip = run(child, xs, "ideal").y, run(parent, xs, "ideal").y
        d2, e2, p2 = _best_shift(ic, ip, warm)
        rel = 10 * math.log10(max(e2, 1e-300) / max(p2, 1e-300))
        out = {"actual": "T2" if rel <= T2_REL_DB else "T3", "by": "ideal-interpretation",
               "ideal_rel_err_db": round(rel, 1), "fixed_mismatch_power_lsb2": round(e, 3)}
    out["declared"] = claim
    want = {"equiv": "T1", "math": "T2", "precision": "T2", "approx": "T3", "structure": "T3"}.get(claim or "")
    if want and want != out["actual"]:
        out["note"] = f"声明为 {claim}（{want}），实际为 {out['actual']}：按实际类别判定"
    return out


# ---------------------------------------------------------------------- G2 容差门
def _scores(task, prog, idxs, mode, xs=None):
    xs = xs if xs is not None else inputs_for(task, idxs)
    r = run(prog, xs, mode)
    rows = [task.score(i, r.y[k]) for k, i in enumerate(idxs)]
    return rows, r


def g2(prog: Prog, task, idxs=None, sweep: bool = True, ideal_from: dict | None = None) -> dict:
    """搜索场景上的系统质量约束（定点解释），附理想解释的同口径质量（结构余量）。
    ideal_from：T2 候选的父节点报告；理想解释与父节点相同，直接继承其结构余量，不重算。"""
    from dspgen.verdict import _contract, _gap, _margins, _round, alias_requirement, quality_constraints
    idxs = list(idxs or task.search_scenarios)
    c = _contract(task.name)
    xs = inputs_for(task, idxs)
    rows, rf = _scores(task, prog, idxs, "fixed", xs)
    req = alias_requirement(task, c) if sweep else None
    cons = quality_constraints(rows, c, "sim:search", ripple=req is None)
    inherit_ideal = bool(ideal_from and ideal_from.get("diagnostics", {}).get("ideal_constraints"))
    if inherit_ideal:
        cons_i = [dict(k) for k in ideal_from["diagnostics"]["ideal_constraints"]]
    else:
        rows_i, _ = _scores(task, prog, idxs, "ideal", xs)
        cons_i = quality_constraints(rows_i, c, "ideal:search", ripple=req is None)
    sw_f = sw_i = None
    if req is not None:
        from dspgen.symbolic import sweep as do_sweep
        env = (c.envelope if c is not None else {}) or {}
        kw = dict(nf=128, amp_pass=env.get("desired_peak", 0.05), amp_stop=env.get("peak", 0.9))
        sw_f = do_sweep(None, task.name, runner=lambda xb: list(run(prog, [xb], "fixed").y), **kw)
        sweeps = [(sw_f, cons, "sweep")]
        if not inherit_ideal:
            sw_i = do_sweep(None, task.name, runner=lambda xb: list(run(prog, [xb], "ideal").y), **kw)
            sweeps.append((sw_i, cons_i, "ideal:sweep"))
        _, mrip = _margins(c)
        for sw, out, src in sweeps:
            out.append({"name": "alias_rejection", "source": src, "unit": "dB",
                        "value": sw["worst_alias_rejection_db"], "threshold": req,
                        "slack": sw["worst_alias_rejection_db"] - req, "margin": 1.0, "scale": 1.0,
                        "worst_scenario": f"f_in={sw['worst_alias_input_freq']:.5f}"})
            rmax = task.tolerance.get("ripple_max_db")
            if rmax is not None:
                out.append({"name": "ripple", "source": src, "unit": "dB", "value": sw["passband_ripple_db"],
                            "threshold": rmax, "slack": rmax - sw["passband_ripple_db"], "margin": mrip * rmax,
                            "scale": rmax, "worst_scenario": "passband sweep"})
    for k in cons + cons_i:
        k["ok"] = k["slack"] >= k["margin"]
    return {"verdict": "FEASIBLE" if all(k["ok"] for k in cons) else "OPEN", "v": round(_gap(cons), 4),
            "constraints": [_round(k) for k in cons], "ideal_constraints": [_round(k) for k in cons_i],
            "per_scenario": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()
                              if k in ("scenario", "snr_db", "snr_min_db", "ripple_db")} for s in rows],
            "saturation": {str(k): v for k, v in rf.sat.items()},
            "qstats": rf.qstats, "floor_limited": bool(sw_f and sw_f.get("floor_limited")),
            "ideal_inherited": inherit_ideal}


def suggest(cons, cons_i) -> dict:
    """按结构余量与精度余量建议修改粒度。"""
    def worst(cs):
        return min(((k["slack"] - k["margin"]) / k["scale"], k["name"]) for k in cs) if cs else (float("inf"), "")
    s_ideal, n_ideal = worst(cons_i)
    s_fixed, n_fixed = worst(cons)
    if s_ideal < 0:
        g, why = "REWRITE", f"理想解释也不满足（{n_ideal}）：结构本身是瓶颈，调精度无法补救"
    elif s_fixed < 0:
        g, why = "TUNE", f"理想解释满足但定点解释不满足（{n_fixed}）：精度是瓶颈，加位宽或调截位"
    else:
        g, why = "TUNE", "两者都有余量：可以收窄精度，或修改 B 层（折叠、去流水）省面积"
    return {"granularity": g, "why": why, "structure_slack": round(s_ideal, 3), "precision_slack": round(s_fixed, 3)}


# ---------------------------------------------------------------------- 入口
def verdict(code: str, task_name: str, parent_code: str | None = None, claim: str | None = None,
            sweep: bool = True, parent_report: dict | None = None) -> dict:
    """候选级判定的唯一入口。返回的报告原样反馈给设计 Agent。"""
    from dspgen.task import get
    task = get(task_name)
    try:
        prog = load(code, task)
    except Exception as e:  # noqa: BLE001
        return broken(e)
    from dspgen.verdict import _contract
    c = _contract(task_name)
    env = (c.envelope if c is not None else {}) or {}
    st = analysis.g0(prog, input_max=env.get("peak", 1.0))
    if not st["ok"]:
        return {"verdict": "BROKEN", "error": {"code": "G0", "message": st["errors"]}, "g0": st}
    try:
        parent = load(parent_code, task) if parent_code else None
        xs = inputs_for(task, task.search_scenarios)
        cls = g1(prog, parent, task, claim, xs, warm=task.measure["warm"])
        if cls.get("actual") == "T1" and parent_report and parent_report.get("verdict") in ("FEASIBLE", "OPEN"):
            q = {k: parent_report[k] for k in ("verdict", "v", "constraints", "ideal_constraints") if k in parent_report}
            q["inherited"] = True
        else:
            q = g2(prog, task, sweep=sweep, ideal_from=parent_report if cls.get("actual") == "T2" else None)
    except Exception as e:  # noqa: BLE001
        return broken(e)
    rep = {"verdict": q["verdict"], "v": q["v"], "constraints": q["constraints"], "class": cls,
           "suggestion": suggest(q["constraints"], q.get("ideal_constraints", [])),
           "g0": {"approx_points": len(st["approx_points"]), "saturation_possible": st["saturation_possible"][:8],
                  "modular": len(st["modular"]), "summary": st["summary"]},
           "diagnostics": {k: q[k] for k in ("ideal_constraints", "per_scenario", "saturation", "floor_limited",
                                             "ideal_inherited") if k in q}}
    if "qstats" in q:
        noise = []
        for i, sv in q["qstats"].items():
            if sv is None:
                continue
            n = prog.nodes[i]
            noise.append({"node": i, "scope": n.scope, "fmt": str(n.fmt), "where": n.where,
                          "local_sqnr_db": round(10 * math.log10(max(sv[0], 1e-300) / max(sv[1], 1e-300)), 2)})
        noise.sort(key=lambda r: r["local_sqnr_db"])
        rep["diagnostics"]["approx_noise_weakest"] = noise[:8]
    if q.get("inherited"):
        rep["inherited"] = True
    return rep


# ---------------------------------------------------------------------- G5 的候选部分：隐藏场景
def hidden(prog: Prog, task, n_stat: int = 30, stat_start: int = 100, conf: float = 0.95) -> dict:
    """留出场景 + 统计复核场景（同一输入类的新随机实例）上的系统质量。只向 agent 返回通过与否。

    统计复核给出失败概率的 Clopper–Pearson 上界。"""
    from scipy.stats import beta
    from dspgen.verdict import _contract, quality_constraints
    c = _contract(task.name)
    out = {}
    for name, idxs in (("holdout", list(task.holdout_scenarios)),
                       ("stat", list(range(stat_start, stat_start + n_stat)))):
        rows, _ = _scores(task, prog, idxs, "fixed")
        cons = quality_constraints(rows, c, f"sim:{name}")
        fails = sum(1 for r in rows if r["snr_db"] < r["snr_min_db"])
        out[name] = {"min_snr_slack": round(min(r["snr_db"] - r["snr_min_db"] for r in rows), 4),
                     "failures": fails, "scenarios": len(rows),
                     "constraints": [{k: v for k, v in x.items() if k in ("name", "slack", "value", "threshold")}
                                     for x in cons]}
    n, f = out["stat"]["scenarios"], out["stat"]["failures"]
    out["fail_prob_upper"] = float(beta.ppf(conf, f + 1, n - f)) if f < n else 1.0
    out["ok"] = all(v["failures"] == 0 and v["min_snr_slack"] >= 0 for k, v in out.items() if isinstance(v, dict))
    return out
