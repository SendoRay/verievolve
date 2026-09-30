# 近邻能力矩阵：WLO、近似 HLS 与可验证 RTL 重写

> 状态：2026-09-29 持续核查中的合并矩阵。已覆盖 WLO、近似 HLS、数值编译、e-graph 与
> 可验证 RTL 重写；本表用于收紧问题和基线定义，不单独支持领域空白结论。

## 1. 判定口径

符号：**✓** 表示方法直接支持且进入搜索或验证闭环；**△** 表示只覆盖受限子类、使用代理，
或仅在最终结果上复核；**—** 表示论文/官方文档中未见该能力。

八列按以下严格含义填写：

1. **实数语义分解**：搜索会改变公式或算法分解，而不只是既定图上的位宽、调度、绑定或局部
   等价 RTL 重写。
2. **近似实现原语**：近似算子/算法实现是显式选择项；单纯改变 word/fraction length 不单独算此项。
3. **定点 round/sat bit-true**：适应度或正确性模型忠实覆盖候选整数数据通路的舍入、截断、溢出/
   饱和语义。仅有统计量化噪声模型或“最终生成 RTL”记为部分覆盖。
4. **状态/多速率**：方法明确处理状态递推或采样率变化及其误差语义；不能因输入语言原则上能表达它们
   就记为支持。
5. **系统级非加性目标**：搜索闭环能直接使用整链黑盒目标或契约；把局部噪声按可加模型传播为一个
   输出方差/SQNR 只记部分覆盖。
6. **真实综合 PPA**：真实综合结果直接进入候选选择闭环。特征化算子库、解析门数、bit-width sum，
   或仅对最终点综合均记为部分覆盖。
7. **LLM**：LLM 是候选、规则或搜索策略的一部分。
8. **验证/soundness**：区分形式等价/全域保证、基于假设的解析模型、以及有限场景仿真。

## 2. 能力矩阵

| 工作 | 实数语义分解 | 近似实现原语 | 定点 round/sat bit-true | 状态/多速率 | 系统级非加性目标 | 真实综合 PPA | LLM | 验证 / soundness |
|---|---|---|---|---|---|---|---|---|
| 经典 WLO（Han–Evans 等） | —：固定 SFG/实现图 | —：主要调字长/缩放 | △：仿真型可 bit-true；解析型依赖噪声模型 | △：已有 IIR、CDMA、OFDM 等系统实例，但结构固定，未形成统一多速率语义 | △/✓：可用端到端 BER/SNR/MSE；通常靠有限场景仿真或特定解析传播 | —/△：多为位宽/算子成本代理 | — | 仿真覆盖或模型假设内保证；一般不是全输入证明 |
| MathWorks `fxpopt` / Fixed-Point Designer | —：模型拓扑固定 | —：优化 heterogeneous data types，不自动在 LUT/CORDIC 等算法类间选择 | ✓：Simulink 定点类型、舍入和溢出语义由模型执行 | △：可优化有状态 Simulink 系统；文档未把多速率误差作为独立方法贡献 | ✓：整模型 simulation tolerance、SNR/noise-floor、Model Verification assertion 均可作 behavioral constraint | —/△：默认 BitWidthSum，也可 OperatorCount/自定义成本；不是每候选综合 PPA | — | 有限 simulation scenarios 上满足行为约束；文档建议扩大场景覆盖，不给全输入 soundness |
| Menard et al., 2012 | —：输入是既定 DFG/SFG | —：WLO + allocation/scheduling/binding/grouping | △：解析输出量化噪声；整数位宽避免 overflow，但不是候选 datapath 的逐位 round/sat 模型 | △：SFG 含 delay，实证含 IIR；未见显式多速率误差语义 | △：先把系统质量要求映射成 SQNR，再优化解析 SQNR 约束 | △：GAUT + 特征化算子库/LUT 面积；搜索目标不是逐候选真实综合 | — | LTI impulse response 或 smooth-operation 统计噪声模型的适用域内；不是全域 bit-true 保证 |
| Li et al., DAC 2015 | —：固定 task graph/DFG | ✓：每个操作在不同位宽与近似实现库中选择，并联动调度、FU 分配/绑定 | △：算子误差方差/敏感度模型；用 Verilog Monte Carlo MSE 验证，不是逐位精确 evaluator | —：数据流图；未覆盖状态或多速率 | —/△：约束是传播后的输出方差，显式忽略大部分跨误差源协方差 | △：特征化实现库的能耗/时延；非每候选真实综合 | — | 经验校准：解析方差与 Verilog MC MSE 相关系数 0.94、数值差约 10%；无 sound 全域保证 |
| AxHLS / Lee et al., DATE 2017 | —：固定 CDFG | △：bit rounding、operation elimination、voltage scaling；不是跨算法分解类 | △：一次 profiling 后传播均值/方差；最终生成 RTL，但搜索 quality model 非 bit-true | △：支持 CDFG control flow/branch probability；未见流式多速率误差语义 | △：输出 quality requirement 进入优化，但由半解析标量统计模型估计 | △：AC 库经 HSPICE/门级特征化，最终综合/调度；搜索期不是逐候选真实 PPA | — | 与综合后仿真经验比较，低质量区误差可到数 dB，并需质量余量；不是形式保证 |
| ROVER, 2024 | △：精确等价 RTL datapath 重写，不是公式级近似分解 | —：所有 rewrite 保持 bit-vector 功能等价 | △：精确 bit-vector 语义可覆盖位宽/符号，但没有 round/sat 近似质量维度 | —：论文基准为组合算术 datapath；未建立状态/多速率语义 | —：优化等价实现的面积，不评价系统数值质量 | △：理论门数 + ILP 提取；最后用 TSMC 5 nm 商业综合报告 | — | 强：egg proof chain、逐规则 EC 与后端验证；位宽 >8 的规则条件有外推，但最终验证兜底 |
| ASPEN, 2025 | △：LLM 提出/筛选精确等价 RTL 规则；不搜索数值近似分解 | —：近似实现和误差预算不在 e-class 语义中 | △：在 RTL bit-vector 等价层精确，但没有 round/sat 近似质量 evaluator | —：公开基准是算术 datapath；未见状态/多速率误差语义 | —：反馈目标是 PPA，不是端到端数值契约 | ✓：商业综合 PPA 回灌 e-node 成本并迭代，最终 Pareto 点再综合/等价检查 | ✓：规则提议、规则选择和 PPA 反馈 | 强：新规则附 Z3 proof，最终 Pareto 点做商业 RTL equivalence checking |

## 3. 对项目定位与基线的约束

这组近邻已经覆盖了三个不能再单独声称新颖的能力：

- 固定计算图上的系统级字长优化和行为约束；
- 近似算子、精度、调度与绑定的联合优化；
- LLM 引导、形式验证的 RTL 等价重写，以及真实综合反馈。

因此当前可检验的工作假设应收紧为：

> 在同一个闭环里，联合搜索 **exact formula decomposition、approximate realization 与定点 RTL**，
> 并用包含状态/采样率变化的端到端数值契约和真实 PPA 选择候选；LLM 是否对这个组合空间有独特增益，
> 由同预算搜索基线决定。

这里的关键不是把上述三块并排放进一个系统，而是证明它们必须联合：至少需要一个实例显示，固定图 WLO、
算子库近似 HLS、精确等价 RTL 重写中的任一路线，因缺少另一个自由度而错过了可复现的系统级前沿点。

### 必须进入实验的强基线

1. **固定结构 WLO**：`fxpopt` 式 simulation-constrained datatype optimization，以及 Menard 式解析 SQNR WLO。
2. **固定 DFG 的近似 HLS**：Li DAC'15 的 implementation-set + scheduling/binding，和 AxHLS 的
   rounding/elimination + quality model。
3. **实数等价重写 + 定点优化**：Darulova EMSOFT'13 的 GP 重写，以及 Anton ICCPS'18 的
   rewrite-then-mixed-precision 流程。
4. **精确结构搜索**：ROVER/ASPEN 风格的 equality-saturation 或已验证规则库，在相同 PPA 口径下提取。
5. **同语言非 LLM 搜索**：beam、MCTS、iterative ILP/约束求解和 GP；不能由“目标不可加”直接推出
   进化或 LLM 必要。

## 4. 逐项证据与来源

- **Han & Evans 2006**：在固定实现图上以 complexity–distortion measure 搜索字长；失真函数直接使用
  CDMA 输出 SNR/FER、OFDM BER 与 IIR MSE，说明“系统输出质量驱动 WLO”早已成立，但搜索自由度仍是
  字长而非公式分解或近似结构。来源：[EURASIP JASP 论文](https://doi.org/10.1155/ASP/2006/92849)；
  仓库全文核查记录见 `thesis/LIT_GAP.md` R1。
- **Menard et al. 2012**：原文明确以 DFG 为输入，在 GAUT HLS 与 WLO 间迭代；解析工具从 SFG
  自动生成输出量化噪声表达式，LTI 情形由噪声源到输出的 impulse response 给出增益，smooth operations
  使用其团队的统计传播方法；面积按 operator library 的 LUT cost 评价。案例含 FIR、FFT、IIR 和
  WCDMA correlator。来源：[Wiley 全文](https://doi.org/10.1155/2012/906350)。
- **Li et al. DAC 2015**：每个 operation 有 implementation set，MMKP/ILP 做实现选择并与 list scheduling、
  FU allocation/binding 联动；质量约束为 error sensitivity 传播的输出方差，并以 Verilog Monte Carlo
  校准。来源：[作者 PDF](https://www.ece.umn.edu/~sachin/conf/dac15-cl.pdf)；仓库核查记录见
  `thesis/LIT_GAP.md` R3。
- **AxHLS / Lee et al. DATE 2017**：对 CDFG 做 rounding、operation elimination、voltage scaling 与
  scheduling 的联合优化；一次 C simulation 收集均值、方差和 branch probability，搜索期用半解析
  quality/energy model，最后生成 Verilog RTL。来源：[作者 PDF](https://lca.ece.utexas.edu/pubs/lee_date_2017.pdf)。
- **`fxpopt`**：官方文档把搜索变量定义为 fixed-point data types，默认目标为 BitWidthSum；候选是否
  合法由原模型与定点模型的 simulation tolerance 或 Model Verification assertion 判断，官方例子直接
  使用整模型 noise floor 与 SNR。来源：[函数文档](https://www.mathworks.com/help/fixedpoint/ref/fxpopt.html)、
  [自定义行为约束](https://www.mathworks.com/help/fixedpoint/ug/perform-data-type-optimization-with-custom-behavioral-constraints.html)。
- **ROVER**：mixed-precision RTL rewrite 保持功能等价，e-graph 紧凑表示等价实现；理论 area cost + ILP
  提取，后端产生可由工业工具检查的 verification chain，并报告商业综合结果。来源：
  [arXiv:2406.12421](https://arxiv.org/abs/2406.12421)；仓库核查记录见 `thesis/LIT_GAP.md` R7。
- **ASPEN**：LLM 负责规则提议、规则选择与 PPA feedback；规则先过 Z3，商业综合结果回灌提取成本，
  Pareto 点最后做商业等价检查。来源：[NVIDIA 论文页](https://research.nvidia.com/labs/electronic-design-automation/publication/deng2025aspen/)；
  全文核查记录见 `thesis/LIT_GAP.md` R8。

## 5. 尚未关闭的 gate

- Pherbie 当前仅完成摘要/检索级核查；它对 rewrite space、误差口径和 target cost 的具体边界在全文
  核对前不进入最强新颖性判断。
- 商业 WLO/HLS 产品的“支持”与“自动联合搜索”必须继续分开；一个工具能手动搭建多速率链，不能据此
  记为其优化器能跨分解类联合搜索。
- “状态/多速率”仍是本表最薄弱的一列。后续检索需要直接查方法与实验正文，不能由 benchmark 名称、
  输入语言或营销页反推。

## 6. 数值编译 / e-graph 近邻

同一列头与符号口径。核查深度逐行标注。

| 工作 | 实数语义分解 | 近似实现原语 | 定点 round/sat bit-true | 状态/多速率 | 系统级非加性目标 | 真实综合 PPA | LLM | 验证 / soundness |
|---|---|---|---|---|---|---|---|---|
| Chassis（arXiv 2410.14025；**全文精读**） | ✓：egg 上做 mixed real-float equality saturation，数学恒等式只定义一次、跨 target 复用 | ✓：target description 为每个算子声明 `#:approx`（它近似的实数表达式）与标量 cost，如 `rcp.f32 ≈ 1/x`；也含 vdt 的 fast_/appr_ 库函数 | —：浮点（binary32/64），精度按 `p − log2 ULP` 计 | —：FPBench 标量表达式，只有 regime 分支 | △：候选整体在采样训练输入上执行测精度（输出级，不按节点相加）；**速度 = 各算子标量 cost 之和**（可加），extraction 只用 cost | —：9 个软件 / ISA target，实测运行时间只用于最终评价 | — | 采样经验精度，无 sound 保证；作者明说 “accuracy is difficult to evaluate one e-node at a time”，把精度感知 extraction 列为 future work |
| Pherbie（ARITH'21；**仅摘要 / 检索级**） | ✓：继承 Herbie 的重写 + series expansion | △：精度转换作为 rewrite（mixed precision），不是近似算子库 | —：浮点 | — | △：accuracy–speed Pareto，采样误差 | —：cost 模型 | — | 采样；局部误差启发式 |
| E-ALS（ICCAD'26, arXiv 2609.13276；**HTML 方法与实验**） | —：门级 AIG 的精确等价重构，不是实数公式 | △：近似发生在 e-graph 之后的 ALS（SASIMI 式局部替换），e-graph 内只保持精确等价 | —：Boolean，误差为 Hamming / Error Distance | —：组合逻辑 | △：ALS-coupled surrogate + 1024 个采样 pattern 的增量仿真；搜索式 extraction（模拟退火） | △：最终统一经 ABC 映射到 ASAP7；搜索期用 surrogate | — | 采样误差检查，非 SAT 精确验证 |
| Darulova et al., EMSOFT'13 / Xfp（**全文精读**） | ✓：对 `+,-,*,/` 表达式用实数恒等式改变结合、分配与求值顺序 | —：无 LUT/CORDIC/多项式阶数等近似原语；总位宽固定 | △：有 signed fixed-point、自动小数位分配与 truncation；fitness 是 affine-arithmetic 最坏误差上界，不是 RTL 逐位执行，也无 saturation | —：controller 的各 state update 被拆成独立标量表达式；无递推轨迹或多速率语义 | △：优化单表达式的 worst-case absolute error；控制稳定性只作下游应用分析 | —：无 RTL/综合/PPA；等价重写默认不增加运行时资源 | — | 强但有边界：静态上界对实数语义 sound；非线性时可能很松，另以大样本仿真校准排序 |
| Rosa / TOPLAS'17（**HTML 全文方法核查**） | —：分析并 lowering 给定实数程序，不执行 GP/结构搜索 | —：选择数据类型；Taylor 等近似公式由输入程序给定 | △：fixed-point codegen 含整数运算/移位，静态分析 sound 地界定 rounding/overflow；不是 saturation-aware RTL bit-true evaluator | △：支持带 branch 的程序，并对单层、无分支、范围静态有界的循环给出随迭代次数变化的误差；无多速率 | △：方法级 pre/postcondition 的 worst-case absolute error，不是跨 kernel 的通信契约 | —：生成 Scala 源码并比较软件 runtime；无硬件综合 | — | 强：在声明输入范围与受支持程序类内给 sound range/error bound；循环覆盖有明确结构前提 |
| Anton / Daisy，ICCPS'18（**全文精读**） | ✓：GP 以实数恒等式搜索求值顺序，并扩展到 Herbie 规则集 | —：选择 arithmetic precision，不选择硬件近似算法族 | △：支持 16/32-bit fixed point、truncation、casts/shifts 和 sound 静态误差；硬件实验缺失且无 saturation | —：论文明确排除 conditionals/loops；无状态/多速率优化 | △：每个 arithmetic kernel 的 worst-case absolute error 约束；不是整链黑盒目标 | —：静态 operation/cast cost；生成 C/Scala，specialized hardware 留作 future work | — | 强：误差约束 sound；重写是启发式、不保证找到最优；论文实验只评估 floating point |

### 6.1 这一组给出的约束

1. **「精确 e-graph + 近似算子作为 typed lowering + 精度 / 成本 Pareto」已被 Chassis 占据**（抽象结构几乎一致）。
   我们不能把这种两层表示当作新意，只能把它当作继承的基础设施，Chassis 作首要强基线。
2. Chassis 的精度评估已经是**整候选采样**，不按节点相加。所以「非加性整体评估」本身也不是新意。
3. **Darulova 组已经占据“实数等价重写 + 定点误差上界 + GP”，并进一步占据重写后 mixed-precision
   tuning。** 简单 truncation 的解析误差也已覆盖；定点语义差异必须具体落到生成 RTL 的逐位
   round/trunc/sat、状态交互及模型—RTL 对拍，不能再写成泛化的“定点 + 重写”。Rosa 还对受限循环
   给出 sound 分析，因此“有状态程序无人处理”也不成立；尚未覆盖的是把这类分析并入结构优化闭环，
   以及流式多速率系统语义。
4. E-ALS 证实「先在 e-graph 里找 approximation-friendly 的精确结构，再做近似」在门级已有；
   在算术层是否有对应工作仍待查。

综合这些近邻后，当前仍需逐项实证的组合差别是：

- 可参数化的硬件近似结构族（如 `LUT_k` / `CORDIC_N` / `Poly_d`）与实数等价分解共同搜索；
- 生成 RTL 的 round/trunc/sat bit-true 语义及模型—RTL 一致性，而非只给抽象 roundoff 上界；
- 有状态、流式、多速率、跨 kernel 的系统契约；
- 候选级真实综合 PPA；
- LLM 相对同语言 GP/beam/MCTS/约束搜索的可测增益。

### 6.2 Darulova 组的搜索空间与证据边界

**EMSOFT'13 / Xfp。** 输入是一个标量实数表达式和输入区间，语法为常数、变量和 `+,-,*,/`。
搜索只应用 13 条实数等价恒等式，包括交换、结合、负号搬移、倒数变换和分配/提因子；它能改变
表达式树与操作数，但不引入新的近似算法族。默认 GP 为 population 30 × 30 generations，使用
tournament selection、mutation 和 equivalence-preserving crossover，最多约 900 次候选评价。仅 6 项的
线性和就有 945 种结合树（忽略交换），最大 benchmark 有 15 项，已无法穷举；论文还用相同的 900
候选预算与 random rewriting 比较，GP 多次得到超过 50% 的误差改进。因此它是本项目同语言 GP 基线的
直接先例，不能把 GP 描述成只会参数扰动的弱基线。

fitness 是 fixed total bit length 下的 worst-case absolute error 上界：中间范围决定整数位和小数位，
舍入模式为 truncation，affine arithmetic 传播量化误差。上界对模型 sound，但论文明确指出非线性表达式
会使抽象解释变松；其仿真用于检查上界的相对排序质量，而不是把采样结果当保证。

**Rosa。** Rosa 展示了 fixed-point integer/shift codegen，并能在声明范围内 sound 地分析 overflow、
roundoff、输入误差传播和 branch divergence。它对循环的覆盖是受限而非空白：单层、无条件分支、
变量范围静态给定的循环，可把误差表示为迭代次数的函数；它不自动证明范围归纳不变式。该能力属于
分析/编译，不是 EMSOFT'13 GP 或 ICCPS'18 mixed-precision 搜索已经覆盖状态闭环的证据。

**ICCPS'18 / Anton（后来并入 Daisy）。** 重写阶段沿用 GP，参数为 population 30 × 30 iterations，
取消 crossover，并扩充到 Herbie 的实数恒等式；目标是在操作数不超过原表达式的前提下降低 uniform-
precision 最坏误差。precision tuning 随后用 delta debugging 单独执行；作者试过用 GA 调 mixed precision，
但认为不合适。也就是说，这篇工作的组合是两阶段的 `rewrite → tune`，不是同时联合搜索。

Anton 为固定点提供 16/32-bit、truncation、casts 与 bit shifts，静态误差约束是 sound 的；但论文明确
排除 conditionals 和 loops，fixed-point specialized hardware 留作 future work，正式实验只评估 floating
point。成本是静态 operation/cast score，而非 RTL 综合 PPA。

主要来源：

- [Synthesis of Fixed-Point Programs, EMSOFT'13](https://lara.epfl.ch/~kuncak/papers/DarulovaETAL13SynthesisFixedPointPrograms.pdf)
- [Towards a Compiler for Reals / Rosa](https://arxiv.org/abs/1410.0198)
- [Sound Mixed-Precision Optimization with Rewriting, ICCPS'18](https://arxiv.org/abs/1707.02118)
- [Daisy tool paper, TACAS'18](https://link.springer.com/chapter/10.1007/978-3-319-89960-2_15)
