"""黑盒单音扫描（不调用 API）：对任意候选程序输入单个实数单音，测量输出在期望频率 +f·R、
镜像频率 −f·R 处的复幅度与其余功率，得到通带幅频响应、I/Q 符号、混叠抑制与非线性/时序错误的直接证据。
用于结构生成方案的失败归因。python -m dspgen.probe_tones DIAG.json OUT.json
"""
import json
import math
import sys

import numpy as np
import scipy
import scipy.signal

from .graph import TaskGraph
from .task import get


def run(code, t, xs):
    g = TaskGraph(t.spec(), np.stack(xs), None, in_kind=t.iface("in_kind"), out_kind=t.iface("out_kind"),
                  in_period=t.iface("in_period"), out_period=t.iface("out_period"))
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "__name__": "candidate"}
    exec(compile(code, "<candidate>", "exec"), env)
    env["build"](g, t.spec())
    return np.asarray(g.y), g.sat


def probe(code, task_name, amp=None):
    t = get(task_name)
    if amp is None:     # 单音功率 = 测试场景中期望信号的总功率（输出增益按期望信号设定，单音过大会使输出饱和）
        sc = t.scene(t.search_scenarios[0])
        amp = float(np.sqrt(2 * np.mean(sc["clean"].at(np.arange(4096)).real ** 2)))
    p = t.params
    R, n = t.rate(), t.n_in()
    fo = 1.0 / R
    fp = p["passband"]
    f_if = p["f_if"]
    full = 1 << (t.interface["in_bits"] - 1)
    tt = np.arange(n)
    offs = list(np.linspace(-0.9 * fp, 0.9 * fp, 8)) + [fo - 0.5 * fp, 2 * fo + 0.3 * fp, -fo + 0.5 * fp]
    xs = [np.round(amp * full * np.cos(2 * np.pi * (f_if + f) * tt)).astype(np.int64) for f in offs]
    y, sat = run(code, t, xs)
    ms = t.measure
    m = np.arange(ms["warm"], ms["warm"] + ms["n_out"])
    rows = []
    for k, f in enumerate(offs):
        ys = y[k][m]
        fb = ((f * R + 0.5) % 1) - 0.5          # 抽取后应出现的频率（周/输出样点）
        B = np.stack([np.exp(2j * np.pi * fb * m), np.exp(-2j * np.pi * fb * m)], axis=1)
        c, *_ = np.linalg.lstsq(B, ys, rcond=None)
        rest = ys - B @ c
        tot = float(np.mean(np.abs(ys) ** 2)) or 1e-300
        rows.append({"f_off": float(f), "in_band": abs(f) < fp, "plus": float(abs(c[0])), "minus": float(abs(c[1])),
                     "rest_frac": float(np.mean(np.abs(rest) ** 2) / tot), "rms": math.sqrt(tot)})
    pb = [r for r in rows if r["in_band"]]
    ab = [r for r in rows if not r["in_band"]]
    plus = np.array([r["plus"] for r in pb])
    ref_amp = amp / 2                            # 实数单音下变频后复幅度为 amp/2（增益 1 时）
    res = {"gain_db": float(20 * np.log10(max(np.median(plus), 1e-300) / ref_amp)),
           "pass_spread_db": float(20 * np.log10(max(plus.max(), 1e-300) / max(plus.min(), 1e-300))),
           "image_db": float(20 * np.log10(max(np.median([r["minus"] for r in pb]), 1e-300) / max(np.median(plus), 1e-300))),
           "pass_rest_frac": float(np.median([r["rest_frac"] for r in pb])),
           "alias_rej_db": float(20 * np.log10(max(max(math.sqrt(r["rms"] ** 2) for r in ab), 1e-300) / max(np.median(plus), 1e-300))),
           "sat": {k: v for k, v in (sat or {}).items() if v} if isinstance(sat, dict) else sat, "tones": rows}
    return res


def classify(r):
    if r["image_db"] > 0:
        return "iq_sign_or_mix_direction"
    if r["pass_rest_frac"] > 0.1:
        return "nonlinear_or_timing" + ("+saturation" if r["sat"] else "")
    if r["gain_db"] < -60:
        return "gain_too_low"
    if r["pass_spread_db"] > 3:
        return "passband_shape(filter_design)"
    if r["alias_rej_db"] > -40:
        return "alias_rejection_insufficient"
    return "fine_on_tones(fails only on full scene)"


if __name__ == "__main__":
    diag = json.load(open(sys.argv[1]))
    out = []
    for d in diag:
        if "path" not in d or d.get("class") == "construct_fail":
            continue
        try:
            r = probe(open(d["path"]).read(), d["task"])
            r["class"] = classify(r)
        except Exception as e:
            r = {"class": "probe_error", "error": repr(e)[:300]}
        out.append({"task": d["task"], "variant": d["variant"]} | r)
        json.dump(out, open(sys.argv[2], "w"), indent=1, default=float)
        print(d["task"], d["variant"], r["class"], {k: round(v, 2) for k, v in r.items() if isinstance(v, float)}, r.get("sat"), flush=True)
