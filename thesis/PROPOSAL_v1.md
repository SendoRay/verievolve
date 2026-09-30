# 论文主线提案 v1（待用户确认）

- 日期：2026-09-29
- 来源：Claude 与 Codex 多轮讨论（Tin Can 线程至 `msg_0b99228b66a44abdb012d516`，已按其 4 个 blocker 与 2 个次要问题修订）
- 依据文档：`NEIGHBOR_MATRIX_HLS_RTL.md`（近邻能力矩阵）、`CATALOG.md`（算子目录）、
  `VALIDATION_PROTOCOL.md`（评估协议）、`DIRECTION.md`（旧方向，部分被本文替代）
- 状态：**提案，未冻结**。用户确认前不写实验代码、不跑数。

---

## 1. 问题

给定通信 DSP 的数学 / 数据流规格和端到端数值契约（EVM / ACLR / BER 等），在同一闭环里联合决定：

1. 实数语义下的算法分解；
2. 近似实现原语（LUT_k / CORDIC_N / Poly_d / NR 迭代 …）及其参数；
3. 定点化位置、字长、round / trunc / sat；

并按系统契约与 post-synthesis cost vector 选择候选（area 先纳入；timing / power 须在 SDC、
综合 / P&R 流程与功耗口径冻结后才进入正式证据）。流式 RTL 微结构（流水级数、折叠、握手）由确定性 lowering
后端生成，**不作搜索自由度，也不在主张内**；以后若要纳入，须先在 F2.5 中给出表示和合法性约束
（延迟对齐、吞吐、状态初值）。

**已被占据、不能再当差别的能力**（见近邻矩阵）：
- 固定图上按系统级仿真约束做字长优化（fxpopt、经典 WLO）；
- 近似算子选择 + 精度 + 调度 / 绑定（Li DAC'15、AxHLS）；
- 可验证的精确 RTL 重写 + LLM + 综合反馈（ROVER、ASPEN）；
- 实数 e-graph + 近似算子 lowering + 精度 / 成本 Pareto（Chassis）；
- 实数重写 + 定点 sound 误差界 + GP（Xfp EMSOFT'13、Daisy）；
- 「误差谱与下游滤波相互作用」这一工程事实（Nicholas–Samueli 1987、Vankka 1996、
  Callegari–Bizzarri 2013、输出加权 WLO）。

## 2. 技术核心（待证）

> **预注册的信息丢失型局部指标，在多速率部署契约下不保序。**
> For a pre-registered family M of context-free local scalar metrics, rankings under m ∈ M are
> not, in general, preserved by a pre-specified deployment-level risk functional over a family of
> multirate contracts.

### 2.1 对象

- **指标族** `M = {SQNR, WCE, last-bit accuracy}`，实验前冻结；不得事后增补其他局部指标来「找到」或「消除」反转。
- **部署契约** `Q_{C,ρ}(h) = ρ_{c∈C} q(h, c)`：
  - `C` 是设计时已知的规格集合：FCW / 信道栅格、**目标传递函数与通带 / 阻带规格**、抽取率与抽取相位、
    初相、blocker 规格等外部场景一并冻结。`C` **不**冻结候选 FIR 的结构或系数量化——那属于候选 `h`；
  - `q` 是**唯一的主数值风险**，定义在线性功率域（建议：链输出归一化误差功率，即线性 EVM²），witness
    只用它；其他数值量只作敏感性分析；
  - `ρ` 在线性域聚合 `q`（预注册一个：mean、栅格 worst 或 CVaR 之一，CVaR 须同时冻结场景权重 / 概率），
    不能事后切换；最终报告再转 EVM% / dB。不对 dB 值取 mean / CVaR（那是几何平均，不是误差风险），
    与 `VALIDATION_PROTOCOL.md` 在线性功率域合成的纪律一致。
- **外层选择规则**（不进入 `ρ`）：先按硬门槛（ACLR、alias、overflow 等）判可行，再在可行集合内
  按 `(Q_{C,ρ}, post-synthesis cost)` 做 Pareto 比较。

### 2.2 保序失败的定义

`M` 中每个指标先显式转成「越小越好」的形式：`m_SQNR = −SQNR_dB`，`m_WCE = WCE`（原始单位），
`m_lastbit = 1 − accuracy`。对某个 `m ∈ M`，一对候选 `(h_a, h_b)` 出现 **order-preservation failure**，分两种：

- **strict reversal**：`m(h_a) + ε_m^(m) < m(h_b)`，但 `Q_{C,ρ}(h_a) > Q_{C,ρ}(h_b) + ε_Q`；
- **collapse**（non-identification）：`|m(h_a) − m(h_b)| ≤ ε_m^(m)`，但 `|Q_{C,ρ}(h_a) − Q_{C,ρ}(h_b)| > ε_Q`。

`ε_m^(m)` 按指标**分别**预注册（各指标单位和尺度不同，不共享容差）；`ε_Q` 是统一的链级风险阈值（线性域）。
不用 `τ`，以免与 Kendall τ 混淆。两者须满足同一组外层
硬门槛，并报告 post-synthesis cost。最强的 contract witness 优先用 strict reversal；collapse 作辅助证据
（此前 strict all-pass 全同分的 witness 属于 collapse）。

### 2.3 契约纪律

- **栅格 worst ≠ 连续 worst**：只称「冻结部署栅格上的 worst」；栅格须来自真实的 channel raster /
  场景规范，并用栅格细化或插值点 held-out 检查结论是否稳定（v1 网格的共振教训，见 `spec.py`）；
- **两种部署规格各自真实**：最强证据是同一 `(h_a, h_b)` 在两个预先定义的契约 `(C1, ρ1)`、`(C2, ρ2)`
  下排序互换；不得事后从大池子里挑 c1 / c2。只做一个可调谐接收机时，主 witness 是「局部排序与整个 `C`
  上聚合排序反转」；
- 单点的 two-context 图只作解释机制的最小反例，不作部署结论。

### 2.4 边界：反转本身不是新贡献

- 经典反转可以出现在**纯线性链**中：只要局部指标丢掉了误差谱信息，线性混频 + FIR + 抽取（含相干 alias）
  就足以让排序翻转；这类失败由基线 ③（§4.2）完整解释，属于已知物理；
- 新的**评价方法**贡献只在最强线性基线 ③ 失效时成立，且失效须可归因于 ③ 遗漏的部分：下游 CMUL / FIR
  的 round / sat residual，以及它与主误差、抽取 alias 之间的交叉项；**alias 本身不算新贡献**；
- 主张对象是「预注册的局部标量指标不保序」，**不是**「一切局部模型都不行」。

## 3. 方法

- **精确层**：可验证的实数语义重写（e-graph 作基础设施，不作贡献）；
- **近似层**：参数化的硬件近似原语族，作为 typed lowering，不进入 e-class；
- **评估**：结构感知的全链 bit-true evaluator（B 类为主）；在可证的子问题上用 A-op / A-bound
  做 sound pruning 与校准（见 `VALIDATION_PROTOCOL.md` §8）；
- **搜索**：同一开放结构空间（F2.5 typed AST，覆盖 §1 的三项自由度）上，LLM 与 GP / beam / MCTS /
  约束搜索同预算比较。LLM 的作用限定为开放空间中的结构提案与诊断驱动修复；它是否有独特收益是**待证假设**。

## 4. 证据

### 4.1 contract-level order-preservation witness

证据分两级，都在清洁的 evaluator 上重算（旧 420 对只作诊断）：

1. **mechanism witness**：同一 `(h_a, h_b)`、同一接口，满足 §2.2 的定义（优先 strict reversal，或两个真实
   契约下互换），证明局部指标不保序；
2. **decision witness**：在同一组硬门槛和同一成本预算下，按局部指标 `m` 做出的选择相对按 `Q_{C,ρ}` 做出的
   选择产生 `ε_Q` 以上的 regret，或在 `(Q_{C,ρ}, post-synthesis cost)` 上被严格 Pareto 支配。不要求两者
   成本完全相等，但必须证明失败真的改变了设计选择（与 `VALIDATION_PROTOCOL.md` Gate B 的 top-k regret 对齐）。
   只有 mechanism witness、没有 decision witness 时，不能声称局部指标造成设计损失。

**阶段划分**：第一篇 witness 只变 NCO / 近似原语，下游 FIR 实现固定（`H` 固定）；FIR 结构与系数量化的
联合搜索放到 §4.3 的方法实验。

### 4.2 强基线梯子（看反转在哪一层被解释）

① **local scalar**：`M` 中的 SQNR / WCE / last-bit；

② **marginal power spectrum + 非相干折叠**（含 Nicholas / Vankka 式 FCW-aware 杂散预测，只适用于相位截断 DDS）；

③ **candidate-exact 复残差 + 相干线性传播**（最强线性基线，candidate-exact linear-reference baseline）：
   - 误差注入点取在 NCO / 近似原语的输出接口；在冻结的输入、初态与时间对齐下，取该接口处候选自身的
     **bit-true 复残差** `δm_c = m̂_c − m_c`；
   - 下游线性算子必须包含 mixer：`L_{h,c}(δm) = D_c · H_h · diag(x_c) · δm`（`diag(x_c)` 为混频，
     `H_h` 为候选自身的 FIR 实现（系数量化后），`D_c` 为抽取），多个误差源时保留源间互谱；
     witness 阶段 `H_h` 固定，退化为 `H`；
   - 下游 CMUL / FIR 自身的 round / sat 一律排除（留给 ④）；
   - 它对每种结构都公平，避免用不匹配的模型把 CORDIC / 多项式做成稻草人；但它**不是** ⑤ 的上界或下界——
     被排除的 round / sat residual 可能与线性项同相增强，也可能反相抵消。记录其计算成本，与 ⑤ 对比；

④ 在 ③ 上加入 CMUL / FIR 的 round / sat 残差与交叉项模型（解析或统计）；

⑤ 全链 bit-true truth。

另设固定图系统级 WLO（fxpopt 式）作为**搜索**基线，不放在误差模型梯子里。

### 4.3 搜索实验

- **2×2 主实验**：GP / LLM × satisfaction / numerical fitness；
  - satisfaction 臂：冻结每个用例的 pass / fail verdict 口径（与 numerical 臂共用同一场景集），实验前写死；
- **第五臂 = within-LLM 诊断消融**：LLM + numerical + 诊断反馈，只与 LLM + numerical 比较，回答
  「诊断对 LLM 是否有用」。若要主张诊断收益是 **LLM 特有**的，必须再加 GP + 诊断（诊断转为 mutation
  偏置）臂，否则不作此主张；
- **预算**：主预算单位预注册为「候选评估数」（若综合成为瓶颈则改为「综合次数」，二选一，实验前冻结）；
  预算计入**所有**提案尝试，包括语法 / 类型 / lowering / 综合失败的候选，不免费忽略 proposer 的无效率；
  同时报告 LLM 调用数、token、wall-clock，不作为主比较口径。

### 4.4 迁移

目录中至少再选一条机制不同的多速率链重复 witness。

### 4.5 e-graph 消融

方法消融，不进 2×2：与不用 e-graph 的 AST GP 比较重复候选比例、语义去重覆盖率和最终 Pareto 前沿。

## 5. 预注册的结果分支（做出来之前不知道哪一支成立）

「≈」「失败」「改善前沿」的判据统一引用 `VALIDATION_PROTOCOL.md` 的 Gate A / Gate B，
或在跑数前另行冻结的阈值（排序一致率、`ε_m^(m)` / `ε_Q`、hypervolume 差的置信区间）；不得事后调整。

结果分两条正交的轴，每条轴内部互斥且穷尽；论文定位由两轴的组合决定。

**Evaluation axis**（评价层，E0–E3 互斥）：

| 结果 | 判据 | 含义 |
|---|---|---|
| **E0** | 预注册契约与目录内无 order-preservation failure | 技术核心终止；结论只限于所测契约与目录，**不写「任何契约下都不存在」** |
| **E1** | 有 failure，③ 相对 ⑤ 通过 Gate | 经典线性谱解释；**不声称新误差理论** |
| **E2** | 有 failure，③ 不过、④ 通过 | 「round / sat residual 及其交叉项使线性谱模型不保序」成为评价方法贡献 |
| **E3** | 有 failure，③ ④ 均不过 | 撤下解析 / 模型主张，只能用 ⑤ |

**Search axis**（搜索层；S 为二值，L / D 仅在 S1 条件下为二值，S0 时记 N/A）：

| 子项 | 结果 | 含义 |
|---|---|---|
| 前沿 | **S0** / **S1** | ⑤ / numerical fitness 驱动的搜索相对强基线（fxpopt 式 WLO、Chassis 式、同语言 GP）不改善 / 改善前沿；S0 时搜索主张终止 |
| LLM | **L+** / **L−** | LLM × fitness 交互阳性 / 阴性；L− 时撤 LLM 独特性主张 |
| 诊断 | **D+** / **D−** | within-LLM 诊断消融阳性 / 阴性；只影响诊断相关表述 |

典型组合：

| 组合 | 论文定位 |
|---|---|
| E2 + S1 + L+ | 最强形态：评价方法贡献 + 契约搜索 + LLM 独特收益 |
| E1 + S1 | 结构特异模型的自动装配、开放结构联合搜索与系统实现证据；LLM 是否保留看 L± |
| E3 + S1 | full-chain bit-true 契约搜索作为方法贡献，无模型主张 |
| E1/E2/E3 + S0 | 只有机制 / benchmark / evaluator，没有搜索贡献；是否成稿另议 |
| E0 + 任意 | 技术核心不成立，整体 go/no-go |

S0 时 L、D 记 N/A，不报告 LLM 独特性。

纪律：
- tie 构造只说明最坏界可能是紧的，A-bound 粗界只说明无法 sound 分离；两者都**不**证明前沿顶端存在
  显著的 round / sat 残差，也**不**预先指定 n6 / n3 为 witness。由清洁 truth 和误差分解决定；
- 若饱和在正式可行域几乎不发生，不能用人为饱和场景撑起 E2；若只在极端 blocker 下发生，须明写适用边界；
- LLM 是受实验检验的搜索机制，不能由物理难点自动推出（见 `OUTLINE_DIFF.md` D4）。

## 6. 算子范围与顺序

两种顺序分开写：

- **目录 / 基础设施顺序**（`CATALOG.md`）：建全目录（A 前端 / 多速率、B CFR / DPD、C FFT、D 同步、
  E 估计 / 均衡 / MIMO、F 解调 / 译码），E / C / X 三类并列展示；实现排期 A1 NCO → A8 倒数 →
  A3 FIR / 多相 → A2 DDC → C1 FFT → A7 / A9。A8 等 kernel 族服务于方法广度，不参与核心命题的 go/no-go。
- **论文 go/no-go 顺序**（最小链）：
  1. A1 + A3 + A2 组成最小多速率链，冻结契约 `(C, ρ, q, {ε_m^(m)}, ε_Q)`；
  2. 找 contract-level 保序失败（§4.1）；
  3. 过强基线梯子 ③ / ④（§4.2），确定 Evaluation axis 的结果；
  4. 搜索实验（§4.3），判定 S / L / D；
  5. S1 成立后，再在第二条机制不同的多速率链上迁移（§4.4）。
  落入 E0 或 S0，即停止扩展目录、重新评估。

## 7. 需要用户拍板

1. 是否接受第 2 节作为技术核心（替代旧的「pass-rate 错配」和「解析 fitness」主线）？
2. 是否接受第 5 节的预注册分支，特别是 E1 或 L− 时论文不再声称新误差理论或 LLM 独特性，只剩结构自动装配、联合搜索与系统实现贡献？
3. 第一步是否就做 witness 的**纸面预测**（先冻结 `(C, ρ, q, {ε_m^(m)}, ε_Q)`，再预测哪一对结构可能反转），通过后再修 evaluator、跑数？
