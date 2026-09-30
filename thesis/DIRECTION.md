# DIRECTION.md — 论文方向（暂定稿）

- 建立日期：2026-09-28
- 状态：**架构可冻结，新颖性措辞不可冻结**（见 §7、§8）。
  SPIRAL gate 已判**黄灯**（§5.1.6）；新颖性收窄为「structure-aware analytic bit-true fitness in
  formula-conditioned RTL search」，并以 2×2 机制实验为主要证据
- 与既有文档的关系：本文替代 `RESEARCH_PLAN.md` 中"解析误差模型当适应度、零采样方差"的
  原始主张框架；`AGENTS.md` §1 的对手对照表须按 §5 修订。`EXPERIMENT_GAPS.md` 的优先级
  需按 §6 重排。
- 纪律：本文所有比较性陈述（"某工作缺某段"）**必须逐条读 method/evaluation 正文确认**，
  不得只凭 abstract。核实状态逐条标注。

---

## 1. 一句话主张

> 用「数学公式 + 数值质量契约」而非 bit-exact 功能正确性作为规格，借用 LLM 的结构探索能力
> 生成定点硬件；并指出：**在数值质量这件事上，功能正确性判据不可识别（non-identifying）**
> ——这是近似计算中 ER 与 MED/MSE 之分的已知事实，但 LLM-RTL 进化工作仍以 ER 型统计量
> 作适应度。准确地说，这是 **evaluator migration** 问题：pass-rate 在 VerilogEval/RTLLM 这类
> exact-functional spec 上完全合理；**原样迁移到允许数值近似的 formula-to-RTL 任务后**，
> 它就不再是目标质量的充分统计量。不得暗示 COEVO 等在它们自己的任务上选错了指标。

三个组成部分，缺一不可：

| 部分 | 内容 | 地位 |
|---|---|---|
| **问题形式化** | satisfaction-rate / verdict fitness 不能识别数值风险（proposition + witness） | 方法前提；**不列入贡献编号**，不称 theorem |
| **方法** | structure-aware 解析数值适应度，把缺失的排序信号接进 formula-conditioned 硬件搜索 | 主要贡献 |
| **机制实验** | 检验该信号是否释放 LLM 的结构探索价值 | 主要证据 |

---

## 2. 问题形式化：为什么 satisfaction-rate fitness 不够

**篇幅纪律**（2026-09-29 与 Codex 定）：会议稿只写 **0.5–0.75 页**，包括一个 proposition、
一行构造证明、一个 exact-match corollary、一个真实 witness，以及一段直接引出 §3 的设计结论。
完整形式、两个 corollary、边界、构造例和负结果放进附录 / 硕论。
贡献列表只写「identify and quantify an evaluator mismatch in formula-conditioned
approximate RTL search」，**不得**写「prove a new theorem」。这一节作为「不可绕过的方法前提」
站得住，作为「理论贡献」站不住。

### 2.1 形式陈述

设输入概率空间 `(X, μ)`，参考函数 `f`，候选实现 `h`，误差 `e_h = h − f`。

- verdict（**单阈值一般形式**）：`v_h(x) = 1[ |e_h(x)| ≤ τ ]`
- 数值风险：`R(h) = ∫ |e_h|² dμ`

> 若候选类 `H` 中存在 `h₁, h₂`，使 `v_h₁ = v_h₂` 在 `μ` 下几乎处处成立，
> 而 `R(h₁) ≠ R(h₂)`，则**不存在**仅依赖完整 verdict function `v_h` 的映射，
> 能在 `H` 上恢复 `R` 或保证与 `R` 一致的全排序。

通过率只是 `v_h` 的一个更弱的聚合，因此该不可能性对通过率自然成立。

**采用单阈值一般形式的理由**：即使某工作的单用例判据带容差，完整 verdict bitmap 与
通过率仍不能一般地决定 `E|e|²`——同一个阈值内集合可以有**不同的集合内外误差幅值**。
因此不必预设 `τ = 0`（exact-match）。只有确证 `τ = 0`（`expected == actual`）后，
才在具体论述中称 exact-match。

**技术条件**：`e_h` 可测且平方可积。硬件的有限输入/输出域自动满足。

**逻辑方向注意**：命题是「zero set **不能决定** MSE」，**不是**「相同的 zero set ⇒ 不同的 MSE」。
后者是更强的假命题。

**命名称谓**：论文中此项称 **proposition / counterexample**，**不得**声称
「零点测度不能决定二阶矩」本身是新数学。

**已确认的直接先例（2026-09-29 检索）**：近似计算领域早已区分
**error rate `ER = P(ED≠0)`** 与 **MED / MSE / WCE**（Liang–Han–Lombardi 系 error
metrics；近似加法器文献中有「LSB 近似加法器 ER 很高但 MED 适中」的实例；MCAC
`2411.10037` 精确计算 ER/MAE/MSE/WCE/PMF；Vasicek 等 IEEE Access 2019，
DOI 10.1109/ACCESS.2019.2958605，原文："high error rate does not imply high WCAE and vice
versa"）。**pass-rate 就是 ER 的补**，因此 §2.1 在数学上是该领域的常识。

第二个先例族：**proper scoring / property elicitation**。0–1 score 不是严格 proper 的，
只能识别阈值一侧的性质，不能识别完整分布或平方风险（Gneiting & Raftery, JASA 2007,
Example 4）。

⚠️ **不要**把可靠性领域的「零失效数据」当成主先例：那类文献讨论的是删失样本下估计失效率时的
不确定性，而我们讨论的是观测映射 `v_τ` **主动丢弃幅值**。问题不同，引它会招来攻击。

**据此重新定位本节的价值**：不是提出新命题，而是指出一个**跨社区的错配**——
近似计算社区知道 ER 不能代替 MED/MSE，而 **LLM-RTL 进化社区（COEVO / Verilog-Evolve /
FinHardBench 等）在数值型任务上仍以 ER 型统计量作适应度或评分**。本节的写法应为「把近似计算的
已知区分引入 LLM-RTL 适应度设计，并给出 `(B/δ)²` 定量界与真实 witness」，引用该领域
先例，而非独立宣称。方法贡献落在 §3，证据落在 §4。

### 2.2 定量版：两个 corollary 必须分开写

⚠️ 订正（2026-09-29，Codex 指出）：原稿把单阈值一般形式和 `(B/δ)²` 界写在一起，
**这是错的**。倍率界**只对 τ = 0 成立**。

**记号**：`q = P(|e| > τ)`，`0 ≤ |e| ≤ B`。

**Corollary A（exact-match，τ = 0）**：pass 集上误差恒为 0。设非零误差的最小幅值为 `δ`，则

```
R ∈ [ q·δ²,  q·B² ]        不确定倍率 (B/δ)²
```

**Corollary B（一般 τ > 0）**：pass 集内允许 `0 < |e| ≤ τ`，这部分本身就贡献未知风险：

```
q·δ_out²  ≤  R  ≤  (1−q)·τ² + q·B²,     δ_out = min{ |e| : |e| > τ }（连续域约为 τ）
```

当 `q = 0`（全部 pass）时，R 仍可在 `[0, τ²)` 内变化，**没有有限的乘法倍率**。
因此 `(B/δ)²` **不覆盖** FinHardBench 的 ±5% 情形，只覆盖它的 exact-match 部分。

**单位纪律**：`δ` 和 `B` 必须在**公共的外部数值单位**下定义，并冻结接口格式。如果候选能改变
输出的 scale / format，各自的 1 LSB 就不同，`(B/δ)²` 不能跨候选比较。做法是：把 `e` 全部
反量化到同一个 real-valued contract 上，再定义公共的 `δ` 和 `B`。如果没有公共的最小 `δ`，
就只给候选类上的 inf/sup，或者放弃倍率表述。

在上述前提下可以说：**输出位宽越大，exact-match 丢掉的幅值信息越多**。这正是定点 DSP 的处境。

### 2.3 边界：前提不成立的情形（必须主动写进论文）

定理在这些候选类上**不成立，是前提不成立，不是定理塌陷**：

1. Boolean / 单位代价输出，所有非零误差幅值相同 → MSE 与 mismatch rate 成比例；
2. 候选类被限制为「zero set 唯一决定非零幅值」的特殊族；
3. verdict 本身已含误差幅值 / 连续 loss 层级 → 它**已经是数值判据**，不纳入本结论。

这个边界反而加强可信度：我们针对的是**多级数值输出、不同非零误差幅值**的定点 DSP。

### 2.4 已有的 collapse witness（无需新实验）

对**严格 all-tests-pass 判据**，仓库现有 NCO 候选构成真实 witness。

数据来源：`certfit/tpl_cordic.py::cert_metrics` 的全枚举（65536 角度码，零采样、零积分误差），
2026-09-28 只读复算。**该 kernel 的输入空间是 `algo/order/depth/stages`，
不含 `phase_bits`**（`phase_bits` 属 composite NCO 的前端相位截断，见 §5.1.2）。

| 候选 | exact 通过数 | 通过率 | SQNR |
|---|---|---|---|
| n1_lut256near_b12 | 252 | 0.38% | 36.98 dB |
| n2_lut256near_b16 | 252 | 0.38% | 36.98 dB |
| n5_cordic12_b12 | 1,232 | 1.88% | 70.92 dB |
| n6_cordic16_b16 | 7,826 | 11.94% | 84.18 dB |
| n3_lut1024lin_b12 | 43,316 | 66.09% | 96.01 dB |
| n4_lut1024lin_b16 | 43,316 | 66.09% | 96.01 dB |

⚠️ **样本数须如实报**：因 `phase_bits` 不进入该 kernel，`n1/n2` 与 `n3/n4` 各为**重复标签**，
统计上只有 **4 个独特 kernel 点**（SQNR 范围不变，仍 36.98–96.01 dB）。
不得写成 6 个独立实现以放大样本。

**关键**：这些候选**全部不通过**严格 all-pass，因此二值适应度**完全相同**，
而 SQNR 跨度 **59.03 dB**。二值接口只看"是否 100% 通过"，59 dB 的质量差异被压成同一分数。

⚠️ **witness 的证明范围**：它只证明 **strict all-pass 会塌缩**，**不能**证明 fractional
pass-rate 会塌缩。这 4 个独特点的 pass fraction 与 SQNR **单调一致**，这是一个负结果，必须保留。
写法分工如下：
- 完整 verdict / pass fraction 的一般不可识别性：由 **构造例**（±1/±3 LSB，同一 bitmap 下 MSE 差 9 倍）支撑；
- all-pass 在本任务上的实际退化：由 **真实 4 点**支撑；
- **不得**把 59.03 dB 写成 COEVO 式 fractional score 在实证上的失败。
如果在完整池（§2.5）里仍然找不到「pass-rate 相同或相近、但质量差距大」的 pair，
实证主张就限定在 all-pass，fractional 部分只作为理论可能性。

这同时确证了一条**退化事实**：对近似定点实现，全域 bit-exact 等价**不可达**
（最高通过率仅 66.09%）。这不是候选太差，是判据设错。

**两个正交的轴，不要混成一个「信息层级」**：

| 轴 | 取值 | 与本定理的关系 |
|---|---|---|
| **观测统计量** | all-pass bit（最粗）→ verdict bitmap / pass fraction → 连续数值 loss | 决定**能拿到多少信息**；前两者均不识别 `E\|e\|²` |
| **选择策略** | 硬门槛 / 退火门槛 / Pareto 维度 / 标量化 | 只改变**选择压力**，**不修复幅值信息丢失** |

⚠️ COEVO 的 `θ_t` 退火属于**选择策略**轴，是对同一个 `c` 的门控，**不增加观测信息**。
其 "continuous correctness" 应引号说明为 `[0,1]`-valued **satisfaction rate**；
有限 `T` 下仍是步长 `1/T` 的**离散统计量**，不是对数值偏差连续的 loss。

### 2.5 适用范围澄清

上表的单调性**不是**整个 `cordic_sincos` 族或整个 NCO 的结论，只是**冻结 DDC-NCO 配置经
standalone sin/cos kernel 投影后**的共调切片。`e3_nav.py::cordic_space()` 的 standalone 空间
含 LUT depth/order 与 CORDIC stages 的完整点集，须在该完整池上另行统计。

「单一分辨率旋钮必然同向」目前只能作**诊断假设**，不可写成机制结论。

**「加测试也救不了」的准确限定**：成立范围是 **in general**，且**在保持 Boolean 聚合、
不引入额外误差分布假设时**。生成更多/更针对性的测试能改善功能 bug 覆盖，也可能改变
`p` 与 SQNR 的**经验相关性**；但它**不能从 Boolean verdict 恢复被丢弃的幅值**。
这个限定用于挡住「主动 test generation 会挑出边界样例」的反驳。

### 2.6 措辞纪律

| 可用 | 禁用 |
|---|---|
| non-identifying（不可识别） | 盲（blind） |
| 完整 verdict function 是更优信息 | 纯定理形式的「低信噪比」 |
| test-pass 提供功能可行性信号，但不诱导与数值质量一致的排序 | 「零信息」「无梯度」（结构空间离散，梯度非严格术语） |

经验层可另行报告：同分数档内的 quality spread、tie rate、Kendall τ-b、selection regret。
信息论语言（`I(T; Q)`）仅在样本足够时使用，否则不硬上。

---

## 3. 方法：structure-aware 解析数值适应度

**核心**：把 §2 中缺失的排序信号——误差的**二阶矩与其谱结构**——以确定性方式接入搜索。

⚠️ **单项都不新**（2026-09-29 与 Codex 的 gate 复核）：
- 解析数值量进入实现选择与 HLS：Menard'12、Li DAC'15、Lee DATE'17；
- 精度作为结构搜索的 cost：SPIRAL；
- 跨算法类的保精度 RTL 生成：FloPoCo；
- 进化搜索配数值质量适应度：LPQ。
因此下面四条**必须同时成立**，新颖性来自**组合与机制证据**，不来自任何单项。

1. **formula-conditioned 的 LLM 结构提案**，而不是在固定 DFG/CDFG 上做 HLS/WLO；
2. **跨算法族**：architecture class 正式定义为 **algorithm / formula decomposition class**
   （LUT / 插值 / CORDIC / 多项式 / 直接型 vs 多速率）。**不包括**单纯的 FU binding、
   scheduling、operation elimination 和位宽选择；
3. **结构感知的整数域 bit-true 数值风险**，并能跨模块组合成系统质量。它要明显强于「误差独立
   / 标量均值方差传播」这类假设（Li'15 丢掉了协方差，Lee'17 需要一次仿真）；
4. **LLM×fitness 的 2×2 因果实验 + 真实 PPA**：证明新增的排序信号真的改变了结构探索结果。

**「全输入」一词必须拆开写，不得笼统使用**：

| 说法 | 实际含义 | 什么时候能用 |
|---|---|---|
| finite-domain exhaustive expectation | 在冻结的输入分布或有限域上，期望值是精确的 | NCO kernel 这类全枚举（§2.4） |
| worst-case bound | 对每一个输入都成立 | 只有给出最坏界时才能用 |
| fixed grid / low-discrepancy 估计 | 确定性的估计，但不是 all-input | 链级 EVM、带内误差 |

SQNR 本身是分布量，**不能**说它「对全体输入成立」。

---

## 4. 机制实验：2×2 + difference-in-differences

**必须四格**（三格无法分离主效应与交互）：

|  | test-pass 适应度 | 数值质量适应度 |
|---|---|---|
| **LLM 提议** | ① | ② |
| **强非 LLM 提议器** | ③ | ④ |

核心量：`[① − ③] − [② − ④]`

**假设表述**（措辞须精确）：

> 数值质量反馈增加了与有效结构变异对齐的选择压力，因此 LLM 的相对收益更大。

**不得**写成「没有梯度就不能奖励」——MAP-Elites / novelty / 中性漂移仍可能保留二值同分
候选，LLM 也可能一次命中好结构。

**四格必须同**：候选表示、初始化、代数 / 评价次数、保留策略、终考协议；多种子。
终考用 held-out 数值质量 + PPA；报告 architecture-class coverage、hypervolume、
time/evals-to-first-feasible、unique non-dominated structures。

**基线不得是弱 uniform random**——至少用同参数空间的强进化 / 结构 mutation。
小空间的全枚举 oracle 只作地面真值，不占第五格。

---

## 5. 对手对照与核实状态

### 5.1 LLM-RTL 精读对象的轴（**不是**领域结构图）

⚠️ 原标题「两条轴，交集为空」**已撤回**：Menard'12、Li'15、Lee'17、SPIRAL、FloPoCo
都落在两条轴之间（见 §5.1.5）。下表只描述我们精读过的对象。

| 阵营 | 工作 | 它们的轴 | 数值误差幅值 |
|---|---|---|---|
| LLM-RTL 系 | COEVO、EvolVE、REvolution、EvoVerilog、Verilog-Evolve | 功能正确性得分 + PPA | **未纳入** |
| 数值精密度系 | Daisy、FPTaylor、Real2Float | 数值误差界 | 不涉及 RTL / 结构搜索 |
| 进化 + 数值适应度 | LPQ | 标定集经验 loss | 只选数制参数，没有 algorithm/topology 搜索（§5.1.3） |

**COEVO 的「连续正确性」属功能轴**（测试覆盖面的聚合），不是数值轴——这是它与本工作的
根本区别，也是它作为**最强基线**而非占位者的原因。

#### 5.1.1 COEVO 精读结论（2026-09-28，全文精读 `arxiv.org/html/2604.15001v2`，LaTeXML 全文 2211 行）

**它不构成本章问题定理的反例。** 决定性证据：

- **连续正确性的定义**（§4.2.1 原文）：`c(I) = p(I) / T`，"where `p(I)` is the number of
  passed test cases"。即对二值指示 `1[e=0]` 求均值，只是不设 0/1 硬门槛，另加退火阈值
  `θ_t`（Eq. 7）。**聚合方式百分之百是比例计数，不是连续 loss。**
- **单个用例如何判 pass 原文未明确**（只说失败时回显 expected 与 actual 信号值作诊断反馈）。
  **代码层核查**（Codex，2026-09-29，公开仓库 commit `335d8d7`）：evaluator 只解析
  `FORGE_RESULT` 中的 TOTAL/PASSED/FAILED，然后取 `score = passed/total`，不参与单用例判据；
  原 benchmark TB 大量用 `!==` 和位级 `tb_match`，所以**报告用的 TB 是 exact equality**；
  但 README 提到的 `testbench_enhanced.v` / `*_test_enhanced.sv` 在公开代码树里**一个也没有**，
  所以**搜索内部所用增强 TB 的 τ 仍无法核实**。
  写法：「聚合层已确认是 Boolean pass count；增强 TB 的单用例判据因公开 artifact 缺失而 unverified」。
  另外应把「code available」和「artifact complete / runnable」分开写。这是复现性缺口，
  不要扩大成对方法的攻击。
- **全文关键词命中为零**：`quantiz` / `bit-width` / `SQNR` / `SNR` / `MSE` / `precision` /
  `tolerance` / `deviation` / `approximation` 在方法与实验部分**全部 0 命中**
  （`fixed-point` 仅出现在 RTLLM 的设计名中）。`error` 7 次全部指**功能错误**。

**因此本工作与 COEVO 的关系是**：COEVO 占位「把 correctness 从二值门槛**连续化**并作为
Pareto 维度」；本工作的定理正好接在其后——**即使 pass-rate 已连续化到 `[0,1]`，只要单个
用例判据是 exact-match，仍不可识别数值质量**。这是「加测试也救不了」的缺失，不是分辨率不足。

**可直接对比的点**：COEVO 的 PPA 全部来自**真实综合**（Yosys + OpenSTA + NanGate 45nm，
报 area μm² / delay ns / power μW，无代理模型），与本工作口径一致，是合格的**同级基线**。
其任务为**自然语言 spec**（VerilogEval 2.0 + RTLLM 2.0，无通信 DSP 算子），与本工作的
「数学公式 + 数值契约」输入语义不同。

**一处须如实记录**：COEVO 搜索内部使用 **LLM 生成的增强 testbench**，报告指标用原
benchmark testbench，而论文未将其表述为隔离（全文未提 held-out、防作弊、训练/测试分离）。
本工作的解析误差模型对全体输入成立，与此构成「sound 量 vs 生成式估计」的可测对比。

**一处细节**：4 维 Pareto 是**搜索内部**排序机制；对外报告（RQ2）仍压回 `A×D×P` 复合标量。

#### 5.1.2 Verilog-Evolve 精读结论（2026-09-28，HTML 全文 §1–§5 + References）

**不构成本章问题定理的反例。** 其 "optional GEMM metrics" 经查**不含任何数值精度量**：

- §3.3 原文对该评估器的定义只列结构量：`multiplier count, adder count, DFF count, mux count,
  preferred bit-width hits, pipeline-depth proxies, area-delay-product proxies, and an aggregate
  downstream score`。§4.3 补充实现方式为「parses Yosys JSON netlists」。
- Table 2 列全部为 `Func. Pass / GEMM Held-out Pass / Cell Count / Mul Cells / DFF Cells /
  ABC Delay / ADP Proxy / Downstream Score`，**无精度、误差或 SNR 列**。
- **全文对 `accuracy` / `relative error` / `SQNR` / `quantization error` / `rounding` /
  `truncation` 零命中**（`accuracy` 一词在全文一次未出现）。
- 功能 mismatch 的处理是**计数式**：§3.4「A mismatch receives a penalty **proportional to its
  mismatch ratio**」——这是**错误样本占比**，不是误差幅值。即：**知道有多少样本错，
  仍不知道错得多离谱**。这是本章问题定理在另一条轴上的实例。
- mixed-precision 是**任务语境标签**（三个内置任务 `int4_int8_mac_pe` /
  `mixed_precision_dot4` / `requantize_int32_to_int8`），**位宽不出现在任何搜索空间、
  决策变量或分数项中**——是给定精度做实现，不是把精度当搜索维度。
- 待核实：`preferred bit-width hits` 的计算方式与偏好位宽集合、`Downstream Score` 的聚合
  公式，**原文均未给出**，不可推测。
- 结构自由度：LLM 生成的 RTL 结构完全自由（§3.2 "rewrite focus rotates among
  combinational, sequential, and mixed transformations"），但论文**未把结构写成显式的
  参数化搜索空间**。

#### 5.1.3 LPQ 精读结论（2026-09-28，全文精读）

**它不构成本章问题定理的反例，也不是本方法的先占者。** 它占的是另一条轴：

- **决策变量**：逐层 posit 格式参数 `⟨n, es, rs, sf⟩`，即**给定网络的数制/位宽选择**。
  它**没有 algorithm / topology 层面的结构自由度**，但 posit 参数会改变算术单元的位宽和实现成本，
  所以不能笼统写成「无结构自由度」。
- **适应度**：`L_F = L_CO · L_CR^λ`（`λ = 0.4`）。其中 `L_CO` 是在 **128 张标定图像上实测**的
  对比表征散度，属于 **empirical finite-calibration loss，不是解析量**；`L_CR` 为压缩率。
  注意：标定集冻结后，重复执行是完全确定的。所以准确的对比是
  **「有限标定集上的经验 loss」vs「解析 / 穷举 / 有保证的风险」**，不是确定 vs 随机。
- **它已经占了「进化搜索 + 数值质量适应度」**：我们不是第一个把近似误差接进 evolutionary fitness 的。
- **数值误差的地位**：RMSE 只在 Fig. 5(b) **事后报告**，不进入适应度。
- **硬件**：RTL 为**手工设计**的 LPA，不做结构搜索；**硬件代价不进入适应度**。
- 一处原文自相矛盾须如实记录：`sf` 搜索半径在文中同时出现 `10⁻³` 与 `10³`，引用时不得择一。

**三方对照（本工作定位的最小证据）**：

| 工作 | algorithm/topology 结构自由度 | 适应度含数值误差幅值 | 数值量性质 | 硬件代价进适应度 |
|---|---|---|---|---|
| Verilog-Evolve | 有（LLM 自由改写，隐式） | 无（mismatch ratio 为计数） | — | 结构代理（Yosys 计数） |
| LPQ | 无（只选数制参数） | 有（标定集散度） | 有限标定集上的经验 loss | 否 |
| COEVO | 有（LLM） | 无（pass 比例） | — | 是（真实综合） |
| **本工作** | 有（跨算法族） | 有（二阶矩 + 谱结构） | 解析；kernel 级有限域精确，链级另注（见 §3 表） | 是 |

⚠️ 此表只能写成「**在我们精读的这三篇中**没有同时具备四列者」，不得外推为领域空白
（§7 已把「空白点」降为脚注）。表的作用是**界定比较对象**，不是新颖性主张。

**对方法边界的影响（gate 结果）**：LPQ 证明「近似误差进进化适应度」本身不新。§3 已按
§5.1.5 的近邻改写为四条组合，**不能**落在「把精度放进适应度」这一句上。

#### 5.1.4 WebSearch 补查（2026-09-29，abstract/HTML 问答级，**未全文精读**）

- **FinHardBench**（`2608.00909`）：守卫 / P&L 任务用 **exact-match 定点 testbench**，
  期权定价用 **±5% 容差**对照解析参考；评分为二值 Sim%。它**同时出现 `τ=0` 与 `τ>0`
  两种单用例判据**，正好支持 §2.1 采用单阈值一般形式。另可作动机数据：需要定点多项式逼近
  超越函数的任务通过率极低（摘要称部分任务所有模型均为 0%）。有 knobs 驱动的迭代 DSE，
  但无进化、无数值误差适应度。**定位：支撑证据，非对手。**
- **2608.23317**（LLM + GA 生成 netlist）：晶体管级模拟电路 / SPICE，与定点 DSP 无关。排除。
- **2205.09504**（完整多项式插值设计空间）：在**单一方法族（分段多项式）内**给定误差界枚举
  可行设计；不跨 LUT / CORDIC 类。属于「给定结构类的误差约束生成器」，与 FloPoCo 同类，
  应作为**结构类内的强基线**，而非跨类搜索的先占者。
- 未检出同时做「LLM 结构提议 + 解析数值适应度」的工作。**这是一次检索的负结果，不是证明**，
  §8 的冻结条件不变。

#### 5.1.5 非 LLM 直接近邻 gate 表（2026-09-29，Codex 反例猎手 + `LIT_GAP.md` 已核对内容）

⚠️ 自我订正：以下前四项在 `LIT_GAP.md`（2026-09-27）里**已经核对过**，但写 §3 / §5.1 初稿时
没有和它对照，导致「交集为空」这个过强表述。

| 工作 | 已占据 | 边界（我们还能站的地方） | 在论文中的角色 |
|---|---|---|---|
| Menard/Sentieys'12 | HLS（allocation/scheduling/binding）↔ WLO 迭代，解析 SQNR，tabu 搜索每步用解析式评价精度和架构代价；更早还有 Kum&Sung'01、Caffarena'06/'10 | 固定 DFG/CDFG；结构变化只到绑定/调度/分组和字长；SQNR 依赖统计噪声假设 | 解析精度 + HLS 的基线 |
| Li DAC'15 | 近似实现选择 + 位宽 + 调度 + FU 绑定；解析误差方差 / 误差敏感度；MMKP | 固定 task graph；候选来自算子库；丢掉协方差；敏感度靠一次预处理经验缩放 | **最危险的 HLS 近邻**，也是 2×2 中非 LLM 格的候选来源 |
| Lee DATE'17 | 半解析质量模型驱动 AHLS（rounding / elimination / scheduling / 电压），并输出 RTL | 固定 CDFG；需要一次仿真；传播的是标量均值和方差 | 同上 |
| **SPIRAL 组**（三篇作一组） | 见下方 §5.1.6 | 见 §5.1.6 | **最强近邻组**；ICASSP'12 的采样 NMSE 流是「采样质量适应度」的强基线 |
| FloPoCo | 数学函数→多种算法的 RTL（FixAtan2 的 method 0–12 横跨多项式 / CORDIC / Taylor 等）；last-bit accurate | 不是自动跨类搜索回路，需要人选 method；只到算子级，没有链路语境 | 生成器基线 / 候选池来源 |
| ROVER / ASPEN | 精确等价重写 + PPA | 未检出转向近似的后续；ROVER 作者学位论文 §8.2.2 把 approximate e-graph 列为 future work | 不是反例 |

#### 5.1.6 SPIRAL gate 结论（2026-09-29，**黄灯**：方向不死，新颖性再收窄）

Codex 全文核查三篇；我已独立读 2004 年那篇的 pp.1–4，对式 (2) 和范围声明做了抽查确认。

| 论文 | 已占据 | 没有做到的 |
|---|---|---|
| Püschel/Zelinski/Hoe, **ICCAD 2004**《Custom-Optimized Multiplierless Implementations of DSP Algorithms》 | **精度直接驱动跨公式的算法选择**：把 SPIRAL 的 runtime 度量换成 `N_k(T)=‖T−T̃_k-bit‖∞`，得到对任意输入成立的界 `‖y−ỹ‖∞ ≤ N_k(T)‖x‖∞`（确定性的算子最坏界）；随后在误差阈值下搜常数位宽，使加法数最少；也支持应用指标（JPEG PSNR、MP3 合规性） | 原文明说只自动化 algorithm selection 与 accuracy configuration 两块，synthesis 交给既有工具；实验是软件定点，**没有 Verilog 或综合 PPA** |
| **TODAES 2012**《Computer Generation of Hardware for Linear DSP Transforms》 | 公式→datapath→可综合 Verilog 真正打通；联合探索算法 / radix / streaming width / reuse，给出 FPGA 和 65nm ASIC 的 Pareto | accuracy/error 全文零命中；定点统一取 16 位；**RTL DSE 的目标只有 cost/performance** |
| **ICASSP 2012**《Improving Fixed-Point Accuracy of FFT Cores in O-OFDM Systems》 | 数值质量影响最终 RTL：按仿真选每级 scaling/saturation directive 和位宽，生成 RTL，65nm 综合，给出 area–NMSE 折中 | 算法固定（radix-4 Pease FFT）；directive 由**设计时仿真**得出；NMSE 是 1000 次 QAM-64 的**统计量**；是 FFT 专用方法，不是跨公式的自动搜索 |

**补充边界**（2026-09-29；我提出，Codex 收紧了措辞）：

> SPIRAL 的解析指标把有限精度候选表示为近似线性变换 `T̃`，并用 `‖T−T̃‖∞` 评价常数量化后的
> 算子偏差。这种表示适用于保持线性的常数近似，但**不能直接表达**中间舍入、截断、溢出或饱和
> 带来的、随输入变化的 bit-true 误差；要覆盖后者，需要额外的残差、分段或统计误差模型。
> ICCAD'04 没有构造这类模型，并且明确把数据通路位宽和常数精度分开处理。

⚠️ **不得**写成「数据通路量化写不成矩阵」。有三个形式反例：把有限输入域 one-hot 提升后，
任意函数都能用大矩阵表示；纯模运算在 `Z/2^wZ` 上仍然是线性的；在固定的量化模式内可以用
分段仿射表示。

**防夸大句**（必须同时写）：
> 这不是声称数据通路量化不可分析；已有加性噪声、区间/仿射和概率传播方法可以近似或界定它。
> 本文的差别在于：按候选结构对这些整数数据通路效应做确定性的 bit-true 计算，并直接用于 RTL 搜索。

**如何挡「加性噪声」反驳**：`q = Q(z) − z` 只是恒等分解，它本身不给出可用的 evaluator。
- 把 `q` 当独立均匀白噪声：这是统计近似，会丢掉 `q` 对输入的确定依赖、跨节点相关性，
  以及饱和 / 溢出造成的重尾和偏置；
- 保留 `q(z)` 的精确输入依赖：模型就不再是单个矩阵范数，而是我们要做的 bit-true 残差模型；
- 对 `q` 取区间或范数最坏界：这是另一种扩展模型，通常较松。
「原则上可以扩展」不等于「ICCAD'04 已经覆盖」。

**不得**把贡献写成「首次考虑 datapath rounding」：Li'15 / Lee'17 已经传播过均值 / 方差或界。
三方的准确区分是：

| 工作 | 数值模型 | 结构 |
|---|---|---|
| SPIRAL ICCAD'04 | 常数量化 → 线性算子范数 | 跨公式分解，没有 RTL |
| Li'15 / Lee'17 | 固定 DFG 上的误差传播近似（均值 / 方差） | 固定图 |
| **本工作（待证）** | 按候选结构精确或经验证的整数残差模型 | 闭环 RTL 结构选择 |

**必须撤掉 / 避免的说法**：
- 「解析误差从未参与结构选择」——被 ICCAD'04 直接反驳；
- 「精度从未进入 SPIRAL 硬件设计」——被 ICASSP'12 反驳；
- 「跨 formula decomposition 是我们独有的」——SPIRAL 早已做了。

**建议定稿句**：
> SPIRAL 已有 accuracy-aware formula decomposition search（解析矩阵范数或应用指标），也已有
> formula-to-RTL hardware generation；2012 O-OFDM 工作还把采样 NMSE 用于专用 FFT 的
> scaling / 位宽 RTL 设计。然而，在所核查的主文中，尚未发现将**结构感知的解析 bit-true
> numerical fitness** 作为闭环目标、自动驱动**跨 architecture-class（含非线性 / 异构实现族）**
> 的 RTL 搜索，并以真实综合共同评估的系统。

**仍站得住的差别**：
1. SPIRAL 的解析量针对**线性变换 + 常数量化**；我们的增量应落在**按候选结构、确定性计算的
   整数数据通路 bit-true 误差**（截断 / 舍入 / 饱和 / 残差及其系统传播），以及**非线性 / 异构实现族**
   （如 NCO 的 LUT / 插值 / CORDIC）；
2. ICASSP'12 的采样 NMSE 流正好是 §4 中「采样质量适应度」的强基线；
3. LLM 的价值只能由 proposer×fitness 的 2×2 实验给出，**不能**靠「SPIRAL 不搜结构」来论证。

### 5.2 核实状态（重要）

下表条目由本会话的核实 agent 于 2026-09-28 **实际抓取 arXiv abs 页面**确认标题与作者。
其中公告日期晚于 2026 年 1 月的条目**超出文档作者本人的独立知识范围**，
作者须自行读原文复核后方可写入论文，尤其：

- **COEVO**（`2604.15001`）：其"continuous correctness score"究竟是对 exact 逐测试
  verdict 聚合成比例，还是 testbench 本身按误差给分——**必须读到实现层**再下结论；
- **Verilog-Evolve**（`2605.26498`）：其 "optional GEMM metrics" 是否含数值精度——同上。

一处已确证的订正：**AlphaEvolve**（`2506.13131`）的 abstract 关于硬件只写
`"functionally equivalent simplification in the circuit design of hardware accelerators"`，
**无 TPU、无 Verilog**。仓库内任何引用该案例处须改。

另一处订正：**FPTaylor** 的正确出处是 **ACM TOPLAS 41(1), Article 2, 2018,
DOI 10.1145/3230733**，不是 TACAS 2018。

### 5.3 需要修订的既有文档

`AGENTS.md` §1 对照表中「正确性是二值门槛」的表述**已被 COEVO 推翻**，须改为
「现有 LLM-RTL 工作的正确性判据为功能轴（二值或部分得分），均不涉及数值误差幅值」。

---

## 6. 暂缓与不做

- **筛选定理 / η 上界**：降出主线。理由见下条 cost audit。仅当其闭式形式通过
  tightness + cost audit 才回到主线，否则进附录或删除。
- **cost audit 实测结论**（2026-09-28，本机）：

  | 项 | 成本 |
  |---|---|
  | 系统真值（全链） | 4.850 ms |
  | 局部测量 `m`（仅 NCO 级） | 0.184 ms |
  | η 上界（仅边际功率） | 0.185 ms |
  | 相干折叠真值 `q` | 0.169 ms |

  **η 并不比真值便宜**——两者都被同一 FFT 主导（0.127 ms）。故「廉价筛选」作为卖点不成立。
  若解析误差模型能**闭式**给出完整 `q`，则筛选理论多余（解析适应度本身就是方法）；
  若只能给松的边际矩界，则应砍掉。

  ⚠️ **`q` 的身份订正**（2026-09-29，Codex 提出）：这里的 `q` 是在**冻结场景轨迹**上的残差
  做 FFT 再相干折叠，属于 **deterministic trace evaluation**（确定性轨迹评估）：重复评估零方差，
  但仍然是对场景轨迹的评估，**不能**改名为 analytic。
  **不再追求闭式**：有限域精确的整数残差计算本身就可以构成解析适应度，但要按
  `VALIDATION_PROTOCOL.md` §1 的身份分类判定，并通过 Gate A/B。
  成本只写实测值（例如「measured 0.169 ms」），**不得**写「零评估成本」；与 4.850 ms 的全链真值
  比较速度时，必须在同一台机器、同一批量 / 缓存条件、同一计时边界下报。

- **H3（跨规格复用）**：维持不启动。
- 代码修复（`metrics.py` / `run_s1.py`）**暂缓**，等方向落定后再排期。

---

## 7. 已撤回的表述（诚实记录）

| 原表述 | 状态 | 原因 |
|---|---|---|
| 「零采样方差」是贡献 | **撤回** | 采样方差是噪声，多采集即可压低；且 E5 显示模板+采样与模板+确定性评估精度相同 |
| 「判据决定可达空间」为核心命题 | **降为 insight** | exact 可行集 ⊆ tolerance 可行集是定义推论，属 approximate computing 已知母题 |
| 75.6 dB 结构类地板**由判据盲性造成** | **撤回** | 无因果消融，只能称现象 |
| 75.6 dB 属 **atan2** 族 | **撤回** | 实为 `cordic_sincos`（75.6→96.0 dB）；atan2 为 71.7→77.6 dB，见 `chapter5.md` |
| 「空白点」式立论 | **降为脚注** | 该方向 12 个月内已 5 篇；且「深」式主张不依赖空白点 |
| §5.1「两条轴，交集为空」 | **撤回** | Menard'12 / Li'15 / Lee'17 / SPIRAL / FloPoCo 均落在两轴之间 |
| §3「确定性 + 全输入 + 跨结构类」即为差别 | **撤回** | 单项均有先例；「全输入」对 SQNR 不成立；改为 §3 四条组合 |
| 「跨 formula decomposition 的精度搜索」为本工作独有 | **撤回** | SPIRAL ICCAD'04 已做（矩阵 ∞ 范数） |
| LPQ「非确定性」 | **订正** | 冻结标定集后是确定的；应写成经验 loss vs 解析风险 |

---

## 8. 冻结与不冻结

- **可冻结（架构）**：§1 三部分组成、§2 定理形式、§4 四格设计、§6 暂缓项。
- **不可冻结（优先权与措辞）**：「比所有人更深」「四类对手各缺一段」这类比较性句子，
  须待反例猎手结果与逐条读正文确认后方可定稿。若发现已有工作已证明 §2 的不可识别性
  或已做解析数值适应度 + 结构搜索，则问题定理降为已知动机，贡献须落到结构感知解析模型、
  跨结构组合、系统级后果或 LLM×fitness 交互证据之一。
