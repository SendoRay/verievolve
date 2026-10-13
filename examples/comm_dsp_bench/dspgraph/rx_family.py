"""接收链族的接口约束、系统指标与经过验证的失败归因（对任意积木组合通用）。

指标：
- ripple_db / alias_rejection_db：由各积木 LTI 频响乘积解析计算（量化系数）。
- snr_db：位精确输出对理想基带期望信号（解析多音、按整链群时延对齐）做最小二乘
  复增益拟合后的信噪比，包含阻塞混叠、纹波失真与全部算术量化。
归因：把单一积木切换为理想算术、或使用未量化系数重算，得到各来源的误差占比；
每一项都是确定性重算结果，不是模型猜测。
"""

from __future__ import annotations

import math

import numpy as np

from .core import (PlanError, block_response, build, composite_response, run_chain,
                   total_delay)
from .rx_spec import N_WARM_OUT, ChainSpec, Scenario, make_scenario, reference_output


def interface(chain, ctx_out: dict) -> None:
    spec: ChainSpec = chain.spec
    if ctx_out["rate_in"] != spec.r_total:
        raise PlanError("decimation", "$",
                        f"total decimation {ctx_out['rate_in']} != required {spec.r_total}")
    if ctx_out["kind_in"] != "complex":
        raise PlanError("interface", "$", "chain must output complex baseband")
    if ctx_out["width_in"] != spec.output_bits:
        raise PlanError("interface", "$",
                        f"final output width {ctx_out['width_in']} != {spec.output_bits}")


def build_rx(plan: dict, spec: ChainSpec):
    return build(plan, spec, interface=interface)


def _snr(y: np.ndarray, spec: ChainSpec, sc: Scenario, delay: float) -> tuple[float, float]:
    m = np.arange(len(y))
    sel = m >= N_WARM_OUT
    r = reference_output(sc, m[sel] * spec.r_total - delay)
    ys = y[sel]
    a = np.vdot(r, ys) / np.vdot(r, r)
    err = ys - a * r
    p_sig = float(np.mean(np.abs(a * r) ** 2))
    p_err = float(np.mean(np.abs(err) ** 2))
    return 10 * math.log10(p_sig / max(p_err, 1e-300)), p_err


def analytic(chain, quantized: bool = True) -> dict:
    spec: ChainSpec = chain.spec
    fp, fo = spec.passband, spec.fs_out
    pb = np.linspace(0, fp, 257)
    hp = np.abs(composite_response(chain, pb, quantized))
    g0 = hp[0]
    ripple = float(20 * np.log10(hp.max() / max(hp.min(), 1e-300)))
    u = np.linspace(-fp, fp, 97)
    fa = np.concatenate([k * fo + u for k in range(-spec.r_total, spec.r_total + 1) if k != 0])
    fa = fa[(fa >= -0.5) & (fa < 0.5)]
    ha = np.abs(composite_response(chain, fa, quantized))
    rej = -20 * np.log10(np.maximum(ha, 1e-300) / g0)
    i = int(np.argmin(rej))
    wf = float(fa[i])
    per = {}
    for j, key in enumerate(chain.keys):
        r = block_response(chain, j, np.array([wf, 0.0]), quantized)
        if r is not None:
            per[key] = float(-20 * np.log10(max(abs(r[0]) / max(abs(r[1]), 1e-300), 1e-300)))
    return {"ripple_db": ripple, "alias_rejection_db": float(rej[i]), "worst_alias_freq": wf,
            "block_attenuation_at_worst_alias_db": per}


_SCEN: dict = {}


def scenario(spec: ChainSpec) -> Scenario:
    k = spec.sha256()
    if k not in _SCEN:
        _SCEN[k] = make_scenario(spec)
    return _SCEN[k]


def evaluate(chain, *, attribution: bool = False, ideal: bool = False) -> dict:
    """ideal=True：全部算术取理想、系数不量化（算法/结构级评价，用于分阶段的结构阶段）。"""
    spec: ChainSpec = chain.spec
    sc = scenario(spec)
    ana = analytic(chain, quantized=not ideal)
    delay = total_delay(chain)
    x = sc.x_codes / float(1 << (spec.input_bits - 1))
    if ideal:
        y, stats = run_chain(chain, x, exact={k: False for k in chain.keys}, ideal_coef=True)
        attribution = False
    else:
        y, stats = run_chain(chain, x)
    snr, p_err = _snr(y, spec, sc, delay)
    viol = []
    if ana["ripple_db"] > spec.ripple_max_db:
        viol.append({"metric": "ripple_db", "value": ana["ripple_db"], "limit": spec.ripple_max_db})
    if ana["alias_rejection_db"] < spec.alias_min_db:
        viol.append({"metric": "alias_rejection_db", "value": ana["alias_rejection_db"],
                     "limit": spec.alias_min_db})
    if snr < spec.snr_min_db:
        viol.append({"metric": "snr_db", "value": snr, "limit": spec.snr_min_db})
    out = {"snr_db": snr, "ripple_db": ana["ripple_db"],
           "alias_rejection_db": ana["alias_rejection_db"],
           "worst_alias_freq": ana["worst_alias_freq"],
           "saturation": {k: v for k, v in stats.items() if v and k.endswith("sat")},
           "violations": viol, "passed": not viol}
    if attribution:
        out["attribution"] = attribute(chain, x, sc, p_err, ana)
    return out


def attribute(chain, x, sc, p_err_total: float, ana: dict) -> dict:
    spec = chain.spec
    delay = total_delay(chain)
    allf = {k: False for k in chain.keys}
    y_s, _ = run_chain(chain, x, exact=allf, ideal_coef=True)
    snr_s, p_s = _snr(y_s, spec, sc, delay)
    y_c, _ = run_chain(chain, x, exact=allf)
    snr_c, p_c = _snr(y_c, spec, sc, delay)
    per = {}
    for k in chain.keys:
        y_k, _ = run_chain(chain, x, exact=allf | {k: True})
        per[k] = max(_snr(y_k, spec, sc, delay)[1] - p_c, 0.0)

    def share(p):
        return float(p / p_err_total) if p_err_total > 0 else 0.0
    ana_u = analytic(chain, quantized=False)
    return {
        "snr_if_all_arithmetic_ideal_db": snr_c,
        "snr_if_also_coefficients_ideal_db": snr_s,
        "error_share": {"filter_structure": share(p_s),
                        "coefficient_quantization": share(max(p_c - p_s, 0.0)),
                        **{f"arithmetic:{k}": share(v) for k, v in per.items()}},
        "dominant_arithmetic_block": max(per, key=per.get),
        "alias_rejection_unquantized_db": ana_u["alias_rejection_db"],
        "ripple_unquantized_db": ana_u["ripple_db"],
        "block_attenuation_at_worst_alias_db": ana["block_attenuation_at_worst_alias_db"],
    }
