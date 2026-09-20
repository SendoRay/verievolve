# 通信 DSP 领域数学公式驱动的 Verilog 自动生成方法研究
## ——证书化评估与质量多样性进化

> 学位类型：工学博士　　学科：信息与通信工程
> 作者：XXX　　导师：XXX 教授　　单位：XXX 大学
> （署名为占位符，交付后自行替换）

---

**目录**

- 摘要（中/英）：abstract.md
- 第一章 绪论：chapter1.md
- 第二章 相关理论基础：chapter2.md
- 第三章 CommDSP-Bench：公式驱动的通信 DSP 硬件基准：chapter3.md
- 第四章 证书化评估体系：chapter4.md
- 第五章 证书携带的进化搜索与系统实验：chapter5.md
- 第六章 总结与展望：chapter6.md
- 参考文献：references.md
- 附录 A：探索性预实验与设计决策依据
- 附录 B：可复现性索引（脚本与数据清单）

**图表索引**（PNG 于 figures/，由 examples/comm_dsp_bench/make_figures.py 生成）

- 图 3.1 stream_v1 流式握手时序（make_figures: fig3_1）
- 图 3.2 基线回归修复前后对比（fig3_2）
- 图 4.1 模分解引理与确定性积分的一致性（fig4_1_lemma.png ✓）
- 图 4.2 平滑族新鲜种子重评噪声（fig4_2_noise.png ✓）
- 图 4.3 证书-采样散点：平滑族 vs 重尾族（fig4_3_scatter，数据 e2b_scatter.json）
- 图 5.1 两臂 Pareto 前沿对比 2×2（fig5_1_fronts.png）
- 图 5.2 重判一致性散点（fig5_2_rejudge.png）
- 图 5.3 E3 综合预算-前沿质量曲线（fig5_3_e3_nav.png）
- 图 5.4 E4 位宽决策：BER 证书 vs SQNR 门槛（fig5_4_e4_ber.png）

---

# 附录 A　探索性预实验与设计决策依据

以下预实验在正式实验设计定稿前完成，用于约束实验设计，其数据不进入主表
（manual 模式的应答器为确定性脚本，可复现但不代表真实 LLM 能力）：

1. **混合变异机制**（SPEC v0.4）：同一 checkpoint 起点的三组 52 迭代消融，
   diff-only / 全重写 / 混合(50%) 的超体积分别为 0.3550 / 0.4543 / 0.4579——
   确立正式实验统一采用混合模式。数据：ablation_results.json。
2. **结构跳变预演**（SPEC v0.3）：从 76.9 dB 天花板出发的 8 次全重写迭代产出
   4 个算法族、单迭代 +17 dB——确立了"算法类地板"假说与模板空间的动机。
3. **两级翻译基线**（B2，two_stage_baseline.py）：公式→浮点→无反馈定点化→RTL
   的单点产出 61.1 dB/2538 LUT，对照联合搜索同面积 +33 dB——两级流程的
   结构性损失的量化证据。

# 附录 B　可复现性索引

| 产物 | 路径 | 说明 |
|---|---|---|
| 基准规范 | examples/comm_dsp_bench/SPEC.md | v1.0，含版本记录 |
| 任务审计 | examples/comm_dsp_bench/AUDIT.md | 三层审计与修复清单 |
| 任务族生成器 | task_family_gen.py / family_baselines_gen.py | 110 实例与基线 |
| 评估器（L1 采样） | evaluator.py | Arm S 口径 |
| 证书引擎 | certfit/（common + 四族模板） | L2/L3 层 |
| 证书评估器 | cert_evaluator.py | Arm C 口径 |
| 消融评估器 | e5_cs_evaluator.py | Arm CS 口径 |
| E1 运行/分析 | run_e1.py / analyze_e1.py / rejudge_e1.py | experiments_e1/ |
| E3/E4/E2b | e3_nav.py / e4_ber.py / e2b_scatter.py | 同上 |
| 图表生成 | make_figures.py | thesis/figures/ |
| 回归报告 | regression_report.json | 106 实例（run4 口径） |
| LLM 后端 | DeepSeek deepseek-flash（OpenAI 兼容） | key 不入库 |

**LLM 使用声明**：E1/E5 进化实验共约 500 次 deepseek-flash 调用（思维链开启）；
所有 prompt 与应答原文在 experiments_e1/*/ 下留档。
