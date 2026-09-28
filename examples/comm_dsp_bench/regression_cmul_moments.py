#!/usr/bin/env python3
"""复乘误差矩回归：模分解引理 helper vs 全枚举真值（RESEARCH_PLAN §9.3 第 1 项验收）。

背景（2026-09-27 修复前）：
  - certfit/common.py::_residue_dist 把 r=0（A≡0）混入 ν=0 奇数残差类，
    drop=1、half-up 时 direct helper 给 0.21875（真值 0.375）；
  - cmul_exact_err_moments 的 karatsuba 分支把 P1=(a+b)(c+d) 与 A、B 按
    独立项卷积（忽略共享操作数的相关性），drop=1 给 0.2890625。

验收内容（全部必须通过）：
  R1  φ/量化器一致性：_phi(r) == Q(v) − v（含负数、平局）；
  R2  残差分布：_residue_dist 与 (a,c) mod 2^s 全枚举频数一致，且和为 1；
  R3  小位宽全枚举：nbits ∈ {4,5,6}，s ∈ [1, nbits-1]，两种舍入 × 两种结构，
      helper 矩 == 全枚举矩（rel tol 1e-9）；
  R4  结构等价：中间结果精确时 direct 与 karatsuba 输出位恒等，
      误差矩相等（这是 ε-等价类的直接推论）；
  R5  基准锚点：drop=1、rne → E[e²] = 0.375（两种结构）；
  R6  生产位宽抽查：nbits=16 大样本蒙特卡罗与 helper 一致（rel tol 1%）。

运行：python regression_cmul_moments.py
退出码 0 = 全部通过；JSON 报告写入 experiments_system/s0_model_fix/。
"""

from __future__ import annotations

import itertools
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from certfit import common  # noqa: E402

REPORT_DIR = os.path.join(HERE, "experiments_system", "s0_model_fix")


def quant(v: np.ndarray, s: int, mode: str) -> np.ndarray:
    """与 common.quant_rne/quant_trunc 一致的向量化量化（保持 2^s 倍数）。"""
    if s <= 0:
        return v
    if mode == "trunc":
        return (v >> s) << s
    return ((v + (1 << (s - 1))) >> s) << s


def check_r1_phi_quantizer() -> dict:
    """R1: φ(r, s, mode) == Q(v) − v 对所有残差类与正负样本成立。"""
    worst = 0
    for s in range(1, 9):
        for mode in ("rne", "trunc"):
            rng = np.random.default_rng(20260927)
            for r in range(1 << s):
                v = rng.integers(-(1 << 12), 1 << 12, size=64) * (1 << s) + r
                q = quant(v, s, mode)
                e = q - v
                phi_r = common._phi(r, s, mode)
                # 同一残差类的误差必须恒等于 φ(r)
                assert int(np.max(np.abs(e - phi_r))) == 0, (
                    f"R1 FAIL s={s} mode={mode} r={r}: "
                    f"e 范围 [{e.min()},{e.max()}] φ={phi_r}")
    assert worst == 0, f"R1 FAIL: φ 与量化器语义最大偏差 {worst}"
    return {"status": "pass", "max_abs_dev": worst}


def check_r2_residue_dist() -> dict:
    """R2: _residue_dist(s, nbits) 与 (a,c) mod 2^s 全枚举频数一致。"""
    worst = 0.0
    for nbits in (4, 6, 8):
        for s in range(1, nbits):
            dist = common._residue_dist(s, nbits)
            assert abs(dist.sum() - 1.0) < 1e-12, f"分布和 {dist.sum()} != 1"
            m = 1 << s
            a = np.arange(m)
            tall = np.bincount(((a[:, None] * a[None, :]) % m).ravel(),
                               minlength=m).astype(float) / (m * m)
            worst = max(worst, float(np.max(np.abs(dist - tall))))
    assert worst < 1e-12, f"R2 FAIL: 残差分布最大偏差 {worst}"
    return {"status": "pass", "max_abs_dev": worst}


def enumerate_moments(nbits: int, s: int, mode: str) -> dict:
    """小位宽全枚举：a,b,c,d 独立均匀于 [−2^(nbits-1), 2^(nbits-1))。

    返回 direct/karatsuba 各自 re/im 的 (E[e], E[e²])，并验证两种结构的
    im 在整数域位恒等。
    """
    lo, hi = -(1 << (nbits - 1)), 1 << (nbits - 1)
    vals = [np.arange(lo, hi, dtype=np.int64)] * 2  # a、b 扫描用
    acc = {k: [0.0, 0.0] for k in ("re", "im_direct", "im_kar")}
    n_total = 0
    im_ident_max = 0
    for a in vals[0]:
        for b in vals[1]:
            c = np.arange(lo, hi, dtype=np.int64)
            A, B, C, D = np.meshgrid(a, b, c, c, indexing="ij")
            # A 对应 a 固定、B 对应 b 固定、C/D 独立扫描
            re = A * C - B * D
            im_d = A * D + B * C
            im_k = (A + B) * (C + D) - A * C - B * D
            im_ident_max = max(im_ident_max, int(np.max(np.abs(im_k - im_d))))
            for key, v in (("re", re), ("im_direct", im_d), ("im_kar", im_k)):
                e = quant(v, s, mode) - v
                acc[key][0] += float(e.astype(np.float64).sum())
                acc[key][1] += float((e.astype(np.float64) ** 2).sum())
            n_total += re.size
    assert im_ident_max == 0, f"direct/karatsuba im 位恒等被破坏: {im_ident_max}"
    out = {}
    for key in ("re", "im_direct", "im_kar"):
        out[key] = (acc[key][0] / n_total, acc[key][1] / n_total)
    return out


def check_r3_r4_r5_exhaustive() -> dict:
    """R3/R4/R5: 全枚举 vs helper、结构等价、基准锚点。"""
    rows = []
    worst_rel = 0.0
    for nbits in (4, 5, 6):
        for s in range(1, nbits):
            for mode in ("rne", "trunc"):
                enum = enumerate_moments(nbits, s, mode)
                for kar in (False, True):
                    m = common.cmul_exact_err_moments(
                        s, mode=mode, karatsuba=kar, nbits=nbits)
                    pairs = [
                        ("re_mean", enum["re"][0], m["re_mean"]),
                        ("re_mom2", enum["re"][1], m["re_mom2"]),
                        ("im_mean", enum["im_direct"][0], m["im_mean"]),
                        ("im_mom2", enum["im_direct"][1], m["im_mom2"]),
                    ]
                    for name, truth, got in pairs:
                        denom = max(abs(truth), 1e-12)
                        rel = abs(got - truth) / denom
                        worst_rel = max(worst_rel, rel)
                        assert rel < 1e-9, (
                            f"R3 FAIL nbits={nbits} s={s} mode={mode} "
                            f"karatsuba={kar} {name}: enum={truth} helper={got}")
                # R4: direct 与 karatsuba 误差矩相等（结构等价）
                md = common.cmul_exact_err_moments(s, mode=mode, karatsuba=False, nbits=nbits)
                mk = common.cmul_exact_err_moments(s, mode=mode, karatsuba=True, nbits=nbits)
                for name in ("re_mean", "re_mom2", "im_mean", "im_mom2"):
                    assert abs(md[name] - mk[name]) < 1e-12, (
                        f"R4 FAIL nbits={nbits} s={s} mode={mode} {name}")
                # 全枚举的 im_kar 与 im_direct 矩也应一致（同一输出的两条路径）
                assert abs(enum["im_direct"][1] - enum["im_kar"][1]) < 1e-12
                rows.append({"nbits": nbits, "s": s, "mode": mode,
                             "enum_re_mom2": enum["re"][1],
                             "enum_im_mom2": enum["im_direct"][1],
                             "helper_re_mom2": md["re_mom2"]})
    # R5: 基准锚点 drop=1 rne → 0.375（16 位操作数口径）
    m1d = common.cmul_exact_err_moments(1, mode="rne", karatsuba=False)
    m1k = common.cmul_exact_err_moments(1, mode="rne", karatsuba=True)
    assert abs(m1d["re_mom2"] - 0.375) < 1e-12, f"R5 FAIL direct={m1d['re_mom2']}"
    assert abs(m1k["im_mom2"] - 0.375) < 1e-12, f"R5 FAIL karatsuba={m1k['im_mom2']}"
    return {"status": "pass", "worst_rel_err": worst_rel, "rows": rows,
            "anchor_drop1_rne": {"direct": m1d["re_mom2"], "karatsuba": m1k["im_mom2"],
                                 "expected": 0.375}}


def check_r6_mc_16bit() -> dict:
    """R6: 生产位宽（nbits=16）蒙特卡罗抽查，rel tol 1%。"""
    rng = np.random.default_rng(20260927)
    n = 1 << 22
    worst_rel = 0.0
    for s in (1, 4, 8, 12, 15):
        pts = common.lattice_points(n, [1 << 16] * 4)
        a = pts[:, 0] - (1 << 15)
        b = pts[:, 1] - (1 << 15)
        c = pts[:, 2] - (1 << 15)
        d = pts[:, 3] - (1 << 15)
        re = a * c - b * d
        im = a * d + b * c
        for name, v in (("re", re), ("im", im)):
            e = (quant(v, s, "rne") - v).astype(np.float64)
            mc = float((e ** 2).mean())
            m = common.cmul_exact_err_moments(s, mode="rne")
            ref = m["re_mom2"] if name == "re" else m["im_mom2"]
            rel = abs(mc - ref) / ref
            worst_rel = max(worst_rel, rel)
            assert rel < 0.01, f"R6 FAIL s={s} {name}: mc={mc} helper={ref} rel={rel}"
    return {"status": "pass", "worst_rel_err": worst_rel, "n_samples": n}


def main() -> int:
    os.makedirs(REPORT_DIR, exist_ok=True)
    checks = {}
    ok = True
    for name, fn in (("R1_phi_quantizer", check_r1_phi_quantizer),
                     ("R2_residue_dist", check_r2_residue_dist),
                     ("R3_R4_R5_exhaustive", check_r3_r4_r5_exhaustive),
                     ("R6_mc_16bit", check_r6_mc_16bit)):
        try:
            checks[name] = fn()
            print(f"[PASS] {name}: {json.dumps(checks[name], ensure_ascii=False)[:160]}")
        except AssertionError as exc:
            ok = False
            checks[name] = {"status": "fail", "detail": str(exc)}
            print(f"[FAIL] {name}: {exc}")

    summary = {
        "date": "2026-09-27",
        "target": "certfit/common.py cmul_exact_err_moments / _residue_dist",
        "all_pass": ok,
        "checks": checks,
    }
    path = os.path.join(REPORT_DIR, "regression_cmul_moments.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"报告已写入 {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
