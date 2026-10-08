#!/usr/bin/env python3
"""CONTRACT_CIC_WITNESS_v1 §4 生成规则的实现：展开 28 行候选表并做四项静态检查。

本脚本只做候选表展开与静态检查（数量/单调性/窗口合法性/blocker Nyquist），
不计算任何链级 q，不写预检 manifest（那是终冻前实现步骤的产物）。

H 类按 Hogenauer 1981 §IV-C 式 (21) 实现（文献复现测试钉定，见
tests/test_cic_hogenauer.py）：误差源位于每一级输入的锁存器，方差增益
G_j = 等效 FIR 系数平方和（整数精确）；预算为每个级间源到输出的方差贡献
不超过输出寄存器误差的 1/(2N)：
    B_j = max{ b >= 0 : G_j·(2N)·2^(2b) <= 2^(2·B_fmt) }，
负值钳 0，再做反向累计最小（含输出边界 B_{2N+1} = B_fmt）保证非递减且
不超过任何一级自身误差上界。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

B_IN = 12          # W_adc：输入 Q1.11 位宽
W_OUT = 16         # 输出 Q1.15 字宽
F_SIG_KHZ = 169.0
COMBOS = [(2, 3), (2, 4), (4, 3), (4, 4)]


def poly_mul(a: list[int], b: list[int]) -> list[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def poly_norm2(p: list[int]) -> int:
    return sum(x * x for x in p)


def eq21_gain(R: int, N: int, source: int) -> int:
    """式 (21) 的 G_j = Σ h_j[k]²（源位于每一级输入，整数精确，§4.1-1）。

    积分器级输入 j=1..N：h_j = (1−z^-1)^(j−1)·(Σ_R)^N；
    梳状器级输入 j=N+1..2N：h_j = (1−z^-1)^(2N−j+1)（j=N+1 为抽取边界锁存，
    与积分器公式在 (1−z)^N(Σ_R)^N = (1−z^-R)^N 处连续）。
    """
    if source <= N:
        a, b = source - 1, N
    else:
        a, b = 2 * N - source + 1, 0
    poly = [1] * R if b > 0 else [1]
    for _ in range(b - 1):
        poly = poly_mul(poly, [1] * R)
    for _ in range(a):
        poly = poly_mul(poly, [1, -1])
    return poly_norm2(poly)


def hogenauer_profile(
    R: int, N: int, W_ADC: int = B_IN, W_OUT: int = W_OUT
) -> tuple[list[int], int, int, list[dict]]:
    """§4.1-2..3：论文式 (21) 程序，返回 (B_1..B_2N, B_fmt, W_full, clamp_log)。

    输出寄存器（第 2N+1 源）丢位数由格式唯一决定：B_fmt = W_full − W_OUT；
    每个级间源贡献 ≤ 其 1/(2N)：B_j = max{ b ≥ 0 : G_j·(2N)·2^(2b) ≤ 2^(2·B_fmt) }，
    负值钳到 0，再从后向前做累计最小收紧。
    """
    growth = math.ceil(N * math.log2(R))
    W_full = W_ADC + growth
    B_fmt = W_full - W_OUT
    B: list[int] = []
    clamp_log: list[dict] = []
    for j in range(1, 2 * N + 1):
        G = eq21_gain(R, N, j)
        raw = -1
        b = B_fmt - 1  # G·(2N) ≥ 2，故 b ≤ B_fmt − 1
        while b >= 0:
            if G * (2 * N) * (1 << (2 * b)) <= (1 << (2 * B_fmt)):
                raw = b
                break
            b -= 1
        val = max(raw, 0)
        if raw < 0:
            clamp_log.append({"j": j, "raw": raw, "reason": "negative_clamped_to_0"})
        B.append(val)
    # 反向累计最小（边界 = max(B_fmt, 0)：B_fmt < 0 时输出锁存比内部网格更细，
    # 末级无裁剪、不构成单调上界）：非递减且不超过任何一级自身误差上界
    nxt = max(B_fmt, 0)
    for j in range(2 * N, 0, -1):
        if B[j - 1] > nxt:
            B[j - 1] = nxt
            clamp_log.append({"j": j, "reason": "lowered_backward_monotonic"})
        nxt = B[j - 1]
    return B, B_fmt, W_full, clamp_log


def expand() -> list[dict]:
    rows = []
    for R, N in COMBOS:
        W_full = B_IN + math.ceil(N * math.log2(R))
        B_max = W_full - 1
        tag = f"R{R}N{N}"
        # H 类
        B, B_fmt, _, clamps = hogenauer_profile(R, N)
        rows.append({"name": f"comp_H_{tag}", "class": "H", "R": R, "N": N,
                     "B": B, "B_fmt": B_fmt, "overflow": "wrap", "rounding": "rne",
                     "hogenauer_clamps": clamps})
        # U 类：c ∈ {0,1,2}
        for c in (0, 1, 2):
            rows.append({"name": f"comp_U{c}_{tag}", "class": "U", "R": R, "N": N,
                         "B": [c] * (2 * N), "B_fmt": B_fmt,
                         "overflow": "wrap", "rounding": "rne"})
        # T 类：(2,4) 与 (4,4)，α ∈ {2,4} 的线性递减宽度剖面
        if (R, N) in ((2, 4), (4, 4)):
            for alpha in (2, 4):
                w = [W_full - round(alpha * (j) / (2 * N - 1)) for j in range(2 * N)]
                Bt = [B_max + 1 - wj for wj in w]
                rows.append({"name": f"comp_T{alpha}_{tag}", "class": "T", "R": R, "N": N,
                             "B": Bt, "B_fmt": B_fmt, "overflow": "wrap", "rounding": "rne"})
        # O 类：H 档 sat
        rows.append({"name": f"comp_O_{tag}", "class": "O", "R": R, "N": N,
                     "B": list(B), "B_fmt": B_fmt, "overflow": "sat", "rounding": "rne"})
        # RND 类：H 档 trunc
        rows.append({"name": f"comp_RND_{tag}", "class": "RND", "R": R, "N": N,
                     "B": list(B), "B_fmt": B_fmt, "overflow": "wrap", "rounding": "trunc"})
    return rows


def static_checks(rows: list[dict]) -> dict:
    problems = []
    # 1) 数量
    if len(rows) != 28:
        problems.append(f"count={len(rows)} != 28")
    # 2) B_j 非递减 + 3) 窗口合法
    for r in rows:
        W_full = B_IN + math.ceil(r["N"] * math.log2(r["R"]))
        B_max = W_full - 1
        for j in range(1, len(r["B"])):
            if r["B"][j] < r["B"][j - 1]:
                problems.append(f"{r['name']}: B 非递减违反 @j={j}")
                break
        for j, Bj in enumerate(r["B"], 1):
            w = B_max - Bj + 1
            if not (1 <= w <= W_full) or Bj < 0:
                problems.append(f"{r['name']}: 窗口非法 j={j} B={Bj} w={w}")
                break
    # 4) blocker 频率
    scen = []
    for R, grid in ((2, [200, 250, 300, 350, 400, 450]), (4, [180, 195, 210, 225, 240, 248])):
        fs_out, fs_in = 2_000_000.0 / R, 2_000_000.0
        for g in grid:
            f_b = (fs_out - g * 1e3) if R == 2 else (fs_out + g * 1e3)
            scen.append((R, g, f_b))
    for R, g, f_b in scen:
        if not (F_SIG_KHZ * 1e3 < f_b < 1_000_000.0):
            problems.append(f"blocker 非法 R={R} g={g} f_b={f_b}")
    return {"count": len(rows), "n_blockers_checked": len(scen), "problems": problems,
            "blockers": scen}


def main() -> int:
    rows = expand()
    checks = static_checks(rows)
    out = {"schema_version": "cic-candidate-gen-v1-draft", "rows": rows,
           "static_checks": checks}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if not checks["problems"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
