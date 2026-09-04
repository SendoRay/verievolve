# CommDSP-Bench 规格

- 版本: v0.1（2026-09-04）
- 状态: P0 任务清单已确认（cmul / cordic_sincos / nco / fir），待 PoC 验证
- 定位: 本文件是基准集实现与论文实验的共同依据。实现细节与本文冲突时，以本文为准；本文修改需同步论文实验章节。

---

## 1. 定位与目标

从数学规范直接进化通信 DSP 硬件（Verilog），输出**精度–PPA Pareto 前沿**。

与现有工作的差异（一段话口径）：

> EvolVE 与 REvolution 的正确性是二值门槛（全测试通过或 −∞/C_penalty）、适应度是标量（AT 积或相对参考设计的加权和）、依赖人工提供的 golden model；CommDSP-Bench 以数学规范自动生成 golden model 与随机激励，以连续精度指标（SQNR / SFDR / FER）为可谈判的搜索维度，以 MAP-Elites 一次运行输出整条 Pareto 前沿。

## 2. 设计原则（P1–P5）

- **P1 锁定外部，放开内部**：任务规范只锁接口协议、功能语义、定点格式、精度指标定义。算法选择、内部位宽、流水深度、存储结构、系数量化全部是搜索自由度。
- **P2 统一握手接口**：所有任务共用流式 valid/ready 协议。输出有效由 DUT 自己声明，测试框架按握手收数，**流水延迟自动对齐**——全并行与迭代串行设计严格可比。
- **P3 约束最少化**：吞吐等性能量默认**不设硬门**，作为 Pareto 维度由搜索探索。硬约束只允许两类用途：feasibility（能跑通）与评估成本防护（超时）。**任何硬约束进入正式 schema 前，必须书面论证"为什么它不能作为 Pareto 维度"**。
- **P4 防作弊内建**：每次评估 fresh seed 激励 + golden 现算；终考用独立分布 held-out；联合指标中面积维度自带记忆化惩罚（小输入空间任务背题 ROM 的面积是真实实现的 10–100 倍，在 Pareto 口径下自动出局）。
- **P5 可扩展注册制**：metric 类型、约束类型、激励分布、接口扩展信号均为注册表条目而非硬编码。新增任务默认只写任务卡；新增能力加注册条目，不动内核（见 §10）。

## 3. 任务规范格式（spec_version: 1）

### 3.1 目录结构

```
examples/comm_dsp_bench/
  SPEC.md                  # 本文件
  tasks/
    cmul/task.yaml
    cmul/initial_program.v
    cordic_sincos/task.yaml
    cordic_sincos/initial_program.v
    nco/task.yaml
    nco/initial_program.v
    fir/task.yaml
    fir/initial_program.v
  evaluator.py             # 通用评估器（解析 task.yaml，按 COMMDSP_TASK 环境变量选任务）
  config.yaml              # OpenEvolve 配置（任务间共用）
  run_experiments.py       # 多 seed 统计框架（运行 + 前沿提取 + 精确 3D 超体积）
```

### 3.2 task.yaml 字段定义

```yaml
spec_version: 1
task: cordic_sincos

spec: |
  # 数学规范全文（LaTeX/文字）。这是进入 LLM prompt 的唯一任务描述。
  # 禁止出现任何算法提示（见 §9 提示泄漏禁令）。

io_protocol:
  base: stream_v1            # §4 定义的统一握手协议
  inputs:                    # 端口列表
    - {name: z, width: 16, format: "signed Q1.15, 单位 rad, 范围 [-pi, pi)"}
  outputs:
    - {name: sin_out, width: 16, format: "signed Q1.15"}
    - {name: cos_out, width: 16, format: "signed Q1.15"}
  extensions: []             # 可选: ["frame_marks", "multichannel", "sideband"]，见 §10.3

golden:
  stimulus:
    distribution: uniform_angle      # 激励分布注册表条目，见 §10.1
    samples: 65536
    seed: fresh_per_eval
  reference:
    impl: "numpy.sin / numpy.cos on float64"   # golden 实现说明（不进 prompt）

metric:
  type: sqnr                  # metric 类型注册表条目，见 §5.1
  params: {}                  # 类型特定参数

constraints: {}               # 默认为空。允许的条目见 §6，启用需过 P3 论证

timeouts:
  L1: 5                       # 秒，冒烟仿真
  L2_sim: 30                  # 秒，全量仿真
  L2_synth: 180               # 秒，综合
```

## 4. 接口协议 stream_v1

### 4.1 信号定义

| 信号 | 方向 | 语义 |
|---|---|---|
| `clk` | in | 时钟。名义频率仅用于报告，不构成约束 |
| `rst_n` | in | **同步**复位，低有效。释放后 DUT 可经任意延迟开始输出 |
| `in_valid` / `in_ready` | in/out | 输入侧握手 |
| `in_*`（每个 inputs 条目） | in | 输入数据，位宽与定点格式由任务卡定义 |
| `out_valid` / `out_ready` | out/in | 输出侧握手 |
| `out_*`（每个 outputs 条目） | out | 输出数据 |

### 4.2 语义细则

- 复位期间及复位后未置起 `out_valid` 期间，输出值不定，测试框架**不采样**，只认握手
- 一个 `out_valid` 拍对应一组完整的 `out_*`（多字段输出同拍给出，如 sin 与 cos）
- 允许任意内部缓冲；反压行为（`out_ready` 拉低时 DUT 不得丢数据）计入正确性
- DUT 不得假设激励间隔（测试框架可插入随机气泡周期，L2 层启用，比例 10%）

### 4.3 为什么这是基石

- 不同流水深度/迭代次数的设计**无需延迟检测即可比对**
- 竞品 testbench 均按特定模块延迟定制，换结构即失效；本协议一次定义处处可比
- 吞吐在接口层**实测**（M 个样本消耗的总周期数，含气泡与反压），无需 DUT 自报

## 5. 指标体系

### 5.1 精度指标注册表

| type | 定义 | 适用任务 | 状态 |
|---|---|---|---|
| `sqnr` | 见 5.2 | 函数/滤波类（cmul, cordic, fir, farrow, fft） | v1 内置 |
| `sfdr` | 见 5.3 | 振荡器类（nco） | v1 内置 |
| `fer` | 给定 SNR（AWGN+BPSK）下的误帧率 | 译码类（ldpc, P2） | v1 预留 |
| `detection_pd` / `settling_time` | 检测概率 / 收敛时间 | 闭环/检测类（未来） | 未定义，走 §10 注册流程 |

### 5.2 SQNR（信号量化噪声比）

对 M 个样本，golden 输出 \(y_i\)（float64），DUT 输出 \(\hat{y}_i\)（按任务卡定点格式解释后转 float64）：

\[
\text{SQNR} = 10 \log_{10} \frac{\sum_{i=1}^{M} y_i^2}{\sum_{i=1}^{M} (y_i - \hat{y}_i)^2} \;\text{dB}
\]

- 多字段输出（如 sin/cos、I/Q）：逐字段计算后取**最差值**
- M = 65536 时估计误差 < 0.05 dB（白噪声类激励下）
- 溢出/饱和：输出超出定点格式可表示范围按饱和值解释，不判死——饱和误差自然计入 SQNR

### 5.3 SFDR（无杂散动态范围）

振荡器类任务：对每个测试激励配置（如 NCO 的每个 FCW 值）取 65536 个连续输出样本，加 Blackman-Harris 窗做 FFT：

\[
\text{SFDR} = P_\text{tone} - \max_{k \notin \text{mainlobe}} P_k \;\text{dB}
\]

- 主瓣屏蔽：主音 ±8 bin
- 多个测试配置取 **worst-case SFDR**（通信口径）
- 测试配置集合在任务卡中固定（如 nco 的 7 个 FCW 值覆盖频率范围）

### 5.4 硬件指标

| 指标 | 来源 | 口径 |
|---|---|---|
| 面积 | Yosys `synth` + Nangate45（ABC） | μm²（主口径，对齐 REvolution 的开源流程） |
| FPGA 资源 | Yosys + nextpnr ECP5 | LUT / FF / DSP / BRAM 计数（辅助口径） |
| 周期数 | 接口层实测 | M 样本消耗总周期数 |
| 吞吐 thr | 接口层实测 | 样本/周期（含气泡与反压） |

时序声明克制：只报周期数与固定时钟约束下的综合面积，**不用开源工具输出 Fmax 结论**。

### 5.5 搜索层指标（论文报告用）

- **主指标：Pareto 超体积 HV**。目标向量（最小化）\((-\text{precision}_{dB},\, \text{area},\, -\text{thr})\)，各维按任务固定常数归一化到 [0,1]，参考点 \(r_t\) 每任务固定并随基准发布。报告 HV vs 预算曲线（节点数 / token / 综合次数）
- **等约束点**：
  - \(A_{\min}(\epsilon, \tau) = \min\{ \text{area}(D) \mid \text{precision}(D) \ge \epsilon,\ \text{thr}(D) \ge \tau \}\)
  - \(Q_{\max}(A, \tau) = \max\{ \text{precision}(D) \mid \text{area}(D) \le A,\ \text{thr}(D) \ge \tau \}\)
- **多样性**：占用 MAP-Elites 网格单元数

## 6. 约束模型

### 6.1 硬约束 vs Pareto 维度（显式分离）

```yaml
constraints:
  throughput_floor: {samples_per_cycle: null}   # 硬吞吐下限（默认不启用）
  iteration_cap: null                            # 统计类任务迭代/帧预算上限
  resource_budget: {lut: null, bram: null, dsp: null, area_um2: null}
```

- P0 全部任务 `constraints: {}`——无任何硬门，靠超时兜底评估成本
- 任何条目从 null 改为生效值，须在任务卡中附 P3 论证（为何不能作为 Pareto 维度）
- 预期使用场景：`iteration_cap`（LDPC 评估成本）、`resource_budget`（FPGA 物理上限实验）

### 6.2 Feasibility 门（不属于 constraints，恒定生效）

L0 语法/可综合性、L1 冒烟、超时——这些是"能评估"的门，不是设计空间的约束。

## 7. 评估协议

### 7.1 Cascade 三层

| 层 | 内容 | 预算 | 失败处置 |
|---|---|---|---|
| L0 | Verilator `--lint-only`（或 iverilog 编译检查） | 毫秒 | 弃，记 parse_error |
| L1 | 冒烟：编译 + 256 随机样本 + 粗一致性（SQNR > 10 dB 或逐样本误差 < 1/8 满量程） | ≤ 5 s | 弃，记 smoke_fail |
| L2 | 全量 65536 样本（含 10% 气泡周期）+ Yosys/Nangate45 综合取面积 | 仿真 ≤ 30 s，综合 ≤ 180 s | 弃，记原因 |

仅 L2 通过的个体进入程序数据库与 MAP-Elites 网格。

### 7.2 终考协议（仅最终 Pareto 前沿个体）

- fresh seed + **独立分布**激励 ≥ 10⁶ 样本：
  - fir：带限 QPSK 符号流替换白噪声
  - nco：非默认 FCW 集合
  - cordic：角度分布偏向小角度与 ±π 邻域
- 结果进论文附表；终考指标劣化超过 3 dB 视为过拟合，标记并在正文报告

### 7.3 防作弊协议

1. 激励每次评估 fresh seed 现生成，golden 现算，无固定向量可背
2. 联合 Pareto 口径下，记忆化 ROM 面积惩罚使其自动出局（见 P4）
3. 可选辅助检测：Yosys stat 中的 ROM 推断报告（不作主防线）

### 7.4 统计规范

- 每任务 × 每方法 ≥ 5 seeds；HV 与等约束点报均值 ± 标准差
- 方法两两 Wilcoxon 符号秩检验
- 预算三口径强制报告：LLM tokens、综合调用数、墙钟
- 单次运行的结果不得进主表

## 8. P0 任务卡

### 8.1 cmul（锚点任务）

```yaml
task: cmul
spec: |
  复数乘法器：计算 (a + b·j) · (c + d·j) 的实部与虚部。
io_protocol:
  inputs:
    - {name: a_re, width: 16, format: signed Q1.15}
    - {name: a_im, width: 16, format: signed Q1.15}
    - {name: b_re, width: 16, format: signed Q1.15}
    - {name: b_im, width: 16, format: signed Q1.15}
  outputs:
    - {name: y_re, width: 33, format: signed, 语义: 全精度积的和}
    - {name: y_im, width: 33, format: signed, 语义: 全精度积的差}
golden:
  stimulus: {distribution: uniform_iq, samples: 65536}
  reference: float64 复数乘法（全精度，不量化）
metric: {type: sqnr}
```

- 输出位宽放宽到全精度：定点化截断策略（截断/舍入/收敛舍入）留作自由度
- **角色**：算法空间小，预期各方法逼近同一前沿。用于校准"方法间差异来自搜索空间而非评估噪声"——主表的前置合法性检验
- 结构原型：纯组合数据通路
- **M2 实测观察（2026-09-04，qwen3.8-max，40 迭代）**：进化发现了精度可谈判点（12 位截断 Karatsuba，SQNR 63.6 dB，面积 3244 = 基线 52%），以及满精度最优（999 dB，5620 = 基线 82%）。锚点任务即已呈现精度–面积 Pareto 折中；此类近似设计在二值正确性口径（EvolVE/REvolution）下会被直接拒绝，是框架差异的直观证据

### 8.2 cordic_sincos

```yaml
task: cordic_sincos
spec: |
  计算 sin(z) 与 cos(z)。z 为角度输入。
io_protocol:
  inputs:
    - {name: z, width: 16, format: "signed, 线性编码角度，范围 [-pi, pi)"}
  outputs:
    - {name: sin_out, width: 16, format: signed Q1.15}
    - {name: cos_out, width: 16, format: signed Q1.15}
golden:
  stimulus: {distribution: uniform_angle, samples: 65536}
  reference: numpy.sin / numpy.cos on float64
metric: {type: sqnr}
```

- 结构原型：迭代数值算法（状态机 + 数据通路）
- 算法分支（仅供论文分析，**不进 prompt**）：CORDIC 迭代 / 查表 / 多项式逼近 / 混合；自由度含迭代级数、内部数据路径位宽、范围缩减策略
- 防作弊注意：16 位输入空间 64K 点可被 ROM 背题，但面积维度自动惩罚（P4），另加终考小角度/±π 邻域分布偏置
- **M2 实测观察（2026-09-04，qwen3.8-max，40 迭代，基线 = 64 点最近邻 LUT，24.9 dB / 236 LUT）**：
  - 迭代 3：LLM 自主发明 LUT + 线性插值（61.1 dB / 2544 LUT，+36 dB）——无任何算法提示，纯精度指标驱动
  - 迭代 27/30/38：另一条谱系演化出 ~33.5-34 dB / ~2000 LUT 中间档
  - 迭代 39：128 点紧凑 LUT，30.9 dB / **78 LUT**——全面支配基线（两维均优）；Yosys 利用正弦表结构规律性将共亨压缩至 78 LUT
  - 任务失败率 ~51%（vs cmul ~25%），印证数值硬件变异难度更高，修复环路（哨兵保留）不可或缺
  - 40 迭代未触及 90+ dB（深表/CORDIC 路线），需更大预算——正式实验需多预算梯度

### 8.3 nco

```yaml
task: nco
spec: |
  数控振荡器：FCW 更新后，输出正弦序列，相位按 2*pi*FCW/2^W 每样本累加。
  FCW 在运行中可随时更新，更新在下一输入握手拍生效。
io_protocol:
  inputs:
    - {name: fcw, width: 24, format: unsigned}
  outputs:
    - {name: sin_out, width: 16, format: signed Q1.15}
golden:
  stimulus:
    distribution: nco_fcw_sequence   # 7 个固定 FCW 段 + 段间切换瞬态，任务卡锁定 FCW 集合
    samples: 7 × 65536
  reference: float64 相位累加 + numpy.sin
metric: {type: sfdr}
```

- FCW 段切换的瞬态样本不计入 SFDR 统计（丢弃切换后 64 样本）
- 结构原型：流式状态机 + LUT
- 算法分支（分析用）：LUT 深度 × 幅度位宽、相位截断、1/4 波对称压缩、Taylor 校正、相位抖动
- 24 位相位累加器使状态空间无界，天然免疫记忆化

### 8.4 fir

```yaml
task: fir
spec: |
  16 抽头线性相位低通 FIR 滤波器（截止 0.25·fs）。
  浮点系数如下（任务给定）：
  h[0..15] = <窗函数法生成的 float64 系数，实现时定点化自由>
io_protocol:
  inputs:
    - {name: x, width: 16, format: signed Q1.15}
  outputs:
    - {name: y, width: 40, format: signed, 语义: 全精度累加输出}
golden:
  stimulus: {distribution: gaussian_white, samples: 65536}
  reference: float64 卷积（用连续系数）
metric: {type: sqnr}
```

- **系数定点化本身是搜索自由度**：任务给连续系数，golden 用连续系数计算——这是"两级翻译断裂点"的微缩模型
- 结构原型：流式乘加结构
- 算法分支（分析用）：直接/转置/脉动、分布式算法（全并行 vs 位串行）、对称折叠、多相分解
- 终考激励：带限 QPSK 符号流

## 9. 提示泄漏禁令（新增任务时最高频错误）

任务卡中"算法分支/预期解法"清单**只用于论文分析与结果解读，严禁以任何形式进入 LLM prompt**（包括 system prompt、few-shot 示例、evaluator 反馈文案）。违反即破坏搜索公平性，所有跨方法对比失效。规范评审时逐条检查 prompt 模板与 task.yaml 的 `spec` 字段。

## 10. 可扩展性设计（注册制）

### 10.1 metric 类型注册

新增类型需提交：名称、参数 schema、`compute(stimulus, reference, dut_output) -> float` 实现约定、适用任务类、防作弊分析。示例：`fer`（LDPC，含 seed 管理的统计参考）、`detection_pd`、`settling_time`。

### 10.2 约束类型注册

新增硬约束需提交：名称、检查函数（基于综合/仿真报告）、以及 **P3 论证**（为何不能作为 Pareto 维度）。内置：`throughput_floor`、`iteration_cap`、`resource_budget`。

### 10.3 接口扩展

`stream_v1` 之上的可选扩展（任务卡 `extensions` 字段声明，旧任务零影响）：

- `frame_marks`：`in_sop`/`in_eop` 帧边界（突发类、译码类任务需要）
- `multichannel`：`in_data_ch{k}` 多通道（MIMO）
- `sideband`：带外控制/状态（闭环类）

### 10.4 Pareto 维度

- 默认 3 维 `(precision, area, throughput)`，主表固定
- FPGA 口径可扩为资源向量（LUT/DSP/BRAM 分列），**只进附录**——MAP-Elites 高维稀疏化，主表维度 ≤ 3
- 功耗维度：仅在引入开关活动仿真或商用工具后启用，当前明确不承诺

### 10.5 扩展风险声明

约束模型的扩展风险不在"不够"而在"过死"：新任务作者的默认动作应是"放进 Pareto 维度"而非"加硬门"。P3 论证是唯一的例外通道。

## 11. 与 OpenEvolve 的映射

| 基准机制 | OpenEvolve 载体 |
|---|---|
| Cascade L0/L1/L2 | `evaluator.cascade_evaluation` + `timeout`（多层阈值已有配置项） |
| MAP-Elites 特征维度 | `database.feature_dimensions: [precision, area, throughput]`（自定义 metric 名，per-dimension bins 已支持） |
| 岛屿/迁移 | 不变，默认配置 |
| 进化块标记 | Verilog 注释形式的 `// EVOLVE-BLOCK-START/END` |
| 评估反馈 | evaluator 返回 SQNR/SFDR 数值 + 仿真/综合错误文本（artifact 通道） |

## 12. 版本记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-09-04 | P0 四任务清单确认；spec_version 1 schema；注册制扩展机制；提示泄漏禁令 |
| v0.1.1 | 2026-09-04 | M2 进化验证通过：补入 cmul 锚点任务的精度可谈判观察；评估协议补充失败路径哨兵指标（保留失败个体为父代材料，参照 REvolution Fail population 机制） |
| v0.1.2 | 2026-09-04 | M2 后续：cmul 重跑 A/B（丢弃迭代 25%→5%，首达最优 16→11 迭代，22% 有效程序源自失败父代修复环路）；cordic_sincos 任务接入并完成首轮进化（算法阶梯：最近邻→插值→深表压缩，前沿 5 点跨越 30 dB/33×面积，78-LUT 设计全面支配基线）；初始程序移至 tasks/<task>/ 目录 |
| v0.2 | 2026-09-04 | P0 四任务全部闭环：nco（SFDR 指标落地，基线 35.5 dB/274 LUT）、fir（连续系数金标，基线 85.1 dB/8474 LUT——恰在 Q1.15 系数量化地板，修正基线抽头对齐 bug）；evaluator 支持 sfdr/gaussian_white/nco_fcw_sequence 激励与任务参数化样本数；run_experiments.py 多 seed 框架（精确 3D 超体积，经 5 项单元测试 + 蒙特卡洛交叉验证） |
