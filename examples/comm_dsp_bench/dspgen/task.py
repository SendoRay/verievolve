"""Task 规格与评价。新增一条链 = 写一个 Task；其余（场景、参考、门槛、打分、提示词素材）由此自动得到。"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import metrics, stimuli
from .ideal import Ideal

BENCH = Path(__file__).resolve().parent.parent
REGISTRY: dict = {}


@dataclass
class Task:
    name: str
    params: dict                       # 公式参数（程序中以 spec.<名字> 读取）
    interface: dict                    # in_bits, out_bits, rate（输出相对输入的抽取倍率）
    ideal: Callable                    # ideal(g: Ideal, p: dict) -> ISig，理想版程序（公式）
    stimulus: str                      # 信号库中的名字
    metric: str = "aligned_snr_ripple"
    tolerance: dict = field(default_factory=dict)   # {"snr_loss_db": 理想版成绩 − 该值, "ripple_max_db": 上限}
    measure: dict = field(default_factory=lambda: {"n_out": 1024, "warm": 192, "max_delay_out": 160})
    search_scenarios: tuple = (0, 1)
    holdout_scenarios: tuple = (10, 11, 12)
    seed_key: int = 0
    description: str = ""
    _cache: dict = field(default_factory=dict, repr=False)

    # 接口缺省值：实数输入、复数输出、每个时钟一个输入样点、每 rate 个时钟一个输出样点
    def iface(self, key):
        d = {"in_kind": "real", "out_kind": "complex", "in_period": 1,
             "out_period": self.interface.get("rate", 1)}
        return self.interface.get(key, d.get(key))

    def rate(self):
        """每个输出样点对应的输入样点数。"""
        return self.interface["rate"] if "rate" in self.interface else self.iface("out_period") / self.iface("in_period")

    def n_in(self) -> int:
        m = self.measure
        return int(math.ceil((m["n_out"] + m["warm"] + m["max_delay_out"]) * self.rate()))

    def spec(self):
        """给候选程序使用的 spec 对象：公式参数 + 接口。"""
        ns = types.SimpleNamespace(**self.params)
        ns.input_bits, ns.output_bits = self.interface["in_bits"], self.interface["out_bits"]
        if "rate" in self.interface:
            ns.r_total = self.interface["rate"]
        ns.name = self.name
        return ns

    def scene(self, idx: int) -> dict:
        if idx not in self._cache:
            st = stimuli.LIB[self.stimulus](self, idx, self.n_in())
            x = st["x_codes"] / float(1 << (self.interface["in_bits"] - 1))
            if "xq_codes" in st:
                x = x + 1j * st["xq_codes"] / float(1 << (self.interface["in_bits"] - 1))
            out = self.ideal(Ideal(x, st["clean"]), self.params)       # 理想版：带损伤输入上的采样结果 + 干净参考
            kd = metrics.known_delay_snr_real if out.real else metrics.known_delay_snr
            ceil = kd(out.x, out.tones, out.rate, out.delay, out.settle)
            st.update(reference=out.tones, ceiling_db=ceil, snr_min_db=ceil - self.tolerance["snr_loss_db"])
            self._cache[idx] = st
        return self._cache[idx]

    def direct_start(self, gain_shift: int | None = None) -> str:
        """自动生成直写起点：理想版程序逐运算展开成足够宽的定点实现。"""
        from .direct import Direct
        if gain_shift is None:      # 输出增益：参考信号在整个场景上的峰值不超过 0.8 满量程（可为负，即衰减）
            pk = 0.0
            for i in self.search_scenarios:
                ref = self.scene(i)["reference"]
                n_out = int(self.n_in() / self.rate())
                v = ref.at(np.arange(n_out) * self.rate())
                pk = max(pk, float(np.max(np.abs(v.real))),
                         0.0 if self.iface("out_kind") == "real" else float(np.max(np.abs(v.imag))))
            gain_shift = int(math.floor(math.log2(0.8 / pk)))
        d = Direct(self.iface("in_kind"))
        out = self.ideal(d, self.params)
        header = (f"# 直写起点（自动生成）：任务 {self.name}\n# {self.description}\n"
                  f"# 由理想版程序逐运算展开；正确但不考虑面积。\n")
        return d.program(out, gain_shift, header)

    def score(self, idx: int, y) -> dict:
        sc, m = self.scene(idx), self.measure
        if self.iface("out_kind") == "real":
            r = metrics.aligned_snr_ripple_real(np.asarray(y), sc["reference"], self.rate(), m["warm"], m["n_out"],
                                                m["max_delay_out"], self.params["passband"])
        else:
            r = metrics.aligned_snr_ripple(np.asarray(y), sc["reference"], self.interface["rate"],
                                           m["warm"], m["n_out"], m["max_delay_out"])
        r.update(scenario=idx, snr_min_db=sc["snr_min_db"], ripple_max_db=self.tolerance["ripple_max_db"])
        r["passed"] = bool(r.get("valid_output", True) and r["snr_db"] >= sc["snr_min_db"]
                           and r["ripple_db"] <= self.tolerance["ripple_max_db"])
        return r

    def combine(self, rows: list) -> dict:
        worst = min(rows, key=lambda r: r["snr_db"] - r["snr_min_db"])
        return {"passed": all(r["passed"] for r in rows),
                "snr_margin_db": float(worst["snr_db"] - worst["snr_min_db"]),
                "ripple_db": float(max(r["ripple_db"] for r in rows)),
                "ripple_max_db": self.tolerance["ripple_max_db"], "scenarios": rows}


def register(task: Task) -> Task:
    REGISTRY[task.name] = task
    return task


def get(name: str) -> Task:
    if name not in REGISTRY:
        from . import tasks  # noqa: F401  导入即登记
    return REGISTRY[name]


def run_program(code: str, task_name: str, scenarios, extra_bits=0, extra_scopes=None, want_verilog=False,
                timeout=180, want_outputs=False) -> dict:
    req = {"code": code, "task": task_name, "scenarios": list(scenarios), "extra_bits": extra_bits,
           "extra_scopes": extra_scopes, "want_verilog": want_verilog, "want_outputs": want_outputs}
    try:
        pr = subprocess.run([sys.executable, "-W", "ignore", "-m", "dspgen.worker"], input=json.dumps(req),
                            capture_output=True, text=True, cwd=BENCH, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "build_timeout", "message": f"build() exceeded {timeout} s"}}
    try:
        return json.loads(pr.stdout)
    except Exception:
        return {"ok": False, "error": {"code": "worker_crash", "message": pr.stderr[-600:]}}


def evaluate_program(code: str, task_name: str, scenarios=None) -> dict:
    task = get(task_name)
    r = run_program(code, task_name, scenarios or task.search_scenarios)
    if not r.get("ok"):
        return {"valid": False, "error": r["error"]}
    q = task.combine(r["scores"])
    q["saturation"] = r["saturation"]
    return {"valid": True, "quality": q, "area": r["area"]["total"], "area_per_scope": r["area"]["per_scope"],
            "stats": r["stats"]}
