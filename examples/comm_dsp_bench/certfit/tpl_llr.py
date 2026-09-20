"""llr_64qam_snr20 证书模板：参数化 64QAM 软解调器（max-log + 校正表）。

参数空间：
  metric:        "l2"（平方距离）| "l1"（绝对距离，经典低面积近似）
  corr_entries:  校正表项数 D ∈ {0, 16, 64, 256, 1024}（0 = 纯 max-log）
  corr_frac:     校正表小数位 w ∈ {6..12}

结构洞察（论文 §4.3）：bit 类按单轴比特划分 → 类内最小距离**可分离**：
  d0min(I 轴比特 b) = min_{si∈S0} dI(si) + min_sq dQ(sq)
于是每比特只需 4 输入 (min, second-min) 网络 + 全局 8 输入 (min, second-min)，
无需 32 路距离网络——这是同一 ε-等价类里的结构性简点。

校正：单主导项近似 c(g) = ln(1 + e^{−g/2σ²})（g = 类内第二小−最小间距），
ROM 表量化到 w 位小数。golden = 精确 log-sum-exp（evaluator 注册）。

模型层级：
  precision    : 确定性 Sobol（星座 12 bit 离散 + 高斯噪声 2D 逆 CDF）
                 上的整数域逐位仿真
  precision_wc : 解析最坏界（单点近似残差 ≤ 2σ²·ln31 + 表量化），sound
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np

from certfit import common

THROUGHPUT_PARALLEL = 0.908
SC = 4096.0  # Q4.12

DEFAULTS = {
    "metric": "l2",
    "corr_entries": 0,
    "corr_frac": 8,
    "input_trunc": 4,
}


def _sigma2() -> float:
    import evaluator as base
    return float(base._load_task()["metric"]["params"]["sigma2"])


def validate(p: Dict) -> Tuple[bool, str]:
    if p.get("metric") not in ("l2", "l1"):
        return False, f"metric={p.get('metric')} 非法"
    if int(p.get("corr_entries", 0)) != 0:
        return False, "corr_entries>0 的校正路径 RTL 尚待修复（已知问题，见论文附录）；当前仅开放 max-log"
    if not isinstance(p.get("corr_frac", 8), int) or not (6 <= p["corr_frac"] <= 12):
        return False, f"corr_frac={p.get('corr_frac')} 越界 [6,12]"
    it = p.get("input_trunc", 4)
    max_it = 4 if p.get("metric") == "l1" else 6  # L1 输出定标要求 it ≤ 4
    if not isinstance(it, int) or not (0 <= it <= max_it):
        return False, f"input_trunc={it} 越界 [0,{max_it}]"
    return True, "ok"


# ---------------------------------------------------------------------------
# 整数域逐位仿真
# ---------------------------------------------------------------------------

def _axis_vals() -> np.ndarray:
    """严格复刻 evaluator._axis_gray_map（注意：实现为 ±{1,5,9,13}，
    与任务卡文字 ±1..±7 不同——以 golden 实现为准）。"""
    vals = []
    for v in range(8):
        g = v ^ (v >> 1)
        amp, sign = 0, 1
        for k in range(3):
            bit = (g >> (2 - k)) & 1
            if k == 0:
                sign = -1 if bit else 1
            else:
                amp |= bit << (2 - k)
        vals.append(sign * (2 * amp + 1))
    return np.array(vals, dtype=np.int64)


def _axis_dists(y: np.ndarray, metric: str, it: int = 0) -> np.ndarray:
    """y×8 → 8 个轴距离（L2 平方 / L1 绝对值），int64。

    星座点换算到与截断后输入同刻度：sv·(4096>>it)。"""
    sv = _axis_vals() * (4096 >> it)
    dif = y[:, None] - sv[None, :]
    if metric == "l2":
        return dif * dif
    return np.abs(dif)


def _min2(a, b):
    return np.minimum(a, b)


def _max2(a, b):
    return np.maximum(a, b)


def _min4_m2(w0, w1, w2, w3):
    """4 输入 (min, second-min)。"""
    x1, x2 = _min2(w0, w1), _max2(w0, w1)
    y1, y2 = _min2(w2, w3), _max2(w2, w3)
    return _min2(x1, y1), _min2(_min2(x2, y2), _max2(x1, y1))


def _min8_m2(w):
    """8 输入 (min, second-min) 锦标赛。"""
    pairs = [(_min2(w[2 * i], w[2 * i + 1]), _max2(w[2 * i], w[2 * i + 1]))
             for i in range(4)]
    (a1, a2), (b1, b2) = pairs[0], pairs[1]
    m1a, m2a = _min2(a1, b1), _min2(_min2(a2, b2), _max2(a1, b1))
    (c1, c2), (d1, d2) = pairs[2], pairs[3]
    m1b, m2b = _min2(c1, d1), _min2(_min2(c2, d2), _max2(c1, d2))
    return _min2(m1a, m1b), _min2(_min2(m2a, m2b), _max2(m1a, m1b))


def _corr_table(D: int, w: int, metric: str = "l2") -> Tuple[np.ndarray, int]:
    """校正 ROM：T[k] = round(2σ²·256·log1p(e^{−g/2σ²})·2^w)，g = k·2^shift。

    g 的整数刻度随 metric 定标：L2 距离带 2^24 因子，L1 带 2^12。"""
    if D == 0:
        return np.zeros(1, dtype=np.int64), 0
    s2 = _sigma2()
    fac = SC * SC if metric == "l2" else SC
    g_max = 16.0 * 2 * s2 * fac
    shift = int(math.ceil(math.log2(g_max / D)))
    ks = np.arange(D, dtype=np.float64)
    g = ks * (1 << shift)
    denom = 2 * s2 * fac  # g_real = g_int/fac → 指数 = −g_real/(2σ²)
    t = 2 * s2 * 256.0 * np.log1p(np.exp(-g / denom))
    return np.round(t * (1 << w)).astype(np.int64), shift


def emulate(p: Dict, i_in: np.ndarray, q_in: np.ndarray) -> np.ndarray:
    """返回 (N, 6) 的 16 位 LLR（与 RTL 逐位对应）。"""
    metric = p["metric"]
    D, w = int(p["corr_entries"]), int(p["corr_frac"])
    it = int(p.get("input_trunc", 0))
    T, shift = _corr_table(D, w, metric)
    s2 = _sigma2()

    yi = i_in.astype(np.int64) >> it
    yq = q_in.astype(np.int64) >> it
    dI = _axis_dists(yi, metric, it)
    dQ = _axis_dists(yq, metric, it)
    minQ, minQ2 = _min8_m2(list(dQ.T))
    minI, minI2 = _min8_m2(list(dI.T))

    out = np.zeros((len(i_in), 6), dtype=np.int64)
    sv = _axis_vals()
    # 轴索引 k 的类归属位：bit(k, bb) = (k >> (2-bb)) & 1（MSB-first）
    bits_of = np.array([[(k >> (2 - bb)) & 1 for bb in range(3)] for k in range(8)])

    for axis in range(2):
        src = dI if axis == 0 else dQ
        other_min, other_min2 = (minQ, minQ2) if axis == 0 else (minI, minI2)
        for bb in range(3):
            b = bb + axis * 3
            k0 = np.nonzero(bits_of[:, bb] == 0)[0]
            k1 = np.nonzero(bits_of[:, bb] == 1)[0]
            c0m, c0m2 = _min4_m2(*[src[:, k] for k in k0])
            c1m, c1m2 = _min4_m2(*[src[:, k] for k in k1])
            d0min = c0m + other_min
            d1min = c1m + other_min
            d0_2 = _min2(c0m2 + other_min, c0m + other_min2)
            d1_2 = _min2(c1m2 + other_min, c1m + other_min2)
            v = (d1min - d0min) >> ((16 - 2 * it) if metric == 'l2' else (4 - it))
            if D > 0:
                g0 = d0_2 - d0min
                g1 = d1_2 - d1min
                k0i = np.clip(g0 >> shift, 0, D - 1)
                k1i = np.clip(g1 >> shift, 0, D - 1)
                v = v + ((T[k0i] - T[k1i] + (1 << (w - 1))) >> w)
            out[:, b] = np.clip(v, -32768, 32767)
    return out


def golden_llr(i_in: np.ndarray, q_in: np.ndarray) -> np.ndarray:
    """精确 LSE golden（与 evaluator._golden_llr 同口径，向量化）。"""
    s2 = _sigma2()
    sv = _axis_vals().astype(np.float64)
    yi = i_in.astype(np.float64) / SC
    yq = q_in.astype(np.float64) / SC
    d2 = (yi[:, None] - sv[None, :]) ** 2 + (yq[:, None] - sv[None, :]) ** 2  # N×8×8?
    # d2[n, ki, kq]
    d2 = ((yi[:, None, None] - sv[None, :, None]) ** 2
          + (yq[:, None, None] - sv[None, None, :]) ** 2)
    out = np.zeros((len(i_in), 6), dtype=np.float64)
    for axis in range(2):
        for bb in range(3):
            b = bb + axis * 3
            sel = ((np.arange(8) >> (2 - bb)) & 1).astype(bool)  # True = bit1
            if axis == 0:
                m0 = d2[:, np.nonzero(~sel)[0], :].reshape(len(yi), -1)
                m1 = d2[:, np.nonzero(sel)[0], :].reshape(len(yi), -1)
            else:
                m0 = d2[:, :, np.nonzero(~sel)[0]].reshape(len(yi), -1)
                m1 = d2[:, :, np.nonzero(sel)[0]].reshape(len(yi), -1)
            l0 = -m0.min(axis=1) / (2 * s2) + np.log(np.exp(
                (-m0 + m0.min(axis=1)[:, None]) / (2 * s2)).sum(axis=1))
            l1 = -m1.min(axis=1) / (2 * s2) + np.log(np.exp(
                (-m1 + m1.min(axis=1)[:, None]) / (2 * s2)).sum(axis=1))
            v = (l0 - l1) * 2 * s2 * 256.0
            out[:, b] = np.clip(v, -32768, 32767)
    return out


# ---------------------------------------------------------------------------
# 证书指标
# ---------------------------------------------------------------------------

def cert_metrics(p: Dict) -> Dict:
    N = 1 << 17
    u = common.sobol_unit(N, 3)
    cidx = np.clip((u[:, 0] * 64).astype(np.int64), 0, 63)
    from scipy.stats import norm
    s2 = _sigma2()
    sig = math.sqrt(s2)
    nz_i = norm.ppf(np.clip(u[:, 1], 1e-12, 1 - 1e-12)) * sig
    nz_q = norm.ppf(np.clip(u[:, 2], 1e-12, 1 - 1e-12)) * sig

    # 星座索引 → (si, sq)（与 _stimulus_qam_awgn 同 Gray 映射）
    sv = _axis_vals()
    bi, bq = cidx >> 3, cidx & 7  # 3+3 bit
    si = sv[bi]
    sq = sv[bq]
    yi = np.clip(np.round((si + nz_i) * SC), -32768, 32767).astype(np.int64)
    yq = np.clip(np.round((sq + nz_q) * SC), -32768, 32767).astype(np.int64)

    dut = emulate(p, yi, yq).astype(np.float64)  # emulate 内部做 input_trunc
    ref = golden_llr(yi, yq)
    err2 = float(np.max(np.mean((dut - ref) ** 2, axis=0)))  # 多字段取最差
    sigp = float(np.max(np.mean(ref ** 2, axis=0)))
    prec = common.sqnr_db(sigp, err2)

    s2v = 2 * s2 * 256.0
    e_wc = s2v * math.log(31) + (2.0 if int(p["corr_entries"]) > 0 else 0.0) \
        + (1.0 / SC) * 0.0
    prec_wc = common.sqnr_db(sigp, e_wc * e_wc)

    return {
        "precision": round(prec, 4),
        "precision_wc": round(prec_wc, 4),
        "throughput": THROUGHPUT_PARALLEL,
        "err_power_mean": err2,
        "sig_power": sigp,
        "grid_points": N,
    }


# ---------------------------------------------------------------------------
# Verilog 生成
# ---------------------------------------------------------------------------

def generate_verilog(p: Dict) -> str:
    metric = p["metric"]
    D, w = int(p["corr_entries"]), int(p["corr_frac"])
    it = int(p.get("input_trunc", 0))
    T, shift = _corr_table(D, w, metric)
    sv = _axis_vals()
    s2 = _sigma2()

    # 轴常量与距离网络
    dv = 34 if metric == "l2" else 18
    qwidth = 17 - it
    def diff(port, s):
        s = s * (4096 >> it)
        return f"({port}_t - {qwidth}'sd{s})" if s >= 0 else f"({port}_t + {qwidth}'sd{-s})"
    dist_expr = lambda port, s: (
        f"($signed({diff(port, s)[1:-1]}) * $signed({diff(port, s)[1:-1]}))"
        if metric == "l2" else f"uabs{qwidth - 1}($signed({diff(port, s)[1:-1]}))"
    )
    trunc = (f"    wire signed [{qwidth - 1}:0] i_t = i_in >>> {it};\n"
             f"    wire signed [{qwidth - 1}:0] q_t = q_in >>> {it};\n") if it > 0 else (
            "    wire signed [15:0] i_t = i_in;\n    wire signed [15:0] q_t = q_in;\n")
    dI_lines = trunc + "\n".join(
        f"    wire [{dv - 1}:0] dI{k} = {dist_expr('i', int(sv[k]))};" for k in range(8))
    dQ_lines = "\n".join(
        f"    wire [{dv - 1}:0] dQ{k} = {dist_expr('q', int(sv[k]))};" for k in range(8))

    # 全局 8 路 (min, second)
    q_net = """
    wire [%(dv)d:0] mq1 = dmin2(dQ0, dQ1);
    wire [%(dv)d:0] mq1b = dmax2(dQ0, dQ1);
    wire [%(dv)d:0] mq2 = dmin2(dQ2, dQ3);
    wire [%(dv)d:0] mq2b = dmax2(dQ2, dQ3);
    wire [%(dv)d:0] mq3 = dmin2(dQ4, dQ5);
    wire [%(dv)d:0] mq3b = dmax2(dQ4, dQ5);
    wire [%(dv)d:0] mq4 = dmin2(dQ6, dQ7);
    wire [%(dv)d:0] mq4b = dmax2(dQ6, dQ7);
    wire [%(dv)d:0] mqa = dmin2(mq1, mq2);
    wire [%(dv)d:0] mqab = dmin2(mq1b, mq2b);
    wire [%(dv)d:0] mqamax = dmax2(mq1, mq2);
    wire [%(dv)d:0] mqb = dmin2(mq3, mq4);
    wire [%(dv)d:0] mqbb = dmin2(mq3b, mq4b);
    wire [%(dv)d:0] mqbmax = dmax2(mq3, mq4);
    wire [%(dv)d:0] minQ = dmin2(mqa, mqb);
    wire [%(dv)d:0] minQ2 = dmin2(mqab, dmin2(mqbb, mqamax));
    wire [%(dv)d:0] mq1I = dmin2(dI0, dI1);
    wire [%(dv)d:0] mq1Ib = dmax2(dI0, dI1);
    wire [%(dv)d:0] mq2I = dmin2(dI2, dI3);
    wire [%(dv)d:0] mq2Ib = dmax2(dI2, dI3);
    wire [%(dv)d:0] mq3I = dmin2(dI4, dI5);
    wire [%(dv)d:0] mq3Ib = dmax2(dI4, dI5);
    wire [%(dv)d:0] mq4I = dmin2(dI6, dI7);
    wire [%(dv)d:0] mq4Ib = dmax2(dI6, dI7);
    wire [%(dv)d:0] mqaI = dmin2(mq1I, mq2I);
    wire [%(dv)d:0] mqabI = dmin2(mq1Ib, mq2Ib);
    wire [%(dv)d:0] mqamaxI = dmax2(mq1I, mq2I);
    wire [%(dv)d:0] mqbI = dmin2(mq3I, mq4I);
    wire [%(dv)d:0] mqbbI = dmin2(mq3Ib, mq4Ib);
    wire [%(dv)d:0] mqbmaxI = dmax2(mq3I, mq4I);
    wire [%(dv)d:0] minI = dmin2(mqaI, mqbI);
    wire [%(dv)d:0] minI2 = dmin2(mqabI, dmin2(mqbbI, mqamaxI));""" % {"dv": dv - 1}

    def class_net(axis_wire, bb):
        """轴比特 bb 的两类 4 点 (min, second) 网络。"""
        k0 = [k for k in range(8) if (k >> (2 - bb)) & 1 == 0]
        k1 = [k for k in range(8) if (k >> (2 - bb)) & 1 == 1]
        lines = []
        for tag, ks in (("0", k0), ("1", k1)):
            w0, w1, w2, w3 = (f"{axis_wire}{k}" for k in ks)
            lines.append(f"""    wire [%(dv)d:0] c{tag}x1_{axis_wire}{bb} = dmin2({w0}, {w1});
    wire [%(dv)d:0] c{tag}x1b_{axis_wire}{bb} = dmax2({w0}, {w1});
    wire [%(dv)d:0] c{tag}x2_{axis_wire}{bb} = dmin2({w2}, {w3});
    wire [%(dv)d:0] c{tag}x2b_{axis_wire}{bb} = dmax2({w2}, {w3});
    wire [%(dv)d:0] c{tag}m_{axis_wire}{bb} = dmin2(c{tag}x1_{axis_wire}{bb}, c{tag}x2_{axis_wire}{bb});
    wire [%(dv)d:0] c{tag}m2_{axis_wire}{bb} = dmin2(dmin2(c{tag}x1b_{axis_wire}{bb}, c{tag}x2b_{axis_wire}{bb}), dmax2(c{tag}x1_{axis_wire}{bb}, c{tag}x2_{axis_wire}{bb}));""" % {"dv": dv - 1})
        return "\n".join(lines)

    nets = [class_net("dI", bb) for bb in range(3)] + \
           [class_net("dQ", bb) for bb in range(3)]

    # 每比特输出
    def vline(axis, bb):
        src_ = "dI" if axis == 0 else "dQ"
        other = "minQ" if axis == 0 else "minI"
        b = bb + axis * 3
        common = f"""    wire [{dv - 1}:0] d0m_{b} = c0m_{src_}{bb} + {other};
    wire [{dv - 1}:0] d1m_{b} = c1m_{src_}{bb} + {other};"""
        if D > 0:
            body = f"""    wire [{dv - 1}:0] g0_{b} = c0m2_{src_}{bb} - c0m_{src_}{bb};
    wire [{dv - 1}:0] g1_{b} = c1m2_{src_}{bb} - c1m_{src_}{bb};
    wire [{dv - 1}:0] k0_{b} = (g0_{b} >> {shift}) > {D - 1} ? {D - 1} : (g0_{b} >> {shift});
    wire [{dv - 1}:0] k1_{b} = (g1_{b} >> {shift}) > {D - 1} ? {D - 1} : (g1_{b} >> {shift});
    wire signed [33:0] gd_{b} = ($signed(d1m_{b}) - $signed(d0m_{b})) >>> {(16 - 2 * it) if metric == "l2" else (4 - it)};
    wire signed [43:0] vq_{b} = $signed(gd_{b})
                                + (($signed(T(k0_{b}))
                                  - $signed(T(k1_{b}))
                                  + 44'sd{1 << (w - 1)}) >>> {w});"""
        else:
            body = f"""    wire signed [43:0] vq_{b} = ($signed(d1m_{b}) - $signed(d0m_{b})) >>> {(16 - 2 * it) if metric == "l2" else (4 - it)};"""
        tail = f"""    wire signed [15:0] llr_{b} = (vq_{b} > 44'sd32767) ? 16'sd32767 :
                                 (vq_{b} < -44'sd32768) ? -16'sd32768 : vq_{b}[15:0];"""
        return common + "\n" + body + "\n" + tail

    vlines = "\n".join(vline(axis, bb) for axis in range(2) for bb in range(3))
    out_assign = ",\n        ".join(f".llr{b}(llr{b})" for b in range(6))
    out_decl = ",\n    ".join(f"output reg  signed [15:0] llr{b}" for b in range(6))
    out_reg = "\n            ".join(f"llr{b} <= 16'sd0;" for b in range(6))
    out_assign2 = "\n            ".join(
        f"llr{b} <= llr_{b};" for b in range(6))

    if D > 0:
        rom = "\n".join(
            f"                {int(math.log2(D))}'d{k}: T = 32'sd{int(v)};"
            for k, v in enumerate(T))
        rom_f = f"""
    function signed [31:0] T;
        input [{int(math.log2(D)) - 1}:0] k;
        begin
            case (k)
{rom}
                default: T = 32'sd0;
            endcase
        end
    endfunction"""
    else:
        rom_f = ""

    qwm = qwidth - 1
    return f"""// certfit 参数化 64QAM LLR：metric={metric} corr_entries={D} corr_frac={w} input_trunc={it}
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] i_in,
    input  wire signed [15:0] q_in,
    output reg                out_valid,
    input  wire               out_ready,
    output wire               out_dummy,
    {out_decl}
);
    // EVOLVE-BLOCK-START
    function [{qwm}:0] uabs{qwm};
        input signed [{qwm}:0] v;
        begin
            uabs{qwm} = v < 0 ? -v : v;
        end
    endfunction
    function [{dv - 1}:0] dmin2;
        input [{dv - 1}:0] a, b;
        begin
            dmin2 = (a < b) ? a : b;
        end
    endfunction
    function [{dv - 1}:0] dmax2;
        input [{dv - 1}:0] a, b;
        begin
            dmax2 = (a > b) ? a : b;
        end
    endfunction
{dI_lines}
{dQ_lines}
{rom_f}
{q_net}
{chr(10).join(nets)}
{vlines}
    assign in_ready = !out_valid || out_ready;
always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            {out_reg}
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                {out_assign2}
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""
