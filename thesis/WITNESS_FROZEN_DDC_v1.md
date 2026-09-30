# DDC witness 冻结版预测 v1

- 日期：2026-09-29
- 状态：**已冻结**（Codex 复核 `msg_c69faee32b064c42a85f6c52`；Claude 条件复核通过
  `msg_dedb192ddd644ad786b534c1`；其唯一条件 B3 已补入 §5）
- 来源：`CONTRACT_DDC_v1.md`、`WITNESS_PREDICTION_DDC.md`、`WITNESS_PREDICTION_DIFF.md`
- 范围：DDC 第一阶段只改变 NCO / 近似原语；下游 CMUL、FIR、抽取实现固定
- 禁止覆盖：双方确认后把状态改为“已冻结”；此后任何改动必须新建 `v2`，不得修改本文件

本文是运行 truth 之前的预注册对象，不含实验结果。旧 420 对、旧 SFDR、静态 SQNR 量级只属于已披露的
预测污染源，不作为证据或阈值来源。

---

## 1. 冻结主张与预测

### P0：现有六候选

对 `n1`–`n6`，使用完整、公平的 NCO 局部指标后，**E0 更可能**：高精度 `n4/n6` 即使出现排序符号变化，
其链级风险差也很可能小于 `ε_Q`。这只是纸面先验，不是“构造上必然 E0”；full-chain 共同残差与交叉项尚未测。

保留的条件预测：`n4_lut1024lin_b16` 与 `n6_cordic16_b16` 最可能出现亚阈值的符号变化，因为二者同为
16-bit phase path、结构不同；不得在 truth 前称其为 strict reversal。

### P1：v2 低精度跨结构区

若 v2 出现 `|ΔQ|>ε_Q` 的保序失败，最可能来自低精度端的
“LUT 相位截断型 vs CORDIC 7–9 级”局部 SQNR 相邻对：局部 SQNR 较高的截断型候选，可能在
`C_main` 的 worst 栅格点上反而给出更差 `Q`。

物理依据是相位截断误差基频

```math
f_e=\operatorname{frac}(2^B f_\mathrm{off}/F_s)F_s
```

折回输入 Nyquist 区间后，会随 FCW 改变而把低阶相干误差线搬入或搬出固定 FIR 有效带。30 kHz 栅格中
B=8/12 都存在低阶线入带的点；这一机制不需要强 blocker。

证伪条件：若所选 CORDIC 候选在决定 worst 的场景中，其带内误差捕获比例不低于截断型候选的一半，
上述方向预测不成立。本文不假设 CORDIC、LUT-linear 或任何候选的误差是白噪声；它们统一视为
candidate-dependent coherent spectra。

按当前实现作纸面量级估计，§2.3 的规则最可能选出 `CORDIC_8` 与 `LUT-nearest512`：预估 calibrated
SQNR 分别约为 46.9 dB 与 49.0 dB，差约 2.1 dB，且到 `S*` 的最大距离约 2.7 dB。对 B=9 的九个主栅格点，
相位截断误差基频的纸面折叠值依次约为
`{-0.32,-0.96,0.40,-0.24,-0.88,0.48,-0.16,-0.80,0.56} MHz`；最坏点的一阶带内捕获
粗估约 0.4，叠加 `0.30 MHz` blocker 后粗估约 0.55，而宽带参照粗估约 0.45。因此 2.1 dB 的局部优势
可能抵消捕获劣势，Claude 对这条**按规则选中的纸面对**预测为“不出现超过 `ε_Q` 的 strict reversal”，
置信度低到中。以上均是 truth 前的未验证解析估算，不是实验数字；若实算局部指标使规则选出另一对，登记
“纸面对在 selection stage 被证伪”，不得重选纸面预测。若该对最终反转，则优先检查线性模型是否低估了
worst 场景的相干捕获。

### P2：结果分支

- 发生 failure 且最强线性基线 ③ 通过 Gate：E1；这是最可能的阳性分支；
- ③ 不过、加入 CMUL/FIR round/sat residual 与交叉项的 ④ 通过：E2；不预设；
- ③④ 均不过：E3，只保留 full-chain bit-true evaluation；
- 预注册池内无超过容差的 failure：E0，停止以该 witness 扩张主张。

SFDR 排对而 SQNR 排错，是有价值的指标边界细化，不算失败；SFDR 也发生反转则说明单一 DDS 杂散标量仍不足。

## 2. 候选池

### 2.1 现有六点池

沿用 `candidates.py` 中 `n1`–`n6`，不改变名称或参数。当前 `cert_metrics` 忽略 `phase_bits`，不能作为
本协议的公平局部指标；`n3/n4` 的旧同分只算指标漏项。

### 2.2 v2 二十点池

| architecture class | 参数 | 数量 |
|---|---|---:|
| LUT nearest | full-wave `depth∈{128,256,512,1024}`，`phase_bits=16` | 4 |
| LUT linear | `depth∈{256,1024}` × `phase_bits∈{8,10,12,14,16}` | 10 |
| CORDIC | `stages∈{7,8,9,10,11,12}`，`phase_bits=16` | 6 |

总计 20 点。CORDIC 合法范围由 `8..20` 放宽为 `7..20`，是用户在 truth 前明确批准的预注册扩展，
理由是覆盖工程风险锚点附近的低精度跨结构重叠；不是看到 E0 后补点。实现阶段才修改代码，并在
`examples/comm_dsp_bench/AUDIT.md` 登记范围变化、理由、逐位模型/RTL 对拍与回归结果。

这里沿用仓库兼容名称 `nearest`，但冻结的数值语义是当前实现：quadrant folding 后对段地址作
`mi=floor(ms/2^fb)`（整数右移），**不是**加半 LSB 的 round-to-nearest。实现时不得静默改成半步舍入；
若以后要比较真正的 nearest rounding，须作为新候选和新协议版本。

### 2.3 v2 主 pair 选择规则

由工程预算定义

```math
S^*=-10\log_{10}(q_\mathrm{budget})\approx46.33\ \mathrm{dB}.
```

只使用 calibrated local SQNR，不读取系统 `Q`：

1. 先在完整 accumulator 域按 bit-true NCO 输出映射建立数值等价类；完全相同的映射在 pair 选择时合并，
   代表元取 candidate ID 字典序最小者，不按面积或 `Q` 选择；近似相同不合并；
2. 枚举不同 architecture class 且不属于同一数值等价类的候选对；
3. 丢弃 `|ΔSQNR|>3 dB` 的对；
4. 依次最小化两端到 `S*` 的最大距离、`|ΔSQNR|`、candidate ID 字典序；
5. 若没有合格对，登记“v2 无合格 pair”，不得放宽 3 dB 门限；
6. 固定池的全部候选与全部跨类对仍完整报告，不能只展示主 pair。数值等价但硬件不同的实现仍全部保留
   在面积与 Pareto 分析中，只在主 pair 选择时去重。

`S*` 只用于预选，不表示局部 SQNR 等于链级 `Q`。

## 3. 局部指标

### 3.1 共同输入域与复标量约定

`M_core={SQNR,WCE,last-bit accuracy}` 在均匀 32-bit accumulator 域
`a∈{0,…,2^32−1}` 上评价完整 NCO 映射：phase truncation、LUT/CORDIC 与 16-bit 输出量化全部包含，
参考为 `exp(j2πa/2^32)`。允许严格等价的 residue/coset 化简，但不得改变状态权重。

局部 `M_core` 与主链级 `q` 使用同一常数偏置语义：在 accumulator 域估计并移除一个全局复标量，随后冻结；
raw 版本同时报告为敏感性分析，不得用 raw `m` 与 calibrated `q` 构造主 reversal。

- SQNR：理想复输出功率 / 校正后的复均方误差；
- WCE：校正后 I/Q 两分量的全域最大绝对误差，以 16-bit 输出 LSB 表示；
- last-bit accuracy：校正后 I/Q 均在正确舍入理想码 ±1 LSB 内的状态比例。

### 3.2 DDS 专属强基线 M_DDS

```text
M_DDS = {clean-FCW-grid SFDR}
```

SFDR 是 DDS 专属的强局部基线，不外推为所有算子的通用指标。主标量为九个 `C_main` FCW 上的 worst：

```math
m_\mathrm{SFDR}(h)=-\min_{f\in F_\mathrm{main}}\mathrm{SFDR}(h,f).
```

越小越好。八个 held-out FCW 单独检查稳定性，不并回主标量重新选 pair。若 SFDR 在主 worst 契约上排对，
如实报告成功；不得为了让它失败而把 mean 升格为第二主契约。

### 3.3 SFDR 测量定义

主 FCW 来自

```text
f_off/MHz = {0.390,0.420,0.450,0.480,0.510,0.540,0.570,0.600,0.630}
FCW(f) = round((f·10^6/Fs_in)·2^32),  Fs_in=2 MHz.
```

held-out 使用 `{0.405,0.435,0.465,0.495,0.525,0.555,0.585,0.615} MHz` 的同一整数映射。
每个整数 FCW、`gcd(FCW,2^32)` 与周期写入 manifest。

对每个候选和 FCW：

1. accumulator 初态为 0，生成 `N_SFDR=2^16` 个候选复 NCO 输出
   `m_h[n]=(cos_h[n]+j sin_h[n])/2^15`；
2. 已知理想载波 `u[n]=exp(j2π·FCW·n/2^32)`；用全记录最小二乘只估计载波系数
   `g=<u,m_h>/<u,u>`，然后作精确载波消除 `e[n]=m_h[n]−g·u[n]`；
3. 对 `e[n]` 乘四项 Blackman–Harris 窗
   `(a0,a1,a2,a3)=(0.35875,0.48829,0.14128,0.01168)`；
4. 做 `8N_SFDR` 点零填充复 FFT；按窗 coherent gain `Σw[n]` 还原复幅度；
5. `A_spur=max_k |FFT{w·e}[k]|/Σw`，包含 DC 和 close-in spur，不再用“峰值 ±2 bin”排除法；
6. `SFDR=20log10(|g|/A_spur)`。若 `A_spur=0`，记为数值上限并保存底噪而非写无穷。

载波先按已知精确频率消除，因此 Blackman–Harris 主瓣不会伪装成最大杂散；零填充用于降低 off-bin
spur 的 scalloping。该定义是有限记录、冻结长度的确定性指标，不冒充无限周期解析 SFDR。跨结构比较时
必须显式注明 `N_SFDR=2^16`：宽带残差的最大单 bin 会随记录长度和极值统计改变，不能把这里的 CORDIC/LUT
SFDR 外推为记录长度无关的物理常数。

### 3.4 SFDR 校准与 ε

候选 SFDR 启用前必须通过：

1. 九个主 FCW 的理想复单音均测得至少 140 dB 的数值 SFDR；
2. 向理想单音注入 `−40/−60/−80 dBc` 的单个已知复 spur；spur 分别放在 FFT 整数 bin 与半 bin，
   且离 carrier 至少 8 个原始 FFT bin；恢复误差均不超过 0.10 dB；
3. 双 spur 用例必须选择幅度较大的真实 spur，误差不超过 0.10 dB；
4. 任一项失败，先修测量器；不得通过增大 `ε_m^(SFDR)` 放行。

冻结

```math
\epsilon_m^{(\mathrm{SFDR})}=0.25\ \mathrm{dB}.
```

它是覆盖 0.10 dB 校准误差与数值/窗峰值恢复余量的工程 tie band，不是统计显著性阈值。

### 3.5 全部局部容差

| 指标 | 越小越好形式 | 冻结容差 |
|---|---|---:|
| SQNR | `m=-SQNR_dB` | 0.10 dB |
| WCE | `m=WCE` | 1 个 16-bit 输出 LSB |
| last-bit accuracy | `m=1−accuracy` | `2^-32` 概率质量 |
| SFDR | `m=-min_F SFDR_dB` | 0.25 dB |

## 4. 部署契约

### 4.1 场景 C

- `C_main`：九个 30 kHz 主栅格点；每点含 `clean + OBB(0.300 MHz,−3 dB) +
  OBB(0.420 MHz,−3 dB) + alias-edge(0.555 MHz,−3 dB)`，共 36 场景；
- `C_heldout`：八个交错 15 kHz 点，使用同一四场景模板，共 32 场景；
- `C_stress`：九个主点的 alias-edge `+6 dB`，共 9 场景，只作敏感性分析；
- AWGN 为相对 desired、加 blocker 之前的 30 dB SNR；
- blocker 电平是工程压力点，不冒充 3GPP blocker 表项；
- NCO 初相 0、抽取 phase 0、`R=2`、固定 33-tap FIR、passband 0.20 MHz、stopband 0.45 MHz；
- seed 由完整场景键稳定派生，不依赖列表位置。

主结论只称 `C_main` 栅格上的 worst，不称连续频率 worst。候选、阈值和结论模板锁定后才揭示 held-out；
held-out 失效则登记“不稳定”，不得回头修改栅格。

### 4.2 主风险 q 与聚合 ρ

只在冻结前导段 `P_c` 上，相对同一输入的完整 float reference 输出估计：

```math
g_{h,c}=\frac{\sum_{n\in\mathcal P_c}y^*_{\mathrm{ref},c}[n]y_{h,c}[n]}
               {\sum_{n\in\mathcal P_c}|y_{\mathrm{ref},c}[n]|^2}.
```

冻结 `g` 后，在互不重叠的数据段 `M_c` 计算：

```math
q(h,c)=
\frac{\sum_{n\in\mathcal M_c}|y_{h,c}[n]/g_{h,c}-y_{\mathrm{ref},c}[n]|^2}
     {\sum_{n\in\mathcal M_c}|y_{\mathrm{des,ref},c}[n]|^2},
\qquad
Q(h)=\max_{c\in C_\mathrm{main}}q(h,c).
```

候选与 float reference 使用同一量化 `x_adc`。该对齐使用 `q` 本来就依赖的完整 `y_ref`，但不另外读取或
分解 noise/blocker truth；`y_h=y_ref` 时严格给出 `g=1`。它是评价器的相对对齐自由度，不冒充部署端
desired-only CPE/AGC，并且不在数据段重拟合。`q` 是 sample-domain implementation NMSE，不称 3GPP symbol EVM。raw、passband-only、符号域与 mean
聚合只作敏感性分析。

### 4.3 对齐与测量段

- 按 sequence tag / valid 语义对齐，不用相关峰值或最小误差搜索平移；
- 允许 lowering 有不同周期延迟，但 sample mapping 必须由接口 manifest 声明；
- 当前语义下 33-tap valid FIR 后 phase-0 抽取，64-symbol preamble 对应丢弃首 240 个抽取输出；
  正式实现按 sequence tag，不硬编码 240；
- 全候选使用相同数据段长度和共同尾部交集。

## 5. 工程阈值与成本

30 dB 背景下，将实现误差近似为不相关附加误差时：

```math
q_\mathrm{budget}=\frac{10^{0.10/10}-1}{10^{30/10}}\approx2.33\times10^{-5},
\qquad
\epsilon_Q=\max(q_\mathrm{cal},0.1q_\mathrm{budget}).
```

0.10 dB 损耗映射是工程分配近似，不是对相干 spur / saturation 的定理。`q_cal` 在候选 truth 前由
exact-representable zero-error calibration 得到；底噪过高时先修 evaluator，不放宽阈值。

主成本为固定版本 Yosys + Nangate45 `typ.lib` 的 mapped `area_um2`。冻结工具版本、liberty hash、综合脚本
与 top module；无 SDC 时不把 timing/power 当正式证据。主判定的候选集合固定为现有六点池与 v2 二十点池的
并集，共 26 个实现。对每个 `m∈M_core∪M_DDS`，在该并集上按 `(m,area)` 的确定性数值计算标准 Pareto
前沿 `F_m`。主 decision witness 定义为：存在 `h∈F_m` 与同池
候选 `h'`，使 `h'` 在 `(Q,area)` 上严格 Pareto 支配 `h`，且 `Q(h)-Q(h')≥ε_Q`。这一规则不需要事后
选择面积阈值。SQNR 的辅助选择固定为 calibrated `SQNR≥S*` 下的最小面积点，并报告相对 `(Q,area)`
选择的 quality / area regret；辅助结果不替代主 Pareto 判据。

现有六点池与 v2 二十点池各自的前沿和 decision witness 分开报告，但只作辅助。P0 与 P1 的机制预测分别只在
其六点池与二十点池内判定；不得借用另一池候选改写某条预测的成败。

## 6. 保序失败与基线

对每个 `m∈M_core∪M_DDS`：

- strict reversal：`m(h_a)+ε_m^(m)<m(h_b)`，但 `Q(h_a)>Q(h_b)+ε_Q`；
- collapse：`|m(h_a)−m(h_b)|≤ε_m^(m)`，但 `|Q(h_a)−Q(h_b)|>ε_Q`。

基线梯子：

1. local scalar：`M_core∪M_DDS`；
2. marginal power spectrum + 非相干折叠，含适用时的 Nicholas/Vankka 相位截断 DDS 模型；
3. candidate-exact 复残差 + `D·H·diag(x)` 相干线性传播，保留互谱；
4. 在 ③ 上加入 CMUL/FIR round/sat residual 与交叉项；
5. full-chain bit-true truth。

第一阶段固定 `H`，只变 NCO。相干 alias 若由 ③ 解释，属于 E1；只有 ③ 失败且 ④ 通过时才主张 E2。

## 7. truth 前的工程前置项

冻结版通过双方审阅后，才允许按顺序实施；当前步骤不改代码：

1. 修 `spectral_prediction` alias preimage 索引；
2. 按 §3 重写/修正 `sfdr_db`，完成理想单音与注入 spur 校准；
3. 统一预测/truth 的误差对象、频带、分母、前导、暖机和测量段；
4. 修 `worst_drop` 的 kept/dropped 标签；
5. 修 NCO 两实数字段被当复数合并的 SQNR；
6. 增加 tau-b、任一最优命中率与全并列保留率；
7. 修 QPSK 功率声明/实现不一致；
8. 让 AWGN SNR 相对 desired，而非 desired+blocker；
9. 暴露 desired/blocker/noise 与共同前端缩放；
10. 实现前导段相对同输入完整 `y_ref` 的复标量估计，并验证 `y_h=y_ref` 时严格得到 `g=1`；不得改成
    desired-only 投影，也不得在测量段重拟合；
11. manifest 写入 sequence mapping、抽取相位、整数 FCW、gcd、周期与稳定 seed；
12. 新场景生成新版本，旧产物不覆盖；
13. 用校准例冻结 `q_cal`；
14. 把 CORDIC 合法范围改为 `7..20`，同步模型/RTL 测试，并登记 `AUDIT.md`。

任何前置项失败，停止 truth；旧 420 对和旧 SFDR 只保留为历史诊断。

## 8. 冻结与审计规则

双方已逐项确认：候选池、pair 规则、`M_core/M_DDS`、SFDR 定义与 `ε_m^(SFDR)`、`C/q/ρ`、
`ε_Q`、成本口径、基线和结果分支。冻结审阅记录为 Codex `msg_c69faee32b064c42a85f6c52` 与 Claude
`msg_dedb192ddd644ad786b534c1`；Claude 的条件 B3（主判定使用 26 个实现并集）已补入 §5。自此：

- 文件内容不再修改；实现偏差、失败或协议变更写入新版本与 `AUDIT.md`；
- truth 无论为阳性、阴性或低于阈值，都保留原预测，不覆盖；
- 评价器修复、候选实现和数值运行只能在冻结后开始。
