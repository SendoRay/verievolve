# S1 汇总：局部指标 vs 系统级实现选择

- chain `ddc-p0-v2`，96 组合 × 15 场景，运行 7.1s，margin 1.0 dB
- 真值跨场景排序稳定性：Kendall τ 均值 0.9331（最小 0.8022）

| 预测器 | 平均 Kendall τ | 出现错筛的场景数 | 显著错筛对总数 | top-6 命中真值最优比例 |
|---|---|---|---|---|
| L0_sqnr | 0.8419 | 1/15 | 32 | 1.0 |
| L1_sfdr | -0.2019 | 0/15 | 0 | 0.0 |
| L2_traj | 0.8539 | 1/15 | 32 | 1.0 |
| L3_spectral | 0.9361 | 3/15 | 420 | 1.0 |

## 典型错筛实例（预测器判可丢弃、真值更优）

- **L0_sqnr** @ alias_f390_b550_r6：丢弃 `n2_lut256near_b16|f6_c12_trunc|c1_exact_rne`，保留 `n4_lut1024lin_b16|f5_c12_acc24|c1_exact_rne`；预测差 2.25 dB，真值反转 1.57 dB
- **L2_traj** @ alias_f390_b550_r6：丢弃 `n2_lut256near_b16|f6_c12_trunc|c1_exact_rne`，保留 `n4_lut1024lin_b16|f5_c12_acc24|c1_exact_rne`；预测差 2.41 dB，真值反转 1.57 dB
- **L3_spectral** @ alias_f390_b550_r6：丢弃 `n6_cordic16_b16|f7_c12_pd2|c1_exact_rne`，保留 `n6_cordic16_b16|f8_c14_acc28_pd1_trunc|c2_pd2_trunc`；预测差 8.88 dB，真值反转 2.44 dB
- **L3_spectral** @ alias_f510_b550_r6：丢弃 `n4_lut1024lin_b16|f2_c12|c1_exact_rne`，保留 `n6_cordic16_b16|f8_c14_acc28_pd1_trunc|c1_exact_rne`；预测差 8.77 dB，真值反转 2.54 dB
- **L3_spectral** @ alias_f630_b550_r6：丢弃 `n6_cordic16_b16|f7_c12_pd2|c1_exact_rne`，保留 `n5_cordic12_b12|f8_c14_acc28_pd1_trunc|c1_exact_rne`；预测差 9.63 dB，真值反转 1.81 dB
