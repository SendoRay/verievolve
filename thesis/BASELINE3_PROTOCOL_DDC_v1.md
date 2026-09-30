# DDC candidate-exact linear-reference baseline ③ 冻结协议 v1

- 日期：2026-09-30
- 状态：**已冻结，尚未运行 baseline ③**
- 上游协议：`WITNESS_FROZEN_DDC_v1.md`
- truth：`experiments_system/ddc_witness_v1/runs/formal-v1-20260930/`
- 禁止覆盖：运行后如需修改阈值或对象，建立 v2，不修改本文件

## 1. 目标与身份

基线③检验 observed order-preservation failure 是否已由经典线性物理完整解释。对每个候选 `h`、场景 `c`，
在 NCO 输出接口取得候选自身的 bit-true 复本振，并与共享整数 FCW 的理想本振比较；随后使用同一冻结
`x_adc`、固定 `f1_c16` 的量化系数所定义的线性 FIR 与 phase-0 抽取做相干传播。它保留确定性误差谱、
输入调制、FIR 和抽取 alias 的相位，
但明确排除固定 CMUL/FIR 的 round/sat residual。

该对象是 candidate-exact linear-reference baseline，不是 full-chain truth 的上界或下界。若通过下述工程
容差，只称 **validated approximation / ranking surrogate**；不称对 full-chain bit-true `q` 精确。

## 2. 预测量

对候选复本振

```math
\hat m_h[n]=(\mathrm{cos}_h[n]-j\,\mathrm{sin}_h[n])/2^{15},
\qquad m_c[n]=e^{-j2\pi\mathrm{FCW}_c n/2^{32}},
```

计算

```math
\hat y^{(3)}_{h,c}=D\,H\,(x_{\mathrm{adc},c}\hat m_h),
```

其中 `H` 为冻结 `f1_c16` 的 `hq/2^(wc-2)`（保留系数量化、排除数据通路舍入/饱和），`D` 为
`R=2, phase=0` 抽取。float reference 仍使用 prototype FIR；前导 LS 复标量、desired-only 分母、
`P_c/M_c` 分段与 truth 完全相同，得到线性域 `q3(h,c)`；不得在测量段重拟合，不得对 dB 聚合。

主聚合：`Q3(h)=max_{c∈C_main} q3(h,c)`，并保存 argmax。heldout 使用同式但不参与重新选择或调参；
stress 只作边界报告。

## 3. Gate A：工程绝对精度

阈值直接复用 truth 前已冻结的

```text
epsilon_Q = 2.32929922807541e-6
q_floor   = epsilon_Q
```

对 main+heldout 的全部 `candidate×scenario`：

- 主判据：`max |q3-q_true| ≤ epsilon_Q`；
- 同时报 median / p95 / max 绝对误差；
- 相对误差用 `max(q_true,q_floor)` 作分母，只作诊断；
- nearest LUT、linear LUT、CORDIC 三类分别报告，任一类 max 超阈即 Gate A 不通过；
- stress 分层报告，但不决定 Gate A。

该阈值是已有 0.10 dB 实现损耗分配的 10%，不是根据 baseline 输出校准的统计阈值。

## 4. Gate B：契约选择有效性

候选集固定为 26 点并集，按 `Q3` 从小到大排序；`Q_true` 取 formal truth 的 main 聚合。冻结
`k∈{1,3,5}`：

```math
R@k=\min_{h\in\operatorname{top-k}(Q3)}Q_\mathrm{true}(h)
    -\min_{h\in C}Q_\mathrm{true}(h).
```

边界相同值全部保留。Gate B 通过当且仅当：

1. `max_{k∈{1,3,5}} R@k ≤ epsilon_Q`；
2. 若 `Q3(h)≤q_budget` 但 `Q_true(h)>q_budget`，其最大预算违约
   `Q_true(h)-q_budget ≤ epsilon_Q`；
3. 对 formal truth 已登记的每个 strict reversal/collapse，③ 的排序与 truth 同向，或两端 `Q3` 差落在
   `epsilon_Q` 内；逐 witness 报告，不用总体 tau 掩盖。

同时报告 true-best 命中、false-feasible 个数、tau-b、全并列保留率；这些不是额外通过条件。

## 5. 结果分支

- Gate A+B 通过：Evaluation axis = E1；failure 由经典 candidate-specific coherent linear propagation
  解释，不声称新误差理论。
- Gate A 不过、Gate B 通过：③ 只称 ranking surrogate；仍归 E1 的排序解释，但不称 validated chain-level model。
- Gate B 不过：实现基线④，加入 CMUL/FIR round residual 与交叉项，再判 E2/E3。

无论哪一支，当前 truth 已经没有 decision witness；不得把 mechanism witness 改写成设计损失。
