# VeriEvolve 全部实验目录

> 整理日期：2026-10-13。只汇总已落盘的结果，不含推测。数字均可在“数据”一栏的文件中核对。

## 0. 阅读约定

### 0.1 路径

| 简写 | 实际位置 | 是否在 git 中 |
|---|---|---|
| `代码/` | `/Users/chengzhy/verievolve/examples/comm_dsp_bench/`（main 分支，2026-10-13 从 Codex 工作区复制，**尚未提交**） | 待提交 |
| `B/` | `/Users/chengzhy/.codex/worktrees/da43/verievolve/examples/comm_dsp_bench/experiments_dspgraph/`（1.3 GB） | **否** |
| `M1/` | `/Users/chengzhy/verievolve/examples/comm_dsp_bench/`（第一阶段的实验目录） | 部分 |
| `D43/` | `/Users/chengzhy/.codex/worktrees/da43/verievolve/examples/comm_dsp_bench/`（第一阶段在 Codex 工作区的实验目录） | 否 |
| `AW/` | `/Users/chengzhy/verievolve_agent_ws/`（agent 实验工作区） | 否 |
| `T/` | `/Users/chengzhy/verievolve_tools/`（agent 工具、驱动脚本的原始副本） | 否 |

### 0.2 通用口径

| 项目 | 说明 |
|---|---|
| **链 A 规格** | 接收 DDC。开发规格 6 个：`dev_r{16,32,64}_{wide,narrow}`；留出规格 6 个：`ho_r16_mid / r24_wide / r32_mid / r48_narrow / r64_mid / r96_narrow`。定义在 `代码/dspgraph/rx_spec.py`，新框架里为 `代码/dspgen/tasks/ddc.py` |
| **链 B 规格** | 发射 DUC：`duc_l4_narrow / l8_wide / l16_mid`，定义在 `代码/dspgen/tasks/duc.py` |
| **裁判 v1** | 每个场景 3 个强阻塞音，2 个搜索场景。**有漏洞**（只检验 6 个频点），v1 下的面积结论全部作废 |
| **裁判 v2** | 阻塞音覆盖全部混叠带（每带 2 个随机频点，共 12–57 个），搜索场景 0、1，留出场景 10、11、12。`JUDGE_VERSION="v2-dense-blockers"`，`代码/dspgraph/judge.py` |
| **达标** | 各场景 SNR ≥ 理想上限 − 允许损失，且纹波 ≤ 上限。“裕量”= 最差场景 SNR − 门槛 |
| **代理面积** | 原语单价模型。2026-10-10 用真实综合校准后，单位为 μm²（快速 ABC 口径） |
| **真实面积** | Yosys + ABC，Nangate45 typical。“快速 ABC”为轻量映射脚本，比完整映射约高 5%–10% |
| **时序** | 10-11 起用 ABC stime（sized，口径粗）；10-13 起改用 **OpenSTA**（含 clk-to-q、建立时间、NLDM，输出负载 5 fF） |
| **功耗** | 10-13 起由 OpenSTA 报告，全局翻转率 0.1、时钟 2 ns（500 MHz），只适合横向比较 |
| **LLM** | 默认 DeepSeek `deepseek-flash`（关闭思考）；部分实验用 `deepseek-v4-pro`；agent 实验用 Claude |
| **M** | 本方法（OpenEvolve diff 进化 + 原语程序），起点为照公式直写的程序 |
| **R** | 教科书结构模板（NCO → CIC → 半带 → 补偿 FIR）经参数搜索的最优设计。**模板代码由 Claude 在指定结构的条件下写成，不是人类专家设计** |
| **R03** | 满足 0.3 dB 裕量的模板设计中面积最小者 |

---

## 1. 总览

| 编号 | 实验 | 日期 | 状态 | 一句话结论 |
|---|---|---|---|---|
| **第一阶段：单算子与受限结构空间（10-08 至 10-09）** |||||
| S1 | 单算子短跑与复现（6 算子） | 10-08 | 完成 | 见 §2 |
| S2 | 受限空间 2×2 搜索（cmul / sin-cos / atan2 / NCO / FIR / LLR） | 10-09 | 完成 | 有限空间内 LLM 没有优势 |
| S3 | typed IR 公式到硬件路径（DDC） | 10-08 | 完成 | 流程打通，DeepSeek 候选可综合 |
| **第二阶段：原语程序与整链 DDC（10-09 起）** |||||
| P0 | 一次性生成试点（harness A/B） | 10-09 | 完成 | 9/80、1/80、1/80 |
| P1 | 早期 OpenEvolve 试跑 | 10-09 | 完成 | 种群达标 46%–55% |
| P2 | 命题 2（裁判 v1） | 10-09/10 | **作废** | 裁判 v1 漏洞 |
| P3 | 命题 1：联合 vs 分阶段（v1） | 10-10 | **作废** | 裁判 v1 漏洞 |
| P4 | 反馈消融（v1） | 10-10 | **作废** | 裁判 v1 漏洞 |
| C1 | 裁判 v1 留出复核 | 10-10 | 完成 | v1 被钻空子，最差 −34.6 dB |
| C2 | 代价模型校准 | 10-10 | 完成 | Spearman 0.57 → 0.987 |
| **E1** | **主表：M vs 直写 vs R（v2）** | 10-10 | 完成 | 真实面积降 71.5%–89.0% |
| E2 | 非 LLM 程序搜索（数值 / 结构变异） | 10-10 | 完成 | 面积比 0.871 / 0.884，M 为 0.131 |
| E3 | 命题 1：联合 vs 分阶段（v2，开发 + 留出） | 10-10 | 完成 | 分阶段显著更优（p < 0.001） |
| E4 | 反馈消融（v2，2 种子 → 4 种子） | 10-10/11 | 完成 | 指标数值显著有效，诊断无额外收益 |
| E5 | 领域知识增强 | 10-10 | 完成 | 单种子未见收益 |
| E6 | 演化路径与进化曲线 | 10-10 | 完成 | 面积主要由结构变换降低 |
| E7 | 时序（ABC stime） | 10-11 | 完成 | 关键路径 2–3.5 ns |
| E8 | 逐级最优 vs 整链（E2.1/E2.2） | 10-11 | 完成 | 整链省 19%–42%，宽带逐级无解 |
| E9 | 分工混合（A2） | 10-11 | 完成 | 负结果 |
| E10 | 主表补到 3 种子（E4.2） | 10-12 | 完成 | 18/18 达标，留出 13/18 |
| E11 | 留出规格复验（E4.3） | 10-12 | 完成 | 6/6 达标，降 40.5%–92.5% |
| E12 | 0.3 dB 安全裕量（A5，链 A + 链 B） | 10-12 | 完成 | 4/4 原不达标规格转为达标 |
| E13 | LLM 直接写 Verilog（B1） | 10-12 | 完成 | 4/6 有结果，弱于 M |
| E14 | 链 B（DUC）：M 与模板 | 10-12 | 完成 | M 降 45%–50%，达到模板的 20%–59% |
| E15 | 两层搜索（E3.6） | 10-12 | 完成 | 从直写：不优于 M；从模板：只调参数 |
| E16 | 开源 USRP DDC 人类基线（H1 / H1b） | 10-12 | 完成 | 12/12 不达标 |
| E17 | 统一系统 v1（结构生成 + 两层） | 10-12 | 完成 | 负结果，面积为 M 的 2.1 倍 |
| E18 | 结构生成失败诊断 | 10-12 | 完成 | 全部是约定错误 |
| E19 | DeepSeek 用法对照（E-H） | 10-12 | 部分完成 | 裸对话 0/6；自建循环最好 22.1 万 |
| **E20** | **Claude agent（任务契约 + 工具），r32n** | 10-12 | 完成（未做最终评估） | 代理面积 12,645 |
| E21 | DeepSeek 在 Claude Code 中，r32n | 10-12 | 被用户停止 | 最好 10.4 万 |
| **E22** | **OpenSTA PPA 对比，r32n** | 10-13 | 完成 | Claude agent 设计 PPA 全面最优 |
| F1 | 通用框架回归与链 B 接入 | 10-11/12 | 完成 | 回归全过，链 B 规格 20 行 |

---

## 2. 第一阶段：单算子与受限结构空间（10-08 至 10-09）

这一阶段研究“LLM 在预设结构空间中选择或组合”。详细记录在 `Iknow.md` 的 10-08、10-09 各节。结论是：**在可以穷举的有限空间里，LLM 不比枚举或随机搜索更好**。这直接导致了第二阶段转向“LLM 用通用原语写构造程序”。

| 编号 | 内容 | 数据目录 | 结论（摘自 Iknow.md） |
|---|---|---|---|
| S1 | 六个通信 DSP 算子真实短跑、三种子复现、GF(2) 与长抽头补测 | `M1/experiments_e1/`、`M1/experiments_system/` | 流程跑通，提供了单算子基准 |
| S2a | sin/cos 2×2 搜索 | `M1/experiments_m5/joint_sincos_*` | — |
| S2b | atan2 2×2 与同预算离散进化 | `D43/experiments_m3/`、Iknow 10-09 | 有限空间内 LLM 未证明优势 |
| S2c | cmul 2×2、非均匀截位、三路 seed-1 对照 | `M1/experiments_m5/joint_cmul_*` | 未击败最强统一基线 |
| S2d | NCO 2×2、受限分解、同预算随机基线 | Iknow 10-09 | 受限分解为负结果；LLM 明显落后随机基线 |
| S2e | FIR 2×2、2:1 FIR 抽取器运算图 | `M1/experiments_m5/joint_fir_*` | — |
| S2f | max-log 64QAM LLR 2×2 | Iknow 10-09 | — |
| S2g | 层级动作提议器（FIR / NCO） | `M1/experiments_m4/` | — |
| S2h | Gold scrambler 三个结构点、FFT64 结构 | `D43/experiments_benchmark/` | 面积排序依赖后端 |
| S2i | 复数旋转：专家结构、LLM 延续开发、原生 RTL | `D43/experiments_rotation/` | — |
| S3 | typed IR 公式到硬件（DDC）、DeepSeek 候选真实映射 | `M1/experiments_system/formula_to_rtl_dev/` | 16 级 CORDIC + 16 位对称 FIR，41,426 μm²；600 s 综合超时，1200 s 内完成 |
| S4 | DDC 系统主集、held-out 与 stress、100 MHz 约束批次 | `M1/experiments_system/` | 本机当时没有 STA |
| S5 | 证书化适应度、Search IR 一系列运行 | `M1/experiments_search/`（7.2 GB） | 早期方向，已被替代 |

---

## 3. 第二阶段：原语程序与整链 DDC

### P0 一次性生成试点（harness A/B）

| 项目 | 内容 |
|---|---|
| 问题 | 让 LLM 每次从头写一个完整的 DDC 程序，能否达标；加编译修复和探针是否有帮助 |
| 代码 | `代码/dspgraph/llm_prog.py`、`run_prog.py` |
| 数据 | `B/harness_ab_v1_flash_20261009/`、`harness_ab_v2_flash_20261009/`、`harness_ab_v2_pro_20261009/`；逐次记录在 `*/call_NNN.json` 的 `outcome` 字段 |
| 设置 | 2 规格 × 2 种子 × 20 次调用 = 80 次；裁判 v1 |
| 结果 | v1（flash）9/80 达标；v2（加编译修复、自动截位、探针）1/80；v2 pro 1/80。未达标的大多差 10 dB 以上 |
| 附 | 思考模式试点 `B/pilot_prog_v3_thinking_20261009/`：开启思考后 2 万 token 用于推理，没有输出代码 |

### P1 早期 OpenEvolve 试跑

| 项目 | 内容 |
|---|---|
| 数据 | `B/oe_v2_verified_dev_r16_narrow_s0_20261009/`、`oe_v2_verified_dev_r32_wide_s0_20261009/` |
| 设置 | 80 次迭代，裁判 v1 |
| 结果 | 最终种群达标 22/40（55%）、19/41（46%） |

### P2–P4 命题 1/2/3 首轮（裁判 v1，**全部作废**）

| 编号 | 数据 | 原结论（作废） |
|---|---|---|
| P2 命题 2 | `B/p2_oe_dev_verified_v1_20261009/`、`p2_oe_dev_verified_v1b_20261010/`；汇总 `B/analysis_v1_20261010.json`；综合 `B/synth_compare_v1_20261010.json` | 代理面积降 86%–96% |
| P2 从专家起点 | `B/p2_oe_from_expert_v1_20261010/`、`p2_oe_from_expert_structonly_v1_20261010/`；`B/verify_structonly_r16n_v1_20261010.json` | structonly r16n 代理降 46%，真实只降 2.2% |
| P2 对照 | `B/expert_continue_120_v1_20261010.json` | 模板继续调参降 0–4.4% |
| P3 命题 1 | `B/p1_template_dev_v1_20261009/` | 联合/分阶段 0.90，p = 0.95 |
| P4 命题 3 | `B/p3_oe_feedback_v2_20261010/`（另有 3 个 ABORTED 目录） | 6 对：0.131 / 0.139 / 0.109 |

作废原因见 C1。原始数据保留，只作为“发现评价器漏洞”的证据。

### C1 裁判 v1 留出复核

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/holdout_check.py` |
| 数据 | `B/holdout_check_v1_20261010.json`；搜索/留出裕量对（74 + 21 条）`B/margin_pairs_v1_v2_20261010.json` |
| 结果 | 分阶段 7/30、联合 3/29、LLM 1/6、structonly 0/6 在留出场景达标；最差 −34.6 dB |
| 修订 | 裁判 v2；直写起点在 v2 下搜索/留出裕量一致（如 1.78 / 1.74 dB） |

### C2 代价模型校准

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/calibrate_sdf.py`；单价写入 `代码/dspgraph/cost_calibration.json` |
| 数据 | `B/sdf_cost_calibration_v1_20261010/summary.json` |
| 设置 | 52 个设计真实综合（快速 ABC），奇偶划分训练/留出 |
| 结果 | 留出集 Spearman 0.57 → **0.987**，相对误差中位数 13.6% → **2.3%**，p90 8.6%；查找表单价 0.55 → 0.044/bit（原模型高估约 12 倍）。主表 17 个设计复核：Spearman 1.0，误差中位数 4.8% |

### E1 主表：M vs 直写 vs R（裁判 v2，种子 0）

| 项目 | 内容 |
|---|---|
| 代码 | 运行 `代码/dspgraph/run_oe_grid.py` + `oe_eval.py`；最终评估 `final_eval.py` |
| 数据 | 汇总 `B/main_table_v2_20261010.json`；M 的运行在 `B/p3_oe_feedback_v3_judge2_20261010/`（r16n、r32w、r64n 的 verified 档）与 `B/p2_oe_naive_v3_judge2_20261010/`（r16w、r32n、r64w）；最终评估 `B/final_eval_M_naive_v2_20261010*.json`、`B/final_eval_R_v2_20261010.json`、`B/final_eval_naive_r64w_v2_20261010.json` |
| 设置 | deepseek-flash，verified 反馈，120 次迭代；R 为 P3 v2 中 10 次运行（每次 400 次评价）的最优 |

| 规格 | 直写真实面积 | M 真实面积 | 降幅 | M 搜索 / 留出裕量 (dB) | R 真实面积 | R 留出裕量 | R/M |
|---|---|---|---|---|---|---|---|
| r16n | 425,644 | 121,112 | 71.5% | +0.36 / −0.05 | 32,210 | +0.03 | 0.27 |
| r16w | 946,859 | 134,285 | 85.8% | +0.05 / −0.30 | 112,852 | −1.03 | 0.84 |
| r32n | 709,042 | 92,264 | 87.0% | +0.23 / +0.24 | 29,155 | +0.10 | 0.32 |
| r32w | 1,889,223 | 276,398 | 85.4% | +0.63 / +0.94 | 109,802 | −0.85 | 0.40 |
| r64n | 1,622,343 | 178,227 | 89.0% | +0.15 / +0.34 | 35,428 | +0.39 | 0.20 |
| r64w | 2,559,706 | 296,043 | 88.4% | — / +1.26 | 56,303 | +0.58 | 0.19 |

- 所有设计 RTL 对拍 0 失配（直写起点只比较了前 1500 个输入样点）。
- 留出达标：M 4/6，R 4/6，直写 6/6（裕量 1.7–2.3 dB）。

### E2 非 LLM 程序搜索

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/random_prog_search.py`（数值字面量变异）；结构变异版本见同目录 |
| 数据 | `B/random_prog_baseline_v1_judge2_20261010.json`、`B/random_struct_baseline_v1_judge2_20261010.json`；曲线 `B/curves_M_B3_v2_20261010.csv` |
| 设置 | 同一直写起点，120 次评价，6 规格 × 2 种子 |
| 结果（校准面积 / 直写，几何均值） | 数值变异 **0.871**，结构变异 **0.884**，M **0.131** |

### E3 命题 1：联合 vs 按角色分阶段（裁判 v2）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/template_search.py`、`template.py`、`analyze.py` |
| 数据 | 开发集 `B/p1_template_dev_v2_judge2_20261010/results.json`、汇总 `B/analysis_p1_v2_judge2_20261010.json`；留出集 `B/p1_template_heldout_v2_judge2_20261010/`、`B/analysis_p1_heldout_v2_20261010.json` |
| 设置 | 模板空间，6 规格 × 5 种子 × 2 方法，每次 400 次评价 |

| 规格集 | 配对数 | 联合/分阶段面积比 | 分阶段更优 | Wilcoxon p |
|---|---|---|---|---|
| 开发集 | 30 | 1.22 | 24/30 | 0.0004 |
| 留出集 | 30 | 1.26 | 23/30 | 0.0006 |

链 B 上（8 对，见 E14）联合 5/8 更好，几何均值 0.92，不显著；结论只限链 A。

### E4 反馈消融

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/oe_eval.py`（`DSPG_MODE` = scalar / metrics / verified） |
| 数据 | 2 种子：`B/p3_oe_feedback_v3_judge2_20261010/`、`B/analysis_p3_v3_judge2_20261010.json`；4 种子：`B/groupA_v1_20261011/A3_feedback_seeds23/`、`B/groupA_v1_20261011/A3_feedback_4seeds_analysis.json` |
| 设置 | r16n、r32w、r64n × 3 档 × 种子 0–3 × 120 次迭代（共 36 个运行） |

| 反馈 | 面积比（几何均值） | 对“只给分数” |
|---|---|---|
| 只给分数 | 0.224 | — |
| 给全部指标数值 | 0.134 | 0.60，11/12 更好，p = 0.001 |
| 再加诊断归因 | 0.137 | 0.61，11/12 更好，p = 0.002 |
| 诊断 vs 指标数值 | — | 1.02，4/12，p = 0.52（无差异） |

### E5 领域知识增强

| 项目 | 内容 |
|---|---|
| 数据 | `B/k_knowledge_v1_judge2_20261010/`；知识文本 `代码/dspgraph/knowledge_multirate.txt` |
| 设置 | r16n、r32w × 种子 0，提示词加入多速率结构说明（不含具体答案） |
| 结果 | 有知识 / 无知识：r16n 0.256 / 0.226，r32w 0.262 / 0.129。LLM 开始使用多相，但面积更大，仍未用 CIC。单种子，只能说“未见收益” |

### E6 演化路径与进化曲线

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/export_oe.py`、`export_population.py` |
| 数据 | 祖先链 `B/ancestry_M_r32w_r64n_v2_20261010.json`；曲线 `B/curves_M_B3_v2_20261010.csv`；种群前沿 `B/population_M_v2_seed01_20261012.json` |
| r32w 路径（校准面积 / 直写） | 直写 1.000 → 多相分解（未达标）4.056 → 两级抽取 + 多相 0.243 → 四分之一波查表 + 三级抽取 8×2×2 0.138 → 缩短字长 0.129 |
| r64n 路径 | 1.000 → 相位截短 14 位 + 两级抽取 0.184 → 相位截短 12 位 0.114 → 缩短字长 0.107 |

### E7 时序（ABC stime，已被 E22 取代）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/timing.py`（已标为弃用） |
| 数据 | `B/timing_summary_v1_20261011.json`（sized 口径） |
| 结果 | 直写 284–354 MHz，M 382–507 MHz，R 359–412 MHz；关键路径都在 2–3.5 ns |

### E8 逐级最优再拼接 vs 整链优化（E2.1 / E2.2）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/stagewise.py` |
| 数据 | `B/e21_stagewise_v1_20261011/`：冻结规则 `FROZEN_RULES.md`、汇总 `E21_summary.json`、最终评估 `final_eval_stagewise.json`、规则外补充 `supplement_infeasible_loosen.json`、误差份额 `error_shares_E22_normalized.json` |
| 设置 | 模板空间；规则 A 平均分配误差预算，规则 B 混叠类 70% / 量化类 30% |

| 规格 | 整链（R） | 逐级 A | 整链节省 |
|---|---|---|---|
| r16n | 32,210 | 50,542（刚好达标版 39,693） | 36%（裕量拉平后 19%） |
| r32n | 29,155 | 50,439（收紧后达标） | 42% |
| r64n | 35,428 | 55,938 | 37% |
| 宽带 3 个 | 有达标解 | 局部指标无解；放宽到有解时整链差 0.6–2.5 dB | — |

误差份额：6 个规格中 5 个是 NCO 占实现误差的大头（7%–36%），CIC 字长和系数量化几乎不占；各项之和 0.98–1.02。15 个逐级设计 RTL 0 失配。

### E9 分工混合（A2，负结果）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/tune.py` |
| 数据 | `B/groupA_v1_20261011/A2_hybrid/tune_results.json`；“M 最优 + 下降”的最终评估 `final_eval_M120_tuned.json` |
| 设置 | LLM 60 次迭代 + 确定性位宽/复用下降 60 次评价，对比 M 的 120 次迭代，9 对 |
| 结果 | 混合 / M 几何均值约 1.11，3/9 更好。在 M 最优上追加下降可再降 1%–13%，但裕量被压到 0.0003–0.036 dB，留出只有 4/9 达标 |

### E10 主表补到 3 种子（E4.2）

| 项目 | 内容 |
|---|---|
| 数据 | `B/groupA_v1_20261011/E42_M_3seeds_and_A5_chainA.json`、`final_eval_E42_A5.json`；运行 `A4_M_seeds12/` |

| 规格 | 降幅中位数（范围） | R/M 中位数（最好） | 留出达标 |
|---|---|---|---|
| r16n | 71.5%（70.6–89.7） | 0.27（0.74） | 0/3 |
| r16w | 68.1%（51.9–85.8） | 0.37（0.84） | 1/3 |
| r32n | 86.7%（79.1–87.0） | 0.31（0.32） | 3/3 |
| r32w | 85.5%（85.4–85.8） | 0.40（0.41） | 3/3 |
| r64n | 88.9%（83.9–89.0） | 0.20（0.20） | 3/3 |
| r64w | 92.3%（88.4–93.9） | 0.29（0.36） | 3/3 |

18/18 找到达标设计；留出 13/18。

### E11 留出规格复验（E4.3）

| 项目 | 内容 |
|---|---|
| 数据 | `B/groupA_v1_20261011/E43_heldout_specs_table.json`、`final_eval_E43_heldout*.json`；运行 `A4_M_heldout/` |
| 设置 | M，verified 档，种子 0，无安全裕量 |
| 结果 | 6/6 找到达标设计；真实面积降幅 r16_mid 40.5%、r24_wide 68.1%、r32_mid 75.5%、r48_narrow 87.6%、r64_mid 84.6%、r96_narrow 92.5%（186,388 vs 2,500,318）；留出 4/6（r24w、r48n 不达标）；R/M（校准）0.14–0.26 |

### E12 0.3 dB 安全裕量（A5）

| 项目 | 内容 |
|---|---|
| 数据 | 链 A `B/groupA_v1_20261011/A5_margin03/`；链 B `A5_chainB_margin03/`、`final_eval_A5_chainB.json` |

| 规格 | 留出裕量：无裕量 → 0.3 dB | 真实面积 |
|---|---|---|
| r16n | −0.05 → +0.57 | 121,112 → 118,863 |
| r16w | −0.30 → +0.16 | 134,285 → 107,296 |
| duc_l8 | −0.21 → +0.21 | 195,781 → 222,486 |
| duc_l16 | −0.16 → +0.05 | 228,200 → 170,930 |

4/4 转为达标，面积变化 −25% 至 +14%，无一致方向。每个规格 1 个种子。

### E13 LLM 直接写 Verilog（B1）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/oe_eval_verilog.py`、`vlog_eval.py`、`b1_finalize.py`；起点 `代码/dspgraph/seeds/naive_verilog.v` |
| 数据 | `B/groupA_v1_20261011/A1_b1_verilog/`、`B1_summary.json` |
| 设置 | deepseek-flash，metrics 反馈，种子 0，120 次迭代；每次评价约 6 分钟（仿真 + 真实综合） |

| 规格 | 起点真实面积 | 最优真实面积 | 降幅 | 留出 | 种群达标 |
|---|---|---|---|---|---|
| r16n | 661,986 | 148,167 | 77.6% | 达标 | 30/40 |
| r16w | 1,531,518 | 608,599 | 60.3% | 达标 | 21/40 |
| r32n | 1,090,434 | 1,090,434 | 0% | 达标 | 3/41 |
| r32w | 综合 > 900 s | — | — | — | 0/39 |
| r64n | 2,587,814 | 916,691 | 64.6% | 达标 | 1/41 |
| r64w | 综合 > 900 s | — | — | — | 0/39 |

### E14 链 B（DUC）

| 项目 | 内容 |
|---|---|
| 代码 | 规格 `代码/dspgen/tasks/duc.py`；模板 `代码/dspgen/templates/duc.py`；模板搜索 `代码/dspgen/tsearch.py` |
| 数据 | M：`B/chainB_duc_M_v1_20261012/final_eval.json`；模板：`B/chainB_duc_template_v1_20261012/results.json`、`final_eval_R.json` |

| 规格 | 直写真实面积 | M 真实面积 | 降幅 | M 留出 | R 真实面积 | R/M |
|---|---|---|---|---|---|---|
| l4_narrow | 110,533 | 54,800 | 50.4% | +0.13 | 32,207 | 0.59 |
| l8_wide | 354,577 | 195,781 | 44.8% | −0.21 | 65,120 | 0.33 |
| l16_mid | 429,584 | 228,200 | 46.9% | −0.16 | 45,593 | 0.20 |

M 种群达标 31–33/40，RTL 0 失配。R 在 l4、l8 留出不达标（−0.07、−0.60 dB）。

### E15 两层搜索（E3.6）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgraph/e36_finalize.py`、`tune.py` |
| 数据 | `B/e36_twolevel_v1_20261012/`：协议 `FROZEN_PROTOCOL.md`；实验 1 `exp1_summary.json`；实验 2 `exp2_summary.json`、`exp2_final_eval.json`、对照 `exp2_control_tune_only.json` |
| 设置 | 外层 LLM，内层每个达标候选最多 5 次确定性调优，0.3 dB 裕量 |
| 实验 1（从直写，12 个运行） | 对 M 的面积比几何均值 1.46，5/12 更好，p = 0.13；留出 11/12 |
| 实验 2（从 R03，6 规格） | 对 R：几何均值 1.11，只有 r32w 更小（0.927）；对“只调优”：0.951，5/6 更好；留出：两层 5/6、只调优 3/6、R 4/6。6 个规格中 4 个代码结构未变、2 个各改 1 行，面积下降来自调整抽头数等参数 |

### E16 开源 USRP DDC 人类基线（H1 / H1b）

| 项目 | 内容 |
|---|---|
| 源码 | EttusResearch/fpga，commit `287ad57430b1dacdce6d793536ff96dc8f630419`，`usrp2/sdr_lib/ddc_chain.v`；下载在 `/Users/chengzhy/verievolve_untrusted/usrp_ddc_src/`（不可信目录） |
| 驱动 | `T/usrp_h1.py`、`T/run_h1.py`；H1b 为 `T/h1b_design.py`、`T/h1b_run.py` |
| 数据 | `B/h1_usrp_ddc_v2_20261012.json`、`h1_usrp_ddc_v3_lead_20261012.json`（修正输入对齐后）、`h1b_usrp_tuned_v1_20261012.json`（调参版） |
| 结果 | 12/12 不达标。v3 留出裕量 −3.6 至 −28.9 dB；去掉阻塞音后 SNR 37.5–51.8 dB，接线正确。H1b 枚举 48 种配置后仍 12/12 不达标（−7.8 至 −29.9 dB）。原因：固定的 4 阶 CIC + 两级固定半带抑制不了全混叠带的强阻塞。不达标，面积不可比 |

### E17 统一系统 v1（结构生成 + 两层）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgen/structgen.py`、`run_unified.py`、`space_tune.py`、`unified_finalize.py` |
| 数据 | `B/unified_v1_20261013/`：协议、`summary.json`、`structgen/`、`final_eval.json`、`timing_sized.json`、思考模式记录 `notes_thinking_mode.txt` |
| 设置 | deepseek-v4-pro 非思考；每规格 K = 4 个结构，修复 2 轮；diff 与整程序重写 3:1；内层 ≤ 8 次评价；0.3 dB 裕量；花费约 ¥33.4 |
| 结果 | 24 个结构初始达标 0 个（裕量 −77 至 −112 dB）；最终面积为 M 中位数的 2.1 倍，R/U 0.08–0.32；留出 6/6 达标（裕量留得过大） |

### E18 结构生成失败诊断

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgen/diag_structgen.py`、`probe_tones.py`、`slack_check.py` |
| 数据 | `B/unified_v1_20261013/structgen_failure_summary.json`、`slack_check.json`、`rewrite_vs_diff.json`、`notes_blas_warnings.md` |
| 结果 | 可构造的 15 个：NCO/混频错误 10、增益/格式/符号错误 5、滤波不足 0。构造失败 9 个，约一半修复轮被 harness 浪费。修复环节只处理构造失败（bug）。重写达标率 23%，diff 40%。tones.py 警告为 Apple Accelerate BLAS 误报 |

### E19 DeepSeek 用法对照（E-H）

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgen/agent.py`、`agent_tools.py`、`eh_finalize.py`（收尾未执行） |
| 数据 | `B/eh_agent_v1_20261013/`：协议、`STATUS_user_stop.md`、`bare/`、`agent/`、`agent60/`、`agent_v3/` |
| 设置 | deepseek-v4-pro；r32n、r64w，每种用法 K = 3；与 E20 用同一套工具 |
| 结果（代理面积，未收尾） | (a) 裸对话 0/6 达标；(c60) 自建 agent 循环 60 次调用：r32n 72.8 万 / 28.9 万 / 22.1 万，r64w 189 万 / 未达标 / 121.7 万；(c) v3：r32n 125.9 万 / 49.6 万，r64w 171 万 / 923 万。累计约 ¥14.2 |

### E20 Claude agent（任务契约 + 工具），r32n

| 项目 | 内容 |
|---|---|
| 工具 | `代码/dspgen/agent_tool.py`（原始副本 `T/agent_tool.py`）：eval / probe / freqz / direct / api / spec |
| 工作区 | `AW/dev_r32_narrow/`：契约 `CONTRACT.md`、规格 `spec.json`、计划 `notes/plan.md`、总结 `notes/summary.md`、候选 `candidates/c02–c32.py`、记录 `candidates.jsonl`、最终 `final.py`、agent 自建工具 `tools/`（17 个脚本） |
| 设置 | 全新的 Claude 子 agent，只看契约，上限约 60 次评价；契约由人工编写 |
| 过程 | 41 次评价（含 3 次面积标定、3 次 probe、2 次构造报错），78 次工具调用；c02–c08 未达标，c09 首次达标（27.3k），之后逐步降到 12.6k |
| 结果（代理） | 面积 **12,644.5**，裕量 0.385 dB，纹波 0.023 dB |
| 结构 | Taylor 插值 NCO（128 点表）；5 级 CIC 抽 32，盒长 [41,32,32,32,32]；I/Q 交织复用低速部分；梳状合成 (1−z⁻²)⁴；7 抽头 LS + CSD 补偿器；截断偏置合并 |
| 未做 | 留出场景复核、RTL 对拍（真实面积已在 E22 测出） |
| 风险 | 积分器最高位按测试信号峰值设定，溢出会回绕 |
| 说明 | 运行时是通用 agent（Claude），不是本项目自建的智能体框架 |

### E21 DeepSeek 在 Claude Code 中，r32n

| 项目 | 内容 |
|---|---|
| 驱动 | `T/run_cc_deepseek.sh`（DeepSeek 的 Anthropic 兼容接口，配置隔离） |
| 工作区 | `AW/dev_r32_narrow_deepseek/`；日志 `AW/dev_r32_narrow_deepseek.log` |
| 设置 | deepseek-v4-pro，与 E20 相同的契约和工具；花费约 ¥1.09 |
| 结果（代理） | c01–c08 两级/三级 FIR 均达标（13.4 万–27.0 万）；c09–c10 CIC 方案差 16–17 dB 未调通；c11–c13 三级等纹波 FIR 达标，最好 **c12 104,209**（裕量 1.67 dB）。被用户停止 |

### E22 OpenSTA PPA 对比，r32n

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgen/ppa_sta.py`、`代码/dspgen/timing.py`；OpenSTA `/Users/chengzhy/verievolve_thirdparty/OpenSTA/build/sta`（commit `574500d`），CUDD 同目录 |
| 数据 | `AW/ppa_r32n/summary_fast.txt` |
| 设置 | 快速映射，时钟 2 ns，全局翻转率 0.1 |

| 设计 | 面积 (μm²) | 单元数 | 最小周期 (ns) | 最高频率 (MHz) | 功耗 (mW) |
|---|---|---|---|---|---|
| 直写起点 | 715,916 | 564,518 | 3.29 | 304 | 182.0 |
| M | 93,689 | 69,978 | 9.66 | 104 | 32.0 |
| R | 27,345 | 19,650 | 4.00 | 250 | 9.66 |
| DeepSeek in CC（c12） | 110,467 | 87,425 | 4.09 | 244 | 30.7 |
| Claude agent | **14,639** | **10,067** | **2.36** | **423** | **4.78** |

Claude agent 设计在完整映射下为 13,085 μm²，与代理估计（12,645）相差 3.5%。M 时序最差，推测来自乘法器分时复用形成的长组合路径（未逐条核实）。

### F1 通用框架回归与链 B 接入

| 项目 | 内容 |
|---|---|
| 代码 | `代码/dspgen/`（task、ideal、stimuli、metrics、direct、graph、rtl、prompt）；回归 `regress_chain_a.py` |
| 数据 | `B/dspgen_regression_chainA.json` |
| 结果 | 断言 1：60/60 组门槛逐位相同；断言 2：18/18 个设计重新打分完全相同；断言 3：自动直写起点与手写一致，6/6 达标。链 B 规格文件有效代码 20 行，写规格约 2 分钟，一次性补齐通用能力约 15 分钟 |

---

## 4. 横向汇总：r32n 一个规格上的全部方法

| 方法 | 编号 | 面积 (μm²) | 口径 | 留出 |
|---|---|---|---|---|
| 直写起点 | E1 | 709,042 | 真实 | 达标 |
| 开源 USRP DDC | E16 | — | 不达标 | 不达标 |
| LLM 直接写 Verilog | E13 | 1,090,434 | 真实 | 达标 |
| 统一系统 v1 | E17 | 318,824 | 真实 | 达标 |
| DeepSeek 自建 agent 循环（c60 最好） | E19 | ~221,000 | 代理 | 未测 |
| 两层搜索（从直写，2 种子） | E15 | 141,037 / 281,253 | 真实 | 达标 |
| DeepSeek in Claude Code | E21 | 110,467 | 真实（快速） | 未测 |
| M（3 种子） | E10 | 92,264 / 94,270 / … | 真实 | 3/3 |
| R03 | E15 | 51,185 | 真实 | 达标 |
| R | E1 | 29,155 | 真实 | 达标 |
| **Claude agent** | E20/E22 | **13,085**（完整）/ 14,639（快速） | 真实 | **未测** |

---

## 5. 尚未完成的工作

1. E20 Claude agent 设计的留出场景复核与 RTL 对拍。
2. E19 各用法的收尾（位宽下降 + 最终评估）。
3. 基于仿真翻转率的功耗（目前为全局翻转率）。
4. 链 B、留出规格上的多种子结果。
5. 第一阶段实验的数据大多不在 git 中；`B/` 共 1.3 GB，需决定哪些汇总文件纳入仓库。
