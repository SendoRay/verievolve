# Chain-level numerical fitness validation protocol（草案）

- 建立日期：2026-09-29
- 来源：与 Codex 讨论定稿（Tin Can 线程 `msg_04ce29820180407e826148f9`）
- 状态：**草案，未冻结**。所有阈值须先在开发集上校准，冻结后才能跑 held-out。
- 与 `DIRECTION.md` 的关系：本文为 DIRECTION §3 第 3 条（结构感知 bit-true 数值风险）和 §5.1.6
  「本工作（待证）」一行提供可证伪的验收标准。**在本协议通过前，论文不得称链级模型为 validated。**

**定义**：validated 指在预注册的适用域、候选族和 held-out 场景上，模型通过绝对数值 gate（Gate A），
且决策 regret 不超过冻结的工程阈值（Gate B）。这样定义可以证伪，也避免把「排序有用」偷换成
「模型正确」。

---

## 1. 先做身份审查：被评的量到底是什么

| 类别 | 条件 | 可用的称呼 |
|---|---|---|
| **A** | 残差来自对**有限输入域 / 完整周期状态**的精确枚举；后续算子是线性的、不饱和，用复幅度做相干折叠 | finite-domain exact integer-residual evaluation with coherent multirate composition（属于解析，不要求闭式） |
| **B** | 残差来自**一条冻结的有限轨迹**的 bit-true 执行，再做 FFT 和折叠 | deterministic trace evaluation（零重复方差，但**不是** analytic，也不是全输入） |
| **C** | 残差是各局部块**分别算出后相加** | 须单独审查非线性耦合，见下 |

**C 类的风险**：上游误差会改变下游量化器 / 饱和器走哪一支，所以 `e_out` 不一定等于各局部残差
线性传递后的和。相干折叠能精确保留 alias 交叉项，但**补不回量化器之间的输入依赖**。只有以下情况
才能称链级精确：
- 残差已经是抽取前的**总 bit-true 误差波形**，且其后的链路线性、不饱和；或
- 有严格的 telescoping decomposition，并把所有 interaction / residual `r` 都算进去。

因此以下两项要**分开验收**：
1. 相干折叠恒等式本身是否正确（对给定残差谱）；
2. 整链残差分解是否完整。

当前状态：cost audit 中的 `q`（0.169 ms）属于 **B 类**；NCO kernel 的 `certfit` 全枚举属于 **A 类**。

---

## 2. Gate A：数值模型有效性

**问题**：`q̂` 是否真的重建了与 full-chain bit-true truth 相同的物理量？

**真值**：同一冻结段上，full-chain bit-true 输出相对 float reference 的误差。**不能**用另一个谱近似当真值。

**主指标：绝对误差，一律在线性功率域计算**
- 每个 candidate × scenario 的 `|q̂ − q_true|`；
- 相对误差的分母取 `max(q_true, q_floor)`，避免真值接近零时爆掉；
- dB 偏差只作可读报告，**不在 dB 域做误差合成**；
- 报 median / 95th / max，**每个 architecture class 单独报**，不能用总体平均掩盖某一族失败。

**容差怎么定**
- 若模型声称**精确**，容差由数值实现误差定标（FFT 浮点误差、窗 / 归一化误差），不是预留 0.x dB 的工程宽容；
- 先用已知单音和小规模直接 DFT 校准 `q_floor` 与数值容差，再冻结阈值；
- 若只能达到工程容差，就叫 **validated approximation**，不能叫 exact。

**不通过时怎么处理**
- 只有某一结构族，或只有 saturation-active 场景失败：明确缩小适用域；
- 在线性、无饱和的子集上也失败：模型公式或实现无效，**撤下链级 analytic 主张**；
- 平均值好但 worst-case 超阈：**不通过**，不能用「总体相关」判通过。

---

## 3. Gate B：作为搜索适应度的决策有效性

**主判据：top-k regret 与预算违约。** Kendall τ-b 降为诊断。

理由：
- 全局 τ 很高，仍可能在 top-k 边界翻转，恰好选错最终设计；
- 全局 τ 很低，也可能只是大量近乎并列的点互换，top-k 的真实损失接近零；
- 论文要主张的是「这个 fitness 能指导选择」，不是「复现所有两两顺序」。

**定义**（最小化 `q`；若是质量最大化，方向相反）：

```
R@k(s) = min_{i ∈ predicted-top-k} q_true(i, s) − min_{i ∈ C} q_true(i, s)
```

**同时报告**
- true-best 命中率（任一并列最优都算命中）；
- false-feasible rate：模型判为满足预算，真值却超预算；
- worst budget violation；
- τ-b 与全并列保留率（只作全局排序诊断）。

第一版协议**冻结为标量 `q` 的 top-k**。多目标前沿（ε-dominance / hypervolume regret）留到之后，不要一开始就引入多目标的复杂度。

---

## 4. 四种结果预先写明

| Gate A | Gate B | 结论 |
|---|---|---|
| 过 | 过 | validated numerical fitness |
| 过 | 不过 | 数值模型准确，但不足以支持搜索收益主张 |
| 不过 | 过 | 只能叫 ranking surrogate，**不能**叫 validated chain-level numerical model |
| 不过 | 不过 | 模型与方法主张都降级 |

---

## 5. 候选与场景覆盖

**候选**：至少三类真正不同的 architecture class，每类至少两个**非重复**参数点。
- nearest-neighbor LUT；
- interpolation LUT（线性；若有二次插值，单列一类）；
- CORDIC。

至少两个点是为了避免把「结构差异」和「分辨率旋钮」混在一起。`phase_bits` 若没有被 standalone 模型
读取，就不能算独立点（见 DIRECTION §2.4）。

**场景**：分层覆盖
- blocker on/off，强 / 弱；
- alias 原像单一 / 重叠；
- 相位为同相、正交、近反相的构造情形；
- v2 FCW 网格，确保相位累加器低位被激活（见 `spec.py` 中 v1 的教训）；
- saturation-free 与 saturation-active 分层；
- desired-signal-referenced SNR，以及修正后的 QPSK 功率口径。

**数据纪律**
- 开发集只用于校准数值容差；held-out 场景只用于最终 gate；
- 场景版本、seed、warm-up、对齐方式、测量区间全部冻结。

---

## 6. 前置条件（代码层，**暂缓**，只登记不修）

本协议依赖以下已知问题先修复，排期按 DIRECTION §6：
- `metrics.py::spectral_prediction` 的折叠索引错误：当前用 `p_in[j::R]`，正确应为 `X[k + j·N_out]`；
- `metrics.py::sfdr_db` 只排除主峰 ±2 bin，存在窗泄漏（2026-09-28 已用理想单音数值确认）；
- 功率和近似会丢掉相干交叉项，必须换成复幅度相干折叠后才可能过 Gate A；
- `metrics.py::spectral_prediction` docstring 中「预测与真值的差 = 互相关项 + FIR 非线性（饱和）」须校准：
  `fir_err` 按实际输入 `z1` 计算时，饱和已包含在 `r_F(z1)` 里，差值只剩功率交叉项（见 §8.7 第 ④ 行）。

---

## 7. 措辞纪律

- 不追求闭式；有限域精确计算或结构化的整数残差算法都可以构成解析适应度；
- 「逐条固定轨迹 bit-true 仿真 + FFT」**不能**仅因为确定性就改叫解析（见 §1 的 B 类）；
- 成本只报实测值，不写「零评估成本」；
- 相干折叠只对「给定的复幅度残差谱经过线性抽取」是精确的；它是否等于链级真值，取决于残差生成、
  历史状态、后级量化 / 饱和以及交叉项是否完整保留。

---

## 8. 链级能否进 A 类：三层混合方案（2026-09-29，Codex 分析，我已核对仓库事实）

**结论**：CMUL 的舍入会让「对任意输入成立的单一线性泛函」这个说法破功，但**不会让 A 类中间量破功**。
FIR 的丢位、累加饱和和输出量化是**同类的第二个障碍**，不只 CMUL。

### 8.1 误差分解

```
e_out = e_NCO + e_CMUL + e_FIR + r_interaction
```

- **NCO 项**：`δm = m̂ − m`。若乘法、FIR、抽取都是线性且不饱和，则对任意确定输入 `x` 有精确算子式
  `e_NCO = D·H·diag(δm)·x`。`δm` 是周期的，所以这是一个精确的**周期线性时变（LPTV）算子**。
  频域上应称 harmonic transfer / input-to-error operator，**不要**称「对任意输入成立的一条固定误差谱」：
  输出谱仍取决于 `X`，算功率一般还需要输入的谱相关矩阵，不只是普通 PSD。
- **CMUL 项**：`e_mix[n] = x[n]·δm[n] + ρ_c(x[n], m̂[n])`，其中 `ρ_c = Q_c(x·m̂) − x·m̂`。
  第一项属于上面的 LPTV；第二项取决于输入码、NCO 码、`prod_drop`、舍入模式和饱和，
  **不能由 `δm` 的周期谱独立决定**。相干折叠补不回 `ρ_c` 与第一项的互相关。
- **重要修正**：DDC 的输入在硬件边界已被 ADC 量化为 Q1.11，**单拍输入码域是有限的**。所以 `ρ_c`
  可以精确写成**按相位索引的残差核**：
  `ρ_p(i, q) = mixer_fixed(i, q, m̂_p) − ideal_product(i, q, m_p)`。
  它对所有输入码都精确，属于 A 类局部模型。它不是一条周期误差序列，而是一族随 NCO 相位 `p`
  周期变化的非线性映射。

### 8.2 残差核怎么变成链级功率：三种选择

| 目标 | 做法 | 类别 |
|---|---|---|
| 对任意输入序列 | 必须保留实际码序列 | 落回 B |
| 对声明的输入概率律 | 计算 phase-conditioned moments 与跨时刻自 / 互相关，再经 FIR / 抽取传播 | A（若能精确完成） |
| 对任意输入 | 取逐点 / 最坏界，再用 FIR 算子范数传播 | A（界） |

⚠️ 仓库已有的 `common.cmul_exact_err_moments` **不能直接用来填这个洞**：它假设独立均匀的 n 位操作数，
且整数乘积和累加精确、输出一次性丢位。DDC 的实际情况是（已核对 `chains/ddc/fixed_chain.py`）：
- 输入是 12 位的成形 QPSK + 干扰 + AWGN，ADC 码分布不均匀；
- NCO 操作数与相位强相关，也不均匀；
- 四个乘积分支先各自 `prod_drop`，再对总和右移 `MIX_FRAC_SHIFT`，最后 `sat16`；
- `fir_fixed` 另有 `prod_drop`、有限 `wacc` 饱和、输出右移和 `sat16`。

### 8.3 推荐路线：三层混合

- **A1 精确线性骨架**：NCO 的完整周期（或等价的符号谱）→ `D·H·diag(δm)`。限定 mixer / FIR 不饱和，
  暂不含它们的量化残差。它给出精确的 input-to-error operator。
- **A2 精确局部非线性核或严格界**：CMUL / FIR 的每个量化点都建立有限域残差核。能在声明的输入律下
  得到精确 joint moments 就传播；做不到就给最坏界。**总误差功率必须保留交叉项**。若只有残差能量上界
  `B`，在同一加权输出范数下，由三角不等式至少有
  `max(0, √P_NCO − √B)² ≤ P_total ≤ (√P_NCO + √B)²`。
  只有当这个区间**窄于选择所需的 margin** 时，才足以作 fitness。
- **B 真实场景实例化与外部验证**：冻结的 QPSK + blocker + AWGN 场景仍走 deterministic trace evaluation，
  作为 A1 / A2 的 Gate A / B 对照，**不冒充 A**。

**论文可用的说法**：「解析对象是候选特异的误差算子 / 残差核；现实场景上的标量 fitness 是它们的确定性实例化
或经验证的近似。」**不得**说「整条 DDC 对任意随机输入已解析精确」，除非 A2 的跨时相关真的完成。

### 8.4 周期 ≠ 可计算（已核算）

NCO 周期为 `2^32 / gcd(FCW, 2^32)`。v2 网格的实际值：

| f_off | FCW | 周期（拍） |
|---|---|---|
| 0.39 MHz | 837518623 | 2³² |
| 0.51 MHz | 1095216660 | 2³⁰ |
| 0.63 MHz | 1352914698 | 2³¹ |

直接枚举不可行。要么用 DDS 杂散的解析谱结构（Nicholas 系，见 `LIT_GAP.md` §2.2），要么专门选
「既激活低位、周期又可控」的校准 FCW。后者只能作校准场景，**不能替代真实网格**。

### 8.5 下一步：纸面 tractability audit（不写代码）

对 `e_NCO` / `e_CMUL` / `e_FIR` / `r_interaction` 每一项列出：
自变量域、是否有限、是否周期、需要几阶 joint moment、跨时记忆长度、是否饱和；
再列出所有交叉项里哪些能精确算、哪些只能给界。

**决策规则**：若 audit 表明 phase-conditioned 的 CMUL / FIR joint moments 规模太大，会议主线采用
**A1 + 严格残差区间 + B 验证**，而不是把「全链 A」当生死门。只要区间能在 top-k margin 上做出确定决策，
这仍是非平凡的解析适应度；若区间太松，就诚实降为 **B 类 structure-aware deterministic fitness**。

### 8.6 精确 telescoping 恒等式与三级分类（2026-09-29，Codex 提出，我已逐步验算）

令 `z = Q_c(x·m̂)`，FIR 实现 `Ĥ(z) = H(z) + ρ_H(z)`（`H` 为理想线性 FIR），则**对任意输入严格成立**：

```
e_out = D·H·diag(δm)·x          ① NCO 周期线性项
      + D·H·ρ_c(x, m̂)           ② CMUL 输入相关残差
      + D·ρ_H(Q_c(x·m̂))         ③ FIR 输入 / 历史相关残差
```

验算：`out_fix = D·H·z + D·ρ_H(z)`，`z = x·m + x·δm + ρ_c`，`H` 线性，减去 `D·H·(x·m)` 即得。
抽取 `D` 是线性选样，本身不产生残差；但会让三项在输出带内相干叠加，所以**功率必须包含交叉项**。

**「周期均值 + 统计残差」只在给定输入律下有意义**：可以定义 `μ_c[p] = E_X[ρ_c(X, m̂_p)]`、`ε_c = ρ_c − μ_c[p]`，
但 `μ_c` 依赖声明的输入分布（换 QPSK / blocker / SNR 就会变），**不能**叫「对任意输入 A-exact」。
没有输入分布时，所谓的周期部分只是任意选取的基准，既不唯一，也没有物理优势。

**分类细化**（替代 §1 中笼统的 A 类）：

| 类别 | 含义 | 可以说什么 |
|---|---|---|
| **A-op** | 对任意输入成立的精确误差算子（如 ①） | exact error operator |
| **A-bound** | 对任意允许输入成立的严格残差 / 输出区间（如 ②③ 的界） | sound interval |
| **B** | 冻结轨迹上的确定性标量评估 | deterministic trace evaluation |

- 只有 A-op 加上**完整的残差算子**，才能给出整链的 exact mapping；
- A-op + A-bound 能给出整链的 **sound interval**，但**不能**称 exact scalar。

**sound ranking**：设 `a = ①`，`b = ② + ③`，且在同一输出加权范数下 `‖b‖ ≤ β`，则

```
max(0, ‖a‖ − β) ≤ ‖e_out‖ ≤ ‖a‖ + β
```

若两个候选的区间**不重叠**，就能对所有允许输入给出不会翻转的排序。这比强求整链精确标量更有价值。

**主线（更新）**：
1. 方法核心的「解析」落在 **A-op**：NCO 的 harmonic / error operator；
2. 对 CMUL / FIR 残差构造 **A-bound**，检查区间是否窄于 top-k margin；
3. 真实的 QPSK + blocker + AWGN 场景用 **B** 作外部验证；
4. 若界太松，链级主张降为 structure-aware deterministic fitness，但 NCO / kernel 级的 A 类贡献保留。

**可证伪点**：若 CMUL / FIR 残差界大到覆盖候选间的全部 margin，路线 (ii) 对决策无用，**不能靠措辞补救**；
若界足够紧，即使没有整链精确标量，也能给出「对任意允许输入，选择不会翻转」的强结论。

### 8.7 纸面 tractability audit 表（2026-09-29，NCO / CMUL 行由我做，FIR / 交叉项行由 Codex 做，已合表）

已核对的仓库事实：float 参考 `ref_chain.mixer_ideal` 用**名义** `f_off`，而不是 FCW 量化后的频率；
场景 `x = s·e^{jθn}` 与 NCO 用的是**同一个名义 θ**；场景在 ADC 前把 `|x|` 归一到 ≤ 0.95
（`scenarios.py:102`）。

| 项 | 自变量域 | 有限？ | 周期？ | 记忆 | 饱和 | 链级功率需要什么 | 归属 |
|---|---|---|---|---|---|---|---|
| ① `e_NCO` | `acc ∈ Z/2^32`（经 `pw` 高 B 位 + 低 `L=32−B` 位） | 核有限（`2^B` 码）；低位不可枚举 | 是（2³⁰–2³² 拍） | 无（逐拍） | 无 | 相对误差 `η` 的**带奇偶的时间自相关** `r_η^{(par)}[d]`，`\|d\|≤32` | A-op；全周期功率在声明的 `R_s` 下 **A-exact 且便宜**（见下） |
| ② `ρ_c` CMUL | `(i, q) ∈` 合法幅度球内的 12 位码 × `pw` | 是，但联合 `≈2^24·2^B` | 否（随 `x`） | 无 | **在场景幅度契约下可证不可达**；对整个 12 位方盒不成立 | 跨时 lag ≤ 32 的联合矩 → `2^40` 量级，**不可精确** | A-bound（逐点界，见 §8.8）；精确矩不可行 |
| ③ `e_FIR` | 33 拍窗口 × 16 位 | 形式上有限，不可枚举 | 否 | 33 拍 | `wacc` / `sat16` 需 range proof | `(Hq−H)z` 为 A-op；无饱和时 product-drop / 输出舍入为 A-bound | A-op + A-bound |
| ④ `r_interaction` | — | — | — | — | — | 用实际输入的 `r_F(z1)` 时**没有独立时域项**，只剩功率交叉项 `2Re⟨DHe_mix, D r_F(z1)⟩`；用 `r_F(z0)` 时须单列系数交互 `(Hq−H)e_mix` 和算术分支交互 | 取决于分解口径 |

**合表约定**：truth decomposition 一律用**实际输入**的 `r_F(z1)`（`run_s1.py` 的 `fir_err` 定义正确）；
`r_F(z0) + r_int` 只用于 tractability 分析。

**① 的关键发现：全周期 `e_NCO` 功率可以精确算，而且便宜。**
令 `η[n] = m̂[n]·e^{jθn} − 1`（相对误差），则 `x·δm = s·η`，`s` 是基带分量（信号 + 干扰 + 噪声），
与相位累加器无耦合。于是

```
P_NCO = Σ_{k,l} h_k h_l · R_s[l−k] · r_η^{(par)}(k, l)
```

其中 `r_η(c) = avg_a η(a)·η*(a+c)`，`c = d·FCW mod 2^32`。把 `a` 拆成 `(pw, low)`：
`η(a) = m̂(pw)·e^{j2πa/2^32} − 1`，展开后
- `m̂m̂*` 项的相位因子 `e^{−j2πc/2^32}` 是常数，`low` 只通过进位决定 `pw' = pw + c_hi` 或 `+1`，
  权重为 `(1 − c_lo/2^L)` 与 `c_lo/2^L`；
- 交叉项中 `low` 只贡献几何级数，闭式可求；
- 于是所有 lag 只需 `m̂` 在 `2^B` 码上的循环自相关，**一次 `2^B` 点 FFT** 即可得到。

⚠️ **两处订正（2026-09-29，Codex 指出，我已验证）**：
1. **`R_s` 不是 WSS**：RRC 上采样的 QPSK 在输入采样率上是周期 `SPS = 8` 的循环平稳过程。完整式须先写成
   `P_NCO = avg_{n ∈ 所选输出相位} Σ_{k,l} h_k h_l* E[s_{n−k} s*_{n−l}] η_{n−k} η*_{n−l}`，
   只有 `E[·]` 与 `n` 无关，或能证明 `n mod 8` 与 NCO 相位在全周期平均中均匀解耦，才能因式分解为
   `R_s(l−k)·r_η`。phase class 应取「抽取奇偶 × 符号多相 8」的联合，而不只是奇偶。
   干扰的相关只依赖 lag；圆对称 AWGN 反旋后仍白；需要审查的是 RRC-QPSK 的 8 个相位。
2. **carry 化简里的 coset off-by-one**：缩位宽穷举（`W = 10…13`、`B = 4…8`，含 gcd 格点、`R = 2` 的
   两个 coset、`d ∈ [−8, 8]`，共 2040 组）发现：`R = 2` 且 `d` 为奇数时，`c = d·FCW` 不在 coset 格点上。
   初版公式的 carry 权重 `c_lo/2^L` 和第三项的 coset 残差都会错，最大误差达 8.6e−3。
   修正做法：carry 比例取 `#{low ∈ r+gZ : low ≥ 2^L − c_lo} / #{low ∈ r+gZ}`；第三项用 `a+c` 所在
   coset 的残差 `r' = (r+c) mod g`。修正后与穷举的最大误差为 **8.8e−16**（机器精度）。
   脚本在 `/tmp/reta/`，是临时文件，未进仓库。

适用条件：全周期时间平均（`gcd(FCW, 2^32) = 2^t`，`t < L` 时低位在 `2^t` 格上均匀，几何和仍为闭式；
v2 的 `t = 0, 2, 1`）；抽取后只取偶数拍，把格点换成 `2^{t+1}` 即可。`FCW` 相对名义频率的舍入
（≲ 0.23 mHz）作为 `η` 中的慢相位漂移单列，量级约 1e−5 rad，且会被 LS 复增益对齐部分吸收。

两个必须写明的边界：
1. **全周期平均 ≠ 12800 拍 trace 平均**：`B = 16` 时 trace 连所有 `pw` 码都访问不全。两者之差是
   Weyl 序列 `n·FCW mod 2^32` 的有限样本偏差，原则上可用 Koksma–Hlawka 型不等式界定
   （LUT 的 `η` 有跳变，但总变差有限）。未做，登记为选项。
2. **`R_s` 是声明的输入律**：RRC-QPSK 的自相关有解析式，干扰是随机相位单音，AWGN 是白噪声；
   但场景的峰值归一化（`x/peak·0.95`）是依赖样本实现的增益。`P_NCO / p_ref` 对这个增益不变，
   CMUL / FIR 的绝对 LSB 残差则会随它变，所以 ① 与 ②③ 的相对量级取决于归一化。

### 8.8 CMUL 粗界的量级检查（纸面 + 只读数值，未改代码）

**逐点界**（Codex 核算，我复核口径）：统一到实数 Q1.15 输出。
- `c1_exact_rne`：每字段 `|ρ| ≤ 2^−16`，复幅度 `β_c = √2·2^−16 ≈ 2.158e−5`（−93.32 dBFS）；
- `c2_pd2_trunc`：每字段 `|ρ| < (2^11+6)/2^26`，`β_c ≈ 4.328e−5`（−87.27 dBFS）；
- FIR 传播：严格界用 Young 不等式 `‖H‖ ≤ ‖h‖₁ = 1.50549`；密网格 `sup|H| = 1.0` 只是启发式，需另证；
- 饱和：`|x_adc| ≤ 0.95 + √2·0.5/2048`，6 个 kernel 全枚举 `max|m̂| = 1.0000813`（n6），
  故 `|x·m̂| ≤ 0.9504`，**sat16 在场景幅度契约下不可达**。A-bound 的域必须写成「满足冻结场景幅度规范的
  ADC 输入」，不能写成「所有 12 位码」。

**可分性判据**：候选 `i, j` 有 sound order，当且仅当区间不重叠，粗看即
`|√P_i − √P_j| > β_i + β_j`。以 kernel SQNR `S` 作为 `‖①‖/√p_ref` 的代理（`P = p_ref·10^{−S/10}`），
即使两者都用最好的 `c1`，所需的最低输出参考功率为：

| 候选对（kernel SQNR） | `sup\|H\|=1`（启发式） | `‖h‖₁`（严格） |
|---|---|---|
| n1 vs n5（37 vs 71 dB） | `p_ref ≥ −50.1 dBFS` | `≥ −46.6 dBFS` |
| n5 vs n6（71 vs 84 dB） | `≥ −14.1 dBFS` | `≥ −10.5 dBFS` |
| n6 vs n3（84 vs 96 dB） | `≥ −0.8 dBFS` | `≥ +2.8 dBFS` |

**结论（sanity estimate，未证）**：
- 粗界**提示**前沿顶端的 n6 vs n3 可能无法用逐点 A-bound 做 sound 排序，而这正是真正要做决策的地方。
  ⚠️ 已撤回「已证明不可能」：kernel SQNR 与目标量之间有四处错位（均匀角度码平均 vs v2 FCW coset；
  worst-field SQNR vs 复输出能量；未含 `H` / 抽取对不同杂散的选择性；未含循环平稳的 `R_s` 与 `p_ref` 口径）。
  必须用精确 `r_η` 算出 n6、n3（其次 n5，最终 6 个全算）后才能下结论；
- n5 vs n6 是边界情形，取决于场景 backoff；
- 跨大结构档（37 dB vs 70+ dB）可以轻松分开。

**收紧的空间可能很小**：`c1` 只有最后一次右移的 rne 舍入，残差类约束（Codex 的收紧手段 2）帮不上忙；
而带内范数（手段 3）只有在假设 `ρ` 的谱是分散的时才会变紧，这已经是统计假设。
进一步，若对「任意合法输入」可以构造出让 `ρ ≡ +0.5 LSB`（DC）的码序列，这个界就是近似可达的，
那么「对任意输入 sound」在前沿顶端**本身就是过强的要求**，不只是界松。

**tie 构造（Codex 给出，我已逐步验算代数）**：对 `c1`（`prod_drop = 0`，最后右移 11 位，half-up），
令 NCO 整数输出为 `c, s`，`k = min(v2(c), v2(s))`，`c = 2^k c'`、`s = 2^k s'`、`T = 2^{10−k}`。若 `k ≤ 10`：
- `c', s'` 一奇一偶：取 `I = Q = T`，则 `cI + sQ = 2^10(c'+s')`、`−sI + cQ = 2^10(c'−s')`，括号内都是奇数；
- `c', s'` 都是奇数：取 `I = T, Q = 0`，则两式为 `2^10 c'` 和 `−2^10 s'`。

两个字段都 `≡ 2^10 (mod 2^11)`，恰好落在 tie 上，所以 `ρ = +0.5 LSB`；输入幅度 `≤ √2·1024/2048 = 0.707`，
合法。Codex 枚举了 6 个 kernel 的 65536 个角度码：n1–n5 没有坏码；n6 有 4 个码的 `c, s` 同时被 `2^11` 整除，
tie 不可达，其余 99.9939% 可达。输入可以依赖已知的 NCO 相位，这正是「任意输入」的含义；若要求输入与相位独立，
就已经是输入律假设，属于 A-expectation。

**限定**：这只证明 CMUL 残差的逐点 / RMS 界和 DC 增益**近乎可达**，**不**自动证明三角区间两端同时取等，
因为那还需要残差与 `e_NCO` 的输出方向对齐。不得把「β 紧」升级成「整个 ranking interval 必然紧」。

⚠️ 上表用 kernel SQNR 当代理。链级 `‖①‖` 还包含相位截断和 FIR 整形，须用 §8.7 的 `r_η` 精确值替换后重算；
而且 FIR 自身的残差会让 `β` 更大，所以上表对 A-bound 是**偏乐观**的。

**对方法设计的含义（建议）**：A-bound 的合适角色是 **sound pruning**，即淘汰不可能进入 top-k 的结构档，
且永不误删；前沿顶端的排序改用「声明输入律下的 A-expectation（① 精确 + ②③ 的 phase-conditioned 统计）」
或 B。这样分工既保住可证伪的 soundness，也不把 A-bound 推到它做不到的地方。

**三种契约（Codex 提议，我同意作为主线框架，名称暂定 guarantee-aware tiered fitness）**：

| 契约 | 评估 | 角色 |
|---|---|---|
| adversarial | A-bound | 只作 sound feasibility / pruning，零误删 |
| communication | A-expectation（声明输入律下的精确期望） | 排序 |
| held-out implementation | B（bit-true） | 终评 |

要让解析部分不沦为装饰，须满足三条：
1. A-bound 有**非平凡 coverage**：报告多少候选 / 候选对能 sound 决策、多少必须升级，最好给 coverage–tightness 曲线；
2. 被安全淘汰的不能只是局部 SQNR 一眼就能排除的点，要与 local SQNR、SPIRAL 式范数界、经典区间界比较；
3. A-expectation 对声明输入律必须**真的是精确期望**；若用了零均值 / 独立 / 弱相关近似，就叫
   distribution-conditioned model，并走 Gate A/B。

**卖点不能写成加速**：full-chain B 只要 4.85 ms，pruning 省下的时间不构成卖点。A-bound 的价值应写成
soundness、分布漂移下的 guardrail 和零误删；若 coverage 很低，就降为方法边界，不进标题。

---

## 9. 2×2 机制实验与 A 线的依赖（2026-09-29，Codex 提出，我同意）

**2×2 不需要 A 类。** 数值格直接用修正后的 **full-chain B-class bit-true metric** 即可。
只有当数值格改用 `q` 这类近似量作 fitness 时，Gate B 才是 2×2 的前置条件。

```
P0 evaluator correctness + protocol freeze ──→ full-chain B metric ──→ 2×2 机制实验
                          └─→ A1/A2 audit ──→ 实现 ──→ Gate A/B ──→ 方法实验（并行线）
```

**2×2 的四个硬前置**：
1. 修复已知缺陷（§6），或者明确不调用有缺陷的指标；
2. fitness 与 held-out truth 是**同一个物理量**；
3. 训练场景与 held-out 场景分开；
4. 四格同预算，同时报 LLM 调用数和 wall-clock，多个 seed。

**分工不能互相替代**：A1 / A2 决定的是方法贡献、评估成本和可迁移性；**2×2 阳性不能替代 Gate A/B**，
Gate A/B 通过也不能替代 2×2 的机制证据。

### 8.9 待决契约（2026-09-29 登记；在整篇纲要统一前冻结，不做计算）

Codex 核查后提出，我接受：
1. **参考相位**：`ref_chain` 用名义 `θ_nom`，`fixed_chain` 用量化后的 `FCW`（`θ_F`）。两者的频差为
   +1.3e−4 / −2.2e−4 / −1.1e−4 Hz（0.39 / 0.51 / 0.63 MHz）。精确拆分为
   `m̂e^{jθ_nom n} − 1 = (m̂e^{jθ_F n} − 1)e^{jΔθn} + (e^{jΔθn} − 1)`：第一项是结构误差，
   第二项是各候选共用的 FCW 量化误差。对 `θ_nom` 取「全周期均值」会把频偏累积成相位失配，得到病态指标。
   **倾向方案 A**：解析 architecture fitness 以 `θ_F` 为参考，公共频差项单列；终评对 nominal 参考时再把它加回。
2. **循环平稳**：`n mod 8` 是完整累加器状态的确定函数，FCW 为奇数也**不**解耦。须按 8 个 `n mod 8`
   coset 条件化，`R = 2` 时平均其中 4 个偶相位。`R_s^{(q)}(k,l) = E|a|² Σ_j h_tx[q−k−8j] h_tx*[q−l−8j]`
   （稳态、IID 符号）；`mode="same"` 的边缘效应和峰值归一化留给 B。
3. **角度约定**：`tpl_cordic` 为 `θ = πz/2^15`，与 `fixed_chain` 的 signed 映射 mod 2π 一致，没有 2 倍风险。
4. 由此算出的 `‖①‖` 只能叫 **steady-state A-expectation under declared IID symbol law**，不能叫当前 12800 拍场景的 exact truth。
