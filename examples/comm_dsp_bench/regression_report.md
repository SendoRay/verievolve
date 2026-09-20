# 106 实例全量回归报告（基线闭环）

- 总实例: 106，通过: 82，失败: 24

| 族 | 实例 | 通过 | 精度中位 | 面积中位(LUT) | ASIC 中位(μm²) |
|---|---|---|---|---|---|
| cmul | 12 | 2 | 999.0 | 10486.0 | 13306.65 |
| crc | 20 | 20 | 999.0 | 152.0 | 405.12 |
| fir | 30 | 18 | 85.1948 | 8532.0 | 12786.62 |
| llr | 20 | 20 | 66.1381 | 5508.0 | 4981.38 |
| mfilt | 5 | 3 | 999.0 | 4114.0 | 12748.05 |
| nco | 12 | 12 | 47.6082 | 168.0 | 982.87 |
| phase | 7 | 7 | 71.6929 | 2694.0 | 2546.42 |

## 失败清单

- `cmul_w12_free` [zero_score] 
- `cmul_w12_round` [zero_score] 
- `cmul_w12_trunc` [zero_score] 
- `cmul_w16_round` [zero_score] 
- `cmul_w16_trunc` [zero_score] 
- `cmul_w20_round` [zero_score] 
- `cmul_w20_trunc` [zero_score] 
- `cmul_w8_free` [zero_score] 
- `cmul_w8_round` [zero_score] 
- `cmul_w8_trunc` [zero_score] 
- `fir_t128_c15` [full_sim_fail] simulation timeout
- `fir_t128_c15_sym` [full_sim_fail] simulation timeout
- `fir_t128_c25` [full_sim_fail] simulation timeout
- `fir_t128_c25_sym` [full_sim_fail] simulation timeout
- `fir_t128_c40` [full_sim_fail] simulation timeout
- `fir_t128_c40_sym` [full_sim_fail] simulation timeout
- `fir_t64_c15` [full_sim_fail] simulation timeout
- `fir_t64_c15_sym` [full_sim_fail] simulation timeout
- `fir_t64_c25` [full_sim_fail] simulation timeout
- `fir_t64_c25_sym` [full_sim_fail] simulation timeout
- `fir_t64_c40` [full_sim_fail] simulation timeout
- `fir_t64_c40_sym` [full_sim_fail] simulation timeout
- `mfilt_L127` [full_sim_fail] simulation timeout
- `mfilt_L255` [full_sim_fail] simulation timeout
