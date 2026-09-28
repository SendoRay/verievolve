# 文献核对与差距分析（LIT_GAP）

日期：2026-09-27（所有链接均于当日访问）
用途：核对 RESEARCH_PLAN.md §2 的 R1–R8 直接相关文献，追踪 §2.2 末尾要求补查的四类先例，形成"已有方法—当前限制—拟验证差距"对照，检验研究空缺假设。
核对深度标注约定：
- **全文级**：下载原文 PDF 并精读正文主体（算法、流程、实验）。
- **部分正文级**：读原文 HTML/局部章节或经原文页面问答式核实关键段落。
- **摘要级**：经出版页/Semantic Scholar/检索摘要核实元数据与摘要，原文未精读。
- **引用网络级**：经二手来源（综述、教材、检索摘要）交叉确认出处与结论，原文未直接获取。

---

## 1. R1–R8 核对结果

### 1.1 汇总表

| 编号 | 文献 | 访问链接（2026-09-27 可用） | 本次核对深度 | 核对结论 |
|---|---|---|---|---|
| R1 | Han & Evans 2006，字长敏感度搜索 | [出版页](https://doi.org/10.1155/ASP/2006/92849)、[PDF](https://link.springer.com/content/pdf/10.1155/ASP/2006/92849.pdf)（EURASIP JASP, Article 92849, 14 页） | 大部分全文级（读 1–10/14 页；结果讨论与结论尾页未读） | 与计划描述一致；算法细节与两个无线案例规模已核实（见 1.2） |
| R2 | Menard 等 2012，精度约束 HLS | [DOI 页](https://doi.org/10.1155/2012/906350)、[HAL 记录](https://inria.hal.science/hal-00742144v1)（Wiley/HAL 全文均被反爬拦截） | 摘要级（Semantic Scholar 摘要 + HAL 元数据） | 联合优化流程与解析评估的**具体机制待精读**；摘要确认"迭代 HLS↔字长优化 + 解析精度评估 + 面积省 10–28%" |
| R3 | Li 等 DAC 2015 | [作者 PDF](https://www.ece.umn.edu/~sachin/conf/dac15-cl.pdf)、[DOI](https://doi.org/10.1145/2744769.2744883) | 全文级（正文 6 页全部读取；证书问题绕过后下载成功，此前"直接打开失败"已解决） | 与计划描述一致且更具体：MMKP 精度选择 + 迭代 list scheduling + 方差/误差敏感度模型 |
| R4 | Lee 等 DATE 2017 | [作者 PDF](https://slam.ece.utexas.edu/pubs/date17.AHLS.pdf) | 全文级（6 页全部读取） | 与计划描述一致；误差依赖=均值+方差联合传播、操作消除的链式效应；标量统计口径 |
| R5 | SPIRAL 2018 | [项目 PDF](https://www.spiral.net/doc/papers/SPIRAL_IEEE_2018.pdf)（该 PDF 为 10 页版） | 部分正文级（§I–III 已读；§IV–VII 综合流程与验证细节待精读） | 公式(OL)–算法(breakdown rules)–架构(数据流片段)统一框架已核实 |
| R6 | FloPoCo 4.1 手册 | [官方手册](https://flopoco.org/operators_4.1.html) | 部分正文级（条目逐项核对） | FixSinCos/CordicSinCos/FixAtan2 能力已核实；FixSin/FixCos 独立条目**不在 4.1 手册中** |
| R7 | ROVER 2024 | [arXiv:2406.12421](https://arxiv.org/abs/2406.12421)、[正文](https://arxiv.org/html/2406.12421v1) | 部分正文级（HTML 全文问答式核实关键章节） | 位宽重写条件生成、验证链、成本模型、基准规模均已核实 |
| R8 | ASPEN MLCAD 2025 | [作者 PDF](https://www.csl.cornell.edu/~zhiruz/pdfs/aspen-mlcad2025.pdf)、[NVIDIA 页](https://research.nvidia.com/labs/electronic-design-automation/publication/deng2025aspen/) | 全文级（7 页全部读取） | 规则提议(Z3 proof)→规则选择→饱和→提取→综合→PPA 反馈回路已核实 |

### 1.2 各篇已核实内容（本次判定依据）

**R1 Han & Evans 2006（已核实）**
- 算法：提出 **complexity-and-distortion measure (CDM) 搜索**。目标函数 `f_cd(w) = α_c·c_n(w) + α_d·d_n(w)`，其中 `c_n`、`d_n` 分别是归一化的硬件复杂度函数与失真（系统输出误差）函数，`α_c + α_d = 1`；更新方向 `ξ_CDM = −(α_c·∇c_n + α_d·∇d_n)`（式 (22)(26)(27)）。敏感度同时用两条通道（此前工作只用其一：local/evolutionary 用复杂度敏感度，sequential/"Max-1"/preplanned 用误差敏感度），套在 sequential 或 preplanned 搜索框架内执行最陡下降式更新。
- 失真函数取**系统输出级误差指标**：CDMA 用输出 SNR（要求 ≥0.8 dB）+FER<0.03；OFDM 用 BER≤5×10⁻³；IIR 用 MSE≤0.1。即"系统输出误差驱动字长"在该论文中已经是事实标准。
- 无线案例规模：(a) **CDMA 数字解调器**，5 个字长变量 `{B_i, B_fc, B_m, B_fi, B_fc}`（输入/载波/乘法器输出/滤波系数/滤波输出），Rake 接收链；complete search 283,920 次仿真（约 5 年）不可行，exhaustive 56 次、sequential 20 次、preplanned 5 次；CDM 框架比 local search 少 64%–91% 试验。(b) **固定宽带无线接入 OFDM 解调器**（Stanford Interim 信道模型 3，SNR 20 dB，256 点 FFT），4 个字长变量（FFT 输入、均衡器右输入、信道估计器输入、均衡器上输入）；顺序/CDM 搜索 15 次进入可行域，local search 需 38 次；CDM 用 local search **1/4 时间**找到最优。(c) 7 抽头 IIR（MSE 口径）。
- 非凸性：论文明确指出字长优化空间非凸、存在多个可行局部最优（§7），preplanned 与 sequential 收敛到不同点，作者以此讨论 robustness；这是"局部误差排序可能翻转"的早期经验证据，但**未被作为研究对象建模**。
- 待精读：第 11–14 页（剩余结果讨论、结论）。

**R2 Menard 等 2012（摘要级，待精读）**
- 已核实（Semantic Scholar 摘要）：方法面向浮点算法到 FPGA/ASIC 定点实现的自动化；**在 HLS 与字长优化之间迭代**（HLS 需要算子字长做分配/调度/绑定，字长优化需要调度/绑定信息）；精度评估采用**解析方法而非定点仿真**，"大幅减少优化时间"；信号处理案例上平均架构面积比经典方法低 **10%–28%**。作者：D. Menard, N. Hervé, O. Sentieys, H.-N. Nguyen（IRISA/INRIA CAIRN）。
- 待精读：解析精度评估的具体形式（其团队路线通常为 L1/仿射算术与解析 SNR 传播，本次未从原文确认）、迭代循环的终止与收敛控制、案例规模。Wiley 与 HAL 全文均被反爬拦截；可从作者机构页或图书馆渠道获取后再核。

**R3 Li 等 DAC 2015（已核实）**
- 流程：**KILS = Knapsack/MMKP 精度优化 + 迭代近似感知 list scheduling**。每个操作 `ω` 有多候选实现集合 `I_ω`（不同近似算子与精度/位宽），先解多选择背包（ILP，CPLEX）得到满足输出方差约束的最 economical 实现，再做迭代 list scheduling 完成 FU 分配/绑定；绑定允许**非对称兼容**（低精度操作可绑到高精度 FU，反之不行）。
- 误差模型：方差模型。误差经线性组合传播，输出方差含协方差项；作者**显式丢弃协方差**（假设各操作误差独立，仅同源双分支例外），代之以 **error sensitivity (ES)**：`ν(o) = Σ ES²_{ω,o}·ν(ε_ω)`，ES 经 DFS 传播，用于捕获**重汇聚路径上误差相消的一阶效应**（论文 Figure 1 专门讨论近似加法器误差沿两条路径相消）。解析方差与 Verilog 蒙特卡洛 MSE 相关系数 0.94、数值差约 10%。
- 目标与约束：泄漏能耗最小，时延约束 + 输出方差约束。基准 MediaBench（fir/adpcm/sdd/g721/pegwit/ivk/mov），10–100 节点。结果：KILS 比常规 list scheduling 省能 16%（ILP 40%），KILS 比 ILP 快约一个数量级。自称第一个把近似算子选择与调度/分配/绑定联合的工作。
- 对本课题的含义：**"近似算子选择+位宽+调度绑定"的联合已在此完成**；但其误差是标量方差（无频域形态、无多速率）、DFG 固定（无算法结构级候选）、约束是输出方差而非通信质量。

**R4 Lee 等 DATE 2017（已核实）**
- 流程：AHLS = 精度缩放（逐点 bit rounding + 操作消除）× 电压缩放 × 调度/绑定的联合。前端一次 C 仿真收集每操作的均值/方差/误差功率/零位数目；质量估计按 **误差生成（舍入误差均值 0、方差 1/12·2^{2s}）+ 误差传播**（论文 Table II：加法/乘法的传播公式，含输入被近似为零的特殊情形）在 CDFG 上传播；能耗 = 开关活动面积比例模型 × 电压-时延二次模型（HSPICE 特征化 AC 库）。
- 误差依赖处理：与 R3 丢弃协方差不同，本文**同时传播均值与方差并跟踪误差间的相互依赖**（含操作消除引发的下游误差清零与链式周期缩减，论文 Fig. 3 三类 case）；但传播仍是标量统计量（error power），**没有频谱信息，也没有多速率维度**。
- 求解：按 CDFG BFS 顺序对每个决策变量枚举候选、可行性剪枝 + 支配剪枝，只做一次仿真；比穷举快 1400×、能耗差 0.1%；比只考虑开关活动的方案最多多 24.5% 节能（来自时钟周期缩减×电压缩放联动）。
- 验证：SNR 估计与综合后仿真相差 <6 dB（低 SNR 处偏差更大），作者事后加 1–2 dB 余量——这本身就是"解析质量模型在系统边界处变粗糙"的证据。基准：MediaBench + SD-VBS（adct/gblur/fft/com2d），32nm。

**R5 SPIRAL 2018（部分正文级）**
- 已核实：三个抽象层——**OL（operator language）**：参数化数学算子（DFT、卷积、MMM、多项式求值、范数等 50+ 线性变换算子，含非线性）；**算法 = breakdown rules 重写规则树**（200+ 条规则；DFT₈ 的规则树展开示例、SAR/multigrid 的完整规则集见文中 Table 1/2）；**架构 = 可执行数据流片段 + 语法**。规格-算法-架构处于统一形式框架（Fig. 1），搜索 = 重写系统 + 约束求解/autotuning；正确性可形式证明（重写保语义）。目标域含 SDR、软件定义无线电、机器人车辆控制。
- 待精读：§IV–VII（term rewriting 与 DSL 编译器交互、验证方法、开源版本）。
- 对本课题的含义：SPIRAL 组织"公式→算法→架构"搜索的方式是算法级 DSE 的最强组织先例；但它的优化目标是运行时间/性能，**没有定点误差维度，也没有通信质量约束**——SPIRAL 论文自身把"正确性保证"界定为重写语义等价，不含数值精度语义。

**R6 FloPoCo 4.1（已核实条目）**
- **FixSinCos**：计算 `(1−2^(−w))·sin(πx)` 与对应 cos，`x∈[−1,1)`；唯一精度参数 `lsb`（输入与输出共用 LSB 权重）；实现为**表+乘法器**。
- **CordicSinCos**：同函数与范围；参数 `lsb` 与可选 `reducedIterations`（减少迭代次数、代价是额外两次乘法——显式时延/面积折中旋钮）；经典 CORDIC 移加实现，承诺**最后一比特精确、成本最小化**。
- **FixAtan2**：`atan(x/y)`，输出按 `a=(angle/π)∈[−1,1)` 缩放；参数 `lsb` 与 `method 0–12`：InvMultAtan 多项式 0–7 阶、CORDIC(8)、带缩放 CORDIC(9)、surface 近似(10)、Taylor 一/二阶(11/12)。
- 注意：`FixSin`/`FixCos`/`FixBySum` **不在 4.1 手册条目中**（后续版本的条目需另行固定版本核对）。复现时必须锁定具体版本与目标（FloPoCo 是频率驱动的流水线化生成器，4.1 手册条目未给出频率-面积数字）。

**R7 ROVER 2024（部分正文级，已核实关键机制）**
- 位宽处理：中间语言 **VeriLang** 给每个算子标注位宽与符号参数；**单条参数化重写规则覆盖多种位宽/符号**（区别于 IMpress 把类型烘焙进算子名）。重写表示为三元组 `(cond, term, term)`，e-matching 实例化自由变量后检查条件。
- 条件生成与验证：枚举符号×位宽 1–8（关联律实例 |M|=2048），两侧转 Verilog 后**逐一交给商业 RTL 等价性检查器（EC）**，结果表用决策树分类器精确拟合后转 SOP 布尔条件；**位宽 >8 的有效性靠外推，是未证明假设**；若外推出错，后端验证兜底。端到端验证用 **egg 的证明链**：相邻设计逐对 EC + 逐信号 lemma（Media Kernel 与 Shift Mult 在数秒内证明，直接输入-输出 EC 数小时无结论）。
- 成本与后端：理论门数成本模型（prefix adder、Booth Radix-4 乘法器、log tree、mux tree 等**固定微架构假设**）；提取为 ILP（CBC，120 s 超时）；TSMC 5nm 商业综合。基准：Media Kernel −50% 面积、FIR 内核 −22%、Shift Mult −63%；**参数化 3 抽头 FIR（位宽 4–64）在 3 种架构间选择，面积最多 −30%、平均 −15%**。局限：复杂常量乘法仍由专业 MCM 工具胜出、ILP 提取是瓶颈、综合噪声实测可达 15% 面积。
- 对本课题的含义：ROVER 的重写全在**精确等价**语义内（位宽重写不改数值语义或其条件保证等价），**没有近似/误差语义**——计划中"近似结构变化要独立定义误差语义"的定位得到确认；其"参数化 FIR 跨位宽选架构"是与课题二最接近的案例，但候选集只有 3 种微架构、无误差约束。

**R8 ASPEN MLCAD 2025（已核实）**
- 流程：(1) **规则提议 agent**——输入 Verilog、初始规则（Table I：交换/结合/恒等/分配/2 的幂乘/奇偶常量乘/移位化简/Estin 变换/分配因式/MUXAR 等）与 23 个示例 Z3 proof 程序，提出设计特定新规则并为每条生成 Z3 证明，**验证通过才入池**；(2) **规则选择 agent**——结合探索历史与过往 PPA 选 critical 规则子集（过多/过少规则都损害效果）；(3) egglog 饱和 → 提取（e-node 成本）→ Opt Verilog → 商业综合（OpenPath qck-4.1，时钟 250 MHz–5 GHz 扫描）→ **PPA 反馈 agent** 用 K-way 图划分+序列化文本化把 netlist 指标映射回 e-node，更新 e-node 成本 → 迭代（Algorithm 1 两层循环）；(4) **最终对 Pareto 前沿所有设计点做商业 RTL 等价检查**。
- 结果：7 个开源基准（FIR/DCT/Polynomial/MCM 变体）；平均面积比商业综合基线 −24.23%、比 ROVER −16.51%；时延 −12.45%/−6.65%。消融：**去掉 PPA 反馈最差**（FIR 面积反而 −24.4% 恶化），说明代理成本模型误导性真实存在。
- 对本课题的含义：LLM+重写+综合反馈组合已被占据（与计划判断一致）；其反馈回路修的是 **PPA 代理模型误差**，不涉及数值误差语义——两者正交。

---

## 2. 四类关键先例追踪

### 2.1 多速率系统量化误差分析

| 工作 | 链接（2026-09-27 访问） | 深度 | 内容摘要 |
|---|---|---|---|
| E. B. Hogenauer, *An Economical Class of Digital Filters for Decimation and Interpolation*, IEEE Trans. ASSP, ASSP-29(2):155–162, 1981 | [IEEE Xplore 1163535](https://ieeexplore.ieee.org/document/1163535)、[引文背景](https://www.dsprelated.com/showarticle/160.php) | 引用网络级（原文未精读） | CIC 滤波器奠基论文：无乘法、仅加法的抽取/内插结构；内部字长按约 `N·log₂(RM)` 增长；**核心贡献之一是把末级截断/舍入误差按各级分配（register pruning）**，给出每级最大误差幅度界，在保证输出误差的前提下最小化寄存器宽度。这是"抽取结构内字长-误差联合决策"的最早系统性先例。 |
| U. Meyer-Bäse 等， *Cost-effective Hogenauer Cascaded Integrator Comb Filter*, 2005（FPL 系） | [作者侧 PDF](https://senna.ugr.es) | 摘要级 | 对 CIC 的量化误差做再分析：CSA 实现下只需比 Hogenauer 二进制补码分析多约 1 个保护位；讨论截断分配对 ENOB 的实际影响。 |
| A. V. Oppenheim, C. J. Weinstein, *Effects of Finite Register Length in Digital Filtering and the Fast Fourier Transform*, Proc. IEEE 60(8):957–976, 1972 | [出版页](https://ieeexplore.ieee.org/document/1052200)（付费墙；出处经 [Butterweck 1988 综述](https://firmware-developments.com/WEB/DOC/REF/FiniteWordlengthFilterEindhoven.pdf) 等二手来源核实） | 引用网络级 | 定点滤波/FFT 有限寄存器长度效应的系统分析源头：量化噪声作为随机过程经 LTI 系统、输出噪声谱由**噪声传递函数（QNTF）频域加权**决定。这是"误差功率→频带加权"经典模型的出处，即研究计划 B5 基线的理论根源。 |
| CIC 剪枝工程化与后续（DSPRelated 2012 pruning 工具文、专利 CN102629862B 高斯信号 CIC 字长优化） | [DSPRelated](https://www.dsprelated.com)、[专利](https://patents.google.com/patent/CN102629862B/en) | 摘要级 | Hogenauer 截断分配方法被工程化为标准工具；后续工作主要针对具体结构（剪枝、保护位、输入分布）改良，**不涉及跨算法候选筛选**。 |

小结：多速率量化误差的**结构内**分析（CIC 字长增长、截断分配、抽取滤波器噪声）成熟；误差经 LTI 后级的频域加权是 1972 年级经典知识。但均为**固定结构、固定算法**框架：没有文献在这些模型之上做"算法候选集合"层面的筛选或排序。

### 2.2 NCO/DDS 相位截断杂散建模与优化

| 工作 | 链接（2026-09-27 访问） | 深度 | 内容摘要 |
|---|---|---|---|
| H. T. Nicholas III, H. Samueli, *An Analysis of the Output Spectrum of Direct Digital Frequency Synthesizers in the Presence of Phase-Accumulator Truncation*, 41st AFCS, 1987 | [Semantic Scholar 条目](https://www.semanticscholar.org/paper/An-Analysis-of-the-Output-Spectrum-of-Direct-in-the-Nicholas-Samueli/6566d5e90e8390aa2270e43256c4433136774bb4) | 摘要级 | 相位累加器低位截断后相位误差序列产生的**离散杂散的精确位置与电平**分析；最坏杂散电平与保留位数的 −6.02·B dBc 关系的来源。 |
| H. T. Nicholas III, H. Samueli, B. Kim, *The Optimization of a Direct Digital Synthesizer Performance in the Presence of Finite Word Length Effects*, 42nd AFCS, 1988 | [Semantic Scholar（同上作者页）](https://scholar.google.com/citations?user=Kv7032cAAAAJ) | 摘要级 | **Nicholas 架构**：修改相位累加器使误差序列周期化，把最坏杂散钳制到约 −6.02·B + 3.92 dBc；与正弦表压缩联合优化 DDS 参数。 |
| D. A. Sunderland 等， *CMOS/SOS Frequency Synthesizer LSI Circuit for Spread Spectrum Communications*, IEEE JSSC 19(4), 1984 | [IEEE JSSC 出版页](https://ieeexplore.ieee.org/document/1052166) | 摘要级 | 单芯片 DDS：用三角恒等式把相位字分解为粗/细 ROM 的**查找表压缩**技术，是 LUT 压缩一系工作的源头。 |
| A. M. Samueli, H. T. Nicholas III, *A 150-MHz Direct Digital Frequency Synthesizer in 1.25-µm CMOS with −90-dBc Spurious Performance*, IEEE JSSC 26(12), 1991 | [IEEE JSSC](https://ieeexplore.ieee.org/document/104988)（出处经 [Oregon State 学位论文引用](https://ir.library.oregonstate.edu) 核实） | 摘要级 | 上述分析+压缩+**相位抖动（dither）**的完整芯片实例：dither 把相关杂散随机化为宽谱噪声，实测 −90 dBc。 |

小结：NCO/DDS 的杂散建模是**极成熟**的：截断杂散谱线位置/电平、最坏情况公式、dither 与 LUT 压缩的权衡均有解析与实测结论。对本课题的直接含义：(a) "局部 SQNR 不能描述 NCO 杂散"是 DDS 领域常识，**不能作为课题一的贡献点**；(b) 反而是机会——NCO 模块的误差形态有一阶解析模型可用，可作为"紧凑描述信息"的模块级来源与校准参考；(c) 这些模型都假定固定 DDS 结构与固定下游，未处理"同一 NCO 候选在不同滤波/抽取/场景下的系统级排序变化"。

### 2.3 通信接收机字长/精度优化

| 工作 | 链接（2026-09-27 访问） | 深度 | 内容摘要 |
|---|---|---|---|
| D. Novo 等， *Scenario-based Fixed-Point Data Format Refinement to Reduce Energy and Area Use in Multiprocessor Signal Processing*, DATE 2008 | [ACM DOI](https://dl.acm.org/doi/10.1145/1403375.1403550) | 摘要级 | 按**场景（scenario）**做定点数据格式精化：应用于 2 天线 200+ Mbps OFDM SDR 多处理器实现；定点精化中探索 BER 退化因子，按场景差异分配格式。是"以场景为轴组织定点设计"的最直接先例。 |
| D. Novo 等， *Energy-Efficient MIMO Processing: A Case Study of Opportunistic Run-Time Approximations*, DATE 2014 | [EPFL PDF](https://www.epfl.ch/labs/lap/wp-content/uploads/2018/05/NovoMar14_EnergyEfficientMimoProcessingACaseStudyOfOpportunisticRunTimeApproximations_DATE14.pdf) | 摘要级 | MIMO 处理的运行时机会式近似：以显式 **BER 约束 β** 判定定点/近似配置可行，按运行时条件切换实现以省能。 |
| T.-D. Chiueh, P.-Y. Tsai, *OFDM Baseband Receiver Design for Wireless Communications*, Wiley, 2007 | [样章/PDF（IITM 镜像）](https://www.ee.iitm.ac.in/~giri/pdfs/EE6002/book-tsai.pdf) | 部分正文级（章节引用网络核实） | OFDM 接收机工程教科书：给出接收链各模块小数字长最小化的实践流程（含 FIR/FFT/CORDIC 的定点化经验值），是把 BER/EVM 要求翻译为各模块字长的工程参考。 |
| VIZOR：EVM 作为可调字长 OFDM 接收机的运行时质量指标 | [检索命中（SciSpace 摘要页）](https://scispace.com) | 仅检索命中，**待精读** | EVM 被用作与 BER 同级的 at-speed 规格，驱动可调字长接收机的运行时适配。若成立，"EVM 驱动字长"有运行时先例，须在正式开题前取得原文核对。 |

小结：接收机定点化有明确先例（BER/场景驱动精化、运行时 EVM 驱动适配），共同点：**算法结构固定**，决策变量是各模块字长/舍入模式；"场景"是运行时条件/模式（SNR、激活模式），不是"下游处理结构"这一设计轴。R1 的 CDMA/OFDM 案例亦属此类（见 §1.2）。

### 2.4 层次化/多保真设计空间探索

| 工作 | 链接（2026-09-27 访问） | 深度 | 内容摘要 |
|---|---|---|---|
| H. Ye 等， *ScaleHLS: A Scalable HLS Framework with Multi-level Transformations and Optimizations*, DAC 2022（含扩展版） | [作者 PDF](https://hanchenye.com/assets/pdfs/DAC22_ScaleHLS.pdf)、[DAC'22 扩展](https://hanchenye.com/assets/pdfs/DAC22_ScaleHLS.pdf) | 全文级 | 层次化 MLIR 表示（graph/loop/directive 三层）；DSE 算法 = **DP 把全局优化分解为 loop band 子问题，各自局部 DSE 后层次化合并 Pareto 前沿**（Band1–Band4 合并示例）；子问题间强相关时次优，补 EA 演化。分解轴是**语法结构**（循环层次），不涉及误差或场景语义。PolyBench/Rosetta 上相对原 ScaleHLS 最高 60.9× 加速。 |
| C. Sakhuja, C. Hong, C. Lin 等， *Polaris: Multi-Fidelity Design Space Exploration of Deep Learning Accelerators*, arXiv 2024-12（即计划中 R13） | [arXiv:2412.15548](https://arxiv.org/abs/2412.15548) | 摘要级 | 低保真+高保真模型经迁移学习引导 DLA DSE：35 分钟达到 DOSA 6 小时的设计质量。多保真+迁移是通用 DSE 效率先例（计划已将其列为通用基线，本次再次核实定位）。 |
| Z. Ding 等（UCLA，Jason Cong 组）， *Efficient Task Transfer for HLS DSE*（Active-CEM）, arXiv 2024-08 | [arXiv:2408.13270](https://arxiv.org/abs/2408.13270)、[正文](https://arxiv.org/html/2408.13270v1) | 部分正文级 | 跨 HLS 工具链版本的 DSE 任务迁移：GNN（回归+可行性双头）在旧工具链数据上预训练、新工具链上微调；**工具链不变共享嵌入+工具链私有嵌入**的分解表示；CEM+主动学习校准代理模型。关键实证：**最优设计随工具链显著漂移，因此迁移模型知识而非旧排序**；训练/测试按 40/10/50 划分并有 held-out 程序。 |
| L. Cuyckens 等（TODAES 2022 系，*Efficient HLS DSE for FPGA*：离线特征化+在线探索） | [ACM](https://dl.acm.org/doi/10.1145/3495531) | 摘要级 | 离线算子/选项特征化 + 在线探索的 FPGA HLS DSE 流程，代表"分析模型预筛+在线精确评估"的两层保真组织方式。 |

小结：层次化 DSE（按结构分解）与多保真/迁移（按模型分层）均有成熟先例。与课题三最相关的是 Active-CEM 的实证结论——**旧排序不可复用、须迁移可迁移的知识并主动校准**——这与 H3"分开复用实现特征与场景相关误差影响"方向一致，但它的分解轴是工具链版本，不是场景；且任务内没有数值误差维度。

---

## 3. 已有方法—当前限制—拟验证差距对照

**核心问题的直接回答**：在本次检索与核对范围内，**没有发现已发表工作显式地做"上下文相关的候选筛选"**——即同时满足：(a) 指出并系统测量候选的局部误差排序随下游滤波/抽取/场景配置变化而翻转；(b) 把这一翻转结构作为筛选机制的输入（保留/淘汰规则随上下文参数化）；(c) 在算法结构可变的候选池上运行。各方向的最近邻及其未覆盖部分如下表。

| 已有方法 | 已核实能力 | 当前限制（据原文） | 拟验证差距（对应课题） |
|---|---|---|---|
| R1 Han & Evans 2006：系统输出误差敏感度字长搜索 | 失真函数取系统输出（SNR/BER/MSE）；CDM 双敏感度方向；CDMA 5 变量、OFDM 4 变量案例；承认搜索空间非凸、多局部最优 | 算法固定（无 sin/cos 结构候选池）；搜索是逐变量梯度方向，非候选池筛选/保留机制；敏感度靠重复仿真测量，无紧凑传播表示；单链路配置，未研究下游/场景变化引起的排序变化 | **课题一/二**：候选池（LUT/插值/CORDIC×滤波×复乘）在多下游配置下的筛选关系是否存在、可否用紧凑信息参数化 |
| R2 Menard 等 2012：迭代字长↔HLS + 解析精度评估 | 联合字长优化与调度/绑定；解析评估替代仿真；面积 −10~28% | （摘要级，机制待精读）即便按其团队路线推断：解析误差为标量/L1 统计，无频谱形态；图固定；无多速率；无算法结构选择 | **课题一**：解析评估在"算法结构变化+多速率"下的失效模式；需以 R2 为精度评估基线 |
| R3 Li DAC 2015：近似算子+位宽+调度绑定联合（MMKP+迭代 list scheduling） | 每操作多实现候选；ES 一阶捕获重汇聚误差相消；方差 vs MC 相关系数 0.94 | **显式丢弃协方差**；误差=标量方差，无频域；DFG 固定；约束=输出方差而非 EVM/频谱掩码/速率 | **课题一/二**：协方差、误差频谱与多速率服务率进入约束后的候选排序变化；R3 是联合优化强基线（B4 系） |
| R4 Lee DATE 2017：AHLS 精度×电压×调度联合 | 均值+方差联合传播、操作消除链式效应（处理误差依赖）；1 次仿真；Pareto 接近全搜索 | 标量统计口径；无频谱/多速率；C 语言 DFG、无算法结构候选；SNR 估计在低 SNR 偏差大（作者加余量） | **课题一**：其"传播均值+方差"是误差依赖处理的现存上限，需要比较频带信息相对均值/方差的增量价值 |
| R5 SPIRAL：公式-算法-架构统一搜索 | OL/breakdown rules/架构统一形式框架；重写保语义；目标域含 SDR | 优化目标=运行时间；无数值误差维度；无定点/通信质量约束；正确性=语义等价不含精度 | **课题二**：在算法-架构搜索中加入误差形态与通信质量轴的组织方式；SPIRAL 是算法级 DSE 组织基线 |
| R6 FloPoCo：参数化算术算子生成 | FixSinCos/CordicSinCos/FixAtan2 以 lsb 参数化精度、方法可枚举、last-bit accurate | **算子级**精度-资源权衡；无链路上下文；无系统级质量语义（lsb≠EVM 贡献） | **课题一**：专业生成器候选进入链路后，其算子级精度保证如何映射为系统 EVM——候选池来源与 B0 基线 |
| R7 ROVER：位宽重写+等价验证 | 参数化位宽重写、条件自动生成（枚举+EC+决策树）、egg 证明链、TSMC 5nm 口径；FIR 跨位宽选 3 种架构 | 全部在**精确等价**语义内；无近似/误差语义；成本=理论门数（综合噪声 15%） | **课题二**：近似结构变化需要独立误差语义（计划判断正确）；其验证组织（逐对 EC+lemma）可借鉴到"候选等价于参考函数"的验证 |
| R8 ASPEN：LLM 规则提议+PPA 反馈 | Z3 证明验证新规则；critical 规则选择；PPA 反馈修 e-node 成本（消融证明必要）；等价检查兜底 | 反馈目标=PPA 代理模型误差；无数值误差语义；等价=精确 | **课题五(§5)**：LLM 用途对照——其"代理模型误差反馈"与课题一"误差模型校准"结构同形，可引用为机制先例 |
| Novo DATE 2008：场景化定点精化 | 按场景（运行时模式/条件）分配定点格式；OFDM SDR；探索 BER 退化因子 | 场景=**运行时条件**，非"下游处理结构"设计轴；算法结构固定；逐场景仿真评估，无筛选理论 | **课题一/三**：最接近"上下文相关"字面的先例；须精读其场景定义以划清边界 |
| Hogenauer 1981 + CIC 系：多速率结构内字长-误差决策 | 截断误差按级分配、字长增长界、剪枝 | 结构固定（CIC）；误差口径=每级最大幅度界；不跨算法候选 | **课题一**：抽取级内部已有成熟误差-字长方法，DDC 链中的抽取模块应直接复用而非重新发明 |
| Oppenheim & Weinstein 1972：QNTF 频域加权 | 量化噪声经 LTI 的输出谱=输入谱×|H|² 加权框架 | 固定线性图；白噪声假设；无算法结构变化、无多速率混叠项 | **课题一**：经典频谱加权是 B5 基线；贡献点必须在"结构变化+多速率+场景"下其失效处（计划 §4 已定位，本次核实该定位成立） |
| Nicholas 系 DDS（1987/1988/1991）+Sunderland 1984：杂散解析模型与 NCO 优化 | 截断杂散位置/电平公式、−6.02B+3.92 dBc 界、dither 与 LUT 压缩权衡、芯片实测 | 模块内分析；固定 DDS 结构与下游；无链路级候选筛选 | **课题一**：NCO 误差形态一阶模型可直接作为紧凑信息源；同时警示"SQNR→杂散"问题本身已知 |
| ScaleHLS / Polaris / Active-CEM：层次化与多保真迁移 DSE | 结构分解 DP+Pareto 合并；低保真→高保真迁移；共享/私有嵌入分解；**旧排序不可迁移、须迁移模型** | 分解轴=语法结构/工具链版本；无数值误差维度；无场景显式轴 | **课题三**：H3 的"实现特征 vs 场景相关误差"分解须与此类通用分解显式对照；否则通用方法足够时降级为工程实现（计划已有预案） |

### 3.1 关于"上下文相关候选筛选"的证据链评估

1. **存在性**：未发现任何一篇工作同时满足"算法候选池 + 局部误差排序随下游/场景翻转的系统测量 + 显式利用翻转结构的筛选机制"。
2. **最接近的三类工作及缺口**：
   - R1（系统误差驱动搜索）：系统级误差已进入搜索，但以"逐变量更新方向"形式，且链路、算法、下游全部固定；论文自己承认非凸多局部最优但未研究其结构。
   - Novo DATE08（场景化精化）：场景轴已出现，但场景是运行时模式而非下游处理结构，且无候选池与筛选规则。
   - R3/R4（敏感性/统计传播）：考虑误差相关性（重汇聚相消、均值方差联合传播），但口径为标量统计，无频谱形态、无多速率、无算法结构维度。
3. **必须正面承认的既有知识**（若论文不自觉区分将构成风险）：频域加权噪声模型（Oppenheim & Weinstein 1972 系）、DDS 杂散解析公式（Nicholas 系）、CIC 截断分配（Hogenauer）——三者共同覆盖了"单模块、固定结构"下的误差频域/幅度分析。课题一的可辩护空间被压缩为：**在算法结构可变、多速率组合、场景集合条件下，以紧凑信息实现可靠的候选保留与筛选，并给出其充分条件/失效边界**。这与计划 §4 课题一"拟采用的方法"第 3 条和"必要基线"B5 的自我定位一致，本次检索确认该定位无需修改但需更加严格。

---

## 4. 结论：研究空缺假设是否成立、需收窄或调整之处

### 4.1 总体判断

**研究空缺假设（RESEARCH_PLAN §2.2 末）在本次核对范围内仍然成立**：在包含不同算法实现、结构化数值误差和多速率接口的通信数据通路中，未发现现有工作显式利用"候选排序随下游处理与场景变化"这一结构；R1–R8 与四类先例分别占据了该假设的各个组成部分（系统误差驱动字长、联合精度-HLS、误差依赖传播、算法-架构搜索、精确重写、多速率结构内误差、场景化精化、层次/多保真 DSE），但没有一篇把这些组成部分合到候选筛选机制上。

### 4.2 需要收窄或调整的地方

1. **课题一的贡献点必须进一步收窄（最重要）**。"局部 SQNR/SFDR 不足以描述杂散"是 DDS 常识（Nicholas 1987/1988 的公式直接量化了这一点），频域加权噪声模型是 1972 年级经典。计划中"必要基线"已含频谱加权模型，本次核对确认：**任何不超越"白噪声+固定 |H|² 加权"的主张都会被既有文献否定**。可辩护的核心只剩：结构变化（LUT/插值/CORDIC、直接型/多相）与多速率组合下，筛选所需信息的**最小充分集合**及其充分条件/反例。动机实验（计划 §6.1 第 4–7 天）的对照组必须包含"Nicholas 式一阶杂散模型 + QNTF 加权"的强基线，而不只是局部 SQNR。
2. **课题二必须以 R2/R3/R4 为同等预算基线**。"精度+调度+绑定联合"（R2）、"近似算子选择+位宽+调度"（R3）、"精度+电压+调度+误差依赖"（R4）已是完整先例。H2 的增量只能来自计划已列的三处：通信系统级约束（EVM/频谱掩码/速率/多速率服务率换算）、跨混频-滤波-抽取的算法结构候选、物理实现口径。若实验设计退化为固定算法图上的精度×调度，直接与 R3 对比即可，H2 不成立。
3. **课题三的"分开复用"须与 Active-CEM/Polaris 的分解显式对照**。Active-CEM 已实证"旧排序不可迁移、须分解共享/私有知识并主动校准"，这与 H3 同向；H3 的差异轴（场景显式 + 误差传播知识 vs 硬件特征，且可校准性来自链路结构）需要机制证据，否则按计划 §4 预案降级为系统实现部分。
4. **NCO 方向的威胁与机会并存**：Nicholas 系给出一阶解析杂散模型，意味着"上下文相关的候选预测"在混频模块内部有很强的解析基础可借力——若课题一的紧凑信息表示能直接吸纳这些模块级解析模型（而非重新拟合黑箱），收窄后的主张更可信。
5. **多速率与抽取模块应复用既有方法**：CIC/Hogenauer 系的截断分配与字长增长分析是抽取模块内部的成熟方法，课题设计应将其作为抽取模块的现成误差模型来源，而非新贡献点。

### 4.3 待进一步精读清单（P0/P1 前完成）

| 优先级 | 事项 |
|---|---|
| 高 | R2 全文（Wiley/HAL 均被反爬；改走图书馆/作者渠道）：解析精度评估具体形式、迭代循环终止条件、案例规模——直接决定课题一解析评估基线的实现方式 |
| 高 | Novo DATE 2008 全文（ACM 付费墙；作者 EPFL 页面可能有版本）：其"场景"的精确定义与 BER 评估协议，划清与课题一"上下文"的边界 |
| 高 | R1 第 11–14 页与 R5 §IV–VII：搜索方法的鲁棒性讨论、SPIRAL 综合流程与验证细节 |
| 中 | Nicholas 1988（AFCS 42）原文：最坏杂散公式 −6.02B+3.92 dBc 的推导条件（本报告当前为摘要级） |
| 中 | VIZOR 原文：确认"EVM 驱动可调字长接收机"的出处与机制（当前仅检索命中） |
| 中 | FloPoCo 当前版本（≥4.1 之外的稳定版）的 FixSin/FixCos/相关 atan 条目与频率驱动流水线化行为：4.1 手册无 FixSin/FixCos 独立条目，复现基线时须锁定版本 |

---

*本报告依据 2026-09-27 当日可访问的链接与下载原文撰写；"已核实内容"以原文阅读或原文页面问答为据，"待进一步精读"事项列于 §4.3。未复现任何论文的性能数字。*
