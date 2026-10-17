"""帧处理任务：参考答案是逐帧的样点序列（不是音调集），输出为不规则间隔的 out_valid 样点流。

与 Task 的差别只在场景、打分与直写起点；编译、逐位语义、RTL 对拍、综合流程完全相同。
指标：SQNR = Σ|ref|² / Σ|y − ref|²（逐样点精确对齐，不搜时延、不拟合增益），只对前 n_frames 帧计分。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .task import Task


@dataclass
class FrameTask(Task):
    frame_stimulus: Callable | None = None     # idx -> (x_i, x_q, ref)
    frame_outputs: int = 1                     # 每帧输出样点数
    frame_inputs: int = 1                      # 每帧输入样点数
    n_frames: int = 1                          # 计分帧数
    direct_code: str = ""

    def iface(self, key):
        if key == "out_period":
            return None
        return super().iface(key)

    def rate(self):
        return self.frame_inputs / self.frame_outputs

    def n_in(self) -> int:
        return len(self.scene(self.search_scenarios[0])["x_codes"])

    def spec(self):
        ns = super().spec()
        ns.n_out_per_frame = self.frame_outputs
        return ns

    def scene(self, idx: int) -> dict:
        if idx not in self._cache:
            xi, xq, ref = self.frame_stimulus(idx, self.interface["in_bits"])
            self._cache[idx] = {"x_codes": xi, "xq_codes": xq, "reference": ref,
                                "snr_min_db": self.tolerance["sqnr_min_db"], "ceiling_db": float("nan")}
        return self._cache[idx]

    def direct_start(self, gain_shift=None) -> str:
        return self.direct_code

    def score(self, idx: int, y) -> dict:
        sc = self.scene(idx)
        ref = sc["reference"]
        y = np.asarray(y)
        need = len(ref)
        r = {"scenario": idx, "snr_min_db": sc["snr_min_db"], "ripple_db": 0.0, "ripple_max_db": None,
             "outputs": int(len(y)), "needed": need}
        if len(y) < need:
            r.update(valid_output=False, snr_db=-99.0, passed=False)
            return r
        e = y[:need] - ref
        sq = 10 * math.log10(float(np.sum(np.abs(ref) ** 2)) / max(float(np.sum(np.abs(e) ** 2)), 1e-30))
        per = np.abs(e.reshape(self.n_frames, self.frame_outputs)) ** 2
        r.update(valid_output=True, snr_db=sq, max_abs_err_lsb=float(np.max(np.abs(np.concatenate([e.real, e.imag]))))
                 * (1 << (self.interface["out_bits"] - 1)),
                 worst_bins=[int(b) for b in np.argsort(-per.mean(0))[:5]])
        r["passed"] = bool(sq >= sc["snr_min_db"])
        if sq < sc["snr_min_db"]:          # 对齐诊断：输出整体平移 d 个样点时的 SQNR（区分数值误差与顺序/延迟错误）
            best = (0, sq)
            for d in range(-self.frame_outputs, self.frame_outputs + 1):
                if d == 0 or d + need > len(y) or d < -len(y):
                    continue
                yy = y[d:d + need] if d >= 0 else np.concatenate([np.zeros(-d, dtype=y.dtype), y[:need + d]])
                ee = yy - ref
                v = 10 * math.log10(float(np.sum(np.abs(ref) ** 2)) / max(float(np.sum(np.abs(ee) ** 2)), 1e-30))
                if v > best[1]:
                    best = (d, v)
            if best[0] != 0:
                r["shift_diagnosis"] = {"best_shift_samples": best[0], "snr_db_at_best_shift": round(best[1], 3),
                                        "note": "正值表示输出比参考晚到；若平移后达标，问题在输出时序或顺序而不是数值"}
        return r

    def combine(self, rows: list) -> dict:
        worst = min(rows, key=lambda r: r["snr_db"] - r["snr_min_db"])
        return {"passed": all(r["passed"] for r in rows),
                "snr_margin_db": float(worst["snr_db"] - worst["snr_min_db"]),
                "ripple_db": 0.0, "ripple_max_db": None, "scenarios": rows}
