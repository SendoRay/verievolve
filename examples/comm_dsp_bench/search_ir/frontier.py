"""正式比较的纯前沿统计；本模块不决定 S0/S1 或实验是否完整。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from numbers import Real

import numpy as np


QUALITY_MULTIPLIERS = (0.25, 0.5, 1.0)
AREA_MULTIPLIERS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
BOOTSTRAP_SEED = 271828
BOOTSTRAP_RESAMPLES = 10000


def _finite(value: Real, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} 必须是有限实数")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} 必须是有限实数") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} 必须是有限实数")
    return result


def _positive(value: Real, label: str) -> float:
    result = _finite(value, label)
    if result <= 0:
        raise ValueError(f"{label} 必须为正")
    return result


def _points(points: Sequence[Mapping]) -> list[tuple[float, float]]:
    result = []
    for index, point in enumerate(points):
        if not isinstance(point, Mapping) or not {"Q", "area_um2"} <= point.keys():
            raise ValueError(f"points[{index}] 必须包含 Q 和 area_um2")
        quality = _finite(point["Q"], f"points[{index}].Q")
        area = _positive(point["area_um2"], f"points[{index}].area_um2")
        if quality < 0:
            raise ValueError(f"points[{index}].Q 不得为负")
        result.append((quality, area))
    return result


def hypervolume(points: Sequence[Mapping], q_budget: float, A_ref: float) -> float:
    """归一化坐标中的矩形并面积，参考点 (1, 2)，两个目标均越小越好。

    所有输入先校验，再排除 ROI 外点；不把越界点截到边界。重复点、
    被支配点和参考边界上的零面积点均不会重复贡献体积。
    """
    q_budget = _positive(q_budget, "q_budget")
    A_ref = _positive(A_ref, "A_ref")
    normalized = []
    for quality, area in _points(points):
        if quality > q_budget:
            continue
        y = area / A_ref
        if y <= 2.0:
            normalized.append((quality / q_budget, y))
    height = 2.0
    strips = []
    for x, y in sorted(normalized):
        if y < height:
            strips.append((1.0 - x) * (height - y))
            height = y
    return float(math.fsum(strips))


def grid_values(
    points: Sequence[Mapping], q_budget: float, A_ref: float
) -> dict[str, list]:
    """返回固定预算格点的有限最优值；空格点用 None，不用无穷大。

    每个格点只施加对应的预算约束。调用者负责在传入前剔除部署不合法
    或终考不合格的候选；本函数不从质量值推断物理合法性。
    """
    q_budget = _positive(q_budget, "q_budget")
    A_ref = _positive(A_ref, "A_ref")
    values = _points(points)
    quality_budgets = [factor * q_budget for factor in QUALITY_MULTIPLIERS]
    area_budgets = [factor * A_ref for factor in AREA_MULTIPLIERS]
    if any(not math.isfinite(v) or v <= 0 for v in quality_budgets + area_budgets):
        raise ValueError("预算格点不能溢出或下溢为零")
    return {
        "quality_budgets": quality_budgets,
        "area_budgets": area_budgets,
        "min_area": [
            min((area for quality, area in values if quality <= limit), default=None)
            for limit in quality_budgets
        ],
        "min_quality": [
            min((quality for quality, area in values if area <= limit), default=None)
            for limit in area_budgets
        ],
    }


def engineering_hits(
    joint: Sequence[Mapping],
    baselines: Sequence[Sequence[Mapping]],
    q_budget: float,
    A_ref: float,
    epsQ: float,
    epsA: float,
) -> list[dict]:
    """列出在同一格点同时胜过全部基线、且达到工程余量的命中。

    命中字典给出 kind（改善 area 或 quality）、budget、joint、baselines、
    gaps（基线值减 joint 值）及 epsilon。阈值直接按浮点差 >= epsilon
    判定，不引入额外舍入或隐含容差，也不合并各基线不同格点的命中。
    """
    epsQ = _positive(epsQ, "epsQ")
    epsA = _positive(epsA, "epsA")
    if not baselines:
        raise ValueError("至少需要一个基线，不能作空的全称比较")
    own = grid_values(joint, q_budget, A_ref)
    references = [grid_values(points, q_budget, A_ref) for points in baselines]
    hits = []
    for kind, budget_key, value_key, epsilon in (
        ("area", "quality_budgets", "min_area", epsA),
        ("quality", "area_budgets", "min_quality", epsQ),
    ):
        for index, limit in enumerate(own[budget_key]):
            value = own[value_key][index]
            others = [reference[value_key][index] for reference in references]
            if value is None or any(other is None for other in others):
                continue
            gaps = [other - value for other in others]
            if all(gap >= epsilon for gap in gaps):
                hits.append(
                    {
                        "kind": kind,
                        "budget": limit,
                        "joint": value,
                        "baselines": others,
                        "gaps": gaps,
                        "epsilon": epsilon,
                    }
                )
    return hits


def paired_bootstrap(differences: Sequence[float]) -> dict[str, float | int]:
    """以配对 seed 差为单位的固定 bootstrap；不自行判显著或 S 分支。"""
    values = np.asarray(
        [_finite(value, "difference") for value in differences], dtype=np.float64
    )
    n = len(values)
    if n == 0:
        raise ValueError("配对差不能为空")
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indices = rng.integers(0, n, size=(BOOTSTRAP_RESAMPLES, n))
    try:
        with np.errstate(over="raise", invalid="raise"):
            means = values[indices].mean(axis=1)
            lower, upper = np.quantile(means, [0.025, 0.975], method="linear")
            mean = float(values.mean())
    except FloatingPointError as exc:
        raise ValueError("bootstrap 数值计算溢出") from exc
    if not np.all(np.isfinite([mean, lower, upper])):
        raise ValueError("bootstrap 结果不是有限实数")
    return {"mean": mean, "lower": float(lower), "upper": float(upper), "n": n}
