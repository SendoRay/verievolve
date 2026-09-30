# 整篇论文一页纲要（Claude 独立版，2026-09-29）

> 与 Codex 各自独立写，对比分歧后交用户拍板。**用户确认前不做任何实验。**

## 1. 标题（暂定）与一句话主张

**Beyond Pass Rates: Structure-Aware Numerical Fitness for LLM-Driven Formula-to-RTL Evolution**

> 在「数学公式 + 数值质量契约」到定点 RTL 的任务里，LLM 的结构探索能力只有在适应度能按候选结构
> 度量 bit-true 数值误差时才会被释放；pass-rate 适应度会把质量差距几十 dB 的结构压成同一分数。

## 2. 贡献（3 条）与证据

| # | 贡献 | 证据 |
|---|---|---|
| C1 | **任务与评估器**：把 formula-to-RTL 的规格定义为「公式 + 数值契约」；评估器按候选结构计算整数域 bit-true 数值误差（kernel 级在有限域上全枚举，链级做确定性轨迹评估），加真实综合 PPA | 半页的错配论证（ER vs MSE 在 LLM-RTL 中的迁移）；NCO witness（59 dB 被压成同一分数）；Gate A/B 验证协议 |
| C2 | **机制证据**：数值适应度是否放大了 LLM 相对强非 LLM 搜索的收益 | 2×2 proposer × fitness 的 DiD，同预算、多 seed、held-out 场景；报 hypervolume、结构类覆盖、top-k regret、PPA |
| C3 | **保证等级分析**（次要）：哪些质量结论对任意输入 sound，哪些只在声明输入律下成立 | A-bound 能安全剔除粗结构档，但在前沿顶端分不开（tie 构造 + 精确 `r_η`）。**若 coverage 低，放附录 / 硕论** |

## 3. 图表清单

- Fig 1：流程图，公式 + 契约 → LLM 结构提议 → bit-true 数值 fitness + 综合 → 进化
- Fig 2：错配示意，同一 pass-rate / all-pass 分数下的 SQNR 分布（NCO witness）
- Fig 3：2×2 四格的质量–面积 Pareto 前沿（每个 benchmark 一栏）
- Table 1：近邻对比（SPIRAL / Li'15 / Lee'17 / LPQ / COEVO / Verilog-Evolve）
- Table 2：2×2 主结果 + DiD + 置信区间
- Fig 4：结构类覆盖随代数的变化，展示 LLM 是否跨 LUT / 插值 / CORDIC / 多项式探索
- （附录）保证等级的 coverage 表

## 4. LLM 的具体角色

LLM 读入公式、数值契约、当前精英候选和**数值诊断反馈**（误差谱、最差输入区间），提议**跨 algorithm /
decomposition class 的结构改写**，而不只是调位宽。非 LLM 格用同一候选表示的结构 mutation。
**待讨论**：反馈内容是只给标量，还是给诊断信息？后者可能正是 LLM 独有的优势，但会增加一个实验维度。

## 5. Benchmark 范围

利用仓库现有资产：4 个 kernel（`cordic_sincos` / `atan2` / `cmul` / `llr_64qam`）保证广度，
1 条 DDC 链（NCO × CMUL × FIR × 抽取）提供系统组合的深度。不再新增算子。

## 6. 解析部分的分量

正文只写 C1 评估器的定义和身份分类（A-op / A-bound / B，半页），外加 Gate A/B 的结果。
三契约 / tie 构造 / `r_η` 精确式放附录或硕论章节，**除非** A-bound 的 coverage 很高。

## 7. 2×2 阴性时的退路

数值 fitness 对两种 proposer 同等有益（主效应为正、交互为零）：文章降为「评估器 + benchmark +
负的机制发现」，LLM 的价值不能靠本文主张，贡献落在 C1。若连主效应都为零，则只剩硕论章节。

## 8. 不做

- 新定理、筛选定理 / η 上界、闭式误差；
- 「首次把精度放进适应度」「零评估成本」「加速」作为卖点；
- H3 跨规格复用；
- 在纲要确认前做任何 A 线计算（6×3×8 coset 已冻结）。

## 需要用户拍板的问题

1. 主贡献放 C1（评估器）还是 C2（LLM 机制）？
2. benchmark：4 kernel + DDC，还是更窄 / 更宽？
3. 目标会议与时间线（DAC / DATE / ASP-DAC）？
4. C3 进正文还是附录？
