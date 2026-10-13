"""结构生成方案失败原因诊断（不调用 API）：对 structgen 的每个方案取最后一次尝试，运行并按约定类错误逐项检验。

检验项（第一个搜索场景）：
  base      裁判同口径 SNR（单个复增益 + 时延搜索）
  conj      输出取共轭（Q 路符号反）后的 SNR
  delay_ext 时延搜索放宽到 [−R·64, 4×上限] 后的 SNR（时延约定错误）
  eq        逐音复增益自由拟合后的 SNR（去掉通带形状/增益滚降，只剩混叠、噪声与非线性）
  peak/rms  输出峰值与均方根（满量程 = 1）；saturation 为构造器报告的饱和计数
  dc        输出直流分量占总功率比例
python -m dspgen.diag_structgen STRUCTGEN_DIR OUT.json
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

from .task import get, run_program


def _snr(ys, ref, m, rate, delays):
    best = (-1e9, None)
    for d in delays:
        r = ref.at(m * rate - d)
        a = np.vdot(r, ys) / np.vdot(r, r)
        e = ys - a * r
        s = 10 * math.log10(max(np.mean(np.abs(a * r) ** 2), 1e-300) / max(np.mean(np.abs(e) ** 2), 1e-300))
        if s > best[0]:
            best = (s, d)
    return best


def _refine(ys, ref, m, rate, d0, step):
    lo, hi = d0 - step, d0 + step
    for _ in range(30):
        a1, a2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if _snr(ys, ref, m, rate, [a1])[0] < _snr(ys, ref, m, rate, [a2])[0]:
            lo = a1
        else:
            hi = a2
    return _snr(ys, ref, m, rate, [0.5 * (lo + hi)])


def diagnose(code: str, task_name: str) -> dict:
    t = get(task_name)
    idx = t.search_scenarios[0]
    r = run_program(code, task_name, [idx], want_verilog=True, timeout=600)
    if not r.get("ok"):
        return {"class": "construct_fail", "error": r.get("error")}
    yr, yi = r["outputs"][str(idx)]
    y = np.asarray(yr) + 1j * np.asarray(yi)
    sc, ms = t.scene(idx), t.measure
    rate, warm, n_out, mx = t.rate(), ms["warm"], ms["n_out"], ms["max_delay_out"]
    score = r["scores"][0]
    out = {"snr_min_db": sc["snr_min_db"], "base_snr": score["snr_db"], "margin": score["snr_db"] - sc["snr_min_db"],
           "judge_delay_in": score.get("delay_in"), "n_out": int(len(y)), "needed": warm + n_out,
           "saturation": r.get("saturation")}
    if len(y) < warm + n_out:
        return out | {"class": "too_few_outputs"}
    ys = y[warm:warm + n_out]
    m = np.arange(warm, warm + n_out)
    ref = sc["reference"]
    out["peak"] = float(max(np.max(np.abs(ys.real)), np.max(np.abs(ys.imag))))
    out["rms"] = float(np.sqrt(np.mean(np.abs(ys) ** 2)))
    out["dc_frac"] = float(np.abs(np.mean(ys)) ** 2 / max(np.mean(np.abs(ys) ** 2), 1e-300))
    if out["rms"] == 0:
        return out | {"class": "zero_output"}
    grid = np.arange(0.0, mx * rate, rate / 4.0)
    s0, d0 = _snr(ys, ref, m, rate, grid)
    dc0 = _snr(np.conj(ys), ref, m, rate, grid)[1]
    out["conj"] = _refine(np.conj(ys), ref, m, rate, dc0, rate / 4)[0]
    gext = np.arange(-64.0 * rate, 4 * mx * rate, rate / 4.0)
    se, de = _snr(ys, ref, m, rate, gext)
    se, de = _refine(ys, ref, m, rate, de, rate / 4)
    out["delay_ext"], out["delay_ext_at_in"] = se, de
    d = de
    B = np.exp(2j * np.pi * np.outer(m * rate - d, ref.eff()))
    c, *_ = np.linalg.lstsq(B, ys, rcond=None)
    e = ys - B @ c
    out["eq"] = float(10 * np.log10(np.mean(np.abs(B @ c) ** 2) / max(np.mean(np.abs(e) ** 2), 1e-300)))
    g = np.abs(c) / np.abs(ref.amps)
    out["tone_gain_spread_db"] = float(20 * np.log10(g.max() / max(g.min(), 1e-300)))
    # 期望输出幅度（参考在 ±1 满量程下的均方根）与实际增益：用于判断增益过小（被量化吃掉）或过大（饱和）
    ref_rms = float(np.sqrt(np.mean(np.abs(ref.at(m * rate - d)) ** 2)))
    a = np.vdot(ref.at(m * rate - d), ys) / np.vdot(ref.at(m * rate - d), ref.at(m * rate - d))
    out["fit_gain_db"] = float(20 * np.log10(max(abs(a), 1e-300)))
    out["signal_rms"] = float(abs(a) * ref_rms)
    base = out["base_snr"]
    lsb = 2.0 ** -(t.interface["out_bits"] - 1)
    if out["conj"] > base + 20:
        cls = "q_sign"
    elif out["delay_ext"] > base + 20:
        cls = "delay_convention"
    elif out["peak"] >= 0.999 and (out["saturation"] or out["eq"] < base + 10):
        cls = "overflow_saturation"
    elif out["signal_rms"] < 8 * lsb:
        cls = "gain_too_low"
    elif out["dc_frac"] > 0.5:
        cls = "dc_offset"
    elif out["eq"] > base + 20:
        cls = "passband_shape"            # 只拟合一个增益时误差大，逐音拟合后好：通带形状/频率搬移不准
    else:
        cls = "filtering_or_nonlinear"
    return out | {"class": cls}


if __name__ == "__main__":
    root, outp = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        sg = json.loads((d / "structgen.json").read_text())
        for rec in sg:
            last = rec["calls"][-1]
            path = d / f"v{rec['variant']}_a{last['attempt']}.py"
            row = {"task": d.name, "variant": rec["variant"], "attempts": len(rec["calls"]),
                   "compiled": rec.get("compiled"), "idea": last.get("idea"),
                   "attempt_errors": [(c.get("error") or "")[:160] for c in rec["calls"]]}
            if not path.exists():
                row |= {"class": "no_code"}
            else:
                row |= {"path": str(path)} | diagnose(path.read_text(), d.name)
            rows.append(row)
            outp.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=float))
            print(d.name, rec["variant"], row["class"], {k: (round(v, 1) if isinstance(v, float) else v) for k, v in row.items()
                  if k in ("margin", "base_snr", "conj", "delay_ext", "eq", "peak", "fit_gain_db", "signal_rms", "dc_frac")}, flush=True)
