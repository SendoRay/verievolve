"""硬件代价代理的组件单价（Nangate45 μm² 量纲）。

代理只用于搜索排序；最终面积来自逐块真实综合。单价可由校准文件覆盖
（synth 校准集最小二乘拟合），未校准时使用 Nangate45 单元面积量级的先验。
"""

from __future__ import annotations

import json
from pathlib import Path

CAL_PATH = Path(__file__).resolve().parent.parent / "cost_calibration.json"

PRIOR = {
    "adder_bit": 4.6,
    "reg_bit": 4.6,
    "mult_bit2": 5.6,
    "rom_bit": 0.55,
    "mux_bit": 1.9,
    "const_add_bit": 4.6,
}


def _load() -> dict:
    if CAL_PATH.is_file():
        return PRIOR | json.loads(CAL_PATH.read_text()).get("coefficients", {})
    return dict(PRIOR)


C = _load()


def reload() -> None:
    C.clear()
    C.update(_load())


def csd_nonzeros(v: int) -> int:
    v = abs(int(v))
    n = 0
    while v:
        if v & 1:
            n += 1
            v = (v + 1) >> 1 if (v & 2) else v >> 1
        else:
            v >>= 1
    return n
