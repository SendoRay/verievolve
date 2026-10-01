# SEARCH_PROTOCOL_v1.md — 开放结构联合搜索协议（草案）

- 建立日期：2026-09-30
- 状态：**v0.1 草案，尚未冻结，不得据此启动正式搜索**
- 上位方向：[`PROPOSAL_v1.md`](PROPOSAL_v1.md)
- 评价契约：[`CONTRACT_DDC_v1.md`](CONTRACT_DDC_v1.md)
- 已知评价结论：DDC witness 为 E1；见
  `examples/comm_dsp_bench/experiments_system/ddc_witness_v1/baseline3_v1/results.json`
- 实现进度：WP1–WP3 已通过；WP4 的 bit-true / 流式 RTL 对拍与 Yosys 结构检查已通过；WP5
  已形成可编程 FCW 的完整 DDC 模型—RTL最小闭环。冻结场景评价、Nangate45 面积综合与 R4 正式
  签字尚未进行。

## 1. 本阶段到底要回答什么

本阶段只回答一个 go/no-go 问题：

> 在同一个可组合的硬件表示、同一候选评估预算和同一 held-out 契约下，链级 numerical fitness
> 能否使联合结构搜索找到固定结构字长优化、分阶段选择和强通用搜索基线没有找到的
> 质量—综合面积折中？

这是 `PROPOSAL_v1.md` 的 Search axis。DDC 首轮结果已经说明：

- 局部 SQNR / WCE / SFDR 的确可能不保序；
- candidate-exact 线性传播基线能解释已登记的全部反转，评价轴为 E1；
- 现有 26 点 NCO 池没有 decision witness。

因此，不能在现有 `PARAMS` 字典或 26 点池上再跑一次进化并称为结构搜索。下一步必须同时满足：

1. 候选表示是组合式的，不是模板编号；
2. NCO 与 FIR / 抽取至少各有两个真实结构类；
3. numerical fitness 评价的是冻结 DDC 契约，而不是局部 kernel 指标；
4. 强非 LLM 方法与 LLM 使用相同表示、合法动作和预算。

## 2. 候选表示：F2.5 typed design IR

### 2.1 外部语义

输入仍是数学公式与部署契约。DDC v1 的外部语义固定为：

```text
phase_accumulator -> sincos -> complex_multiply -> FIR -> decimate(R=2)
```

接口格式、FCW、抽取相位、场景集合、主质量量 `Q=max_c q_c`、`q_budget` 与 `epsilon_Q`
沿用冻结契约。候选不得修改外部任务来换取面积。

### 2.2 IR 分层

IR 必须把三类对象分开：

1. **实数语义节点**：公式和精确分解；
2. **近似实现原语**：LUT、插值、CORDIC、定点 FIR 等；
3. **定点语义节点**：格式、舍入、截断、饱和与状态。

近似原语不得并入“精确等价”类。精确重写只证明实数语义等价；候选最终质量一律由 bit-true
实现及冻结链级契约评价。

### 2.3 v1 必须支持的结构自由度

| 层 | v1 自由度 | 至少两个真实结构类的要求 |
|---|---|---|
| NCO / sincos | quarter-wave LUT；LUT + interpolation；rotation CORDIC；各自的相位位宽、表深 / 级数 | LUT 与 CORDIC；LUT 内 nearest 与 interpolation 另记子类 |
| FIR / decimator | direct symmetric FIR；polyphase decimator；系数字长、乘积保留位、累加位宽、舍入位置 | direct-symmetric 与 polyphase 的状态更新和运算调度必须真实不同，不能只是标签 |
| complex multiply | v1 先固定数值结构；定点格式、舍入和饱和由公共 lowering 明示 | 不把 direct / Karatsuba 的整数域位恒等写成数值结构多样性 |
| rate change | 抽取率与相位属于契约；实现可由 direct-filter-then-decimate 或 polyphase lowering 承担 | 两种 lowering 在实数语义下等价，并分别做 bit-true / RTL 对拍 |

微结构中的流水、共享和握手调度暂不作为搜索自由度；它们由确定性后端生成。若以后纳入，必须先扩充
IR 类型与合法性规则，不能让 LLM 直接插入任意 RTL。

“可组合”不能只意味着从上述每行各选一个模板。v1 至少要有一个能递归组合、并由通用 lowering 处理的
结构构造器。NCO 首选下面这条精确恒等式作为最小实例：

```text
exp(j * theta) = exp(j * theta_coarse) * exp(j * theta_residual)
theta = theta_coarse + theta_residual
```

其中 coarse 与 residual 可分别由 LUT、CORDIC 或小区间 polynomial 原语实现，形成 coarse-LUT + residual-
CORDIC / polynomial 等未逐个登记的组合。FIR 的 direct-symmetric 与 polyphase 也必须由同一 filter / rate
语义节点 lowering，而不是在候选表里写两个互不相关的生成器入口。

一个新结构若仍需为该组合增加专用 `if candidate_name == ...` 分支，便不满足本协议的开放结构定义。
表示 gate 会保留至少一个**不在初始种群和手写候选表中**的组合，仅通过已有构造器生成并完成 bit-true / RTL
验证，用它检查组合能力不是标签包装。

#### phasor-compose v1 的冻结候选语义

设 32 位无符号累加器状态为 `a`，coarse 位数为 `K=split_bits`，`S=2^(32-K)`。采用最近 coarse
格点，并把残差唯一映射到半开区间 `[-S/2,S/2)`：

```text
q   = floor((a + S/2) / S) mod 2^K
a_c = (q * S) mod 2^32
r   = signed_mod(a - a_c, 2^32) in [-S/2, S/2)
a_r = r mod 2^32
```

coarse 子节点读取 `a_c`，residual 子节点读取 `a_r`。两者各自产生 Q1.15 的 `(cos,sin)`，再按复数乘法

```text
cos = cos_c*cos_r - sin_c*sin_r
sin = sin_c*cos_r + cos_c*sin_r
```

右移 15 位并按节点声明的 `rne`（沿用仓库现有 half-up 整数语义）或 `trunc` 处理，最后饱和到 Q1.15。
实数层恒等式对 modulo-`2π` 相位成立；子节点近似、乘法舍入与饱和属于实现误差，不以精确重写名义消除。
v1 只允许一层 compose，两个子节点均为叶子；递归深度扩展另行审计。

### 2.4 候选的规范形态

候选以可规范化的 JSON / Python AST 表示，至少包含：

- `formula_version`、`contract_version`；
- 有类型节点及有向边；
- 每条边的 signedness、整数位、小数位和 rate；
- 每个近似原语的结构参数；
- 每个量化点的 rounding / saturation 语义；
- 状态节点的初态与更新顺序；
- 规范化后的结构哈希。

同一规范化结构的重复提案仍计入提案预算，但评价与综合结果可以缓存。这样缓存只节省墙钟时间，
不会免费掩盖提议器的重复和无效率。

## 3. 合法动作与 proposer 公平性

LLM、GP、beam 和 MCTS 共享同一组原子动作：

1. 替换一个近似原语的结构类；
2. 应用一条已验证的实数等价分解；
3. 修改一个原语参数或定点格式；
4. 插入、移动或删除一个显式量化点；
5. 在合法边界内改变舍入 / 饱和策略；
6. 对 FIR 应用 direct-symmetric / polyphase 结构变换。

每个动作先过 schema、类型、rate、范围和状态合法性检查，再进入 bit-true lowering。所有 proposer 的：

- 初始种群；
- 动作集合；
- 候选评估数；
- archive / selection 规则；
- 缓存；
- held-out 终考；

必须一致。语法错误、类型错误、lowering 失败、仿真失败和综合失败都计为一次提案尝试并记录原因。

LLM 只输出 IR 或 IR patch，不直接写自由 Verilog。它的可能优势来自公式条件化的组合提案与对诊断的
解释能力；这只是待检验假设，不写进结论。

## 4. 两种反馈信号

### 4.1 numerical fitness

主质量量沿用 DDC 契约：

```text
q_c(h) = implementation NMSE on scenario c
Q(h)   = max over C_main of q_c(h)
```

搜索目标是 `(Q, post-synthesis area)` Pareto，硬合法性与外部协议为约束。开发期允许使用 E1 已验证的
candidate-exact 线性传播作训练评价，但正式终考必须用 full-chain bit-true truth；若训练评价扩展到新
FIR 结构，必须先重新通过 Gate A / Gate B，不能沿用 NCO-only 的通过结论。

### 4.2 Boolean satisfaction fitness

主对照不使用“与实数公式逐位完全相等”这种必然全失败的稻草人。对每个主场景冻结：

```text
v_c(h) = 1[q_c(h) <= q_budget]
satisfaction(h) = sum_c v_c(h)
```

它与 numerical 臂使用同一场景、同一 per-scenario `q_c` 和同一硬件成本，但只向搜索器暴露 verdict / pass
count，不暴露失败幅值、最差余量或误差谱。strict exact-match 只作诊断，不进主 2×2。

## 5. 强基线与实验顺序

### 5.1 搜索基线

至少包含：

1. **staged WLO**：先按局部 kernel 指标定结构，再在固定图上调字长；
2. **Chassis-like extraction**：实数等价候选按可加成本提取，再在整候选上检查数值质量；
3. **同语言 GP**：共享 §3 动作与全部合法性规则；
4. **beam 或 MCTS**：至少一种显式保留多条结构路径的强搜索器；
5. **可枚举切片**：只用于验证搜索实现是否漏掉已知最优，不作为开放空间主结果。

uniform random 可以报告，但不能作为唯一非 LLM 对手。e-graph 只承担精确重写的紧凑表示和规范化；v1
先让 typed AST 管线闭环，e-graph 的收益另做消融，不能让它成为启动 S1 的阻塞项。

### 5.2 分阶段执行

1. **R0 协议冻结**：本文件、IR schema、动作表、fitness 与停止条件审阅通过；
2. **R1 表示与 lowering**：同一 IR 同时生成 bit-true 模型和 RTL；
3. **R2 结构可信性**：每个 primitive / rewrite / lowering 逐位或按冻结 trace 对拍；
4. **R3 非 LLM pilot**：枚举切片、GP、beam / MCTS，检查实现公平性并估计运行方差；
5. **S gate**：正式多种子 numerical search 对 staged / cost-first 基线；
6. **L gate**：只有 S1 后才运行完整 proposer x fitness 2×2；
7. **D gate**：within-LLM 标量反馈与诊断反馈；若要声称诊断为 LLM 特有，再补非 LLM + 诊断。

pilot 只能决定预算和正式 seed 数，不得用于选择成功阈值、任务或报告最有利的候选。

## 6. Go / no-go 判据

### 6.1 表示 gate（全部通过才可搜索）

- `R1`：所有候选可规范化，结构哈希稳定；
- `R2`：实数等价 rewrite 通过独立语义检查；
- `R3`：bit-true 模型与 RTL 在声明输入空间 / 冻结 trace 上满足预注册一致性；
- `R4`：至少 2 个 NCO 结构类和 2 个 FIR / decimator 结构类通过合法性与综合；
- `R5`：同一候选在 numerical 与 satisfaction 臂的唯一差别只有反馈统计量。
- `R6`：至少一个未手工注册的组合结构由通用构造器产生，无专用 generator 分支，并通过 bit-true / RTL
  一致性检查。

### 6.2 S1：联合数值搜索是否真正改善前沿

主判据在 held-out truth 上计算。相对于 staged WLO 与 cost-first extraction 的预注册基线前沿，至少出现
一个具有工程余量的新点：

- 在同一质量预算下，面积至少改善 `epsilon_A`；或
- 在同一面积预算下，`Q` 至少改善 `epsilon_Q`；
- 且正式多种子运行的归一化 Pareto hypervolume 差的 95% 区间下界大于 0。

`epsilon_Q` 沿用 DDC 契约。`epsilon_A` 在综合重复性校准后冻结，建议取“面积口径重复波动上界”与
“参考可行设计面积的 1%”二者较大值；冻结后不得按结果缩小。

若不满足，记为 S0：停止 LLM 独特性主张和第二条链扩展，保留 E1 机制、benchmark 与负结果。

### 6.3 L / D 判据

- `L+`：完整 2×2 中，numerical feedback 对 LLM 的增益显著大于其对强非 LLM proposer 的增益；
- `L-`：交互项不满足预注册阈值，LLM 降为可替换搜索器；
- `D+ / D-`：只比较 LLM numerical 与 LLM numerical + diagnostics；不自动推出 LLM 特有性。

正式统计量、预算、seed 数与置信区间算法在 R3 pilot 后、正式运行前追加并冻结。

## 7. 立即实施的文件边界

协议冻结后，第一批代码只建立基础设施，不调用外部 LLM：

```text
examples/comm_dsp_bench/search_ir/
  schema.py          # typed AST 与 canonical serialization
  validate.py        # type/rate/range/state 合法性
  actions.py         # 所有 proposer 共用的原子动作
  lower_bittrue.py   # IR -> Python integer model
  lower_rtl.py       # IR -> deterministic synthesizable RTL
  canonicalize.py    # 精确重写后的规范化与结构哈希

tests/
  test_search_ir_schema.py
  test_search_ir_actions.py
  test_search_ir_bittrue_rtl.py
```

先接入现有 NCO 原语作为端到端 smoke，再实现 direct-symmetric 与 polyphase FIR / decimator。只有 R4 通过，
才接 OpenEvolve / GP / beam / MCTS；只有 S1 通过，才接真实 LLM 后端。

## 8. 明确不做什么

- 不在 26 点 NCO 池上把模板选择包装成开放结构生成；
- 不用 exact-match 全失败制造 numerical fitness 的虚假优势；
- 不把 e-graph、LLM 或 MAP-Elites 本身写成贡献；
- 不让 proposer 各用不同语言、动作或免费失败预算；
- 不在新 FIR 结构上未经验证复用 NCO-only 的 E1 模型结论；
- 不在 S0 后继续扩大目录或挑第二条链寻找阳性结果；
- 不把流水、资源共享和时序优化纳入 v1 搜索主张。

## 9. 当前实现盘点与首批工作包

| 能力 | 当前实物 | 缺口 | 首批动作 |
|---|---|---|---|
| NCO bit-true | `certfit/tpl_cordic.py`、`chains/ddc/fixed_chain.py` | 接口是参数字典，不是组合树；无 phasor-compose | 包装为按 node kind 分派的 lowering；不按候选名分派 |
| NCO RTL | `design_gen.py`、`chains/ddc/rtl_gen.py` | LUT / CORDIC 各自整段生成；组合必须写新专用代码 | 拆成可组合 module / expression lowering，并加入结构哈希 |
| FIR bit-true | `chains/ddc/fixed_chain.py::fir_fixed` | 只有 direct 数值路径；无显式 polyphase 状态语义 | 先写 direct-symmetric 与 R=2 polyphase 的同口径模型并对拍 |
| FIR RTL | `chains/ddc/rtl_gen.py::_gen_fir` | `prod_drop==0` 隐式切换对称实现，结构身份与数值参数耦合 | 将 structure 与 quantization 解耦为两个 IR 字段 |
| DDC truth | `chains/ddc/run_witness_v1.py` | runner 只接受冻结候选表 | 改为读 candidate manifest / 结构哈希，保留场景与 q 定义 |
| E1 训练评价 | `chains/ddc/run_linear_baseline_v1.py` | 只验证了 NCO 变化 + 固定 FIR | 每增加一个 FIR 类，重新做 Gate A / B；失败则训练直接用 truth |
| 综合 | witness 的 NCO-only 与 `rtl_gen.gen_ddc_verilog` | 搜索需要候选全链 area；暂无统一 IR cache key | 以结构哈希 + 工具链哈希作综合缓存键 |
| proposer | OpenEvolve 当前修改 `PARAMS` | 不能表达组合结构；暂无同语言 GP / beam / MCTS | 先实现公共 action API 与非 LLM proposer，再接 OpenEvolve |

工作包顺序：

1. `WP1 schema`：类型、节点、canonical JSON、hash、非法例测试；
2. `WP2 NCO smoke`：现有 LUT / CORDIC 经 IR lowering 后与旧模型、旧 RTL 逐位一致；
3. `WP3 composition`：phasor-compose 生成一个未注册混合结构并完成模型—RTL 对拍；
4. `WP4 multirate FIR`：direct-symmetric / polyphase 模型、RTL、状态与延迟契约；
5. `WP5 evaluator`：IR 候选进入冻结 DDC 场景、full-chain q 与全链综合；
6. `WP6 baselines`：枚举切片、staged WLO、GP、beam / MCTS；
7. `WP7 pilot/freeze`：只校准预算和 seed 数，随后签发正式 search manifest；
8. `WP8 formal S`：判 S0 / S1；S1 后才实现 LLM proposer 和完整 2x2。
