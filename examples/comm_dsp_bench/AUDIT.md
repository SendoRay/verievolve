# CommDSP-Bench 任务合理性审计（论文第 3 章基础）

- 审计日期：2026-09-20（E1 实验准备期间）
- 审计人：ZCode（GLM）自动审计 + 人工确认
- 范围：`tasks/`（v1 精任务 4 个）+ `tasks_gen/`（v2 参数化族 106 实例）
- 结论先行：**任务语义层合理（数学规范→自动 golden→防背题激励的架构是干净的），
  但存在 (a) 37% 基线编译失败的工程缺陷、(b) 相对自设 V2 设计稿的覆盖缺口、
  (c) 指标层两处方法学风险**。逐项如下。

---

## 1. 逐族合理性判定

| 族 | 实例数 | 语义 | 难度轴 | 判定 |
|---|---|---|---|---|
| cmul | 12 | 复乘，全精度输出=锚点任务 | 位宽×舍入 | ✅ 合理；round/trunc 变体 9 个 zero_score（基线 bug，见 §2） |
| cordic_sincos | 1(v1) | sin/cos，迭代 vs 查表 | 迭代级数/表深 | ✅ 合理；16 位输入空间可 ROM 背题由面积维度惩罚（P4 成立） |
| fir | 30 | 低通 FIR，连续系数进卡、golden 用连续系数 | 抽头×截止×对称 | ✅ 设计优秀（系数定点化=搜索自由度，"两级翻译断裂点"微缩模型）；❌ 基线 0/30 编译失败 |
| atan2/phase | 7 | 复数辐角，八分折叠 | 仅字长 | ⚠️ 合理但维度单薄（仅字长一维）；71.7 dB 算法类地板是特性不是缺陷（论文用它证明结构跳变价值） |
| llr | 20 | 64QAM 软解调，max-log 允许近似 | 调制阶×SNR | ✅ 合理且经典；⚠️ 指标重尾风险见 §3.1 |
| nco | 12 | 数控振荡器，SFDR 指标 | 相位位宽×表深 | ⚠️ 合理；❌ 基线 0/12（语法+路径错误）；SFDR 的 7 段 FCW 扫描使单次评估代价 ×7 |
| mfilt | 5 | m 序列匹配滤波（±1 系数） | 序列长 | ⚠️ 合理；❌ 基线 0/5（同 fir 根因）；±1 退化发现是进化潜力的好素材 |
| crc | 20 | 流式 CRC（3GPP 多项式） | 宽度×步进 | ✅ 合理；exact_match 哨兵 999 使精度维度退化（0 或 999）——文档已声明，可接受 |

## 2. 工程缺陷（必须修复，E2 全量回归的前置）

1. **fir 0/30、mfilt 0/5**：`family_baselines_gen.py` 生成的 unpacked localparam 数组
   iverilog -g2005 不支持（Verilog-2001 无 unpacked array 初始化）→ 改 packed 位拼接。
2. **nco 0/12**：t64 表生成语法错误；t256/t1024 "sim.vvp: Unable to open input file"
   （编译失败后仿真路径不存在——失败路径未短路）。
3. **cmul round/trunc 9 个 zero_score**：golden 定标与基线输出位宽错位（回归报告）。
4. **atan2 基线回归 2.1 dB vs SPEC v1.0 宣称 71.7 dB**：golden 修正后未重验基线——
   修复后以重跑回归为准（2026-09-20 复测：基线 71.71 dB ✓ 与设计值一致，此项已消除）。
5. **B3/cordic_jump 的 best 簿记异常**（负 fitness 导致框架 best 不更新）：不影响 E1 两臂，
   在论文中作为竞品口径的实现注记。

## 3. 指标层方法学风险（论文必须如实报告）

### 3.1 LLR 族：重尾误差分布下的适应度病态（E2 实验发现）
max-log vs 精确 LSE 的 SQNR 由极少数"模糊点"（两类距离接近的星座+噪声组合）
主导：同一设计 65536 样本与 131072 Sobol 点的 SQNR 估计可差 ~11 dB。
**任何有限采样（含 fresh-seed 蒙特卡罗与低差异格点）对该族都不是稳定估计量**。
应对：(a) 证书层提供确定性估计（消除种子彩票）+ L3 最坏界；(b) 终判协议用
超大固定样本 + 分布偏置（终考协议 §7.2 已有思想，需对 llr 显式化）；
(c) 论文将此作为"指标脆弱性"小节——它是"适应度需要证书"的直接论据。

### 3.2 crc 族：MAP-Elites 精度维度退化
exact_match 下精度 ∈ {0, 999}，网格退化为面积×吞吐二维——设计文档已声明。
论文口径：该族验证"框架对不可近似任务同样工作"，与精度可谈判任务形成对照。

## 4. 覆盖缺口（相对 tasks_v2_design.md 十任务收发链叙事）

| 缺口 | 设计稿状态 | 审计意见 |
|---|---|---|
| scrambler（Gold 序列，GF(2) 并行展开） | 设计完成未实现 | **应补**：exact_match + 线性代数结构（跳步矩阵）是"算法族选择"叙事的关键素材，实现代价低 |
| fir_decim（2:1 抽取，速率转换首例） | 设计完成未实现 | 缓补：stream_v1 需先验证 2:1 握手语义，实现代价中 |
| fft（流水 FFT 架构谱系） | SPEC §5.1 提及未设计 | **应补（小规模）**：16/64 点定点 FFT 是通信 DSP 核心算子，R2²SDF/R4MDC/R2MDC 架构族是"算法目录→等价图导航"叙事的最佳载体；golden=numpy.fft 代价低 |
| IIR/PLL 类（反馈环） | 未设计 | 缓补：nco 相位累加器已提供循环案例；一阶环路滤波器可作为证书章节"含环归纳不变量"的第二个案例 |
| qpsk_mod | 设计稿明确不纳入 | 同意（算法空间过小） |

**结论**：当前 110 实例的"广度"合格（7 族 × 参数化），但"链路完整性"不足——
发射/接收链的中断点在 FFT 与加扰。论文叙事应表述为"3GPP-lite 物理层算子集"
而非"收发链全集"（除非补齐 scrambler+fft）。**决策：本轮实验周期内补
scrambler 与 fft_64 两族（见 §5），fir_decim 列为 future work。**

## 5. 行动项

- [x] 修复 fir/mfilt/nco 基线（解包数组→case 函数、nco case 分隔符、mfilt/fir 滞后一拍）
- [x] 修复 atan2 族基线（象限重构公式错误、`y*512` 字面量位宽回绕、w≥20 的 yx 位宽参数化）——w28 复测 71.74 dB
- [x] 修复 cmul round/trunc 饱和缺失；**遗留**：w<33 实例 golden 刻度与输出格式不一致（DUT 输出 Q1.15 而 golden 全精度刻度，Δ=2^15）——需修任务卡或 golden 缩放，列为已知问题
- [x] 回归判据收紧（冒烟 SQNR ≥ 20 dB 才算通过——修复了"stage1 跑通即通过"的漏洞）
- [x] 最终回归 run5：82/106（残余 24 例全部定性：cmul 刻度问题 10、fir t64/t128 仿真超时 12、mfilt L127/255 超时 2）
- [x] 证书模型-RTL 全空间逐位验证中发现并修复 a2[7:0] 截断缝隙（quad+depth64，见 ch4 §4.4）
- [ ] 新增 scrambler 族（task_family_gen 扩展：c_init 参数化）
- [ ] 新增 fft_64 族（golden=numpy.fft，基线=radix-2 DIT）
- [ ] cmul 小字长实例 golden 刻度修复；流水线化 fir 大抽头基线

## 6. 2026-09-27 模分解引理误差矩修复（RESEARCH_PLAN §9.3 第 1 项）

**问题**（只读复核结论：drop=1、half-up 穷举=0.375，旧 direct=0.21875、旧 karatsuba=0.2890625）：

1. `certfit/common.py::_residue_dist`：`nu` 以 0 初始化，r=0（A≡0）被混入 ν=0
   奇数残差类——t=0 时 mask 含 r=0 且分母多计。修复：r=0 置 ν=−1，不进任何类。
2. `cmul_exact_err_moments` karatsuba 分支：把 P1=(a+b)(c+d) 当 17 位均匀乘积
   并与 A、B 按独立项圆卷积。实际 P1−A−B = ad+bc（整数恒等式），ad⊥bc 且各与
   ac 同分布，故两结构 im 误差矩必然相等。修复：karatsuba 分支与 direct 同式，
   并新增 `nbits` 参数（默认 16）供小位宽对拍。

**修复后影响量化**（引理 SQNR 口径）：
- sd=1：direct +2.34 dB、karatsuba +1.13 dB（err2 由低估恢复到真值）
- sd=2：恰好抵消，无变化
- sd=3：−0.016 dB；sd≥4：<0.005 dB

**受影响产物**：
- `exact_lemma_sqnr`（仅 artifacts，不进适应度）：sd=1 的证书数值变化最大
- 图 4.1（fig_lemma）：曲线覆盖 sd∈[2,15]，修复后引理 vs Sobol(2^16) 最大偏差
  由 ≤0.02 dB 变为 ≤0.029 dB（增量来自 Sobol 有限点数离散误差，引理侧现为精确
  值）——图与标题已再生，正文表 4.1/定理 4.1 声明同步改为 ≤0.03 dB
- E1/E5 存量主结果：主 `precision` 走 Sobol 路径，不受本修复影响

**新增回归**：`regression_cmul_moments.py`（R1 φ/量化器一致性、R2 残差分布
频数对拍、R3 小位宽 nbits∈{4,5,6} 全枚举 vs helper 逐点一致、R4 结构等价、
R5 锚点 0.375、R6 16 位蒙特卡罗抽查）。报告：`experiments_system/s0_model_fix/`。

## 7. 2026-09-29 DDC witness 场景集 `ddc-witness-scen-v1`（WITNESS_FROZEN_DDC_v1 §4.1、§7-7/8/9/11/12）

**新增**（`chains/ddc/spec.py`、`chains/ddc/scenarios.py`；旧 `build_scenarios`/`CHAIN_VERSION=ddc-p0-v2` 逐位不变）：
- `build_witness_scenarios()`：C_main 36、C_heldout 32、C_stress 9；`Scenario.split` 标注；
  seed = sha256(`SCENARIO_VERSION|SEED_BASE|klass|f|b|r|snr`)[:8]>>1，与列表位置无关。
- §7-7 QPSK：波形幅度不变（不移动 ADC 工作点），声明改为每符号功率 0.5；desired 输入功率实测 ≈0.0625。
- §7-8 AWGN：相对 desired-only、blocker 之前；与 Codex 澄清（msg_da31862c）后，30 dB 在**输出测量域**成立
  （理想整数-FCW 混频 + 原型 FIR + R=2，测量段起点 240），对应输入全带 SNR ≈24.2–24.5 dB，逐场景入 manifest。
- §7-9：暴露 `desired/blocker/noise` 与共同前端缩放 `scale`，`x = s·(d+b+n)`；77 场景实测均未触发缩放（peak ≤0.903）。
- §7-11 部分：`export_witness_manifest()` 写入整数 FCW、gcd、周期、抽取相位 0、NCO 初相 0、场景键与 levels。

**验证**：`tests/test_ddc_scenarios.py` 9 项通过；旧 15 场景 `x_adc` 与修改前 HEAD 逐位一致（sha256 对拍）。

## 8. 2026-09-29 DDC 指标与排序评价器修复（未运行 truth）

**修复**（`chains/ddc/metrics.py`、`run_s1.py`、`ref_chain.py`）：

- `spectral_prediction` 的抽取折叠改为正确 preimage `k+j·N_out`；主预测改为与冻结 `q` 同口径的
  输出全带功率，通带积分另存辅助字段，不再混为同一量。
- `sfdr_db` 改为复 NCO 的冻结有限记录定义：按已知整数 FCW 载波做复数 LS 消除，再加四项
  Blackman–Harris 窗和 8× 零填充 FFT；不再靠“峰值 ±2 bin”排除泄漏。理想单音和
  −40/−60/−80 dBc 整数/半 bin 已知杂散校准进入单测。
- 主实现误差在前导段相对同输入完整 float reference 估计单一复标量，测量段冻结；分母改为
  desired-only 参考输出功率，同时保留线性 `q` 与 dB 表示。零实现误差例在数值实现中严格给出 `g=1,q=0`。
- NCO 轨迹 SQNR 改用 `cos+j·sin` 复序列，不再把两列实数组误交给复数字段拆分函数。
- 排序同时报告 tau-a 与 tie-corrected tau-b；top-k 在边界保留全部并列，并分别报告“任一最优命中”与
  “全并列最优保留”；`worst_drop` 的 kept/dropped 标签和 gap 方向已修正。
- 排序、跨场景稳定性和图中的主 truth 统一使用 aligned implementation error；raw 误差仍作为敏感性字段。
- float reference NCO 改用与候选相同的 32-bit 整数 FCW，避免公共 FCW 量化进入候选误差或 `q_cal`。
- 新运行目录为 `experiments_system/s1_local_vs_system_witness_v1`，使用 `C_main` 36 场景并写
  witness manifest；不会覆盖旧 `s1_local_vs_system` 历史产物。

**验证**：`tests/test_ddc_metrics.py` 7 项与 `tests/test_ddc_scenarios.py` 9 项联合通过（16 passed）；
旧清单的 `chains/ddc/smoke_test.py` 通过。这里只运行单元/冒烟回归，**没有运行 S1 或任何 truth**。

**本次修复完成时仍未过的正式运行 gate**：完整 32-bit accumulator-domain 的公平 `M_core`（含 `phase_bits`）与冻结的
v2 二十点池尚未实现；在这两项完成、逐位验证并登记前，不得把 `run_s1.py` 产物当正式 witness。

### 8.1 v2 二十点池登记

冻结池已按 `WITNESS_FROZEN_DDC_v1` 落到 `candidates.NCO_WITNESS_V2_CANDIDATES`：4 个 nearest LUT、
10 个 linear LUT、6 个 7–12 级 CORDIC，共 20 点；`witness_nco_candidates()` 默认返回历史六点与 v2 的
26 个实现并集。`tpl_cordic` 与可进化模板的合法范围由 `8..20` 放宽为 `7..20`；历史 checkpoint / result
文件不改。新增测试锁定 20/26 数量、三类计数及 stage 7 合法、stage 6 非法。

### 8.2 完整 accumulator-domain `M_core`

`metrics.nco_accumulator_metrics()` 已实现冻结的三个公平局部指标：calibrated complex SQNR、I/Q WCE
（16-bit 输出 LSB）与 last-bit accuracy。候选只读取高 `phase_bits` 位，因此算法按相位 bin 精确合并
2^32 状态：复增益/MSE 用单位根几何和，WCE 用不跨象限 bin 的端点，last-bit 命中数在整数 accumulator
上对单调量化码区间做二分计数；复杂度不随 2^32 线性增长。nearest LUT、linear LUT、CORDIC_7 三类已在
`acc_bits∈{10,11,12}` 的缩位宽域与全状态 brute force 对拍：复增益、MSE、WCE 与 hit count 全部一致。
`build_witness_nco_pool()` 将其接到
冻结 26 点池，并保留 `run_s1` 所需兼容字段。

**更新后的正式运行 gate**：v2 池与 `M_core` 实现已落地；仍缺 20 点模型/RTL 等价验证，以及按冻结
`ε_m` 做的全尺寸校准。完成前不得运行正式 witness truth。

**runner 边界复核**：`run_s1.py` 当前仍通过 `build_all()` 取历史 6 个 NCO，并同时展开 8 个 FIR 与
2 个 CMUL；这不等于冻结协议要求的“26 个 NCO、固定下游实现”。因此该脚本虽然已经修正场景与指标，
仍只是旧 S1 的诊断 runner，不能直接产生正式 witness。RTL 等价 gate 通过后，须先把正式 runner 的
候选集合锁为 26 个 NCO，并在 manifest 中写死固定下游配置，再允许运行 truth。

### 8.3 `M_core` 独立复核与 raw 敏感性口径

Claude 对 `nco_accumulator_metrics()` 做了只读公式审查，并另用 6 组配置全状态暴力枚举：复增益误差
≤1.1e-14、WCE 误差 ≤5e-11 LSB、last-bit hit count 全部逐项相等；约 96 dB 的一项因闭式功率差
发生浮点抵消，SQNR 误差约 5e-6 dB，远低于冻结的 0.10 dB 容差，但全尺寸校准仍是 truth 前 gate。
几何和符号、calibrated MSE、端点 WCE 与单调区间计数均无 blocker。

按冻结协议补充 raw SQNR/WCE/last-bit 三指标；raw 与 calibrated 均使用 ties-to-even 的理想 Q1.15 码并
饱和到 `[-32768,32767]`，因此 `cos(0)=1` 对应理想码 32767。缩位宽对拍扩到 nearest、linear、
CORDIC_7、`phase_bits<16` 与 `bin_size=1`，并新增 2^16 点测试锁定主链和 `M_core` 的
accumulator 高位到 signed-angle 映射。raw 只作敏感性分析，不与 calibrated `q` 构造主 reversal。

### 8.4 v2 NCO 模型—RTL 全映射等价

`rtl_gen.gen_nco_verilog()` 与完整 DDC 生成器共用 LUT/CORDIC 映射代码；
`tests/test_ddc_nco_rtl_equiv.py` 对冻结 v2 二十点逐个编译 RTL，并穷举候选实际读取的全部
`2^phase_bits` 个高位相位字。联合报告还覆盖历史六点，因此主候选集 26/26 均为
`mismatch=0`。逐候选状态数、映射 SHA-256 与分组见
`experiments_system/nco_rtl_equiv_v1/report.json::{results,classes}`。

完整映射得到 4 个非单例数值等价类：

- `n2_lut256near_b16 = v2_lut256near_b16`；
- `n3_lut1024lin_b12 = v2_lut1024lin_b12`；
- `n4_lut1024lin_b16 = v2_lut1024lin_b16`；
- `v2_lut1024lin_b8 = v2_lut256lin_b8`。

这些候选只在 §2.3 主 pair 选择时按完整映射合并；面积/Pareto 仍保留全部实现。场景、指标与 RTL
联合回归为 42 passed，旧链 smoke PASS。模型—RTL gate 已通过，但正式 truth 仍不能启动：须先补正式
26-NCO/固定下游 runner，并完成 `q_cal` 与 runner manifest 审查。

### 8.5 正式 witness 预检 manifest（未运行 truth）

新增 `chains/ddc/prepare_witness_v1.py`，生成
`experiments_system/ddc_witness_v1/preflight_manifest.json`。该 manifest 锁定：

- 主候选集为历史 6 点 + v2 20 点，共 26 个 NCO；
- 下游固定为 `f1_c16 + c1_exact_rne`，用于隔离 NCO 机制；同时保存 FIR 整数系数及 SHA-256；
- 场景为 `ddc-witness-scen-v1`，聚合为 `C_main` 栅格 worst；
- exact-representable 零误差校准得到 `q_cal=0`，故
  `epsilon_Q=0.1*q_budget=2.32929922807541e-6`；
- 引用并哈希 §8.4 的 26/26 RTL 等价报告。

预检 manifest 明写 `truth_runner.allowed=false`，并把历史 `run_s1.py` 标为禁止的正式入口。新增 3 项预检
测试后，场景/指标/RTL/预检联合回归为 45 passed。这里仍**没有运行任何 chain truth**；下一步须实现
专用 26-NCO/固定下游 runner，并在执行前逐字段校验该 manifest。

### 8.6 专用 runner、面积口径与双阶段 truth gate（仍未运行 truth）

独立只读审查确认 §8.5 无 blocker 后，新增 `chains/ddc/run_witness_v1.py`，并把正式流程拆成不可跳过的
两阶段：

1. `prepare` 先计算并冻结 26 点 `M_core/M_DDS`、完整 Q-blind pair 审计与 NCO-only Nangate45 面积，
   生成带三份产物哈希的 `execution_manifest.json`；该阶段不读取或计算任何链级 `Q`；
2. `truth --run-id <new-id>` 只接受上述 execution manifest，拒绝旧 `run_s1.py`，按
   `main → heldout → stress` 顺序运行。`main_decision.json` 必须先落盘，之后才读取 heldout/stress。

预检 manifest 新增并冻结：Yosys 版本、Nangate45 `typ.lib` SHA-256、综合脚本文本及哈希、主 top
`nco_map`、主成本口径 NCO-only、无 SDC/不得作 timing/power 主张；完整 DDC 面积仅作 context。另写入
协议与 10 个实现文件的 SHA-256、Python/NumPy/SciPy 环境、`P_c=[0,240)` / `M_c=[240,end)`、以及
SFDR 的 `N=2^16`、8× 零填充和四项 Blackman–Harris 定义。

runner 逐候选×场景记录线性 `q_raw/q_aligned`、复增益、参考功率、CMUL/FIR 饱和数、混频预削波峰值、
样本数及场景缩放；`Q` 只在线性域取 max 并保存 argmax。main/heldout 任一饱和即停止；stress 允许但必须
报告。局部前沿、strict reversal/collapse、decision witness 与 SQNR 辅助 regret 均由冻结 local/area
输入和 main `Q` 机械计算，六点、v2 二十点和 26 点并集分开报告。

补充 3 个非零校准单测：已知复增益、已知小误差功率、desired-only 分母；`aligned_impl_error` 同时导出
`gain_re/gain_im`。NCO-only 综合入口用一个临时候选做 smoke，成功解析 mapped area；该数只用于验证
runner，不作为实验结论或候选比较。相关场景/指标/RTL/preflight/runner 测试共 **52 passed**。

当前 `preflight_manifest.json::truth_runner.allowed` 仍为 `false`。下一道 gate 是显式运行 `prepare` 并审阅
其 local/area/pair 三份冻结输入；本节没有生成 `frozen_inputs_v1`，也没有运行任何 chain truth。

### 8.7 `frozen_inputs_v1` 已签发（仍未运行 chain truth）

执行 `run_witness_v1.py prepare` 后生成以下不可覆盖产物：

- `experiments_system/ddc_witness_v1/frozen_inputs_v1/local_metrics.json`：26 点完整 `M_core` 与
  9+8 个整数 FCW 的有限记录 SFDR；
- 同目录 `area_results.json`：26 点 NCO-only Nangate45 mapped area；
- 同目录 `pair_selection.json`：20 点 v2 池全部 190 对的 Q-blind 审计；
- 同目录 `execution_manifest.json`：上述三份产物与 preflight 的 SHA-256，且仅该 manifest
  `truth_runner.allowed=true`。

局部结果来自 `local_metrics.json::rows`：冻结规则选中
`v2_lut512near_b16`（calibrated SQNR `44.58824775500641 dB`）与
`v2_cordic8_b16`（`46.976135312974534 dB`），两端差 `2.387887557968128 dB`，满足 3 dB 门限。
nearest512 的 truth 前纸面估计 `49.0 dB` 因此在 selection stage 被证伪；候选对恰好仍由冻结规则选中，
未重选。两者 9-FCW worst SFDR 分别为 `47.81666971005927 dBc` 与 `47.84500439065506 dBc`，差小于
冻结 `0.25 dB` 容差；这只是局部 collapse 候选，尚无链级 `Q`，不能称 reversal。

面积来自 `area_results.json::rows[*].area_um2`，26 点范围为 `368.41–3809.918 μm²`；主 pair 两端分别为
`820.61` 与 `1584.03 μm²`。这些是综合口径，不是物理实现，也不含固定下游 context。pair 审计 190 对中
11 对 eligible、113 对因 `|ΔSQNR|>3 dB` 剔除、66 对为同 architecture class；没有放宽门限。

`execution_manifest.json` 的四个引用哈希已由 runner 复验，26 点 local/area 均完整且局部 SQNR/SFDR
全部有限。`runs/` 尚不存在，因此截至本节仍没有 main/heldout/stress chain truth。下一步正式入口唯一为
`run_witness_v1.py truth --run-id <new-id>`；ε_Q 只能从 manifest 读取。

### 8.8 formal truth `formal-v1-20260930`

唯一正式入口完成 26 候选 × 77 场景，共 2002 行：main 936、heldout 832、stress 234。产物位于
`experiments_system/ddc_witness_v1/runs/formal-v1-20260930/`；`main_checkpoint.json` 与
`main_decision.json` 在 heldout/stress 之前落盘。全体 `n_sat_mix=n_sat_fir=0`，最大
`mix_preclip_peak_ratio=0.8078684061765671`，没有触发协议停止条件。

主契约结论来自 `main_decision.json::metrics.*.pools`：

- legacy 6 点池四项均无 strict reversal/collapse，P0 的 E0 先验成立；
- v2 二十点池：SQNR/WCE/SFDR 各 1 个 strict reversal；last-bit 有 8 个 strict reversal、3 个 collapse；
- 26 点并集：SQNR/WCE/SFDR 各 3 个 strict reversal；last-bit 有 10 个 strict reversal、7 个 collapse；
- 四项指标的 `decision_witness=false`，即没有任何局部指标–面积前沿点在 `(Q,area)` 上被严格支配。

SQNR/WCE/SFDR 的共同 strict witness 是局部更好的 `v2_cordic7_b16` 被 nearest-256 三个标签中的实现反转。
例如相对 `n1_lut256near_b12`，`ΔSQNR=2.120721093670923 dB`，但
`Q_cordic7-Q_n1=4.968561768671522e-6 > ε_Q`。不过两者主 `Q` 分别为
`1.143729761463575e-4` 与 `1.0940441437768597e-4`，均约为 `q_budget` 的 4.7–4.9 倍；并且 CORDIC7
不在可造成设计损失的局部–面积选择位置。因此该结果只支持 **mechanism witness**，不支持“局部指标造成
设计损失”。

预注册主 pair 为 `v2_lut512near_b16` vs `v2_cordic8_b16`；两者 main `Q` 分别为
`3.27362955299273e-5` 与 `3.418376897719962e-5`，`|ΔQ|=1.447473447272321e-6 < ε_Q`，故 P1 的固定 pair
方向预测为阴性，按协议不重选。SQNR≥S* 的辅助选择为 `v2_lut1024lin_b10`，其 quality/area regret 均为 0。

main `Q` 范围为 `6.3482103150183136e-9–5.312937877302314e-4`；heldout 与 stress 单独保留，未混入主判定。
当前 Evaluation axis 不是 E0（已存在超阈保序失败），但 E1/E2/E3 尚未确定：下一步必须先冻结基线③
相对 truth 的 Gate A/B 阈值，再运行 candidate-exact linear-reference baseline。不得用本轮已见结果调整阈值。

### 8.9 candidate-exact linear-reference baseline ③：E1

运行前新建并冻结 `thesis/BASELINE3_PROTOCOL_DDC_v1.md`。Gate A 的工程绝对阈值直接复用 truth 前已有的
`epsilon_Q=2.32929922807541e-6`；Gate B 冻结 `k={1,3,5}`，要求最大 top-k regret、最大预算违约均不超过
`epsilon_Q`，且 formal truth 登记的每个 failure 均被③同向排序或判为 ε 内并列。stress 不参与 gate。

`chains/ddc/run_linear_baseline_v1.py` 在 NCO 接口取候选 bit-true 复本振，用同一 `x_adc`、固定
`f1_c16` 的 `hq/2^(wc-2)` 线性 FIR 和 phase-0 抽取做相干传播；排除 CMUL/FIR 数据通路 round/sat。
结果保存于 `experiments_system/ddc_witness_v1/baseline3_v1/results.json`，共 2002 行。

Gate A（`results.json::gate_a`）通过：main+heldout 1768 点的绝对误差 median/p95/max 分别为
`3.240737126439407e-9`、`1.6379201467809804e-8`、`8.962187760598898e-8`；最大值仅为 ε_Q 的
`0.03847589718219213`。nearest LUT、linear LUT、CORDIC 三类各自 max 均低于阈值。

Gate B（`results.json::gate_b`）通过：top-1/3/5 regret 全为 0，true-best 均命中；false-feasible 为 0，
最大预算违约为 0；Kendall τ-b=`1.0`；formal truth 登记的 26 个 metric×pair failure 全部 explained。

因此 Evaluation axis 正式归为 **E1**：本轮保序失败由 candidate-dependent coherent linear propagation
完整解释，属于经典线性物理。不得声称新误差理论，也没有证据要求用④解释本批数据。③在工程容差内可称
validated approximation / ranking surrogate，不称 full-chain 精确恒等。当前仍无 decision witness；下一步若做
搜索，贡献只能检验“自动装配结构特异链级 fitness + 开放结构搜索”是否得到 S1，不能把本轮机制反转写成设计损失。

### 8.10 formal S 重跑启动（readiness v2 轮换）

按 `FORMAL_BACKEND_ERRATUM_v1` 的重跑纪律执行：修订实现的就绪复核换用
`refine-logs/FORMAL_S_READY_v2.json`（pin 当前源码 digest `c43b6046…`、协议 sha `b6766909…`
与中止 run 一致、当前源码全量测试 848 passed 记录
`refine-logs/FORMAL_TESTS_20261003_104111.json`）。差异复核（834d449→ffe76b5）确认
`protocol_spec()` 零改动，formal_run/validate_main 修订仅历史源码对账走新增
`search_ir/provenance.py`。

登记一次执行偏差：首次 launch（`formal-necessary-v2-20261003`）在 `_ready` 处立即失败——
签发的 readiness JSON 漏写机器校验字段 `status:"reviewed"`（KeyError），无任何实验副作用；
失败 `.launch` 现场保留未删，文件修复后 amend 提交（5b5c3c6）。正式重跑为
`formal-necessary-v2-20261003b`（5 seeds × {joint, staged} × B=32 = 320 attempts，条件性
cost-first 160），按冻结 `FORMAL_S_PROTOCOL_v1` 原样执行；旧 formal-v1 产物保留，不拼接、
不判 S0。

### 8.11 formal S 判定：`formal-necessary-v2-20261003b` → S0

冻结协议 `FORMAL_S_PROTOCOL_v1`（sha `b6766909…`，与中止 run 一致）完整执行：320/320 attempts
全部计费（229 ok / 74 invalid_proposal / 15 saturation_failed / 2 candidate_timeout），墙钟
25472.6 s（7.08 h，stage1 12 h 限制内）。主 archive 锁定后 held-out 终考 49 个唯一候选；
十个 seed/arm collection 合计 60 条成员记录（跨 collection 的重复候选只评价一次）。
`stage1_decision.json` 判定：

- joint−staged HV 差的配对 bootstrap 95% CI = [−0.0196, +0.0418]（mean +0.0084，n=5），下界
  未 > 0；
- 工程命中 seed 数 2/5（要求 ≥3）：seed 101 joint 面积 34207.068 vs staged 36968.148
  μm²（省 2761.08，> ε_A=383.46），seed 307 省 805.45 μm²；seed 211/401/503 无命中且
  HV 差为负（−0.032/−0.013/−0.008）；
- `necessary_pass=false` → 按预注册 stop rule 判 **S0**，`cost_first=not-run
  -preregistered-necessary-condition-failed`，L/D 记 N/A。

产物：`experiments_search/formal_s/formal-necessary-v2-20261003b/`（manifest、ledger、
archive_lock、heldout_results、stage1_decision、results.json）。协议未改、判据未动、旧
formal-v1 inconclusive 产物继续保留；未运行 LLM，未换链。

### 8.12 CIC witness 第一次冻结后的预检

按 `thesis/CONTRACT_CIC_WITNESS_v1.md` 第 8 节完成逐位整数模型与候选等价扫描。模型在每个
锁存边界显式执行低位裁剪和内部 wrap/sat，I/Q 两路独立运行，并分别记录内部溢出与固定输出
饱和。满宽 wrap 候选已与 CIC 等价 FIR 在四个 `(R,N)` 组合上逐点交叉验证。

预检产物为
`experiments_system/cic_witness_v1/preflight_manifest.json`，SHA-256 为
`0a1bd6b725bc495a719b37e42e0a0dbfec8b1c8281bd79f657c9e35d59997d54`。28 个生成候选合并为
23 个数值语义不同的代表：`R2N3` 的 H/U0/RND、`R2N4` 的 H/U0/RND、`R4N3` 的 H/U0
分别构成三个重复类。R2 两组没有低位右移，因此 rne/trunc 不产生行为差异。wrap 与 sat
在固定压力输入上产生不同位流，保持为不同候选。

manifest 同时物化每个 R 下 18 个 main、12 个 held-out、6 个 stress 场景；这些场景尚未生成
链级质量。相关 CIC 与 DDC 公共回归共 46 项通过。`formal_execution.allowed=false`，下一道门是
用户确认该 manifest；确认前不计算局部排名、链级 q 或反转判定。

用户于 2026-10-08 批准第二次冻结。签发记录为
`experiments_system/cic_witness_v1/SECOND_FREEZE_v1.json`，引用上述 manifest 与第一次冻结协议的
SHA-256，不修改已批准的 manifest。此后允许实现参考链交叉验证并按已冻结清单计算局部指标和链级 q；
候选、场景、阈值和判据不得重选或覆盖修改。

### 8.13 CIC execution-v1 准备顺序偏差

正式 runner 准备时发现累计裁剪位数这一整数指标尚未明确容差。准备命令已经写出
`local_metrics_v1.json` 与 `execution_manifest_v1.json`，但没有计算指标排名、链级 q 或反转判定。
由于原值落盘早于该容差获得用户确认，这两份文件只作历史诊断，不得进入正式结论，且保留不覆盖。

后续须先冻结累计裁剪容差，再使用新文件名生成 execution-v2 与正式局部指标表；formal runner 只能接受
v2 manifest。此次偏差没有读取 main、held-out 或 stress 的候选质量结果。

用户随后授权执行方按默认方案确认。累计裁剪位数容差在正式链级 q 计算前冻结为 `0 bit`：只有整数位数
完全相同才视为局部并列。签发记录为
`experiments_system/cic_witness_v1/PRUNING_TOLERANCE_FREEZE_v1.json`。正式 runner 改为只读取
`local_metrics_v2.json` 与 `execution_manifest_v2.json`；两个 v1 文件继续只作顺序偏差的历史诊断。

### 8.14 CIC 首次正式运行暴露最后一级 wrap 解释缺口

`formal-cic-witness-v1-20261008` 完成 414 条 main、276 条 held-out、138 条 stress 后，满宽 wrap
基线仍出现约 80–150 的链级误差，而冻结预算仅为 `2.32929922807541e-5`。审计定位到
`CICBitTrue.push()`：最后一级梳状器的扩展差值可能带一个整模数偏移，代码未先解释为冻结的
`[B_(2N),B_max]` 有符号位窗口，便直接送入固定 sat16，制造了稀疏的 `-1/+1` 满幅脉冲。

旧目录与结果原样保留，并增加 `INVALIDATED_BY_ERRATUM_v1.json`；其中全部排序、反转计数和
held-out 数字只作评价器诊断，不得进入论文结论。修复只对 wrap 型候选在最终格式转换前恢复同一物理
模数下的有符号代表，不改变候选池、场景、阈值或判据。13,312 点近满量程长序列新增为强制回归，
四个 `(R,N)` 组合在确实发生内部 wrap 时仍须逐样本等于等价 FIR。勘误与完整重跑纪律见
`thesis/CIC_BACKEND_ERRATUM_v1.md`；后续只允许 execution-v3 + 新 run-id 完整重跑。
