"""可证明性质检查（讨论归纳 §5.4 的可实现部分）。只使用编译器本身执行候选程序，不另写第二套语义。

- ranges：在记录的类型化数据流图（dspgen.record）上做区间算术，给出每个量化点输入的取值上界，
  判断饱和/回绕能否被排除。只依赖计数器的模运算（相位、地址）标为按设计回绕；依赖输入的模运算
  （如 CIC 积分器）标为“依赖 Hogenauer 条件”，由仿真复核。区间算术忽略相关性，结论偏保守但可靠。
- sweep（链路 A）：一次构造放入一批单音输入（每行一个频率），用真实定点实现得到输出增益，
  计算通带纹波与全频带最坏混叠抑制（恢复旧规格的 alias_min_db 约束）。覆盖扫频网格上的所有频率，
  不依赖测试场景抽到哪些干扰频点。

未纳入：按分组的误差归因。设计中常见有意的误差相消（例如用常数补偿截断偏置），
“去掉某一组量化”会破坏相消，不能当作该组的误差贡献；这一点已由加宽实验验证。
"""
from __future__ import annotations

import inspect
import math

import numpy as np

from .graph import TaskGraph
from .record import build


def _bind(op, args, kwargs):
    b = inspect.signature(getattr(TaskGraph, op)).bind(None, *args, **kwargs)
    b.apply_defaults()
    d = dict(b.arguments)
    d.pop("self", None)
    return d


def _refs(x):
    if isinstance(x, dict) and isinstance(x.get("sig"), str):     # 信号引用 {"sig": 编号}（注意 sample 的参数名也叫 sig）
        yield x["sig"]
    elif isinstance(x, (list, tuple)):
        for y in x:
            yield from _refs(y)
    elif isinstance(x, dict):
        for y in x.values():
            yield from _refs(y)


def ranges(code: str, task_name: str, input_max: float = 1.0) -> dict:
    g, task, _ = build(code, task_name)
    S = g.rec_sigs
    A, data, flags = {}, set(), []

    def R(ref):
        return A.get(ref["sig"], 0.0)

    def fmax(s):
        return 2.0 ** (s.W - 1 - s.F)

    for node in g.rec_nodes:
        op, p = node["op"], _bind(node["op"], node["args"], node["kwargs"])
        outs = list(_refs(node["out"])) if node["out"] is not None else []
        if op == "input" or set(_refs(p)) & data:
            data.update(outs)
        if op == "input":
            for o in outs:
                A[o] = input_max
        elif op == "const":
            s = S[outs[0]]
            A[outs[0]] = abs(float(s.v)) / 2.0 ** s.F
        elif op in ("counter", "bits"):
            A[outs[0]] = 2.0 ** S[outs[0]].W - 1
        elif op == "lut":
            A[outs[0]] = max(abs(float(x)) for x in p["values"])
        elif op in ("add", "sub"):
            A[outs[0]] = R(p["a"]) + R(p["b"])
        elif op in ("neg", "reg", "decimate", "interpolate", "delay", "sample"):
            A[outs[0]] = R(p["a"] if "a" in p else p["sig"])
        elif op == "shift":
            A[outs[0]] = R(p["a"]) * 2.0 ** p["k"]
        elif op == "mul":
            A[outs[0]] = R(p["a"]) * R(p["b"])
        elif op == "scale":
            A[outs[0]] = R(p["a"]) * abs(float(p["c"])) * (1 + 2.0 ** (1 - p["bits"]))
        elif op == "mux":
            A[outs[0]] = max(R(p["a"]), R(p["b"]))
        elif op == "delay_line":
            for o in outs:
                A[o] = R(p["a"])
        elif op == "mac":
            A[outs[0]] = sum(abs(float(c)) * R(s) for s, c in p["terms"]) * (1 + 2.0 ** (1 - p["coef_bits"]))
        elif op == "gather":
            sigs = p["sigs"] if isinstance(p["sigs"], list) else [p["sigs"]]
            A[outs[0]] = max(R(s) for s in sigs)
        elif op == "clock":
            for o in outs[:-1]:
                A[o] = max(R(s) for s in p["sigs"])
            A[outs[-1]] = 1.0
        elif op in ("integrate", "state"):
            s = S[outs[0]]
            A[outs[0]] = fmax(s)
            flags.append({"node": node["id"], "scope": node["scope"], "op": op,
                          "status": "modular_data" if outs[0] in data else "control_modular",
                          "note": "反馈/累加：取值上界无法由区间算术给出，依赖 Hogenauer 条件或设计约束，由仿真复核"})
        elif op == "q":
            y = S[outs[0]]
            bound = R(p["a"])
            fm = fmax(y) - 2.0 ** (-y.F)
            A[outs[0]] = min(bound, fm)
            if bound > fm:
                if outs[0] not in data:
                    st = "control_modular"
                elif p["ovf"] == "wrap":
                    st = "modular_data"
                else:
                    st = "sat_possible"
                a = S[p["a"]["sig"]]
                obs = float(np.max(np.abs(np.asarray(a.v, dtype=np.float64)))) / 2.0 ** a.F if a.lin is not None else None
                flags.append({"node": node["id"], "scope": node["scope"], "op": "q", "ovf": p["ovf"], "status": st,
                              "bound": bound, "format_max": fm, "observed_max": obs,
                              "headroom_bits": math.log2(fm / bound) if bound > 0 else None})
    summary = {k: sum(1 for f in flags if f["status"] == k)
               for k in ("sat_possible", "modular_data", "control_modular")}
    return {"input_max": input_max, "flags": flags, "summary": summary,
            "note": "区间算术（忽略相关性，偏保守）：未列出的量化点在 |输入| ≤ input_max 时可证明不饱和、不回绕"}


def sweep(code: str | None, task_name: str, nf: int = 384, amp_pass: float = 0.05, amp_stop: float = 0.9,
          n_out: int = 256, batch: int = 24, runner=None, per_band: int = 9) -> dict:
    """链路 A（DDC）：扫频单音经真实定点实现，测通带纹波与全频带最坏混叠抑制。
    幅度按输入类声明：通带单音为期望信号电平 amp_pass，阻带单音为干扰电平 amp_stop（相对满量程）。"""
    from .task import get
    task = get(task_name)
    p = task.params
    R, fp, f_if = int(p["r_total"]), float(p["passband"]), p["fcw"] / 2.0 ** 32
    fo = 1.0 / R
    n = int((n_out + 400) * R)
    b = task.interface["in_bits"]
    full = 1 << (b - 1)
    pb = f_if + np.linspace(-0.92 * fp, 0.92 * fp, 25)
    sb = np.linspace(0.004, 0.496, nf)
    sb = sb[np.abs(sb - f_if) >= fo - fp]                  # 期望信号以外的全部频率
    k = np.arange(-R, R + 1)
    ab = (f_if + k[k != 0][:, None] * fo + np.linspace(-fp, fp, per_band)[None, :]).ravel()
    ab = ab[(ab > 0.002) & (ab < 0.498)]                   # 折入通带的混叠频率：f_if + k·f_out ± passband
    sb = np.concatenate([sb, ab])
    freqs = np.concatenate([pb, sb])
    t = np.arange(n)
    amps = np.concatenate([np.full(len(pb), amp_pass), np.full(len(sb), amp_stop)])
    x = np.clip(np.round(amps[:, None] * full * np.cos(2 * np.pi * freqs[:, None] * t[None, :])),
                -full, full - 1).astype(np.int64)
    gains, floors = [], []
    for k0 in range(0, len(freqs), batch):          # 分批，限制单次构造的内存
        xb = x[k0:k0 + batch]
        if runner is None:
            g, _, _ = build(code, task_name, x_override=xb)
            y = np.asarray(g.y)
            if getattr(g, "rtl_numerics", False):
                from .rtlsim import simulate
                y = np.asarray(simulate(g, xb, None)[0])
        else:                                     # 外部执行器（例如直写 Verilog 的仿真）
            ys = runner(xb)
            L = min(len(v) for v in ys)
            y = np.stack([np.asarray(v[:L]) for v in ys])
        m = np.arange(y.shape[1])
        sel = m >= y.shape[1] - n_out
        for i, f in enumerate(freqs[k0:k0 + batch]):
            fy = ((f - f_if) * R + 0.5) % 1.0 - 0.5
            ref = np.exp(2j * np.pi * fy * m[sel])
            gains.append(abs(np.vdot(ref, y[i, sel])) / sel.sum() / amps[k0 + i])
            fz = ((fy + 0.5 + 7.5 / sel.sum()) % 1.0) - 0.5          # 相邻空频点：测量噪声底
            floors.append(abs(np.vdot(np.exp(2j * np.pi * fz * m[sel]), y[i, sel])) / sel.sum() / amps[k0 + i])
    gains = np.array(gains)
    gp, gs = gains[:len(pb)], gains[len(pb):]
    g0 = float(np.max(gp))
    fys = ((sb - f_if) * R + 0.5) % 1.0 - 0.5
    inband = np.abs(fys) <= fp * R                          # 折入输出通带
    from dspgraph.rx_spec import SPECS
    spec_min = SPECS[task_name].alias_min_db if task_name in SPECS else None
    rej = -20 * math.log10(max(float(np.max(gs[inband])), 1e-30) / g0)
    fl = np.array(floors)[len(pb):]
    iw = int(np.argmax(gs[inband]))
    floor_db = -20 * math.log10(max(float(fl[inband][iw]), 1e-30) / g0)
    leak = -20 * math.log10(max(float(np.max(gs)), 1e-30) / g0)
    return {"passband_ripple_db": 20 * math.log10(g0 / max(float(np.min(gp)), 1e-30)),
            "worst_alias_rejection_db": rej,
            "worst_alias_input_freq": float(sb[inband][int(np.argmax(gs[inband]))]),
            "worst_leak_any_output_freq_db": leak,
            "measurement_floor_db": floor_db, "floor_limited": bool(floor_db - rej < 6.0),
            "stopband_points": int(len(sb)), "alias_min_db_spec": spec_min,
            "alias_ok": (rej >= spec_min) if spec_min is not None else None,
            "amp_pass": amp_pass, "amp_stop": amp_stop,
            "note": "增益按输入幅度归一；输出相干投影，噪声平均后可测到约 100 dB"}


def observe(code: str, task_name: str, max_len: int = 4096) -> dict:
    """导出 g.probe 观测点在搜索场景 0 上的逐样点值（浮点，与 probe 量纲相同），供 agent 与自己的数学模型对照。"""
    g, _, _ = build(code, task_name)
    if getattr(g, "rtl_numerics", False):
        from .rtlsim import simulate
        _, probes, _ = simulate(g, g.x[:1], None if g.xq is None else g.xq[:1])
        return {name: np.asarray(v)[:max_len].tolist() for name, v in probes[0].items()}
    out = {}
    for name, v, period in g.probes:
        a = np.asarray(v)[0][:max_len]
        out[name] = {"period": period,
                     "re": np.real(a).tolist(), **({"im": np.imag(a).tolist()} if np.iscomplexobj(a) else {})}
    return out
