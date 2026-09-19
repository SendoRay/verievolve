# 106 实例全量回归报告（基线闭环）

- 总实例: 106，通过: 83，失败: 23

| 族 | 实例 | 通过 | 精度中位 | 面积中位(LUT) | ASIC 中位(μm²) |
|---|---|---|---|---|---|
| cmul | 12 | 8 | 0.0002 | 7076.0 | 8785.18 |
| crc | 20 | 20 | 999.0 | 152.0 | 405.12 |
| fir | 30 | 16 | 4.5165 | 15504.0 | 12943.83 |
| llr | 20 | 20 | 66.0919 | 5508.0 | 4981.38 |
| mfilt | 5 | 0 | - | - | - |
| nco | 12 | 12 | 47.6082 | 168.0 | 982.87 |
| phase | 7 | 7 | 2.0592 | 2256.0 | 2148.75 |

## 失败清单

- `cmul_w12_free` [zero_score] 
- `cmul_w12_trunc` [zero_score] 
- `cmul_w8_free` [zero_score] 
- `cmul_w8_round` [zero_score] 
- `fir_t128_c15` [full_sim_fail] simulation timeout
- `fir_t128_c15_sym` [full_sim_fail] simulation timeout
- `fir_t128_c25` [full_sim_fail] simulation timeout
- `fir_t128_c25_sym` [full_sim_fail] simulation timeout
- `fir_t128_c40` [zero_score] 
- `fir_t128_c40_sym` [zero_score] 
- `fir_t16_c40` [zero_score] 
- `fir_t16_c40_sym` [zero_score] 
- `fir_t32_c40` [zero_score] 
- `fir_t32_c40_sym` [zero_score] 
- `fir_t64_c40` [zero_score] 
- `fir_t64_c40_sym` [zero_score] 
- `fir_t8_c40` [zero_score] 
- `fir_t8_c40_sym` [zero_score] 
- `mfilt_L127` [zero_score] 
- `mfilt_L15` [zero_score] 
- `mfilt_L255` [zero_score] 
- `mfilt_L31` [zero_score] 
- `mfilt_L63` [zero_score] 
