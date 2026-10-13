"""E2.1 逐级最优再拼接 / E2.2 误差份额。规则见 experiments_dspgraph/e21_stagewise_v1_20261011/FROZEN_RULES.md。

python -m dspgraph.stagewise OUT_DIR
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import scipy.signal as sps

from . import judge, template as T
from .rtl_judge import evaluate_program
from .rx_spec import DEV_SPECS, SPECS
from .sdf import Graph

E = Path(__file__).resolve().parent.parent / "experiments_dspgraph"


def levels(spec):
    sc = judge.scene(spec, 0)
    x = sc.x_codes / float(1 << (spec.input_bits - 1))
    psig = float(np.sum(np.abs(sc.tone_amps) ** 2))
    pin = float(np.mean(x ** 2))
    smin = sc.ceiling_db - spec.impl_loss_db
    return {"psig": psig, "pin": pin, "pblk": max(pin - 2 * psig, 0.0), "ceil": sc.ceiling_db, "snr_min": smin,
            "e_tot": 10 ** (-smin / 10) - 10 ** (-sc.ceiling_db / 10)}


def quant(h, bits):
    _, fc = Graph._qconst(float(np.max(np.abs(h))), bits)
    return np.round(np.asarray(h) * 2.0 ** fc) / 2.0 ** fc


def mag(h, nu):
    return np.abs(sps.freqz(h, worN=2 * np.pi * np.asarray(nu))[1])


def hb_design(nt, fpk):
    h = sps.firls(nt, [0, fpk, 0.5 - fpk, 0.5], [1, 1, 0, 0], fs=1.0)
    c = nt // 2
    h = np.array([0.0 if (j - c) % 2 == 0 and j != c else v for j, v in enumerate(h)])
    h[c] = 0.5
    return 0.5 * (h + h[::-1])


def cic_mag(f, N, R1, M=1):
    f = np.asarray(f, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = np.where(f == 0, 1.0, np.sin(np.pi * f * R1 * M) / (R1 * M * np.sin(np.pi * np.where(f == 0, 1, f))))
    return np.abs(d) ** N


def fir_design(nt, fpk, se, sw, N, R1, rate, M=1):
    fsk = max(fpk + 0.01, 0.25 * se)
    ed = np.linspace(0, fpk, 9)
    gain = 1.0 / cic_mag(ed / rate, N, R1, M)
    bands, des = [], []
    for a0, a1, g0, g1 in zip(ed[:-1], ed[1:], gain[:-1], gain[1:]):
        bands += [a0, a1]
        des += [g0, g1]
    h = sps.firls(nt, bands + [fsk, 0.5], des + [0, 0], weight=[1] * 8 + [sw], fs=1.0)
    h = h / h.sum()
    return 0.5 * (h + h[::-1])


def min_bits(vals, ok):
    for v in vals:
        if ok(v):
            return v
    return None


def design_skeleton(spec, k, rule, delta_db, lv):
    """按冻结规则完成一个骨架 k 的逐级设计；不可行返回 None。"""
    sp = {n: v for n, _, v in T.space(spec)}
    R, fp = spec.r_total, spec.passband
    R1 = R // 2 ** k
    n_alias, n_quant = 1 + (k - 1) + 1, 3 + (k - 1)       # CIC/半带/FIR 混叠；NCO/混频/CIC 字长/半带字长
    m = n_alias + n_quant
    tight = 10 ** (-delta_db / 10)
    if rule == "A":
        e_alias = e_quant = lv["e_tot"] / m * tight
    else:
        e_alias, e_quant = 0.7 * lv["e_tot"] / n_alias * tight, 0.3 * lv["e_tot"] / n_quant * tight
    ripple_each = spec.ripple_max_db / k * 10 ** (-delta_db / 20)
    psig, pin, pblk = lv["psig"], lv["pin"], lv["pblk"]
    p = {"k": k, "M": 1, "comp": 1}
    local = {}
    # NCO
    p["P"] = min_bits(sp["P"], lambda P: pin * 10 ** (-6.02 * P / 10) <= e_quant / 2 * psig)
    p["A"] = min_bits(sp["A"], lambda A: pin * 2 * (2.0 ** -(A - 1)) ** 2 / 12 / R <= e_quant / 2 * psig)

    def word(vals, rate):          # rate：该点的累计抽取倍率；处理增益 = rate/R
        return min_bits(vals, lambda W: 2 * (2.0 ** -(W - 1)) ** 2 / 12 * (rate / R) / psig <= e_quant)
    p["Wm"] = word(sp["Wm"], 1)
    p["Wc"] = word(sp["Wc"], R1)
    p["Wh"] = word(sp["Wh"], R1 * 2) if k > 1 else sp["Wh"][0]
    need_att = 10 * math.log10(pblk / (e_alias * psig))
    local["need_alias_att_db"] = need_att
    # CIC
    fa = np.concatenate([j / R1 + np.linspace(-fp, fp, 41) for j in range(1, R1 // 2 + 1)])
    fa = fa[(fa > 0) & (fa <= 0.5)]
    p["N"] = min_bits(sp["N"], lambda N: -20 * math.log10(max(cic_mag(fa, N, R1).max(), 1e-300)) >= need_att)
    if any(p[x] is None for x in ("P", "A", "Wm", "Wc", "Wh", "N")):
        return None
    # 半带
    rate = R1
    pbg, sbg = np.linspace(0, 1, 65), np.linspace(0, 1, 65)
    p["hb_taps"], p["Ch"] = sp["hb_taps"][0], sp["Ch"][0]
    if k > 1:
        # 模板中各半带共用抽头数与系数位：取满足全部半带局部指标的最小值（最坏的是通带最宽的最后一个半带）
        found = None
        for nt in sp["hb_taps"]:
            for cb in sp["Ch"]:
                ok = True
                for s in range(k - 1):
                    fpk = fp * R1 * 2 ** s
                    h = quant(hb_design(nt, fpk), cb)
                    g0 = mag(h, [0.0])[0]
                    att = -20 * math.log10(max(mag(h, 0.5 - fpk + fpk * sbg).max() / g0, 1e-300))
                    hp = mag(h, fpk * pbg)
                    rip = 20 * math.log10(hp.max() / hp.min())
                    if att < need_att or rip > ripple_each:
                        ok = False
                        break
                if ok:
                    found = (nt, cb)
                    break
            if found:
                break
        if not found:
            return None
        p["hb_taps"], p["Ch"] = found
        rate = R1 * 2 ** (k - 1)
    # 末级 FIR
    fpk = fp * rate
    found = None
    for nt in sp["fir_taps"]:
        for se in sp["se"]:
            for sw in sp["sw"]:
                h0 = fir_design(nt, fpk, se, sw, p["N"], R1, rate)
                for cb in sp["Cf"]:
                    h = quant(h0, cb)
                    g0 = mag(h, [0.0])[0]
                    att = -20 * math.log10(max(mag(h, 0.5 - fpk + fpk * sbg).max() / g0, 1e-300))
                    if att < need_att:
                        continue
                    hp = mag(h, fpk * pbg) * cic_mag(fpk * pbg / rate, p["N"], R1)
                    if 20 * math.log10(hp.max() / hp.min()) <= ripple_each:
                        found = (nt, se, sw, cb)
                        break
                if found:
                    break
            if found:
                break
        if found:
            break
    if not found:
        return None
    p["fir_taps"], p["se"], p["sw"], p["Cf"] = found
    g = int(math.floor(math.log2(1.0 / (4 * math.sqrt(psig)))))
    p["G"] = min(max(g, sp["G"][0]), sp["G"][-1])
    # 微架构：只看面积
    p["sh_h"], p["sh_f"] = 1, 1
    evals = 0
    for name in ("sh_h", "sh_f"):
        if name == "sh_h" and k == 1:
            continue
        best = None
        for v in sp[name]:
            r = evaluate_program(T.code(dict(p, **{name: v})), spec.name)
            evals += 1
            if r.get("valid") and (best is None or r["area"] < best[0]):
                best = (r["area"], v)
        if best is None:
            return None
        p[name] = best[1]
    r = evaluate_program(T.code(p), spec.name)
    evals += 1
    if not r.get("valid"):
        return None
    return {"params": p, "area": r["area"], "local": local, "area_evals": evals, "chain": r}


def stagewise(spec, rule, delta_db, lv):
    cands = [c for c in (design_skeleton(spec, k, rule, delta_db, lv) for k in T.space(spec)[0][2]) if c]
    if not cands:
        return None
    best = min(cands, key=lambda c: c["area"])        # 只按面积选骨架
    q = best["chain"]["quality"]
    h = evaluate_program(T.code(best["params"]), spec.name, scenarios=judge.HOLDOUT_SCENARIOS)["quality"]
    return {"rule": rule, "delta_db": delta_db, "params": best["params"], "area": best["area"],
            "search_passed": q["passed"], "search_margin_db": q["snr_margin_db"], "ripple_db": q["ripple_db"],
            "holdout_passed": h["passed"], "holdout_margin_db": h["snr_margin_db"],
            "need_alias_att_db": best["local"]["need_alias_att_db"],
            "skeletons_feasible": len(cands), "area_evals": sum(c["area_evals"] for c in cands)}


def run_spec(spec_name):
    spec = SPECS[spec_name]
    lv = levels(spec)
    out = {"spec": spec_name, "levels": lv, "rules": {}}
    for rule in ("A", "B"):
        base = stagewise(spec, rule, 0, lv)
        res = {"as_designed": base, "trace": []}
        if base is None:
            res["note"] = "no skeleton satisfies the local specs within the template value ranges"
        step = 1 if (base is None or not base["search_passed"]) else -1
        last_pass, d = (base if base and base["search_passed"] else None), 0
        while abs(d) < 40:
            d += step
            r = stagewise(spec, rule, d, lv)
            res["trace"].append({"delta_db": d, "feasible": r is not None,
                                 "passed": bool(r and r["search_passed"]), "area": r and r["area"],
                                 "margin": r and r["search_margin_db"]})
            if step > 0 and r is not None and r["search_passed"]:
                last_pass = r
                break
            if step < 0:
                if r is not None and r["search_passed"]:
                    last_pass = r
                else:
                    break
        res["just_passing"] = last_pass
        out["rules"][rule] = res
    return out


def error_shares(spec_name, params):
    spec = SPECS[spec_name]

    def err(p):
        r = evaluate_program(T.code(p), spec_name, scenarios=[0])
        s = r["quality"]["scenarios"][0]
        return 10 ** (-s["snr_db"] / 10), s["snr_db"], s["snr_min_db"]
    e_opt, snr_opt, smin = err(params)
    floor = 10 ** (-(smin + spec.impl_loss_db) / 10)
    wide = dict(params, **T.WIDE)
    e_wide, snr_wide, _ = err(wide)
    groups = {"nco(P,A)": ("P", "A"), "mixer_word(Wm)": ("Wm",), "cic_word(Wc)": ("Wc",), "fir_coef(Cf)": ("Cf",)}
    if params["k"] > 1:
        groups["halfband(Ch,Wh)"] = ("Ch", "Wh")
    inc = {}
    for name, keys in groups.items():
        e, _, _ = err(dict(wide, **{k: params[k] for k in keys}))
        inc[name] = e - e_wide
    total = e_opt - floor
    shares = {"structure(alias+ripple+output word)": (e_wide - floor) / total}
    shares.update({k: v / total for k, v in inc.items()})
    return {"spec": spec_name, "snr_opt_db": snr_opt, "snr_all_wide_db": snr_wide, "snr_min_db": smin,
            "ceiling_db": smin + spec.impl_loss_db, "impl_error_rel_signal": total, "shares": shares,
            "sum_of_shares": float(sum(shares.values())),
            "equal_share_rule_A": 1.0 / (5 + 2 * (params["k"] - 1)), "params": params}


def main():
    out = Path(sys.argv[1])
    specs = [s.name for s in DEV_SPECS]
    with ProcessPoolExecutor(6) as ex:
        rows = list(ex.map(run_spec, specs))
    (out / "stagewise_results.json").write_text(json.dumps(rows, indent=1, default=float))
    meta = json.load(open(E / "p1_template_dev_v2_judge2_20261010/results.json"))["rows"]
    best = {}
    for s in specs:
        c = [r for r in meta if r["spec"] == s and r["best"]]
        best[s] = min(c, key=lambda r: r["best"]["area"])["best"]["params"]
    with ProcessPoolExecutor(6) as ex:
        sh = list(ex.map(error_shares, specs, [best[s] for s in specs]))
    (out / "error_shares_E22.json").write_text(json.dumps(sh, indent=1, default=float))
    for r in rows:
        for rule, v in r["rules"].items():
            a, j = v["as_designed"], v["just_passing"]
            print(r["spec"], rule, "as_designed:", a and (a["search_passed"], round(a["search_margin_db"], 2),
                                                         round(a["holdout_margin_db"], 2), round(a["area"])),
                  "just_passing:", j and (j["delta_db"], round(j["area"]), round(j["search_margin_db"], 2)))
    for s in sh:
        print(s["spec"], {k: round(v, 3) for k, v in s["shares"].items()}, "equal", round(s["equal_share_rule_A"], 3))


if __name__ == "__main__":
    main()
