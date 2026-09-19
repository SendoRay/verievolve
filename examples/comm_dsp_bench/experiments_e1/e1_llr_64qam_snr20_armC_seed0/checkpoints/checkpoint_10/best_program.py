"""certfit 模板进化程序：llr_64qam_snr20（证书适应度，Arm C）

可调参数：
  metric:        "l2" | "l1"
  corr_entries:  0/16/64/256/1024（校正表项数，0 = 纯 max-log）
  corr_frac:     6..12
  input_trunc:   0..6（输入预截断，控制综合代价与精度）

证书字段：cert_mean_sqnr_db（确定性 Sobol）、cert_wc_sqnr_db（最坏界）、
area_lut（真实 Yosys 综合）。注意：本任务误差分布重尾，详见论文 §5.4。

本次修改目标：消除 stage2 超时。
  - input_trunc 从 4 提升到 6：更强的输入预截断，显著缩小数据通路规模，
    降低 Yosys 综合时间与面积，直接缓解 stage2 超时。
  - corr_frac 从 8 降到 6：更窄的小数位宽，进一步减小加法器/比较器面积。
  - corr_entries 保持 0（纯 max-log，无校正查表）已是最省资源的选择。
  - metric 保持 "l2"，证书余量充足（mean≈64dB、wc≈55dB），
    精度损失可被吸收，stage1 仍应通过。
"""

# EVOLVE-BLOCK-START
PARAMS = {
    "metric": "l2",
    "corr_entries": 0,
    "corr_frac": 6,
    "input_trunc": 6,
}
# EVOLVE-BLOCK-END