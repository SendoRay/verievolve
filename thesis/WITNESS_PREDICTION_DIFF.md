# DDC witness 两份纸面预测对照

- 日期：2026-09-29
- 输入：`CONTRACT_DDC_v1.md`（Codex）与 `WITNESS_PREDICTION_DDC.md`（Claude）
- 状态：**交换后对照；未跑 truth、未改代码**

## 1. 已达成一致，可进入冻结版

1. 当前 `cert_metrics` 只枚举截断后的 angle code，忽略 `phase_bits`，不能作为公平的完整 NCO 局部指标。
   `M_core={SQNR,WCE,last-bit accuracy}` 必须在均匀 32-bit accumulator 状态域上评价 phase truncation、
   LUT/CORDIC 和 16-bit 输出量化，并参考未截断理想相位。`M_core` 与主 `q` 使用同一种常数偏置约定：
   accumulator 均匀域上也只移除一个全局复标量，不能一个校正、另一个不校正。
2. 主系统量是线性域 sample-domain implementation NMSE，候选与 float reference 使用同一 `x_adc`，
   分母是使用共同前端缩放的 desired-only 参考功率；不是相对发射符号的总 EVM。
3. 主 `q` 允许一个**只在前导段相对同输入完整 float reference 估计、随后冻结**的复标量对齐；raw 误差作
   敏感性结果。这是评价器的相对对齐自由度，不冒充部署端仅凭 desired preamble 可实现的 CPE/AGC。
   它保留现有 floor-truncation 硬件，同时避免常数相位偏置把谱形机制淹没；不得在测量段重新拟合。
4. `ρ` 是 `C_main` 9 个 30 kHz 栅格点及其四场景模板上的线性 worst；mean 只作展示，
   held-out 8 点只检查栅格稳定性，不回并主 `Q` 重新选择。
5. `q_budget≈2.33×10^-5` 来自 30 dB 背景下 0.10 dB 实现损耗分配；
   `ε_Q=max(q_cal,0.1q_budget)`。这是工程阈值，不是统计阈值。
6. 主 decision witness 的选择集冻结为现有六点与 v2 二十点的 26 个实现并集。对每个局部指标 `m`，
   先计算 `(m, Nangate45 mapped area)` 前沿 `F_m`；主 witness 是 `F_m` 中至少一点被同池候选在
   `(Q, area)` 上严格支配，且 `ΔQ≥ε_Q`。六点池和 v2 池分开报告仅作辅助；SQNR 的 `S*` 门槛选择也只作
   辅助 regret 报告。
7. `+6 dB` blocker 只作 stress，不进入主 `ρ`；没有 ADC/AGC/标准映射的 `+10/+40 dB` blocker 不使用。
8. 最可能的结果分支是 E0 或 E1；不预设 E2。相干 alias 本身由线性基线 ③ 解释，不是新贡献。
9. manifest 必须冻结实际整数 FCW、`gcd(FCW,2^32)`、周期、抽取相位、初相、场景键派生 seed。

## 2. 现有六候选：保留的 competing predictions

两份预测不投票，原始污染声明与交换后修订均保留。

| 项目 | Codex 预测 | Claude 预测 | 联合处理 |
|---|---|---|---|
| 现有池总体 | `n4/n6` 最可能发生排序符号变化，但高精度差异很可能低于 `ε_Q`；E0 更可能 | 公平局部指标下现有池更可能 E0 | 冻结为 E0 优先先验；不是证明，full-chain cross term 尚未测 |
| 主候选对 | `n4_lut1024lin_b16` vs `n6_cordic16_b16`，同 B16、混淆较少 | 原先认为现有池无合格对；撤回“n3/n5 在任何契约都不反转”的绝对说法 | `n4/n6` 只作为亚阈值符号预测，不预称 strict reversal |
| `n1/n2` | 非主 pair；折叠借位可造成稀疏差异 | 非主 pair | 修 evaluator 后用单测核对，不当 architecture witness |
| `n3/n4` | 当前同分来自 `phase_bits` 漏项 | 同意 | 只说明旧局部指标定义不完整，不作研究 witness |

核心校准是：高精度对即使发生谱形驱动的**符号反转**，也未必构成
`|ΔQ|>ε_Q` 的 order-preservation failure。不能把“有反转”与“改变工程选择”混写。

## 3. 纸面机制预测

相位截断误差的基频可写为：

```math
f_e=\operatorname{frac}(2^B f_\mathrm{off}/F_s)F_s,
```

折叠到输入 Nyquist 区间。对冻结的 30 kHz 栅格，B=8/12 都存在低阶误差线进入固定 FIR 有效带的点；
例如 B=8、`f_off=0.57 MHz` 时，纸面计算给出 `f_e≈−0.08 MHz`。因此 clean 场景本身就足以检验
“误差谱形 × FIR/抽取”的机制，不需要提高 blocker 来制造结果。

这只预测**相位截断型候选存在强场景依赖**。不得把另一结构预先称作白噪声：LUT、插值和 CORDIC 都可能
产生 candidate-dependent coherent spectra，必须由基线 ③ 的 candidate-exact complex residual 检查。

Claude 的非冻结纸面预期是：若 v2 出现超过 `ε_Q` 的失败，最可能来自低精度端
“LUT 相位截断型 vs CORDIC 7–9 级”的局部 SQNR 相邻对，方向是局部 SQNR 较高的截断型在某个 worst
栅格点上反而更差。若 CORDIC 在该点的带内误差捕获比例不低于截断型的一半，这一方向预测即被证伪。
这是一条待检验的条件预测，不把 CORDIC 预设为白噪声。

## 4. 已批准冻结的 v2 扩展池

现有六点没有在工程阈值附近形成足够密的跨结构重叠。若等看到 E0 后再加候选，会变成结果驱动扩池；
因此建议在任何 truth 之前登记 v2，但本步骤不实现：

| architecture class | 参数网格 | 数量 |
|---|---|---:|
| LUT nearest | full-wave depth `{128,256,512,1024}`，`phase_bits=16` | 4 |
| LUT linear | depth `{256,1024}` × `phase_bits={8,10,12,14,16}` | 10 |
| CORDIC | `stages={7,8,9,10,11,12}`，`phase_bits=16` | 6 |

共 20 点。除 CORDIC_7 外均在当前模板声明的合法范围内。用户已在 truth 之前明确授权把 CORDIC
合法范围由 `8..20` 放宽为 `7..20`，目的是覆盖 `q_budget` 附近的低精度跨结构重叠，不是看到结果后迎合预测。
代码与 `AUDIT.md` 在实现阶段同步修改；本步骤只登记，不动代码。

主 pair 不手选：先由工程预算得到
局部功率锚点 `S*=−10log10(q_budget)≈46.33 dB`，在不读取系统 `Q` 的前提下，对跨 architecture-class
候选对依次最小化：(1) 两端到 `S*` 的最大距离；(2) 两端 calibrated local SQNR 差；(3) candidate ID
字典序。该规则把预注册 pair 放在最可能影响工程决策的低精度重叠区，而不是再次选到远低于 `ε_Q` 的高精度对。
另要求 `|ΔSQNR|≤3 dB`；若没有跨结构候选对满足，就登记“v2 无合格 pair”，不得放宽阈值。
`S*` 只用于预选，不声称局部 SQNR 等于链级 `Q`。其余固定池全量报告，不能只展示成功 pair。

## 5. 已批准的 SFDR 处理

`PROPOSAL_v1.md` 当前冻结 `M_core={SQNR,WCE,last-bit accuracy}`。DDS reviewer 会合理地追问 SFDR，
用户已批准在 truth 前新增：

```text
M_DDS = {clean-FCW-grid SFDR}
```

它是 DDS 专属强局部基线，不伪装成跨算子通用指标。它拥有单独冻结的 `ε_m^(SFDR)`。前置条件是先修
Blackman–Harris 主瓣排除问题，
并用已知杂散/理想单音校准。若 SFDR 在主 worst 契约上保序，应如实报告它成功；不得为了让 SFDR 失败而
把 mean 升格为第二主契约。只有能给出独立、真实的部署语义时，才另建第二契约。

## 6. 用户决议

1. SFDR 现在加入 `M_DDS`；先修并校准测量器，单独冻结 `ε_m^(SFDR)`。
2. truth 前冻结第 4 节的 20 点 v2 池，包含 CORDIC_7；实现时才修改合法范围并登记 `AUDIT.md`。

下一步是把本对照、契约草案与 Claude 预测合成 `WITNESS_FROZEN_DDC_v1.md`。冻结版通过双方审阅前，
不修 evaluator、不跑 truth；通过后该文件不可覆盖，任何口径变化必须新建版本。
