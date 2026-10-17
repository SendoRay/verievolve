"""类型化数据流图的记录与导出（讨论归纳 M1-6）。

编译器（dspgraph.sdf.Graph / dspgen.graph.TaskGraph）是“边构造边执行”的：每个原语调用时立即算出整数序列、
写出 Verilog 片段、记入代价，不保留图结构。RecordingGraph 在 API 边界记录 LLM 直接调用的每个原语：
运算、参数、输入/输出信号及其类型 τ = (W, F, 有无符号, 速率域周期, 时延, held) 和所属 scope，并保留信号的实际整数值。
编译器为对齐时延自动插入的流水寄存器、符号扩展等“机制”不进入记录（它们不改变样点序列）。

用途：
- 运行态图落盘：export() 给出可序列化的图（节点、信号、类型），用于复现、比对和语义哈希；
- 符号层（dspgen.symbolic）：在这张图上做区间范围分析、误差传播与贡献分解；
- 观测：任意信号的逐样点取值可直接导出。
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from dspgraph.sdf import Sig
from .graph import TaskGraph

# 记录的 API（与 contract.py 的原语分层一致）
API = ("input", "const", "counter", "add", "sub", "neg", "mul", "scale", "shift", "q", "bits", "mux", "lut", "reg",
       "delay_line", "delay", "integrate", "decimate", "interpolate", "mac", "gather", "clock", "state", "close",
       "sample", "ram", "output")


class RecordingGraph(TaskGraph):
    """与 TaskGraph 行为完全相同，另外记录类型化数据流图。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rec_nodes: list = []
        self.rec_sigs: dict = {}        # sid -> Sig
        self._sid: dict = {}            # id(Sig) -> sid
        self._depth = 0

    # ---- 信号编号
    def _ref(self, s):
        if isinstance(s, Sig):
            k = id(s)
            if k not in self._sid:
                sid = f"s{len(self._sid)}"
                self._sid[k] = sid
                self.rec_sigs[sid] = s
            return {"sig": self._sid[k]}
        if isinstance(s, (list, tuple)):
            return [self._ref(x) for x in s]
        if isinstance(s, (np.integer,)):
            return int(s)
        if isinstance(s, (np.floating,)):
            return float(s)
        if isinstance(s, np.ndarray):
            return s.tolist()
        return s

    def _record(self, op, args, kwargs, result):
        self.rec_nodes.append({
            "id": len(self.rec_nodes), "op": op, "scope": self._scope[-1],
            "args": self._ref(list(args)), "kwargs": {k: self._ref(v) for k, v in kwargs.items()},
            "out": self._ref(result) if result is not None else None,
        })


def _wrap(name):
    base = getattr(TaskGraph, name)

    def method(self, *args, **kwargs):
        self._depth += 1
        try:
            res = base(self, *args, **kwargs)
        finally:
            self._depth -= 1
        if self._depth == 0:
            self._record(name, args, kwargs, res)
        return res

    method.__name__ = name
    method.__doc__ = base.__doc__
    return method


for _n in API:
    setattr(RecordingGraph, _n, _wrap(_n))


def sig_type(g: RecordingGraph, s: Sig) -> dict:
    lin = g._lin.get(s.lin, {}) if s.lin is not None else {}
    return {"W": s.W, "F": s.F, "w": s.w, "f": s.f, "signed": bool(s.signed),
            "period": lin.get("period"), "irregular": bool(lin.get("irregular", False)),
            "clock_domain": bool(lin.get("free", False)), "lat": s.lat, "held": bool(s.held),
            "const": s.lin is None}


def export(g: RecordingGraph) -> dict:
    """可序列化的类型化数据流图。"""
    sigs = {sid: sig_type(g, s) for sid, s in g.rec_sigs.items()}
    body = {"nodes": g.rec_nodes, "signals": sigs}
    h = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {"version": "dspgraph-ir-v1", "semantic_hash": h, **body,
            "summary": {"nodes": len(g.rec_nodes), "signals": len(sigs),
                        "ops": {op: sum(1 for n in g.rec_nodes if n["op"] == op)
                                for op in sorted({n["op"] for n in g.rec_nodes})},
                        "clock_domain": bool(getattr(g, "rtl_numerics", False))}}


def build(code: str, task_name: str, scenarios=None, x_override=None, xq_override=None):
    """在当前进程中执行候选程序（定点解释），返回 (RecordingGraph, task, 场景列表)。只用于分析，不打分。
    x_override/xq_override：用给定的输入码（[行, 样点]）代替任务场景，例如扫频。"""
    import math
    import scipy
    import scipy.signal  # noqa: F401
    from dspgraph.sdf import BuildError
    from .task import get
    task = get(task_name)
    idxs = list(scenarios if scenarios is not None else task.search_scenarios[:1])
    if x_override is not None:
        x, xq = np.atleast_2d(x_override), (None if xq_override is None else np.atleast_2d(xq_override))
    else:
        x = np.stack([task.scene(i)["x_codes"] for i in idxs])
        xq = np.stack([task.scene(i)["xq_codes"] for i in idxs]) if task.iface("in_kind") == "complex" else None
    spec = task.spec()
    g = RecordingGraph(spec, x, xq, in_kind=task.iface("in_kind"), out_kind=task.iface("out_kind"),
                       in_period=task.iface("in_period"), out_period=task.iface("out_period"))
    env = {"np": np, "numpy": np, "scipy": scipy, "math": math, "__name__": "candidate"}
    exec(compile(code, "<candidate>", "exec"), env)
    if "build" not in env:
        raise BuildError("structure", "program must define build(g, spec)")
    env["build"](g, spec)
    return g, task, idxs
