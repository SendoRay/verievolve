# 106 实例全量回归报告（基线闭环）

- 总实例: 106，通过: 50，失败: 56

| 族 | 实例 | 通过 | 精度中位 | 面积中位(LUT) | ASIC 中位(μm²) |
|---|---|---|---|---|---|
| cmul | 12 | 3 | 999.0 | 6836.0 | 8785.18 |
| crc | 20 | 20 | 999.0 | 152.0 | 405.12 |
| fir | 30 | 0 | - | - | - |
| llr | 20 | 20 | 66.0955 | 5508.0 | 4981.38 |
| mfilt | 5 | 0 | - | - | - |
| nco | 12 | 0 | - | - | - |
| phase | 7 | 7 | 2.0985 | 2256.0 | 2148.75 |

## 失败清单

- `cmul_w12_free` [zero_score] 
- `cmul_w12_round` [zero_score] 
- `cmul_w16_round` [zero_score] 
- `cmul_w16_trunc` [zero_score] 
- `cmul_w20_round` [zero_score] 
- `cmul_w20_trunc` [zero_score] 
- `cmul_w8_free` [zero_score] 
- `cmul_w8_round` [zero_score] 
- `cmul_w8_trunc` [zero_score] 
- `fir_t128_c15` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t128_c15/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t128_c15_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t128_c15_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t128_c25` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t128_c25/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t128_c25_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t128_c25_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t128_c40` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t128_c40/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t128_c40_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t128_c40_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t16_c15` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t16_c15/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t16_c15_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t16_c15_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t16_c25` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t16_c25/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t16_c25_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t16_c25_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t16_c40` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t16_c40/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t16_c40_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t16_c40_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t32_c15` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t32_c15/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t32_c15_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t32_c15_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t32_c25` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t32_c25/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t32_c25_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t32_c25_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t32_c40` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t32_c40/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t32_c40_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t32_c40_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t64_c15` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t64_c15/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t64_c15_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t64_c15_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t64_c25` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t64_c25/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t64_c25_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t64_c25_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t64_c40` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t64_c40/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t64_c40_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t64_c40_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t8_c15` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t8_c15/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t8_c15_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t8_c15_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t8_c25` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t8_c25/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t8_c25_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t8_c25_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t8_c40` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t8_c40/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `fir_t8_c40_sym` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/fir/fir_t8_c40_sym/initial_program.v:13: error: unpacked array parameter requires SystemVerilog.

- `mfilt_L127` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/mfilt/mfilt_L127/initial_program.v:15: error: unpacked array parameter requires SystemVerilog.

- `mfilt_L15` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/mfilt/mfilt_L15/initial_program.v:15: error: unpacked array parameter requires SystemVerilog.

- `mfilt_L255` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/mfilt/mfilt_L255/initial_program.v:15: error: unpacked array parameter requires SystemVerilog.

- `mfilt_L31` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/mfilt/mfilt_L31/initial_program.v:15: error: unpacked array parameter requires SystemVerilog.

- `mfilt_L63` [smoke_fail] /Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/mfilt/mfilt_L63/initial_program.v:15: error: unpacked array parameter requires SystemVerilog.

- `nco_p20_t1024` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p20_t256` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p20_t64` [smoke_fail] volve/examples/comm_dsp_bench/.family_baselines/nco/nco_p20_t64/initial_program.v:34: syntax error
/Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/nco/nco_p20_t64/initial_program.
- `nco_p24_t1024` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p24_t256` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p24_t64` [smoke_fail] volve/examples/comm_dsp_bench/.family_baselines/nco/nco_p24_t64/initial_program.v:34: syntax error
/Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/nco/nco_p24_t64/initial_program.
- `nco_p28_t1024` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p28_t256` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p28_t64` [smoke_fail] volve/examples/comm_dsp_bench/.family_baselines/nco/nco_p28_t64/initial_program.v:34: syntax error
/Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/nco/nco_p28_t64/initial_program.
- `nco_p32_t1024` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p32_t256` [smoke_fail] sim.vvp: Unable to open input file.

- `nco_p32_t64` [smoke_fail] volve/examples/comm_dsp_bench/.family_baselines/nco/nco_p32_t64/initial_program.v:34: syntax error
/Users/chengzhy/verievolve/examples/comm_dsp_bench/.family_baselines/nco/nco_p32_t64/initial_program.
