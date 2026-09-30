# DDC witness 契约草案 v1

- 日期：2026-09-29
- 状态：**草案，未冻结；不含实验结果**
- 作用：在运行任何 DDC truth 之前冻结 `PROPOSAL_v1.md` 中的
  `(C, ρ, q, {ε_m^(m)}, ε_Q)`，并登记一份独立的物理预测。
- 范围：第一阶段只改变 NCO / 近似原语；CMUL、FIR、抽取率和下游 FIR 实现固定。
- 纪律：本文只规定协议和预测，不修评价器、不运行实验、不把旧诊断数字当证据。

---

## 1. 冻结对象与版本

第一轮 witness 的候选集是 `candidates.py` 中的 `n1`–`n6`。所有候选接收同一份量化后的
`x_adc`，使用相同的复乘、FIR、抽取实现和复位初态。变化项只有 NCO 实现结构与它声明的参数。

冻结元组为：

```text
K_DDC_v1 = (C_main, C_heldout, C_stress, ρ, q, M, {ε_m^(m)}, ε_Q,
            feasibility rules, cost flow, alignment rule)
```

任何成员发生变化，都生成新契约版本；不得覆盖旧结果。`C_main` 用于第一次选择，
`C_heldout` 只用于检查结论对栅格细化是否稳定，不用于回头选择候选或阈值。

## 2. 部署场景集合 C

### 2.1 频移栅格

当前 `spec.py` 的 `{0.39, 0.51, 0.63} MHz` 三点不足以代表可调谐接收机：三点虽然落在
30 kHz 子栅格上，但无法揭示候选误差谱随 FCW 改变时的窄带最坏点。

本草案采用 **15 kHz baseband 频移栅格**：

- `C_main`：`f_off = 0.390, 0.420, ..., 0.630 MHz`，步长 30 kHz，共 9 点；
- `C_heldout`：`f_off = 0.405, 0.435, ..., 0.615 MHz`，与训练点交错，共 8 点；
- 最终报告同时展示两者及其并集，即 `[0.390, 0.630] MHz` 上的 15 kHz 栅格，共 17 点；
- 只称“该冻结栅格上的 worst”，不称连续频率区间上的 worst。

主 witness 的 `Q` 只在 `C_main` 上定义；候选对、阈值和结论文字锁定后才揭示 `C_heldout`。
held-out 结果用于判断栅格稳定性，不并回主 `Q` 重新选候选。若两者结论冲突，主结果标为不稳定，
不得改用 17 点并集补做选择。

依据是 3GPP NR FR1 channel raster 中真实存在的 15/30 kHz 档位；这里使用的是其**频率差的离散步长**，
并不声称这个归一化 2 MHz DDC 已完整实现某一个 NR band 的 RF 规范。LTE 的 100 kHz channel raster
另列为迁移契约，不与本契约混合。来源：

- [ETSI TS 138 104，NR BS radio transmission and reception](https://www.etsi.org/deliver/etsi_ts/138100_138199/138104/15.12.00_60/ts_138104v151200p.pdf)
- [ETSI TS 136 101，E-UTRA UE radio transmission and reception](https://www.etsi.org/deliver/etsi_ts/136100_136199/136101/08.05.01_60/ts_136101v080501p.pdf)

选择 0.390–0.630 MHz 是为了保持与 `ddc-p0-v2` 的已声明工作区间一致；它不是从候选结果反推的。
若以后要声称符合具体 3GPP band，必须另行冻结载频、带宽、SCS、接收机类别和 RF blocker 表，不能沿用本抽象。

manifest 对每个频点还必须保存实际整数
`FCW=round(f_off/Fs_in·2^32)`、`gcd(FCW,2^32)` 与对应周期。真实 channel raster 不自动保证 accumulator
轨迹满熵；若某点退化，保留并如实解释，不能看过候选结果后移动频点。

### 2.2 blocker 与噪声

主契约保留三类 blocker 位置，但校准为栅格点：

| 类别 | post-mix offset | 用途 | 规范身份 |
|---|---:|---|---|
| OBB-near | 0.300 MHz | FIR 过渡带压力点 | 工程压力点，不冒充 3GPP 表项 |
| OBB-edge | 0.420 MHz | 接近冻结 stopband edge 的压力点 | 工程压力点，不冒充 3GPP 表项 |
| alias-edge | 0.555 MHz | R=2 后折叠到 0.445 MHz，逼近 0.450 MHz stopband edge | 工程压力点；替代原 0.550 MHz 非栅格点 |

blocker 相对功率的处理：

- `−3 dB` 进入主契约；它代表强但不故意逼迫定点链饱和的压力场景；
- `+6 dB` 只作预注册的敏感性压力点，不进入主 `ρ`。只有在另行给出接收机增益控制、满量程与
  标准 blocker 电平之间的映射，并确认没有用人为饱和制造结果后，才能升级为部署契约；
- 这些相对功率不是 3GPP blocker 电平的直接换算。标准中的绝对电平依赖 band、channel bandwidth、
  reference sensitivity 等，本 2 MHz 归一化链没有足够信息做该映射；
- 主契约另含 no-blocker 场景，用来区分固有实现误差和 blocker 条件下的交叉作用。

由此，`C_main` 每个 `f_off` 含 `clean + 2×OBB(−3 dB) + alias(−3 dB)` 四个场景，共 36 个；
`C_heldout` 使用相同四场景模板，共 32 个；`C_stress` 只在 9 个主栅格点加入
`alias-edge(+6 dB)`，共 9 个。不得把 `+6 dB` 扩展到 OBB 点后仍沿用 v1 名称。

AWGN 固定为**相对 desired signal、加 blocker 之前**的 30 dB SNR。不得使用当前
“把 signal 与 blocker 合在一起后估功率”的实现。随机种子、QPSK 数据、blocker 初相和噪声序列全部在
manifest 中冻结；所有候选共享完全相同的 `x_adc`。
seed 必须由完整场景键 `(contract_version, f_off, blocker_kind, blocker_offset, blocker_level)` 稳定派生，
不能继续依赖列表位置 `SEED_BASE+k`，否则插入 held-out 点会悄悄改变既有波形。

### 2.3 其余上下文

- `Fs_in = 2 MHz`，`R = 2`，抽取相位为当前接口语义的 phase 0；phase 1 只作敏感性检查；
- NCO 初相为 reset 后的 0；若部署允许任意初相，须另建含初相网格的契约，不能从本结果外推；
- QPSK 0.25 Msps、RRC roll-off 0.35、33-tap FIR、passband 0.20 MHz、stopband 0.45 MHz；
- witness 阶段固定候选下游 FIR `H`、CMUL、输出格式与饱和规则；候选 FIR 联合搜索不在此阶段；
- 输入峰值归一化规则及其比例必须写入 manifest。主评价需要同时保存 desired / blocker / noise 分量，
  不能只保留归一化后的总和。

## 3. 主风险 q：实现误差功率

### 3.1 定义

主风险不是相对发射符号的总 EVM；后者会把共同的 30 dB AWGN 和信道场景噪声算进候选误差，掩盖 NCO 差异。
先只用冻结的前导段 `P_c`，相对**同一输入的完整 float reference 输出**估计一个复标量：

```math
g_{h,c}=\frac{\sum_{n\in\mathcal P_c}y^*_{\mathrm{ref},c}[n]y_{h,c}[n]}
               {\sum_{n\in\mathcal P_c}|y_{\mathrm{ref},c}[n]|^2}.
```

再在互不重叠的数据段上定义：

```math
q(h,c)=
\frac{\sum_{n\in\mathcal M_c}|y_{h,c}[n]/g_{h,c}-y_{\mathrm{ref},c}[n]|^2}
     {\sum_{n\in\mathcal M_c}|y_{\mathrm{des,ref},c}[n]|^2}.
```

- `y_h`：候选 bit-true 全链输出；
- `y_ref`：对**同一份量化 `x_adc`**运行 float 参考链的输出；
- `y_des,ref`：只保留 desired component、但使用与总场景相同前端缩放因子的 float 参考输出；
- `M_c`：冻结的有效测量区间；
- `q` 在线性功率域计算，是 sample-domain implementation NMSE，也可解释为 implementation-EVM² 风格的量；
  它不是 3GPP 符号 EVM，正文不得混称。

单一 `g` 是**评价器的相对对齐自由度**，不是声称部署接收机能够从 desired-only 前导恢复的 CPE/AGC。
它使用主误差定义本来就依赖的同一完整 `y_ref`，不另外读取或分解 noise / blocker 分量；因此当
`y_h=y_ref` 时严格给出 `g=1`，不会把共同场景分量的有限样本投影误记成实现误差。它不能吸收时变杂散、
频率偏差或形状误差。只允许使用前导估计并冻结到数据段，禁止在测量段重新拟合。选择这一语义是因为 floor 相位截断
的常数相位偏置不属于本 witness 要检验的“误差谱形 × 多速率上下文”机制；不通过修改候选硬件的舍入方式来
人为删除该偏置。

共同输入中的 AWGN 和 blocker 在误差分子里抵消，但它们仍会通过定点 round / sat 改变候选行为。
用 desired-only 参考功率作分母，避免不同 blocker 强度改变归一化基准。当前场景生成器没有可靠暴露这一分量，
这是运行 truth 前的协议实现前置项。

### 3.2 对齐、预热与延迟

- reference 和 candidate 必须按输入样本的 sequence tag / valid 语义对齐，不允许为每个候选通过相关峰值
  或最小误差搜索额外平移；
- 允许确定性 lowering 带来不同周期延迟，但其 sample mapping 必须由握手与 manifest 声明，而不是从输出拟合；
- 当前 33-tap valid FIR 的第一个输出对应输入索引 32，随后 phase-0 抽取；`N_PRE_SYM=64`、`SPS=8`
  时，测量从对应输入索引 512 之后开始。按当前索引语义，这等价于丢弃首 240 个抽取输出；正式实现以
  sequence tag 规则为准，不硬编码 240；
- 全部候选使用相同测量长度；尾部不足时取共同交集；
- 主风险使用上节冻结的 preamble-only reference alignment；它是候选与同输入 float reference 的评价口径，
  不冒充部署端仅凭 desired preamble 可实现的估计器，也不是用测量段拟合的评价技巧；
- 同时报告 raw、passband-only 与符号域结果作为敏感性分析，均不得用于寻找主 witness。

## 4. 聚合 ρ

主聚合选择：

```math
Q_{C,\rho}(h)=\max_{c\in C_\mathrm{main}} q(h,c).
```

理由：接收机在冻结 channel raster 上必须对所有可调谐点工作，而当前没有可信的 FCW / blocker 出现概率，
所以 mean 会把窄带但真实的 spur failure 稀释，CVaR 还会引入未经支持的场景权重。`ρ` 只对同单位的线性
`q` 取 max；不对 dB 值取 worst 以外的 mean / CVaR。

辅助报告：

- 栅格 mean：只展示典型性能，不参与 witness 判定；
- `C_heldout` 细化：若训练栅格上的选择在 held-out 上失效，报告不稳定，不回头修改栅格；
- `+6 dB` stress：单独给出，不进入主 `Q`；
- CVaR：除非未来得到真实部署概率，否则不启用。

## 5. 容差与工程判据

### 5.1 局部指标容差

指标先转换为越小越好：`m_SQNR=-SQNR_dB`、`m_WCE=WCE`、
`m_lastbit=1-accuracy`。草案建议：

| 指标 | `ε_m^(m)` | 含义 |
|---|---:|---|
| SQNR | 0.10 dB | 小于该差异只视为工程 tie；冻结前须用模型/RTL 校准确认数值误差不超过它 |
| WCE | 1 个候选输出格式 LSB | 小于一个可观测输出码不宣称严格次序 |
| last-bit accuracy | 一个全域状态的概率质量，即 `1/N_domain` | 完整 32-bit accumulator 均匀域时为 `2^-32`；若用严格等价的加权商空间计算，保持相同概率分辨率 |

三个局部指标的输入对象必须是**完整 NCO 接口映射**：在均匀的 32-bit accumulator 状态域
`a∈{0,…,2^32−1}` 上，把候选的 phase truncation、LUT/CORDIC 与 16-bit 输出量化一起评价，并以
`exp(j2πa/2^32)` 的未截断理想相位为参考。这一均匀域定义是 context-free 的，不按某个 FCW 轨迹挑相位；
实现可用严格等价的 residue/coset 化简，但不能改变权重。

- 在均匀域上先估计一个全局复标量并冻结；它只移除与主 `q` 相同的常数增益 / 相位自由度；
- SQNR：理想复 NCO 输出功率除以校正后的 complex mean-square error；
- WCE：校正后全域上 I/Q 两分量绝对误差最大值，以 16-bit 输出 LSB 表示；
- last-bit accuracy：校正后 I、Q 两分量均落在正确舍入理想码的 ±1 LSB 内的状态比例；
- raw 三指标同时报告为敏感性结果，但不与 calibrated `q` 混用来构造主 reversal。

不得继续用只枚举截断后 16-bit angle code、因而忽略 `phase_bits` 的当前 `cert_metrics` 充当公平局部指标。

这些是预注册判定带，不是统计显著性阈值。固定脚本的枚举与综合可能完全确定；若重复运行波动为零，
不得伪造“统计阈值”。

### 5.2 实现损耗预算与 ε_Q

为把实现误差换算成工程量级，使用一个明确标注假设的分配模型：若背景 SNR 为 30 dB，且实现误差可按
与背景噪声不相关的附加误差处理，则额外 SNR 损失为

```math
\Delta_\mathrm{SNR}(q)=10\log_{10}(1+10^{30/10}q).
```

因此 0.10 dB 的实现损耗预算对应

```math
q_\mathrm{budget}=\frac{10^{0.10/10}-1}{10^{30/10}}
\approx 2.33\times10^{-5}\quad(-46.33\ \mathrm{dB}),
```

即约 0.483% RMS 的 implementation EVM。它是**工程分配近似**，不是对相干 spur、饱和或相关误差的定理；
正式报告必须同时给出 bit-true `q`，不能只给这一换算。

主 `ε_Q` 建议冻结为十分之一预算：

```math
ε_Q=max(q_\mathrm{cal}, 0.1q_\mathrm{budget}),
```

其中 `q_cal` 是在运行候选 truth 之前，用 exact-representable identity / zero-error case 得到的评价器数值底噪。
这对应约 0.01 dB 的增量损耗量级，同时要求一个完整 0.10 dB 预算至少含十个可分辨步长。
若 `q_cal` 大于该值，应先修评价器而不是放宽 witness。该选择可能使所有 NCO 候选都达不到
decision-witness 门槛；这是允许且必须报告的结果。

### 5.3 decision witness 与面积

主成本为 **Yosys + Nangate45 `typ.lib` 的 mapped cell area (`area_um2`)**。冻结 Yosys 版本、liberty 文件
哈希、综合脚本和 top module；无 SDC 时不把 timing / power 写入正式证据。ice40 LUT 数只作后端敏感性分析。

主判定的候选集合固定为现有六点池与 v2 二十点池的并集，共 26 个实现。对每个局部指标 `m`，先在该并集上
按 `(m, area_um2)` 的确定性数值计算标准 Pareto 前沿 `F_m`。
decision witness 的**主判据**固定为：存在 `h∈F_m` 和同池候选 `h'`，使 `h'` 在 `(Q, area_um2)` 上
严格 Pareto 支配 `h`，且 `Q(h)-Q(h')≥ε_Q`。不得看完结果后切换局部选择规则或主判据。

现有六点池与 v2 二十点池各自的前沿和 decision witness 分开报告，但只作辅助；P0、P1 的机制预测仍分别只在
其各自池内判定，不用另一池的候选改写预测成败。

SQNR 的辅助报告固定为：在 calibrated local `SQNR≥S*` 的候选中选最小面积点，并报告它相对相同候选池
`(Q,area)` 选择的 quality / area regret。该结果用于解释决策，不替代主 Pareto 判据。

两种判据都要求满足相同的 overflow / alias / 接口硬约束。所有综合失败、超时和非法候选计入尝试预算。
面积流程若重复运行完全确定，比较采用严格 cell-area 次序；只保留解析/序列化容差，不把工具波动臆造为统计噪声。

## 6. truth 前必须完成的评价器前置项

这里只登记，不在本步骤修改：

1. `metrics.py::spectral_prediction`：抽取折叠索引从相邻频点分组改为正确的 alias preimage；
2. `metrics.py::sfdr_db`：修正 Blackman–Harris 主瓣排除，并用已知杂散/理想单音校准；
3. `spectral_prediction` 与 `run_s1.py`：统一误差对象、频带、参考功率、前导、暖机和测量段；
4. `run_s1.py::worst_drop`：修正 `kept` / `dropped` 标签反置；
5. `run_s1.py` NCO 轨迹 SQNR：禁止把实数两列误当复数两字段合并；
6. 排序统计：补 Kendall tau-b、任一最优命中率和全并列保留率；
7. `scenarios.py::qpsk_symbols`：统一声明与实际平均功率；
8. `scenarios.py` AWGN：SNR 必须相对 desired signal，而不是 signal + blocker；
9. 场景生成：暴露 desired / blocker / noise 分量与共同峰值缩放因子，支持 §3 的分母；
10. 复标量对齐：按 §3 只在前导段相对同输入完整 `y_ref` 估计 `g`，并验证 `y_h=y_ref` 时严格得到
    `g=1`；不得改为 desired-only 投影，也不得在测量段重拟合；
11. 对齐：把输入 sequence tag、输出 valid mapping、抽取相位和测量索引写入 manifest；
12. 版本化：新频移栅格与 0.555 MHz alias stress 生成新场景版本，旧产物保留；
13. 校准：用 exact-representable 零误差例确定 `q_cal`，再冻结最终 `ε_Q`。

修复必须登记到 `AUDIT.md`；旧 420 对和旧 SFDR 数只保留为历史诊断，不作验收目标或论文结论。

---

## 附录 A：独立物理预测（truth 前）

### A.1 预测的污染声明

这不是严格意义上的双盲预测。写作前我已经知道：

1. 旧评价器报告过 420 对错筛，但该结果受折叠索引、SFDR 和真值口径缺陷影响，只能作为诊断；
2. standalone kernel 全枚举曾给出约 36.98–96.01 dB 的范围，且 `n1/n2`、`n3/n4` 在
   `cert_metrics` 下分别同分；这些数字不在本预测中作为系统结论；
3. 已阅读 `candidates.py`、`tpl_cordic.py`、`fixed_chain.py`，知道六个候选的结构和当前模型边界；
4. 在搜索契约字段时意外看到了 Claude 预测文件的少量非候选特定文字：它讨论 whole-band 与 symbol-domain
   `q` 的取舍、某一未见名称的 “W1” margin 可能偏薄，以及 `+10 dB` blocker 的风险。我没有看到其候选对，
   也没有继续打开该文件。此污染已在写作前向用户和 Claude 披露。

因此本节准确名称是**独立、理论驱动、预注册预测**，不是 blind result。

### A.2 六个候选的先验判断

| 候选关系 | 物理判断 | witness 价值 |
|---|---|---|
| `n1` vs `n2` | LUT256 nearest 主要由 8-bit table address 决定；在三角折叠象限边界，16-bit 低位可能通过减法借位改变相邻表项，因此不能宣称逐位恒等 | 差异稀疏且同结构，不优先作跨结构 witness |
| `n3` vs `n4` | LUT1024 linear 的当前 standalone metric 未纳入 `phase_bits`，但全 NCO 中 12/16-bit phase path 可能不同 | 若出现 collapse，首先说明局部指标边界漏项；只作辅助，不当跨结构主证据 |
| `n5` vs `n6` | 同为 CORDIC，更多 stages / phase bits 通常同时改善局部和系统误差 | 更像成本—质量单调对，不优先预测 reversal |
| `n1/n2` vs `n5/n6` | nearest LUT 与 CORDIC 的局部质量差距大；宽栅格 worst 很难让低精度一方稳定反超 | 可能有单点 crossover，但不优先作部署 witness |
| `n3/n4` vs `n5/n6` | 两类候选可有不同的、与 FCW 相干的周期误差谱；局部总功率排序不保证经过固定 H/D 后保序 | 最有希望出现 contract-level failure |

不采用“CORDIC 误差近似白噪声”这一未经证明的说法。LUT 插值和 CORDIC 都可能产生
candidate-dependent coherent spectra，必须由 candidate-exact 复残差基线 ③ 检验。

### A.3 主预测

**最可能出现排序符号变化、但未必达到 witness 阈值的对：`n4_lut1024lin_b16` 与
`n6_cordic16_b16`。**

方向预测：公平局部 SQNR 倾向把 `n4` 排在 `n6` 前；WCE 与 last-bit accuracy 的方向不预判。
在预注册的 `C_main` 栅格 worst 聚合下，`n4` 的某个相干误差线可能更不利地落入固定 FIR/抽取后的
有效带，而 `n6` 的主要误差分量更多落入被抑制区域，从而出现 `Q(n4) > Q(n6)`。选择这一对的理由是
二者同为 16-bit phase path，减少把 phase-bit 覆盖缺口
误当成 architecture effect 的风险。

对主契约“9 点 `C_main` 上的 worst”，符号反转置信度为**低到中**；达到 `ε_Q` 的置信度为**低**。
两者都是高精度候选，按局部误差量级估算，它们的 `Q` 差很可能低于面向 0.01 dB 增量损耗的 `ε_Q`。
因此对现有六候选池的总体先验改为 **E0 更可能**，`n4/n6` 只保留为机制符号预测，不能预称
strict reversal。若只在某个事后挑出的 FCW 上反转而在预注册 `Q` 下不反转，也应判 E0，不能缩窄栅格救结论。

机制分支预测：

- no-blocker / `−3 dB`、且下游不饱和时，若出现反转，更可能由基线 ③ 的 candidate-exact 复残差
  加 `diag(x)·H·D` 相干传播解释，即倾向 **E1**；
- 只有当 ③ 相对全链 truth 的排序或 regret 未过 Gate，而误差分解把差异定位到 CMUL/FIR round/sat residual
  及交叉项时，才进入 **E2**；
- `+6 dB` stress 下发生的饱和不能单独支撑 E2，除非它先被证明属于真实部署可行域。

### A.4 辅助预测与反证条件

1. `n3` vs `n6` 也可能表现为局部排序失败，但风险较高：`n3` 的 12-bit phase path 没有进入当前
   standalone metric，结果可能只是指标定义遗漏，不是多速率上下文造成的反转。
2. `n3` vs `n4` 最可能给出当前 metric 的 collapse；只有重定义为完整 NCO 局部映射后仍同分、而链级
   `Q` 分开，它才是合格的 non-identification witness。
3. `n1` vs `n2` 若出现明显 `Q` 差异，先核对三角折叠借位所致的稀疏表项变化能否解释；未解释前不写成
   architecture-level 发现。
4. 若全部预注册指标在主 `Q` 上保序，或差异小于 `ε_Q`，接受 E0；若只有 mechanism witness 而没有
   同面积预算下的 decision witness，只能报告机制，不能声称造成设计损失。
5. 若基线 ③ 已解释所有反转，评价理论结果是 E1：贡献只能落到结构特异模型的自动装配、联合搜索与实现证据，
   不能声称新的 round/sat 误差模型。

### A.5 预测完成后的交换规则

本文件保存后才允许阅读 `WITNESS_PREDICTION_DDC.md`。两份预测比较时：

- 一致项进入冻结版预测，但不提高统计置信度；两份分析并非独立数据；
- 分歧项并列保留理由，不投票、不用旧诊断数字裁决；
- 在修评价器、冻结 manifest 和阈值之前，不运行 truth；
- 运行后无论落入 E0、E1、E2 或 E3，均保留原预测和偏差说明，不覆盖。

### A.6 交换后的事实校准记录

读取 Claude 版预测后，我重新核对 `_emul_lut`：原稿曾写 `n1/n2` “bit-true 输出相同”，这一句过强。
nearest 虽忽略区间内插值余数，但三角折叠的 `0x8000-prs` 会让低位通过借位影响少量边界表项。
上表与 A.4 已改成限定表述。此校准不改变主预测对 `n4/n6`，但作为交换后修订明确登记，不能冒充盲预测内容。

Claude 还指出两项会改变契约而非只改变预测的校准：(1) `ε_Q` 的工程量级使高精度 `n4/n6` 很可能只能
产生亚阈值符号变化；(2) raw `q` 会被 floor phase truncation 的常数相位偏置主导。本文据此把现有池先验
降为 E0 更可能，并选择前导段上相对同输入完整 float reference 的单复标量对齐作为主评价语义。两项均发生在
交换之后，已显式登记。
