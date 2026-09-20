# 摘要

通信物理层算子的 RTL 实现至今以人工为主：工程师需要把数学公式翻译为算法结构选择、
定点化策略与流水线微结构三个耦合空间中的联合决策。大语言模型（LLM）的代码生成能力
为自动化该过程提供了新可能，但现有研究存在三个结构性局限：评测基础设施以自然语言
为输入、以二值功能正确性为口径，无法度量"公式→RTL"方向的方法进步；生成的正确性
验证依赖有限样本的随机仿真，适应度本质上是随机变量；搜索在自由文本空间进行，数值
语义层面的已知结构（算法族、舍入误差可组合性、保精度结构重写）被完全弃用。

针对上述局限，本文完成三方面工作：

**其一，构建公式驱动的通信 DSP 硬件基准 CommDSP-Bench。**以 3GPP 物理层算子为任务
源，建立 7 个算子族、110 个参数化实例：任务卡为纯数学规范，golden 与防背题激励由
评估器自动生成，精度（SQNR/SFDR）作为可谈判的连续搜索维度进入质量多样性网格，
一次运行输出精度-面积-吞吐整条 Pareto 前沿。对基准的系统性审计修复了三类基线
生成器缺陷（解包数组、case 分隔符、输出饱和/除法位宽回绕），识别并定量刻画了
重尾误差分布指标的方法学风险，以全量回归闭环验证基准自洽性。

**其二，建立证书化评估体系。**将评估 oracle 形式化为三级层级：L1 采样层、L2
确定性层（固定种子低差异格点或全枚举上的整数域精确仿真）、L3 声明性层（对全体
输入成立的闭式最坏界）。证明模分解引理：整数域数据通路的输出量化误差只依赖输入
对 2^s 的残差，残差分布由 2-adic 赋值混合精确给出，配合圆卷积合成律，锚点任务的
总体均值 SQNR 可零采样、零积分误差地精确计算。四个算子族的证书模型完成"模型-RTL"
逐位对拍验证（平滑族端到端偏差 < 0.1 dB）；实验揭示重尾指标（LLR 族）下任何有限
样本适应度估计的固有病态性——同设计两组合法估计可差 10.9 dB。

**其三，提出证书携带的进化搜索范式并完成系统实验。**让 LLM 在证书携带的参数化
模板空间中进化：精度由证书引擎确定性给出，面积由真实综合获得，算法结构成为一等
搜索自由度。以 DeepSeek deepseek-flash 为后端的同预算对比实验表明：证书携带空间
中的进化在锚点任务上找到采样基线完全错过的精度可谈判点（57.2 dB/2804 LUT），
在正余弦任务上第 5 次迭代跨越采样基线 40 次迭代未能突破的算法类地板
（93.99 dB vs 75.6 dB，最终 96.0 dB/3648 LUT，且将低面积多周期 CORDIC 分支纳入
同一前沿）；证书引导的等价类导航以约 1/3 的综合预算恢复全量前沿；以 BER 证书
（含最坏情况裕度）替代 SQNR 门槛惯例选型匹配滤波器系数字宽可节省 66% 面积；
机制消融将优势分解为"搜索空间"与"适应度确定性"两个因子，并诚实报告了重尾族
上证书均值适应度的适用边界。

本文的全部实验数据、脚本与原始产物在开源仓库中可复现。

**关键词**：大语言模型；Verilog 自动生成；通信数字信号处理；定点化；质量多样性搜索；
证书化评估；Pareto 优化

# Abstract

RTL implementation of communication physical-layer operators remains largely manual:
engineers must translate mathematical formulas into joint decisions across three coupled
spaces — algorithm-structure selection, fixed-point strategy, and pipeline micro-
architecture. Large language models (LLMs) offer a path to automation, yet existing work
suffers from three structural limitations: benchmarks take natural-language input and
binary functional correctness; correctness verification relies on randomly sampled
simulation, making fitness a random variable; and search operates on free-form text,
discarding the known mathematical structure of numeric semantics.

This dissertation makes three contributions. First, we build CommDSP-Bench, a
formula-driven benchmark of 110 parameterized instances across 7 communication-DSP
operator families, where task cards are pure mathematical specifications, golden models
and anti-memorization stimuli are auto-generated, and continuous precision (SQNR/SFDR)
enters a quality-diversity grid as a negotiable search dimension. A systematic audit
repairs three classes of baseline-generator defects and quantifies the methodological
risk of heavy-tailed error metrics. Second, we establish a certificate-based evaluation
hierarchy (sampled / deterministic / declarative) and prove a modular-decomposition
lemma: the output-quantization error of integer-domain datapaths depends only on input
residues modulo 2^s, whose distribution is given exactly by 2-adic valuation mixing —
yielding zero-sampling, zero-integration-error fitness for the anchor task. Four family
certificate models are validated bit-exactly against generated RTL. Third, we propose
certificate-carrying evolutionary search, where the LLM navigates a parameterized
template space whose fitness is deterministic. Same-budget experiments with a real LLM
backend show that the certificate arm finds precision-negotiable points entirely missed
by the sampled baseline (57.2 dB / 2804 LUT), breaks an algorithm-class floor in 5
iterations that the baseline cannot break in 40 (93.99 dB vs 75.6 dB), and that
BER-certificate word-length selection saves 66% area over the SQNR-threshold convention.
All artifacts are open-sourced for reproducibility.

**Key words**: large language models; automatic Verilog generation; communication DSP;
fixed-point arithmetic; quality-diversity search; certificate-based evaluation; Pareto
optimization
