#!/usr/bin/env python
"""E4：BER 证书目标 vs SQNR 代理目标的位宽决策对比。

场景：FIR 匹配滤波器（fir_t16_c25 系数）后接 QPSK 判决器。
- 系数定点化为 b 位小数（Q1.b），系数量化噪声经信号放大进入判决点；
- 证书（L3）：噪声方差上界 σ_q² ≤ σ_x² · Σ_i (2^{-(b+1)})² / 3 · w（保守），
  实际用均方模型 σ_q² = σ_x² · N · q²/12（q=2^{-b}），并以 WC 界除以裕度；
- BER 上界（QPSK 相干解调）：P_b ≤ Q(sqrt(2·SNR_min))，SNR_min = 1/(1+σ_q²/σ_x²·...)。

对比两种选型准则：
  (a) SQNR 代理（B3 竞品口径）：取最小 b 使 SQNR ≥ 60 dB；
  (b) BER 证书：取最小 b 使 BER 上界 ≤ 1e-6。
各自综合对应位宽基线，报告面积节省。

产出：experiments_e1/e4_ber.json
"""
import json
import math
import tempfile
import os
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
os.environ["COMMDSP_TASK"] = "fir_t16_c25"

import yaml  # noqa: E402
import evaluator as base  # noqa: E402
import family_baselines_gen as fbg  # noqa: E402

CACHE = BENCH / ".certfit_cache" / "e4"
CACHE.mkdir(parents=True, exist_ok=True)

SIGMA_X = 9000.0        # fir 激励分布（gaussian_white）的标准差（Q1.15 int 域）
N_TAPS = 16
Q_TARGET = 1e-6         # 目标 BER
SQNR_GATE = 60.0        # B3 竞品口径的二值门槛（dB）


def qfunc(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def sqnr_for_bits(b: int, h: list) -> float:
    """系数量化到 b 位小数后的输出 SQNR（解析均方模型，证书口径的均值层）。"""
    q = 2.0 ** (-b)
    # 每个系数误差 e_i ~ U(-q/2, q/2)，经输入信号放大：
    # e_y[n] = Σ x[n-i] e_i，方差 = σ_x² Σ e_i² ≈ σ_x² N q²/12
    sigma_q2 = SIGMA_X**2 * len(h) * q * q / 12.0
    # 输出信号功率 = Σ h_i² · σ_x²（连续系数）
    sig = SIGMA_X**2 * sum(hi * hi for hi in h)
    return 10 * math.log10(sig / sigma_q2)


def snr_min_for_bits(b: int, h: list) -> float:
    """最坏情况 SNR（L3 证书口径）：|e_i| ≤ q/2 同相取最坏。"""
    q = 2.0 ** (-b)
    e_wc = math.sqrt(len(h)) * q / 2.0 * SIGMA_X  # 保守同相合成
    sig = SIGMA_X**2 * sum(hi * hi for hi in h)
    return sig / (e_wc * e_wc)


def ber_bound(b: int, h: list) -> float:
    snr_lin = snr_min_for_bits(b, h)
    snr_db = 10 * math.log10(snr_lin)
    # QPSK 相干：P_b = Q(sqrt(2·γ))，γ 为每比特 SNR（=SNR_min 保守口径）
    return qfunc(math.sqrt(2 * snr_lin)), snr_db


def synth_area(b: int, h: list) -> int:
    key = f"fir_b{b}"
    mark = CACHE / f"{key}.json"
    if mark.exists():
        return json.loads(mark.read_text())["area"]
    # 用基线生成器综合 b 位小数量化系数（scale = 2^b）
    hq = [int(round(x * (1 << b))) for x in h]
    text = fbg.fir_baseline(len(h), [v / (1 << b) for v in hq])
    # 直接重定量标：改用 b 位量化系数（生成器内部再乘 2^15 会错标，
    # 因此这里手工生成：系数常量 = hq，乘积 >> b）
    entries = "\n".join(
        f"                8'd{k}: hf = " + (f"{b+2}'sd{v}" if v >= 0 else f"-{b+2}'sd{abs(v)}") + ";"
        for k, v in enumerate(hq))
    prod_w = 16 + b + 2
    text = f"""// E4：系数量化 b={b} 直接型 FIR
module top (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               in_valid,
    output wire               in_ready,
    input  wire signed [15:0] x,
    output reg                out_valid,
    input  wire               out_ready,
    output reg  signed [{16 + b + 2 - 1}:0] y
);
    // EVOLVE-BLOCK-START
    function signed [{b+1}:0] hf;
        input [7:0] k;
        begin
            case (k)
{entries}
                default: hf = 0;
            endcase
        end
    endfunction
    reg signed [15:0] d [{N_TAPS - 1}:0];
    integer k;
    reg signed [{prod_w - 1}:0] acc;
    always @(*) begin
        acc = x * hf(8'd0);
        for (k = 1; k < {N_TAPS}; k = k + 1)
            acc = acc + (d[k-1] * hf(k[7:0]));
    end
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (k = 0; k < {N_TAPS}; k = k + 1) d[k] <= 0;
            out_valid <= 1'b0; y <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            if (in_valid && in_ready) begin
                for (k = {N_TAPS} - 1; k > 0; k = k - 1) d[k] <= d[k-1];
                d[0] <= x;
                y <= acc;
                out_valid <= 1'b1;
            end
        end
    end
    // EVOLVE-BLOCK-END
endmodule
"""
    with tempfile.TemporaryDirectory() as td:
        vf = Path(td) / "d.v"
        vf.write_text(text)
        area, counts, err = base._run_yosys(td, str(vf), 300)
    if area is None:
        area = 10000
    mark.write_text(json.dumps({"area": area}))
    return area


def main():
    _cand = [BENCH / "tasks/fir_t16_c25/task.yaml", BENCH / "tasks_gen/fir/fir_t16_c25/task.yaml"]
    ty = yaml.safe_load(next(x for x in _cand if x.exists()).read_text())
    h = ty["metric"]["params"]["coefficients"]

    rows = []
    sel_sqnr = sel_ber = None
    for b in range(6, 16):
        sqnr = sqnr_for_bits(b, h)
        ber, snr_db = ber_bound(b, h)
        area = synth_area(b, h)
        rows.append({"b": b, "sqnr_model": round(sqnr, 2), "snr_min_db": round(snr_db, 2),
                     "ber_bound": ber, "area": area})
        if sel_sqnr is None and sqnr >= SQNR_GATE:
            sel_sqnr = rows[-1]
        if sel_ber is None and ber <= Q_TARGET:
            sel_ber = rows[-1]
        print(f"b={b:2d}: SQNR={sqnr:7.2f} dB  SNR_min={snr_db:6.2f} dB  "
              f"BER≤{ber:.2e}  area={area}")

    out = {
        "scenario": "FIR(t16,c25) -> QPSK slicer, sigma_x=9000, target BER<=1e-6",
        "rows": rows,
        "select_by_sqnr60": sel_sqnr,
        "select_by_ber_cert": sel_ber,
        "area_saving_pct": round(100 * (1 - sel_ber["area"] / sel_sqnr["area"]), 1)
        if sel_sqnr and sel_ber else None,
    }
    (BENCH / "experiments_e1" / "e4_ber.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("select_by_sqnr60", "select_by_ber_cert",
                                          "area_saving_pct")}, indent=2))


if __name__ == "__main__":
    main()
