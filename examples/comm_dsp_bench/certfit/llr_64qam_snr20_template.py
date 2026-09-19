"""certfit 模板进化程序：llr_64qam_snr20（证书适应度，Arm C）

可调参数：
  metric:        "l2" | "l1"
  corr_entries:  0/16/64/256/1024（校正表项数，0 = 纯 max-log）
  corr_frac:     6..12
  input_trunc:   0..6（输入预截断，控制综合代价与精度）

证书字段：cert_mean_sqnr_db（确定性 Sobol）、cert_wc_sqnr_db（最坏界）、
area_lut（真实 Yosys 综合）。注意：本任务误差分布重尾，详见论文 §5.4。
"""

# EVOLVE-BLOCK-START
PARAMS = {
    "metric": "l2",
    "corr_entries": 0,
    "corr_frac": 8,
    "input_trunc": 4,
}
# EVOLVE-BLOCK-END
