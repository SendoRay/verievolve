# 通信 PHY 算子目录（草案）

- 建立日期：2026-09-29
- 状态：**草案**。只描述任务，不代表已实现，也不代表进入主实验。
- 目的：覆盖 SDR / 3G / 4G / 5G 物理层中有代表性的公式到硬件任务。“全”指目录和任务规格覆盖面，
  不预设同一种搜索方法适用于全部任务。

---

## 1. Schema

每个条目统一写六个研究字段，再标方法适配标签和仓库状态：

| 字段 | 含义 |
|---|---|
| **formula / dataflow** | 实数语义的数学规格，包括公式、状态递推与采样率关系 |
| **contract** | 数值契约（SFDR / EVM / ACLR / BER / NMSE 等）及其层级（kernel / 链 / 系统） |
| **exact identities** | 实数语义下严格成立、可进入 e-class 的恒等式；注明定义域、边界和状态前提 |
| **approx realizations** | 近似实现原语及参数；不并入 e-class，只作为 typed lowering 叶子 |
| **reference / evaluator** | 参考语义和评价方法：整数域全枚举、bit-true 轨迹、确定性场景集、统计估计或最坏界 |
| **strong baseline** | 同口径的生成器、WLO、专用编译器、标准算法或 IP |

**方法适配标签**：

- **E**（EqSat-native）：实数等价分解足够丰富，e-graph 能表示影响实现结果的结构空间；
- **C**（contract-search-native）：主要选择发生在不等价算法或系统策略之间，必须由契约评价；
- **X**（exact-only）：没有合法的精度取舍，只承担连接、置换或 RTL 完整性；
- **E/C**：精确分解和契约层非等价选择都属于一等自由度；
- **C（内部 E）**：顶层算法选择是 C，e-graph 只优化冻结算法内部的等价算术。

标签描述的是**搜索空间结构**，不表示评价容易。有限域能否全枚举单独写在 `reference / evaluator` 中。

**进入主实验的 gate**（每条都必须满足）：

1. 至少两个真实不同的分解或实现类，不以同一模板的参数变化充数；
2. 数值质量可以取舍，且取舍会改变 PPA；
3. 有独立参考实现和适合该状态维数的 evaluator；使用采样时必须冻结分布、场景与统计协议；
4. 有同输入、同契约、同 PPA 口径的强基线；
5. 契约可冻结、可证伪，并明确 kernel、链或系统层级。

---

## 2. 目录

### A. 数字前端与多速率

| # | 算子 | 标签 | formula / dataflow | contract | exact identities | approx realizations | reference / evaluator | strong baseline | 仓库状态 |
|---|---|---|---|---|---|---|---|---|---|
| A1 | NCO / DDS、数字混频 | E | `phase[n+1]=phase[n]+FCW`，`m[n]=exp(j·phase[n])`，混频为 `x[n]m*[n]` | kernel：SQNR/SFDR；链：EVM、alias | 象限/八分对称、三角和角公式、复旋转分解 | LUT 最近邻/插值、`CORDIC_N`、range-reduced `Poly_d`、相位截断、dither | kernel：16-bit 相位码全枚举；链：整数 bit-true 轨迹 | FloPoCo、DDS 杂散模型、固定结构 WLO | `certfit/cordic_sincos` 成熟 |
| A2 | DDC / DUC 链 | E/C | NCO → CMUL → FIR → 抽取；DUC 为反向多速率链 | 链：EVM、alias、ACLR；吞吐/PPA | LTI filter/rate changer 的 noble identity、polyphase、direct ↔ 3-mult CMUL；须冻结边界和 rate convention | A1/A3/CMUL 的实现类、舍入位置、字长、饱和策略 | float64 reference + 整数 bit-true chain；冻结场景集，统计量另报不确定性 | 手工 DDC/DUC、`fxpopt` 式固定结构 WLO、分阶段优化 | `chains/ddc` 已有；评价器缺陷登记在案 |
| A3 | FIR 成形 / 匹配 / 抽取 / 内插 | E | `y[n]=Σh[k]x[n-k]`，并显式声明输入/输出 rate | kernel：频响、输出误差；链：alias、EVM | 系数对称、直接/转置、polyphase、FFT convolution；等价需冻结边界与延迟 | 系数量化、SPT/MCM、tap pruning、内部 trunc/round | bit-true impulse/轨迹；频域恒等检查；一般序列状态空间不做全枚举 | 专用 FIR WLO/MCM、GNU Radio PFB、SPIRAL、FloPoCo/厂商 FIR IP | DDC 中仅有固定 FIR |
| A4 | PFB channelizer | E | prototype filter 的多相分解后接 FFT，输出多个子带 | 子带泄漏、幅相误差、EVM、吞吐 | polyphase/commutator/FFT 分解，须冻结 framing 与边界 | prototype/系数量化、FFT 缩放、内部字长 | float reference + bit-true frame/stream；多音与阻塞场景 | GNU Radio PFB、标准 polyphase channelizer、FFT IP | 无 |
| A5 | CIC + 补偿滤波 | E（结构空间较窄） | `N` 级 integrator → rate change → `N` 级 comb | alias、通带下垂、overflow、EVM | integrator/comb 的速率重排；差分延迟恒等式 | Hogenauer truncation、级宽、补偿 FIR | bit-true stateful stream + 解析频响/增长界 | Hogenauer 方法、固定结构 WLO、标准 CIC IP | 无 |
| A6 | 分数重采样 / 定时插值 | E/C | `y[m]=Σx[n]h(mT_o-nT_i)`；显式相位状态 | 定时 EVM、alias、群时延 | Farrow/多项式/多相 FIR 的受限等价分解 | Lagrange 阶数、相位表、系数字长、插值器结构 | float resampler + bit-true stateful trace；扫相位与 rate ratio | Farrow、多相 resampler、GNU Radio/标准库实现 | 无 |
| A7 | 幅度 / `sqrt` | E/C | `r=sqrt(I²+Q²)`，或在 `max/min` 归一化域计算 | kernel：绝对/相对误差；链：AGC/EVM | 交换/符号对称；当 `max>0` 时 `r=max·sqrt(1+(min/max)²)`，`max=0` 单列 | CORDIC vectoring、square+sqrt（NR/LUT）、`alpha·max+beta·min` | 小位宽二维全枚举；16+16-bit 全域为 `2^32`，需对称约简、最坏界或分层/对抗测试，不能写成直接全枚举 | FloPoCo、标准 `hypot`/CORDIC、最小最大近似文献 | 无 |
| A8 | 倒数 / 归一化 | E/C | `y=1/x`，`x=2^k m` 后 `1/x=2^-k/m` | kernel：相对误差/ULP、异常域；链：均衡 EVM | normalization、指数搬移、符号分离；定义域排除 `x=0` | LUT+插值、Newton–Raphson、Goldschmidt、分段多项式 | 正输入 16-bit 可全枚举；单列 `x=0`、符号和饱和策略 | FloPoCo、标准 divider/reciprocal、Sollya/多项式生成 | 无 |
| A9 | `log` / dB（RSSI、AGC） | E/C | `x=2^k m`，`log x=k·log2+log m`，定义域 `x>0` | kernel：绝对 dB 误差；链：RSSI/AGC 稳态与瞬态 | normalization、base conversion、分段域映射 | LUT、分段 Poly、log-CORDIC | 正输入 16-bit 可全枚举；`0`、动态范围和输出单位须冻结 | FloPoCo、Sollya/分段多项式、标准 log IP | 无 |
| A10 | AGC 环 | C | 检测器、环路滤波和可变增益的状态递推 | 建立时间、超调、稳态误差、EVM、饱和恢复 | 冻结环路结构后可做线性段等价化；顶层检测器/控制律不等价 | A7–A9 实现、环路增益、更新率、字长、限幅 | float closed-loop reference + bit-true trajectory；幅度阶跃/衰落场景 | 标准 AGC 设计、固定结构 WLO、Model-Based Design 流程 | 无 |

### B. 发射机非线性补偿

| # | 算子 | 标签 | formula / dataflow | contract | exact identities | approx realizations | reference / evaluator | strong baseline | 仓库状态 |
|---|---|---|---|---|---|---|---|---|---|
| B1 | CFR | C | OFDM 波形经 clipping/filtering、peak cancellation、tone reservation 或 ACE | PAPR–EVM–ACLR，系统/波形层 | 各固定算法内部的 FFT、滤波和线性代数恒等式 | clipping level、迭代数、峰值核、保留 tone、字长 | float waveform reference + bit-true frame；冻结调制、资源映射和过采样率 | 标准 clipping+filtering、peak cancellation、tone reservation/ACE | 无 |
| B2 | DPD | C | 预失真器与带记忆 PA 串联，目标逼近线性端到端映射 | NMSE、ACLR、EVM、稳定性，系统层 | 固定模型内部的多项式提因子/卷积重排 | memory polynomial、GMP、LUT、Volterra，阶数/记忆深度/字长 | 冻结 PA 模型和辨识/验证数据；bit-true DPD + 独立波形测试 | memory polynomial/GMP、商用/开源 DPD 流程 | 无；独立大课题 |

### C. OFDM / 变换

| # | 算子 | 标签 | formula / dataflow | contract | exact identities | approx realizations | reference / evaluator | strong baseline | 仓库状态 |
|---|---|---|---|---|---|---|---|---|---|
| C1 | FFT / IFFT、DFT-s-OFDM 预编码 | E（旗舰候选） | `X[k]=Σx[n]W_N^{nk}`；声明 streaming/burst 与缩放 | kernel：SQNR/overflow；链：EVM；PPA/吞吐 | Cooley–Tukey、radix-2/4、split-radix、R2²SDF、twiddle 对称 | 级间缩放、twiddle LUT/CORDIC/Poly、每级 trunc/round | double DFT + bit-true frame/stream；小 `N,W` 全枚举仅作单测 | **SPIRAL**、厂商/开源 FFT IP、定点 FFT WLO | 未实现 |
| C2 | CP 插入/去除、资源映射、索引置换 | X | 序列复制、删除与确定性置换 | exact functional equivalence、吞吐 | 置换/地址生成等价化 | 无合法数值近似 | 全输入小规模对拍或形式等价 | 参考 RTL/软件映射 | 无 |

### D. 同步与跟踪

| # | 算子 | 标签 | formula / dataflow | contract | exact identities | approx realizations | reference / evaluator | strong baseline | 仓库状态 |
|---|---|---|---|---|---|---|---|---|---|
| D1 | 前导/PSS/SSS 相关、定时捕获 | E/C | `r[k]=Σx[n]p*[n-k]`，再做峰值/门限判决 | kernel：相关误差；系统：Pd/Pfa、定时 RMSE | direct ↔ FFT correlation 仅在 zero-padding/circular convention 一致时等价；分块求和可等价 | partial/segmented correlation、低精度 FFT、早停、门限近似 | bit-true correlator + 冻结信道/频偏/噪声分布的检测 Monte Carlo；两层指标分开报 | 直接相关、FFT 相关、标准同步器 | 无 |
| D2 | CFO / 相位估计与校正 | E/C | 自相关相位、FFT 峰值或环路估计后接 NCO 校正 | CFO/phase RMSE、捕获范围、EVM、锁定时间 | 固定 estimator 内的相关/FFT/atan2 恒等式 | estimator 选择、atan2/NCO 实现、窗口/插值/字长 | float estimator + bit-true trace；冻结频偏、信道、SNR 分布 | 自相关估计、FFT peak、PLL/Costas 标准实现 | 无 |
| D3 | 定时/载波环（Gardner、M&M、Costas、PFB clock sync） | C | 非线性误差检测器 + 环路滤波器 + NCO/插值器状态递推 | 捕获/锁定、jitter、cycle slip、EVM、稳定性 | 冻结环路后局部线性化或滤波器恒等式 | 检测器/环型、带宽、更新率、字长、限幅 | float closed-loop + bit-true long trace；动态漂移与突变场景 | 各类标准同步环、GNU Radio 实现 | 无；后期系统族 |

**D1 边界**：相关值的 direct/FFT 实现属于 E，但 partial correlation、检测器与门限策略改变统计量，
属于 C。目录保留 `E/C`，实验必须分别评价算术误差和 Pd/Pfa，不能用相关 MSE 代替检测契约。

### E. 信道估计、均衡、MIMO

| # | 算子 | 标签 | formula / dataflow | contract | exact identities | approx realizations | reference / evaluator | strong baseline | 仓库状态 |
|---|---|---|---|---|---|---|---|---|---|
| E1 | LS / LMMSE 信道估计 + 插值/去噪 | C（内部 E） | pilot observation → LS/LMMSE estimate → time/frequency interpolation | NMSE、EVM、BER；冻结 channel/noise prior | 固定 LS 或 LMMSE 内的矩阵分解、DFT/卷积与插值重排 | LS↔LMMSE、linear/spline/DFT denoise 属契约层替代；矩阵核/字长为 lowering | double reference + bit-true kernel；冻结信道模型后做独立 Monte Carlo | LS、LMMSE、DFT denoising、标准插值器 | 无 |
| E2 | ZF / MMSE / DFE / FDE 均衡 | C（内部 E） | `x̂=W(H)y` 或带反馈/FFT 的等化数据流 | EVM、post-equalization SINR、BER、稳定性 | 固定算法内的 inverse/solve、QR/Cholesky、FFT convolution 恒等式 | ZF/MMSE/DFE/FDE 选择，A8 reciprocal、矩阵核、字长 | double linear algebra + bit-true frame；信道/噪声场景集 | LAPACK/软件 reference、QR/Cholesky IP、标准 equalizer | 无 |
| E3 | MIMO 检测 | C | MIMO observation → linear、SIC、tree-search 或 message-passing detector | BER/BLER、吞吐、尾延迟 | 固定 detector 内的 QR、metric 更新与线性代数恒等式 | ZF/MMSE、QR/SIC、K-best、sphere；候选宽度/剪枝/字长 | double detector + bit-true frame；冻结 MIMO/channel/SNR 分布 | linear detector、K-best/sphere decoder、专用文献 RTL | 无；独立大课题 |
| E4 | 预编码 / 波束成形 | C（内部 E） | channel/weight → matrix-vector precoding 或相位旋转 | EVM、阵列增益、leakage、功率约束 | 固定方法内的 QR/Cholesky、矩阵乘与相位对称 | MRT/ZF/MMSE/码本、相位量化、矩阵核/字长 | double matrix reference + bit-true symbol/frame；信道集合 | 标准 MRT/ZF/MMSE、矩阵/旋转 IP | 无 |

**E1 边界**：LS、LMMSE、插值和 DFT 去噪并非同一实数函数，顶层必须按 C 评价；只有冻结某个
estimator 后，其矩阵/卷积/插值实现才进入 E。因此标签写 `C（内部 E）`，不使用对称的 `E/C`。

### F. 解调与译码

| # | 算子 | 标签 | formula / dataflow | contract | exact identities | approx realizations | reference / evaluator | strong baseline | 仓库状态 |
|---|---|---|---|---|---|---|---|---|---|
| F1 | 软解调 / LLR | E/C | constellation likelihood → per-bit log-likelihood | GMI、BER/BLER；LLR MSE 仅作诊断 | Jacobian-log、对称性、共同项消除 | max-log、分段 correction、LUT、低精度 distance | high-precision reference + bit-true vector；冻结信道/SNR，报告重尾稳定性 | exact log-MAP、max-log、标准 demapper | `llr_64qam` 已有；重尾与 RTL 缺陷登记在案 |
| F2 | 硬判决 / 映射 | X | 最近点/阈值判决与确定性 bit mapping | exact decision/mapping、吞吐 | 比较树和对称映射等价化 | 无合法连续精度预算；若引入近似判决则另建 C 任务 | 全输入小规模对拍或形式等价 | reference mapper/demapper | 部分相关组件存在 |
| F3 | LDPC 译码 | C | 校验图上的 variable/check-node message update 与迭代调度 | BER/FER、迭代数、吞吐、尾延迟 | 固定算法内部的 message reduction 和调度等价条件 | SPA、min-sum、normalized/offset min-sum、layered/flooding、量化 | float/fixed decoder + codeword Monte Carlo；冻结 code/channel/停止条件 | 标准 SPA/min-sum、5G LDPC reference/IP | 无；独立系统族 |
| F4 | Polar 译码 | C | factor graph/tree 上的 SC/SCL/SCF/BP | BLER、list size、时延、吞吐 | 固定 decoder 内的树/图调度等价条件 | SC/SCL/SCF/BP、list/pruning、LLR 量化 | software reference + bit-true decoder；冻结 code/channel | 标准 Polar decoder 与公开 RTL | 无；独立系统族 |
| F5 | Turbo / 卷积码 / Viterbi | C | trellis metric update、窗口与迭代调度 | BER/BLER、迭代/窗口、时延 | 固定算法内的 metric normalization 与 reduction 恒等式 | MAP/max-log-MAP/constant-log-MAP、窗口/调度/量化 | software reference + bit-true trellis/decoder；冻结 code/channel | BCJR/Viterbi 标准实现与公开 RTL | 无 |
| F6 | 加扰、CRC、速率匹配、交织 | X | GF(2) 线性递推、CRC、多重集合选择与置换 | exact functional equivalence、吞吐 | GF(2) 矩阵幂、并行展开、置换合成 | 无合法数值近似 | 全输入小规模对拍、形式等价或标准测试向量 | 标准参考实现 | `scrambler` 未实现 |

---

## 3. 审核结论与初步优先级

1. 三类（E / C / X）在论文中并列展示。目录覆盖面不等于同一方法覆盖面；C/X 条目用于明确方法边界、
   组合接口和后续扩展。
2. 每个条目在六个字段写齐之前，不进入实验排期；当前表已给出字段草案，真正开工前还要冻结任务卡。
3. 仓库状态只记录可核查事实；未实现项保持“无”或写明已登记债务。
4. 主实验候选按 gate readiness 与论文辨识力排序：

   1. **A1 NCO/DDS**：现有结构类和整数域 evaluator 最成熟，先用于验证整套 term language、lowering、
      强基线和搜索对照；正式结果仍以评价协议通过为前提。
   2. **A8 reciprocal**：一维有限域可全枚举，LUT/NR/Goldschmidt/Poly 是真实不同实现类，适合作第二个
      kernel 族；主要新增工作是 RTL lowering、PPA 与 FloPoCo/标准 divider 基线。
   3. **A3 FIR/decimator**：提供最关键的线性、多速率与状态证据；只有在至少实现 direct/polyphase/FFT
      convolution 中两个真实类后过 gate，不能以单个固定 FIR 充数。
   4. **A2 DDC**：作为 A1+A3+CMUL 的系统集成与跨-kernel 契约载体；它不是自动成立的独立 kernel
      贡献，且须先完成评价器前置修复和场景冻结。
   5. **C1 FFT**：最能检验 EqSat 的结构价值，也有 SPIRAL 这一强对手；结构空间、流式微架构与基线
      成本最大，作为高价值挑战族而非最先实现项。
   6. **A7/A9**：保留为第三类数学函数候选。A7 的 16+16-bit 二维全枚举不可行；A9 需先冻结 `x=0`、
      动态范围和 dB 单位。完成 evaluator 设计后再与 C1 比较投入产出。

   **D1/E1 暂不进入首批实现**：它们能检验系统契约，但统计场景、检测/信道模型和 top-level C 选择会
   同时引入多个变量。待 A1/A3/A8 把基础机制跑通后，再分别作为同步与估计方向的外部有效性任务。
5. B2、D3、E3、F3–F5 均可形成独立论文规模；目录保留接口和契约，但不与基础方法验证混成一个实验。
