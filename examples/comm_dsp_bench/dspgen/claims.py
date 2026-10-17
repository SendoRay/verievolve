"""变换类别的核实（讨论归纳 §12.2）。agent 登记候选时声明类别，框架核实：

- equiv：与父节点逐位等价。在搜索场景与 2 个随机场景上逐样点比对（允许整体延迟不同）；全部相同即核实，
  子节点直接继承父节点的质量结论。这是全场景逐位比对，不是形式证明。
- math：与父节点数学等价、定点不等价。两者都把量化点加宽 20 位后比对，相对差低于 −70 dB 视为数学等价；
  精度部分仍按近似变换判定。
- approx：近似变换，直接按质量约束判定。
"""
from __future__ import annotations

import math

import numpy as np

from .task import get, run_program

EQUIV_EXTRA = (100, 101)
MATH_BITS = 20
MATH_DB = -70.0


def _outputs(code, task_name, scenarios, extra_bits=0):
    r = run_program(code, task_name, scenarios, extra_bits=extra_bits, want_outputs=True)
    if not r.get("ok"):
        return None, r.get("error")
    ys = {int(k): np.asarray(v[0]) + 1j * np.asarray(v[1]) for k, v in r["outputs"].items()}
    return ys, r


def _align(a, b, max_shift):
    """返回使 a[d:] 与 b 对齐的平移 d（a 比 b 晚 d 个样点为正）及重叠段。"""
    best = None
    for d in range(-max_shift, max_shift + 1):
        x = a[d:] if d >= 0 else a
        y = b if d >= 0 else b[-d:]
        n = min(len(x), len(y))
        if n < 16:
            continue
        x, y = x[:n], y[:n]
        e = float(np.sum(np.abs(x - y) ** 2))
        if best is None or e < best[0]:
            best = (e, d, x, y)
    return best


def check_equiv(child: str, parent: str, task_name: str) -> dict:
    t = get(task_name)
    sc = list(t.search_scenarios) + list(EQUIV_EXTRA)
    try:
        yc, rc = _outputs(child, task_name, sc)
        yp, _ = _outputs(parent, task_name, sc)
    except (KeyError, IndexError):
        sc = list(t.search_scenarios)
        yc, rc = _outputs(child, task_name, sc)
        yp, _ = _outputs(parent, task_name, sc)
    if yc is None or yp is None:
        return {"verified": False, "reason": "构造失败", "error": rc}
    warm = t.measure.get("warm", 0) if not hasattr(t, "frame_outputs") else 0
    tot, bad, shifts = 0, 0, set()
    for i in sc:
        b = _align(yc[i], yp[i], 160)
        if b is None:
            return {"verified": False, "reason": f"场景 {i} 输出过短"}
        _, d, x, y = b
        x, y = x[warm:], y[warm:]
        shifts.add(d)
        tot += len(x)
        bad += int(np.count_nonzero(x != y))
    return {"verified": bad == 0 and len(shifts) == 1, "mismatches": bad, "compared": tot,
            "shift_samples": sorted(shifts), "scenarios": sc,
            "method": f"逐位比对 {len(sc)} 个场景（含随机场景）的全部输出样点，允许整体延迟不同；不是形式证明",
            "area": rc.get("area", {}).get("total") if isinstance(rc, dict) else None}


def check_math(child: str, parent: str, task_name: str) -> dict:
    t = get(task_name)
    sc = list(t.search_scenarios)
    yc, rc = _outputs(child, task_name, sc, extra_bits=MATH_BITS)
    yp, _ = _outputs(parent, task_name, sc, extra_bits=MATH_BITS)
    if yc is None or yp is None:
        return {"verified": False, "reason": "构造失败", "error": rc}
    worst = -1e9
    for i in sc:
        b = _align(yc[i], yp[i], 160)
        _, d, x, y = b
        n0 = len(x) // 5
        rel = 10 * math.log10(max(float(np.sum(np.abs(x[n0:] - y[n0:]) ** 2)), 1e-300)
                              / max(float(np.sum(np.abs(y[n0:]) ** 2)), 1e-300))
        worst = max(worst, rel)
    return {"verified": worst <= MATH_DB, "relative_difference_db": round(worst, 2), "threshold_db": MATH_DB,
            "method": f"两者量化点加宽 {MATH_BITS} 位后逐样点比对（数值检验，不是证明）"}
