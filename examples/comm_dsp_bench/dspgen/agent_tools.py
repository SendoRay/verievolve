"""结构生成 agent 的工具（与链路无关，只依赖 Task 的接口、参考信号与测试信号）。

每个工具在独立子进程中执行候选程序（与裁判同一解释器），返回可直接给 LLM 看的数值：
  run(code)              搜索场景的全部指标（逐场景 SNR/门槛/纹波）、逐段面积、饱和计数；
                         另外给出“只输入期望信号（去掉干扰）”时的 SNR，用于区分功能错误与滤波不足。
  probe(code)            程序中 g.probe("名字", i, q) 标出的中间信号：相对理想输出参考与相对输入期望信号的 SNR、
                         增益、时延、逐音均衡后 SNR、峰值、频谱主峰；在含干扰与不含干扰两种输入下各测一次。
  freqz(snippet)         片段定义 stages = [{"taps": 系数, "rate": 该级输入速率(链输入=1)}, ...]，返回级联响应的
                         通带纹波与各混叠带最小衰减（相对直流增益）。
python -m dspgen.agent_tools  （stdin 为 JSON 请求，stdout 为 JSON 结果）
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import traceback

import numpy as np

BENCH_TIMEOUT = 300


def call(req: dict, timeout=BENCH_TIMEOUT) -> dict:
    from .task import BENCH
    try:
        pr = subprocess.run([sys.executable, "-W", "ignore", "-m", "dspgen.agent_tools"], input=json.dumps(req),
                            capture_output=True, text=True, cwd=BENCH, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "timeout", "message": f"tool exceeded {timeout} s"}}
    try:
        return json.loads(pr.stdout)
    except Exception:
        return {"ok": False, "error": {"code": "worker_crash", "message": pr.stderr[-600:]}}


# ---------------------------------------------------------------- 子进程内
def _build(code, t, xs):
    import scipy
    import scipy.signal
    from dspgraph.sdf import BuildError
    from .graph import TaskGraph
    g = TaskGraph(t.spec(), np.stack(xs), None, in_kind=t.iface("in_kind"), out_kind=t.iface("out_kind"),
                  in_period=t.iface("in_period"), out_period=t.iface("out_period"))
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "__name__": "candidate"}
    exec(compile(code, "<candidate>", "exec"), env)
    if "build" not in env:
        raise BuildError("structure", "program must define build(g, spec)")
    env["build"](g, t.spec())
    if g.y is None:
        raise BuildError("structure", "build() never called g.output(...)")
    return g


def _clean_codes(t, idx):
    sc = t.scene(idx)
    full = 1 << (t.interface["in_bits"] - 1)
    v = sc["clean"].at(np.arange(t.n_in()))
    if t.iface("in_kind") == "complex":
        return np.clip(np.round(v.real * full), -full, full - 1).astype(np.int64)   # 复输入时只取 I（工具近似）
    return np.clip(np.round(v.real * full), -full, full - 1).astype(np.int64)


def _snr1(ys, tones, times):
    r = tones.at(times)
    a = np.vdot(r, ys) / max(np.vdot(r, r).real, 1e-300)
    e = ys - a * r
    return 10 * math.log10(max(np.mean(np.abs(a * r) ** 2), 1e-300) / max(np.mean(np.abs(e) ** 2), 1e-300)), a


def _fit(ys, tones, times):
    snr, a = _snr1(ys, tones, times)
    B = np.exp(2j * np.pi * np.outer(times, tones.eff()))
    c, *_ = np.linalg.lstsq(B, ys, rcond=None)
    ee = ys - B @ c
    eq = 10 * math.log10(max(np.mean(np.abs(B @ c) ** 2), 1e-300) / max(np.mean(np.abs(ee) ** 2), 1e-300))
    return snr, eq, a


def _sig_stats(v, period, t, idx):
    """中间信号 v（每 period 个输入样点一个）相对输出参考（零频基带）与输入期望信号的拟合。"""
    sc = t.scene(idx)
    v = np.asarray(v)
    n = len(v)
    start = min(n // 4, int(t.measure["warm"] * t.rate() / period))
    L = min(n - start, 2048)
    if L < 128:
        return {"error": f"too few samples ({n})"}
    m = np.arange(start, start + L)
    ys = v[start:start + L]
    out = {"samples": int(n), "clocks_per_sample": int(period),
           "peak": float(max(np.max(np.abs(ys.real)), np.max(np.abs(ys.imag)) if np.iscomplexobj(ys) else 0.0)),
           "rms": float(np.sqrt(np.mean(np.abs(ys) ** 2)))}
    for key, tones in (("vs_output_reference", sc["reference"]), ("vs_input_desired", sc["clean"])):
        step = max(period / 2.0, 2.0)
        grid = np.arange(0.0, 4096.0, step)
        vals = [_snr1(ys, tones, m * period - d)[0] for d in grid]
        lo, hi = grid[int(np.argmax(vals))] - step, grid[int(np.argmax(vals))] + step
        for _ in range(25):
            a1, a2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
            if _snr1(ys, tones, m * period - a1)[0] < _snr1(ys, tones, m * period - a2)[0]:
                lo = a1
            else:
                hi = a2
        best = (None, 0.5 * (lo + hi))
        s, eq, a = _fit(ys, tones, m * period - best[1])
        out[key] = {"snr_db": round(s, 2), "per_tone_equalized_snr_db": round(eq, 2),
                    "gain_db": round(20 * math.log10(max(abs(a), 1e-300)), 2), "delay_in_samples": round(float(best[1]), 2)}
    w = np.hanning(L)
    Y = np.abs(np.fft.fft((ys - np.mean(ys)) * w)) ** 2
    fr = np.fft.fftfreq(L)
    top = np.argsort(Y)[-3:][::-1]
    out["spectrum_peaks_cycles_per_input_sample"] = [round(float(fr[k]) / period, 5) for k in top]
    out["dc_fraction"] = round(float(abs(np.mean(ys)) ** 2 / max(np.mean(np.abs(ys) ** 2), 1e-300)), 4)
    return out


def _run(req):
    from .task import get, evaluate_program
    t = get(req["task"])
    r = evaluate_program(req["code"], req["task"])
    if not r.get("valid"):
        return {"ok": False, "error": r.get("error")}
    q = r["quality"]
    out = {"ok": True, "passed_all_scenarios": q["passed"], "worst_snr_margin_db": round(q["snr_margin_db"], 3),
           "scenarios": [{"snr_db": round(s["snr_db"], 2), "threshold_db": round(s["snr_min_db"], 2),
                          "ripple_db": round(s["ripple_db"], 3), "gain_db": round(s.get("gain_db", float("nan")), 2),
                          "delay_in_samples": round(s.get("delay_in", float("nan")), 2)} for s in q["scenarios"]],
           "ripple_max_db": q["ripple_max_db"], "area_total": round(r["area"], 1),
           "area_per_scope": {k: round(v, 1) for k, v in r["area_per_scope"].items()},
           "saturation_counts": {k: v for k, v in (q.get("saturation") or {}).items() if v}}
    idx = t.search_scenarios[0]
    g = _build(req["code"], t, [_clean_codes(t, idx)])
    s = t.score(idx, np.asarray(g.y)[0])
    out["without_interference"] = {"snr_db": round(s["snr_db"], 2), "ripple_db": round(s["ripple_db"], 3),
                                   "note": "只输入期望信号（去掉全部干扰）时的输出 SNR；若这里也很差，问题在功能/增益/符号/时延，而不是滤波"}
    return out


def _probe(req):
    from .task import get
    t = get(req["task"])
    idx = t.search_scenarios[0]
    out = {"ok": True, "probes": {}}
    for label, x in (("with_interference", t.scene(idx)["x_codes"]), ("without_interference", _clean_codes(t, idx))):
        g = _build(req["code"], t, [x])
        if not g.probes:
            return {"ok": False, "error": {"code": "no_probe", "message": "程序中没有 g.probe(...) 观测点"}}
        for name, v, period in g.probes:
            out["probes"].setdefault(name, {})[label] = _sig_stats(np.asarray(v)[0], period, t, idx)
    return out


def _freqz(req):
    import scipy
    import scipy.signal
    from .task import get
    t = get(req["task"])
    p = t.params
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "spec": t.spec()}
    exec(compile(req["snippet"], "<freqz>", "exec"), env)
    stages = env.get("stages")
    if not stages:
        return {"ok": False, "error": {"code": "no_stages", "message": "片段必须定义 stages = [{'taps': ..., 'rate': ...}, ...]"}}
    if "passband" not in p or "fs_out" not in p:
        return {"ok": False, "error": {"code": "unsupported", "message": "该任务没有 passband/fs_out 参数"}}
    fp, fo = p["passband"], p["fs_out"]

    def H(f):
        h = np.ones_like(f, dtype=complex)
        for st in stages:
            b = np.asarray(st["taps"], dtype=float)
            r = float(st.get("rate", 1.0))
            w = 2 * np.pi * f / r
            h *= np.exp(-1j * np.outer(w, np.arange(len(b)))) @ b
        return h
    g0 = abs(H(np.array([0.0]))[0])
    fpb = np.linspace(-fp, fp, 801)
    hp = np.abs(H(fpb))
    ripple = 20 * math.log10(hp.max() / max(hp.min(), 1e-300))
    bands = []
    k = 1
    while k * fo - fp < 0.5 + 1e-12:
        for sgn in (1, -1):
            fb = np.linspace(sgn * k * fo - fp, sgn * k * fo + fp, 201)
            att = 20 * math.log10(max(np.max(np.abs(H(fb))), 1e-300) / max(g0, 1e-300))
            bands.append({"center": round(sgn * k * fo, 6), "max_gain_db_rel_dc": round(att, 2)})
        k += 1
    worst = sorted(bands, key=lambda b: -b["max_gain_db_rel_dc"])[:4]
    return {"ok": True, "dc_gain": round(g0, 6), "passband_ripple_db": round(ripple, 4),
            "passband_droop_at_edge_db": round(20 * math.log10(max(hp[-1], 1e-300) / max(g0, 1e-300)), 4),
            "worst_alias_bands": worst, "n_alias_bands": len(bands),
            "note": "混叠带 = k·fs_out ± passband（k≠0），这些频段的输入在抽取到 fs_out 后会落入通带"}


def main():
    req = json.loads(sys.stdin.read())
    from dspgraph.sdf import BuildError
    try:
        out = {"run": _run, "probe": _probe, "freqz": _freqz}[req["tool"]](req)
    except BuildError as e:
        out = {"ok": False, "error": e.as_dict()}
    except Exception as e:
        tb = traceback.extract_tb(sys.exc_info()[2])
        line = next((f.lineno for f in reversed(tb) if f.filename in ("<candidate>", "<freqz>")), None)
        out = {"ok": False, "error": {"code": "python_error", "line": line, "message": f"{type(e).__name__}: {str(e)[:400]}"}}
    sys.stdout.write(json.dumps(out, default=float, ensure_ascii=False))


if __name__ == "__main__":
    main()
