"""规则/传统基线（链路 A）：教科书结构 + 解析指标推导 + 经典贪心字长优化，不使用 LLM。

结构（Hogenauer 1981；Harris, Multirate Signal Processing, 2004）：
  全速 CORDIC 旋转混频（象限预旋转 + K 级流水，USRP 同类结构；直接查表的 NCO 在 45 dB 强干扰下需要超过 2^16 项，
  已验证不可行）→ N 阶 CIC 抽取 R1 = R/4（寄存器位宽按 Hogenauer 满量程界，模运算）
  → 半带 FIR 抽 2（Kaiser 窗）→ CIC 补偿 FIR 抽 2（firls，补偿 CIC 通带下垂）→ 输出移位。
指标推导：
  混叠抑制要求 A 取方法二的门槛（单个干扰相对功率 + 理想 SNR + 10·log10(1/p)）再加 3 dB；
  CIC 阶数 N 取使 |H_cic(f_s1 − f_p)| ≤ −A 的最小值；半带与补偿 FIR 的抽头数按 Kaiser 公式由 A 与过渡带估算。
字长优化（经典贪心，max−1）：从足够宽的字长出发，依次尝试把每个字长减 1，若候选仍 FEASIBLE 且代理面积下降则接受，
  直到一轮中没有任何改进。判定与候选程序使用同一个 verdict.search。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

PROGRAM = r'''
P = __PARAMS__


def build(g, spec):
    R, fp = spec.r_total, spec.passband
    R1, N = P["R1"], P["N"]
    x = g.input()
    ph = g.counter(spec.fcw, 32)
    K, cw, zw = P["cordic_stages"], P["cordic_w"], P["cordic_zw"]
    with g.scope("cordic"):                     # 下变频：把 (x, 0) 旋转 −θ，θ = 相位（单位：周）
        quad = g.bits(ph, 31, 30)               # 象限：先按 −90° 的整数倍精确旋转（交换与取负）
        b1, b0 = g.bits(quad, 1, 1), g.bits(quad, 0, 0)
        zero = g.const(0.0, 2, 1)
        xa = g.q(x, cw, cw - 2)
        nx = g.neg(xa)
        # 象限 0:(x,0) 1:(0,−x) 2:(−x,0) 3:(0,x)
        xi = g.mux(b0, zero, g.mux(b1, nx, xa))
        yi = g.mux(b0, g.mux(b1, xa, nx), zero)
        xi, yi = g.q(xi, cw, cw - 2), g.q(yi, cw, cw - 2)
        r = g.bits(ph, 29, 30 - zw)            # 余下角度 ∈ [0, 1/4) 周，无符号
        z = g.q(g.neg(g.shift(r, -(zw + 2))), zw + 3, zw + 2)   # z0 = −r（单位：周），有符号，范围 ±1/2 周
        for k in range(K):
            neg = g.bits(z, z.w - 1, z.w - 1)  # z < 0 → 向负方向旋转
            xs, ys = g.shift(xi, -k), g.shift(yi, -k)
            ang = math.atan(2.0 ** -k) / (2 * math.pi)
            xn = g.mux(neg, g.add(xi, ys), g.sub(xi, ys))
            yn = g.mux(neg, g.sub(yi, xs), g.add(yi, xs))
            zn = g.mux(neg, g.add(z, g.const(ang, zw + 3, zw + 2)), g.sub(z, g.const(ang, zw + 3, zw + 2)))
            xi, yi = g.reg(g.q(xn, cw, cw - 2, "trunc")), g.reg(g.q(yn, cw, cw - 2, "trunc"))
            z = g.reg(g.q(zn, zw + 3, zw + 2))
        Kc = 1.0
        for k in range(K):
            Kc *= math.sqrt(1 + 2.0 ** (-2 * k))
    mw = P["mix_w"]
    with g.scope("mixer"):                       # CORDIC 增益补偿（常数乘）
        br = [g.reg(g.q(g.scale(xi, 1.0 / Kc, 16), mw, mw - 2)), g.reg(g.q(g.scale(yi, 1.0 / Kc, 16), mw, mw - 2))]
    out = []
    for k, y in enumerate(br):
        with g.scope("cic"):
            Wc = y.w + N * int(round(math.log2(R1)))              # Hogenauer 满量程界
            for _ in range(N):
                y = g.integrate(y, Wc)
            y = g.decimate(y, R1)
            for _ in range(N):
                y = g.reg(g.q(g.sub(y, g.delay(y, 1)), Wc, y.f, ovf="wrap"))
            y = g.q(g.shift(y, -N * int(round(math.log2(R1)))), P["cic_w"], P["cic_w"] - 2)
        with g.scope("halfband"):
            y = g.mac(list(zip(g.delay_line(y, len(P["h_hb"])), P["h_hb"])), coef_bits=P["hb_coef"], share=P.get("hb_share", 1))
            y = g.decimate(g.reg(g.q(y, P["hb_w"], P["hb_w"] - 2)), 2)
        with g.scope("comp_fir"):
            y = g.mac(list(zip(g.delay_line(y, len(P["h_fir"])), P["h_fir"])), coef_bits=P["fir_coef"], share=P.get("fir_share", 1))
            y = g.decimate(g.reg(g.q(y, P["fir_w"], P["fir_w"] - 2)), 2)
        with g.scope("output"):
            b = spec.output_bits
            out.append(g.q(g.shift(y, P["out_shift"]), b, b - 1))
    g.output(out[0], out[1])
'''


def design(task_name: str, extra_hb: int = 0, extra_fir: int = 0) -> dict:
    """由规格解析推出结构参数与滤波器系数（不经搜索）。extra_*：定尺寸阶段追加的抽头数。"""
    import scipy.signal as ss
    from ..task import get
    from ..verdict import alias_requirement, _contract
    t = get(task_name)
    p = t.params
    R, fp = int(p["r_total"]), float(p["passband"])
    A = alias_requirement(t, _contract(task_name)) + 3.0
    R1 = R // 4
    fs1 = 1.0 / R1
    f = fs1 - fp                                                    # CIC 第一混叠带的最近边缘
    N = 1
    while 20 * math.log10(abs(math.sin(math.pi * f * R1) / (R1 * math.sin(math.pi * f)))) * N > -A and N < 12:
        N += 1
    # 半带：在 fs1 速率上设计，截止 fs1/4，Kaiser 窗（抽头数与窗参数由衰减 A 和过渡带直接算出）
    wp, ws = fp / fs1, 0.5 - fp / fs1
    L, beta = ss.kaiserord(A, (ws - wp) / 0.5)
    L = L + extra_hb
    L = L + (3 - L % 4) % 4                                          # 4K+3
    h_hb = ss.firwin(L, 0.25, window=("kaiser", beta), fs=1.0)
    # 补偿 FIR：在 fs2 = fs1/2 速率上设计，通带 fp 内按 1/|H_cic| 补偿，阻带从 fo − fp 起（抽头数按 Kaiser 公式）
    fs2 = fs1 / 2
    fo = 1.0 / R
    wp2, ws2 = fp / fs2, (fo - fp) / fs2
    L2, beta2 = ss.kaiserord(A, (ws2 - wp2) / 0.5)
    L2 = (L2 + extra_fir) | 1

    def hcic(fin):                     # CIC 在输入速率下的幅频（f 以输入采样率为单位）
        return 1.0 if fin == 0 else abs(math.sin(math.pi * fin * R1) / (R1 * math.sin(math.pi * fin))) ** N
    # firls：通带按 1/|H_cic| 线性补偿（两端点取通带两端的补偿值），阻带加大权重
    seg = np.linspace(0, wp2, 17)          # 通带分 16 段逼近精确的 1/|H_cic|（firls 分段线性）
    bands, des = [], []
    for a, b in zip(seg[:-1], seg[1:]):
        bands += [a, b]
        des += [1.0 / hcic(a * fs2), 1.0 / hcic(b * fs2)]
    bands += [ws2, 0.5]
    des += [0.0, 0.0]
    h_fir = ss.firls(L2, bands, des, weight=[1] * 16 + [100], fs=1.0)
    h_fir = h_fir / np.sum(h_fir)
    h_hb = h_hb / np.sum(h_hb)
    return {"R1": R1, "N": N, "A_target_db": A, "h_hb": [float(v) for v in h_hb], "h_fir": [float(v) for v in h_fir]}


START = {"cordic_stages": 24, "cordic_w": 28, "cordic_zw": 26, "mix_w": 28, "cic_w": 30, "hb_coef": 26, "hb_w": 30,
         "fir_coef": 26, "fir_w": 28, "out_shift": 7}
ORDER = ("cordic_stages", "cordic_w", "cordic_zw", "mix_w", "cic_w", "hb_coef", "hb_w", "fir_coef", "fir_w")


def program(params: dict) -> str:
    return PROGRAM.replace("__PARAMS__", json.dumps(params))


def optimize(task_name: str, log: Path) -> dict:
    """定尺寸（规则：混叠抑制不足则加抽头，否则加 CORDIC 级数与位宽，直到可行）→ 贪心字长优化（max−1）。"""
    from ..verdict import search
    hist = []
    eh, ef = 0, 0
    cur = dict(START)

    def ev(pp, phase):
        r = search(program(pp), task_name)
        rec = {"phase": phase, "params": {k: pp[k] for k in ORDER}, "taps": [len(pp["h_hb"]), len(pp["h_fir"])],
               "N": pp["N"], "verdict": r["verdict"], "v": r.get("v"), "area_est": (r.get("objectives") or {}).get("area_est"),
               "constraints": {k["name"]: k["slack"] for k in r.get("constraints", [])},
               "floor_limited": any("note" in k for k in r.get("constraints", []))}
        hist.append(rec)
        log.write_text(json.dumps({"history": hist}, ensure_ascii=False, indent=1))
        return rec
    for _ in range(16):                      # 定尺寸
        cur.update(design(task_name, eh, ef))
        r = ev(cur, "sizing")
        if r["verdict"] == "FEASIBLE":
            break
        c = r["constraints"]
        if c.get("alias_rejection", 99) < 1.0 and not r["floor_limited"]:
            eh, ef = eh + 4, ef + 2
        elif cur["cordic_w"] < 40:             # 精度不足：所有字长整体加 2 位，CORDIC 加 2 级
            for k in ORDER:
                cur[k] += 2
        else:
            eh, ef = eh + 4, ef + 2
    else:
        return {"feasible": False, "history_len": len(hist)}
    best = r
    improved = True
    while improved:                          # 贪心字长优化
        improved = False
        for k in ORDER:
            while True:
                cand = dict(cur)
                cand[k] -= 1
                r = ev(cand, "wlo")
                if r["verdict"] == "FEASIBLE" and r["area_est"] < best["area_est"]:
                    cur, best, improved = cand, r, True
                else:
                    break
    return {"feasible": True, "best": best, "params": cur, "evaluations": len(hist)}


if __name__ == "__main__":
    task = sys.argv[1]
    out = Path(sys.argv[2])
    res = optimize(task, out.with_suffix(".log.json"))
    if res.get("feasible"):
        Path(out.with_suffix(".py")).write_text(program(res["params"]))
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: res[k] for k in res if k != "params"}, ensure_ascii=False, default=str))
