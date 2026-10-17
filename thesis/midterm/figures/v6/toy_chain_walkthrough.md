# 用一条玩具链路走通整个框架

目的：不依赖 DDC 的领域细节，用一条只有三步计算的链路，把框架图 v6 的每一个环节走一遍：
输入写什么、初始原语程序长什么样、树上怎么分支、每一步检查查什么、失败时反馈什么、
lowering 怎么做、PPA 和 Pareto 前沿怎么算、终验做什么，以及每条关系能否证明。

> **说明**：文中所有数值（面积、裕量、份额等）都是**示意数字**，只用来说明机制，不是实测结果。
> 每节末尾标注当前实现状态：**已实现** / **原型** / **计划**。

---

## 0. 链路本身：三步计算

```text
 x[n] ──► [S1 混频] ──► u[n] ──► [S2 滤波] ──► v[n] ──► [S3 抽取+增益] ──► z[m]
 12 位      y1 = a×b              y2 = Σ h·y1           y3 = g×y2 + d       16 位
 每拍1个     a = x, b = cos表       需要存 4 个历史值        每 2 个样点留 1 个    每2拍1个
```

| 段 | 计算 | 抽象成你说的形式 | 在真实通信里相当于 | 单段指标（只做诊断） |
|---|---|---|---|---|
| S1 混频 | u[n] = x[n] · cos(ω₀n) | y1 = a × b，b 来自查表 | 下变频里的 NCO + 混频器 | 余弦表的杂散（SFDR） |
| S2 滤波 | v[n] = h₀u[n] + h₁u[n−1] + h₂u[n−2] + h₃u[n−3]，h₀=h₃、h₁=h₂ | y2 = Σ hₖ·y1[n−k]，**有存储** | 抗混叠低通滤波器 | 通带纹波、阻带衰减 |
| S3 抽取+增益 | z[m] = g · v[2m] + d | y3 = g × y2 + d | 降采样 + 增益/直流校正 | 输出量化噪声 |

**整条链路只有一个验收指标**：在输出端测 SNR，即理想输出功率与（实际输出 − 理想输出）功率之比。
单段指标只在诊断时用，不参与是否合格的判定。原因见 §4.3：同样大小的误差，出现在不同段，对输出的影响不同。

---

## 1. Stage 0：任务契约（用户写的东西）

```yaml
F:                                   # 理想功能：浮点、不含任何实现信息
  ideal: |
    u = x * cos(2*pi*f0*n)           # f0 = fcw / 2^32
    v = ideal_lowpass(u, pass=0.05, stop=0.20)   # 理想低通（滤波器形状不指定，留给设计）
    z = g * v[::2] + d               # g = 0.75, d = 0.01
  frozen_context: none               # 本例没有冻结的前后级
  observe_at: z                      # 指标在 z 处测

Q:                                   # 验收规范
  input_class:                       # 输入条件类：系统据此生成加固集
    desired: tone in [0, 0.05] fs, -6 dBFS
    blocker: one tone in alias band [0.45, 0.5] fs, +20 dB above desired
  metrics:
    snr:    ">= SNR_ideal - 1.0 dB"  # 允许 1 dB 实现损失
    ripple: "<= 0.5 dB"
  acceptance_set: 3 scenarios        # 用户/标准给的用例，通过即合格

I:                                   # 接口与时序
  in:  {width: 12, frac: 11, signed: true, rate: 1 sample/clk, handshake: valid/ready}
  out: {width: 16, frac: 15, signed: true, rate: 1 sample/2 clk}
  latency_max: 16 clk
  reset: synchronous

C:                                   # 成本目标
  library: Nangate45
  clock_target: 2.0 ns               # 硬约束：达不到算不合格
  objective: [area, power]           # 满足约束后尽量小
```

**系统自动生成、用户不用写的**：
- **加固集**：在 `input_class` 范围内按网格覆盖整个混叠带（例如 8 个干扰频点 × 2 个随机相位）；
- **留出集**：另一组频点和随机种子，只在终验时用；
- 理想参考输出、SNR 门槛（理想 SNR − 1 dB）、随机种子、工具参数。

状态：F/Q/I 的声明式写法已实现（链路 A、B 的规格文件）；验收集与加固集的显式分离为**计划**。

---

## 2. Stage 0 → 1：初始原语程序（树根）

把 F 按默认方式逐项直译，**保守、能跑、不求最优**。注释里的五元组是推导出的类型
τ = (位宽 w, 小数位 f, 有无符号, 速率域, 时延)。

```python
def build(g, p):
    x = g.input()                                         # (12, 11, s, d0, 0)

    with g.scope("S1_mix"):                               # —— S1：y1 = a × b
        ph  = g.counter(p["fcw"], 32)                     # 32 位相位累加器（状态）
        adr = g.bits(ph, 31, 22)                          # 取高 10 位 → 1024 项整周期表
        cs  = g.lut(adr, [cos(2*pi*(i+0.5)/1024) for i in range(1024)], 16, 15)   # 存储：ROM
        u   = g.q(g.mul(x, cs), 18, 17, "round", "sat")   # (18, 17, s, d0, 1)

    with g.scope("S2_fir"):                               # —— S2：y2 = Σ h·y1（有存储）
        taps = g.delay_line(u, 4)                         # u[n], u[n-1], u[n-2], u[n-3]
        v    = g.mac(list(zip(taps, p["h"])), coef_bits=18)
        v    = g.q(v, 20, 19, "round", "sat")             # (20, 19, s, d0, 3)

    with g.scope("S3_dec"):                               # —— S3：y3 = g × y2 + d
        v2 = g.decimate(v, 2)                             # 速率域 d0 → d1
        gz = g.scale(v2, p["g"], bits=16)                 # 乘常数 g（移位加实现）
        z  = g.add(gz, g.const(p["d"], 16, 15))           # + d
        z  = g.q(z, 16, 15, "round", "sat")               # (16, 15, s, d1, 4)

    g.output(z)                                           # 示意：实数输出
```

三个 `scope` 就是三个初始**区域**（R1、R2、R3），它们是树上 OR 节点的最初边界。
这个程序在质量上大概率合格（位宽都给得很宽），但面积大：整周期表 1024 项，FIR 每个抽头一个乘法，
抽取在滤波之后（一半的滤波输出被丢掉，白算了）。

状态：**已实现**（所用原语与签名均来自 `dspgraph/sdf.py`）。

---

## 3. Stage 1：AND/OR 树与分支

### 3.1 树的结构

```text
[OR] 整条链路 ── 根节点 n0：初始原语程序
 │
 ├── 直接对整程序修改（OR 的备选）……………………………… 见 3.2 的 n1、n4 …
 │
 └── [AND] A1：按 u 处切成两个子区域，必须一起实现
      │   边界契约：u 的类型 (18,17,s,d0) 与时延，两边都不许改
      │
      ├── [OR] R1 = S1_mix                    ← 只改 S1 的各种备选
      │     ├─ n1  REWRITE 四分之一波表         bit-exact
      │     ├─ n2  TUNE    地址 10→8 位         approx
      │     └─ n3  REWRITE 小表 + 线性插值       approx
      │
      └── [OR] R23 = S2_fir + S3_dec          ← 只改 S2+S3 的各种备选
            ├─ n4  REWRITE 多相（先抽取再滤波）   bit-exact
            ├─ n5  REWRITE 对称预加              bit-exact
            ├─ n6  REWRITE 把 g 并进系数（分配律） math-eq
            ├─ n7  TUNE    乘法器分时复用 ×2      bit-exact
            ├─ n8  TUNE    系数 18→12 位、q 收窄  approx
            ├─ n9  REWRITE 用 CIC 代替 FIR        approx
            ├─ n10 TUNE    乘法后插一级寄存器      bit-exact
            └─ n11 TUNE    g=0.75 改为移位相加     bit-exact
```

- **OR 节点** = 一个区域 + 它的边界契约；它下面的子节点是"同一区域的不同改法"，互为备选，保留全部。
- **AND 节点** = 一次分解：子区域各自在自己的 OR 里找到好的改法后，**拼成一份完整程序，回到链路根部重新判定**。
  局部指标不能直接相加，比如 R1 的杂散和 R23 的阻带会在输出端叠加。
- 每个节点都是一份**完整**原语程序，带状态：BROKEN / OPEN / FEASIBLE / VERIFIED。

### 3.2 每个分支具体改了什么

| 节点 | 区域 | 动作 | 声明关系 | 具体改动（原语层面） | 新增覆盖的原语 |
|---|---|---|---|---|---|
| n1 | R1 | REWRITE | bit-exact | 1024 项表 → 256 项四分之一周期表；用相位高 2 位判象限，`mux` 选镜像地址，`neg` 取负 | `bits` `mux` `neg` |
| n2 | R1 | TUNE | approx | 表地址 10 位 → 8 位（相位截短，杂散变大） | — |
| n3 | R1 | REWRITE | approx | 64 项小表 + 一次线性插值（多一个乘法，少很多表项） | `sub` `mul` |
| n4 | R23 | REWRITE | bit-exact | 多相：v[2m] = (h₀u[2m] + h₂u[2m−2]) + (h₁u[2m−1] + h₃u[2m−3])，把 `decimate` 挪到 `mac` 之前，只算要保留的输出 | `decimate`（前移） |
| n5 | R23 | REWRITE | bit-exact | 对称预加：h₀(u[n]+u[n−3]) + h₁(u[n−1]+u[n−2])，乘法数减半；加法器多 1 位，保证不溢出 | `add` |
| n6 | R23 | REWRITE | math-eq | 分配律：g·Σhₖu = Σ(g·hₖ)u，删掉 S3 的乘法；数学上相等，但 g·hₖ 重新量化后定点结果不同 | — |
| n7 | R23 | TUNE | bit-exact | 抽取后每个输出有 2 个时钟，`mac(share=2)`：一个乘法器分时算两个乘积；结果不变，时延 +1 | `mac(share)` |
| n8 | R23 | TUNE | approx | 系数 18 → 12 位，S2 输出 `q` 20 → 17 位 | `q` |
| n9 | R23 | REWRITE | approx | 二阶 CIC：`integrate` ×2 → `decimate` → 梳状 `sub` ×2（用 `delay` 取前一个样点），完全没有乘法 | `integrate` `sub` `delay_line` |
| n10 | R23 | TUNE | bit-exact | 在乘法输出后插一级 `reg`，缩短关键路径以满足 2 ns；数据不变，时延 +1 | `reg` |
| n11 | R23 | TUNE | bit-exact | g = 0.75 = 2⁻¹ + 2⁻²：`shift(v,1) + shift(v,2)`，g 恰好能精确表示，所以逐位不变 | `shift` |

**动作和关系是两回事**：n4 是 REWRITE 但逐位不变；n2 是 TUNE 却引入了误差。

### 3.3 一条示意的搜索轨迹

```text
n0 根                                     FEASIBLE  裕量 +2.1 dB  面积 100%  时钟 2.6 ns ✗
 └ n1  四分之一波表        bit-exact✓ 继承  FEASIBLE  裕量 +2.1     面积  82%
    └ n4  多相             bit-exact✓ 继承  FEASIBLE  裕量 +2.1     面积  55%
       └ n5  对称预加      bit-exact✓ 继承  FEASIBLE  裕量 +2.1     面积  43%
          └ n6  g 并入系数  math-eq → 重测   FEASIBLE  裕量 +1.9     面积  38%
             └ n8  系数/q 收窄   approx     OPEN      缺口 0.7 dB          ← §4.3 看反馈
                └ n8b  按归因只把系数加回 2 位 FEASIBLE 裕量 +0.4  面积 33%
                   └ n7  分时复用      bit-exact✓ FEASIBLE        面积 28%  时钟 2.2 ns ✗
                      └ n10 插寄存器   bit-exact✓ FEASIBLE        面积 29%  时钟 1.9 ns ✓
 └ n9  CIC 代替 FIR         approx          OPEN      缺口 4.8 dB（结构残差大）← 保留，不删除
```

- `bit-exact✓` 的节点**不重测质量**，直接继承父节点的结论，只需重新做 RTL、忠实性检查和 PPA；
- n8 不合格，但作为 OPEN 被保留，下一步 n8b 正是从它出发修回来的；
- n9 的缺口大，并且归因显示是结构残差（§4.3），所以后续应该在 n9 上做 REWRITE（如 CIC 后加补偿滤波），而不是加位宽。

状态：OR 分支、整程序修改、状态与父节点保留为**已实现**（`archive.py`、`hier_agent`）；
AND 分解与子区域组合、回传为**计划**。

---

## 4. Stage 2：候选检查

### 4.1 第一步 Legality：这个程序合法吗？声明的关系属实吗？

它不跑完整的质量测试，只回答两件事。代价很低（毫秒到秒级），所以放在最前面。

**(a) 构造与类型检查**：构造程序时自动完成，违反即为 **BROKEN**。

| 检查 | 例子 |
|---|---|
| 位宽与小数点 | 加法对齐小数点、扩 1 位；只允许在 `q` 处截位 |
| 速率域 | 不能把 d0 的信号和 d1 的信号直接相加（n4 若漏挪一路 `decimate` 就会报错） |
| 原语自身约束 | `lut` 的地址必须无符号；`mac(share=2)` 要求该速率域每个样点至少 2 个时钟 |
| 接口 | 输出必须是 (16,15)、每 2 拍 1 个、时延 ≤ 16 |

报错是分类的，例如：`输出每 1 拍一个样点，接口要求每 2 拍一个`，智能体可以据此直接改。

**(b) 核实声明的关系**：决定这个候选能不能**继承**父节点的质量结论。

| 声明 | 怎么核实 | 通过后 | 不通过 |
|---|---|---|---|
| bit-exact | 与父节点在搜索场景 + 2 个随机场景上逐样点比对，允许整体时延差 | 继承父节点的质量结论，**跳过第二步** | 不驳回，按 approx 进入第二步 |
| math-eq | 把所有 `q` 理想化（不截位）后与父节点比对，相对差 < −70 dB | 确认数学上相等，但定点不同，**仍要做第二步** | 按 approx 处理 |
| approx | 不核实 | 直接进入第二步 | — |

为什么需要它：LLM 可能把实际有误差的修改错标成 bit-exact。如果不核实就继承结论，一个不合格的设计会被当成合格。

状态：(a) **已实现**；(b) 场景比对**已实现**（`claims.py`）；对无状态改写做 SAT/穷举证明为**计划**。

### 4.2 第二步 System Quality：在链路末端，质量够不够？

1. 同一段输入分两路：**带干扰**的 x 送入候选的整数模型，**不带干扰**的 x̃ 送入理想浮点 F，得到参考输出；
2. 时延、增益对齐后相减得到误差，算 SNR；
3. 门槛 = 理想实现的 SNR − 1 dB；每项约束算 slack = 指标 − 门槛；
4. 所有 slack ≥ 安全裕量（0.3 dB）→ **FEASIBLE**；否则 → **OPEN**，并给出缺口
   v = Σ max(0, 0.3 − slack)；
5. 线性部分（S2 的 FIR 或 CIC）另做**扫频**：频响由系数直接算出，纹波和阻带对所有频率成立。

状态：**已实现**（`verdict.py`）。

### 4.3 不合格时反馈什么：让智能体知道改哪里

**只返回"不过"是不够的。** 以 n8（OPEN）为例，返回给树节点和智能体的报告如下（数值示意）：

```yaml
node: n8
status: OPEN
constraints:
  snr:    {value: 61.6, threshold: 62.0, slack: -0.4, need: 0.3, gap: 0.7}   # dB
  ripple: {value: 0.31, threshold: 0.5,  slack: +0.19}
attribution:                       # 近似点归因（在输出端测，所以已包含后级的放大/衰减）
  structural_residual: 0.31        # 所有近似点都理想化后剩下的误差份额（滤波器形状本身）
  sites:
    S1.lut   (表地址 8 位, 相位量化):  0.18
    S1.q     (混频输出 18 位):        0.03
    S2.coef  (系数 12 位):            0.41    ← 最大
    S2.q     (滤波输出 17 位):        0.05
    S3.q     (输出 16 位):            0.02
  sum_check: 1.00                  # 可加性自检通过（0.95–1.05 之间）
cost:                              # 每个区域的面积 + 加 1 位的面积代价（代理模型）
  S1.lut:  {area: 2.1k, +1bit: +1.9k}   # 表项翻倍
  S2.coef: {area: 3.4k, +1bit: +0.3k}
residual_spectrum:
  worst_freq: 0.47 fs              # 结构残差主要在哪个频率
  owner: S2                        # 该频带由 S2 的阻带负责
recommendation: "TUNE S2.coef +2 bit（每 dB 改善的面积代价最低）"
```

**归因怎么算**（这是通用做法，不依赖具体链路）：
1. 方法一保证每个候选的**近似点**都是显式且有限的：每个 `q`、每个 `lut`、每个截短。每个原语有确定的**理想语义**：`q` 理想化就是不截位，`lut` 理想化就是换回精确的 cos，而不是换一张更宽的表。
2. **结构残差 R**：把所有近似点理想化后测得的误差。
3. **近似点 i 的贡献 cᵢ**：只保留近似点 i，其余都理想化，测得的误差减去 R。
4. **自检**：R + Σcᵢ 应约等于实际误差。成立就给份额；不成立（有饱和、回绕等耦合），就改报"去掉近似点 i 后 slack 变化多少"，只给排序，并标注存在交互。
5. 代价：n + 2 次整数模型评价，每次几秒。

**智能体据此决定改什么**：

| 情况 | 结论 | 动作 |
|---|---|---|
| R 本身已超出允许误差 | 结构问题，加位宽没用 | 对 `residual_spectrum.owner` 指向的区域做 **REWRITE**（n9 就属于这种情况） |
| R 没超，但总误差超了 | 精度问题 | 对"份额大、加 1 位代价小"的近似点做 **TUNE**（n8 → n8b：加的是系数位宽，不是表地址） |
| 已合格且有裕量 | 可以省面积 | 对"份额小、面积大"的近似点**减**位宽 |

依据是边际代价相等条件：最优时，每一段"多放宽一点误差能省下的面积"都相等。

状态：在模板版 DDC 上**已实现**（`dspgraph/rx_family.py: attribute()`）；在原语程序上按理想语义做归因为**计划**
（现有的"逐段加宽 4 位"不可靠，加宽 NCO 时曾因表格式改变而使裕量变差）。

---

## 5. Stage 3：冻结契约 → lowering → 忠实性检查

### 5.1 冻结实现契约（以 n10 为例）

候选通过 Stage 2 后，以下内容**冻结**，lowering 不许改：

```yaml
interface:
  in:  x  (12,11,s)  valid/ready, 1/clk
  out: z  (16,15,s)  valid/ready, 1 per 2 clk
numerics:                       # 每个近似点的格式与舍入/溢出方式
  S1.lut: 256 x (16,15), quarter-wave, entries listed
  S1.q:   (18,17) round sat
  S2.coef: [g*h0, g*h1] at 14 bit
  S2.q:   (17,16) round sat
  S3.q:   (16,15) round sat
state:
  ph: 32 bit, reset 0
  delay line: 4 x (18,17)
schedule:
  latency: 6 clk  (in_valid -> out_valid)
  II: 2           (每 2 拍接受一个新输出计算)
resources:
  multipliers: 1 (shared x2)
  pre-adders: 2
  rom: 256 x 16
```

### 5.2 lowering：把原语程序写成 RTL（示例：S1 段）

输入是 n1 之后的 S1 原语程序：

```python
with g.scope("S1_mix"):
    ph   = g.counter(p["fcw"], 32)
    quad = g.bits(ph, 31, 30)                    # 象限
    i    = g.bits(ph, 29, 22)                    # 象限内地址
    # 示意：i_mirror = 255 − i（对 8 位无符号数即按位取反）；
    #       quad_is_1_or_2 = quad[1] XOR quad[0]（第 2、3 象限）
    ia   = g.mux(g.bits(quad, 0, 0), i_mirror, i)  # 奇象限镜像地址 255-i
    t    = g.lut(ia, QUARTER_TABLE, 16, 15)      # 256 项，T[i] = cos(2π(i+0.5)/1024)
    c    = g.mux(quad_is_1_or_2, g.neg(t), t)    # 第 2、3 象限取负
    u    = g.q(g.mul(x, c), 18, 17, "round", "sat")
```

lowering agent 在契约内输出的 RTL（节选）：

```verilog
module s1_mix (
  input  wire               clk, rst, in_valid,
  input  wire signed [11:0] x,                 // (12,11)
  output reg                u_valid,
  output reg  signed [17:0] u                  // (18,17)
);
  reg [31:0] ph;                                // counter(fcw, 32)，状态，复位为 0
  always @(posedge clk)
    if (rst) ph <= 32'd0; else if (in_valid) ph <= ph + 32'd1061286419;

  wire [1:0] quad = ph[31:30];                  // bits(ph,31,30)
  wire [7:0] i    = ph[29:22];                  // bits(ph,29,22)
  wire [7:0] ia   = quad[0] ? ~i : i;           // mux：~i 即 255-i
  reg  signed [15:0] t;                         // lut：256 x (16,15)
  always @* case (ia) /* 256 项，取自契约 */ default: t = 16'sd0; endcase
  wire signed [15:0] c = (quad == 2'd1 || quad == 2'd2) ? -t : t;   // neg + mux

  wire signed [27:0] m  = x * c;                // mul：(28,26)
  wire signed [28:0] mr = {m[27], m} + 29'sd256;   // round：加半个 LSB（2^8），先扩 1 位防回绕
  wire signed [19:0] ms = mr[28:9];             // 右移 9 位 → 17 位小数
  always @(posedge clk) begin                   // 契约规定的 1 拍时延
    u_valid <= in_valid;
    u <= (ms >  20'sd131071) ?  18'sd131071 :   // sat
         (ms < -20'sd131072) ? -18'sd131072 : ms[17:0];
  end
endmodule
```

同时输出一份**实现清单**（manifest），供检查和 PPA 定位使用：

```yaml
scope S1_mix -> module s1_mix; signals ph, quad, i, ia, t, c, m, u
latency: 1 clk   II: 1
resources: 1 multiplier (12x16), 1 ROM (256x16), 1 adder (32b)
```

lowering 只能决定**怎么写**（比如 ROM 用 case 还是数组，舍入怎么写），不能改**写什么**（位宽、舍入方式、时延、资源数量）。
想改后者，必须退回 Stage 1，作为一个新的候选。

### 5.3 忠实性检查（RTL ≡ 原语候选）

| 检查 | 做法 |
|---|---|
| 可编译 / lint | iverilog / Verilator |
| 数据一致 | 所有场景上，每次 `valid && ready` 握手时的输出样点与整数模型**逐位相同** |
| 事务时序 | 时延等于契约的 6 拍；随机插入输入空拍和输出反压时，数据保持、不丢不重；中途复位后行为正确 |
| 结构承诺 | 对照 manifest：乘法器数量、ROM 大小符合契约 |
| 形式等价（可选） | 若与确定性编译器的 RTL 调度相同，可直接做等价检查证明两者相等 |

不通过时，把**第一个不一致的样点、对应信号和场景**返回 lowering agent，在 Stage 3 内局部修复，最多 3 次。
仍失败时，该候选记为"实现失败"写回树，或退回用确定性编译器生成 RTL。

状态：确定性编译器生成 RTL、逐位对拍、握手与反压检查**已实现**；lowering agent、manifest 核对、形式等价为**计划**。

---

## 6. Stage 4：真实 PPA、Pareto 前沿、终验

### 6.1 真实 PPA

| 量 | 工具 | 本例 |
|---|---|---|
| 面积 | Yosys + ABC，Nangate45 | µm² |
| 时序 | OpenSTA，2 ns 约束下的最差 slack → 最小时钟周期 | ns |
| 功耗 | OpenSTA；翻转率目前按全局 0.1 | mW |

**PPA 不达标也是反馈**：`C.clock_target = 2.0 ns` 是硬约束。n7 的最小时钟周期是 2.2 ns，所以：

```yaml
node: n7
status: OPEN (timing)
timing: {target: 2.0, achieved: 2.2, gap: 0.2 ns, critical_path: "S2_fir: mul -> acc"}   # 来自 STA 与 manifest
recommendation: "TUNE 在 S2_fir 的 mul 后插 reg（n10）"
```

关键路径能定位到 `S2_fir`，是因为 manifest 记录了"区域 → RTL 信号"的对应，STA 报告的路径端点可以反查到区域。

### 6.2 Pareto 前沿怎么找

**候选集合**：所有 FEASIBLE、且时序达标的节点。
**比较的量**：质量裕量 μ（越大越好）、面积 A、功耗 P（越小越好）。时钟已经作为约束，不再参与比较。
**支配**：p′ 支配 p，当且仅当 μ′ ≥ μ，A′ ≤ A，P′ ≤ P，并且至少一项严格更好（超过 1%，以免把噪声当成改进）。
**前沿**：不被任何节点支配的那些节点。它是从树里筛出来的结果，不另设存储。

示意：

| 节点 | 裕量 μ (dB) | 面积 (k µm²) | 功耗 (mW) | 是否在前沿 | 原因 |
|---|---|---|---|---|---|
| n10 | 0.9 | 9.8 | 1.6 | ✓ | |
| n12 | 0.4 | 8.2 | 1.3 | ✓ | 面积和功耗最小 |
| n14 | 1.5 | 12.5 | 2.0 | ✓ | 裕量最大 |
| n15 | 0.8 | 10.5 | 1.8 | ✗ | 被 n10 支配：裕量更低、面积更大、功耗更高 |
| n16 | 0.35 | 8.4 | 1.35 | ✗ | 被 n12 支配 |

**选哪个输出**由 C 里的偏好决定：偏好最小面积 → n12；偏好鲁棒性 → n14。其余前沿设计作为备选一并输出。

### 6.3 终验 Final Check

只对前沿上的设计做，**结果不回传给搜索**；否则留出集就变成了训练集，设计会"背题"。

| 检查 | 内容 |
|---|---|
| 留出场景 | 搜索时从未用过的干扰频点和随机种子 |
| 统计复核 | 30 个随机场景，统计失败次数，给出 95% 置信的失效概率上界 |
| 验收集 | 用户/标准给的用例（Q.acceptance_set）全部通过 |
| 门级回放 | 用综合后的网表重放验收集，确认综合没有改变行为 |

全部通过 → **VERIFIED**，输出 Verilog + 质量/忠实性/PPA 报告；
不通过 → 不输出，在报告里列出失败的场景。

状态：留出与统计复核**已实现**（`verdict.py`，含失效概率上界）；终验与搜索反馈的完全隔离、门级回放为**计划**。

---

## 7. 每条关系的保证类型

| 关系 | 本例中的具体对象 | 保证类型 | 状态 |
|---|---|---|---|
| 程序合法 | 位宽、速率域、接口 | **证明**（构造时的类型规则，对所有输入成立） | 已实现 |
| 子 ≡ 父（bit-exact） | n4 多相、n5 预加、n7 分时、n10 插寄存器、n11 移位 | 现在为场景比对；**可证明**：无状态的 n5、n11 可做 SAT/穷举；有状态的 n4、n7、n10 需做时序等价检查 | 比对已实现，证明计划 |
| 子 ≈ 父（math-eq） | n6 分配律 | 理想语义下的符号恒等：**可证明**；量化差异转为近似点，归入下一行 | 比对已实现，证明计划 |
| 候选 ≈ 理想：线性部分 | S2 的 FIR / CIC 频响 | **证明**：频响由系数解析算出，对所有频率成立 | 扫频已实现 |
| 候选 ≈ 理想：有限状态源 | S1 的相位与查表 | **证明**：相位取值有限，穷举得到精确杂散谱 | 计划 |
| 候选 ≈ 理想：溢出 | 各 `q` 的饱和、累加器 | **证明**：在 Q.input_class 给定的输入范围内，用区间或 L1 范数界证明不溢出 | 计划 |
| 候选 ≈ 理想：量化噪声 | 各近似点 | **可靠上界**：逐点误差界经线性部分增益传播；若最坏情况仍达标，则为证明 | 计划 |
| 候选 ≈ 理想：非线性耦合 | 量化与强干扰叠加、饱和 | **统计界**：加固集 + 留出集 + 95% 失效概率上界 | 已实现 |
| 候选 vs 标准/用户 | Q.acceptance_set | **按定义成立**：通过验收集即合格 | 已实现（未单独分出） |
| RTL ≡ 候选 | §5.3 | 现在为逐位与事务级仿真；调度相同时**可证明**（形式等价） | 仿真已实现，证明计划 |
| 网表 ≡ RTL | 综合前后 | 现在为门级回放；**可证明**（综合等价检查） | 计划 |

所有"证明"都相对于契约声明的输入范围成立。这也是契约必须写清 `input_class` 的原因：没有输入范围，就谈不上证明。

---

## 8. 原语覆盖

| 原语 | 本例中出现的位置 |
|---|---|
| `input` / `output` | 根节点 |
| `counter` | S1 相位累加器（n0） |
| `bits` | S1 取地址、取象限（n0、n1） |
| `lut` | S1 余弦表（n0 整周期，n1 四分之一，n3 小表） |
| `mux` | n1 镜像地址与取负选择 |
| `neg` | n1 第 2、3 象限取负 |
| `mul` | S1 混频（n0）、n3 插值 |
| `q` | 各段输出截位（n0），n8 收窄 |
| `delay_line` | S2 四个抽头（n0）、n9 梳状 |
| `mac` | S2 滤波（n0），n7 `share=2` |
| `add` | S3 加偏置（n0），n5 预加 |
| `sub` | n3 插值、n9 CIC 梳状 |
| `decimate` | S3（n0），n4 前移，n9 |
| `scale` | S3 乘 g（n0） |
| `shift` | n11 移位相加 |
| `const` | S3 偏置 d（n0） |
| `reg` | n10 插流水寄存器 |
| `integrate` | n9 CIC 积分器 |

论文表中列出的原语全部用到。

---

## 9. 当前实现与计划汇总

| 环节 | 已实现 | 原型 | 计划 |
|---|---|---|---|
| 契约 F/Q/I | 声明式规格文件 | | 验收集与加固集分离；C 中的时钟作为硬约束 |
| 原语程序与类型检查 | ✓ | | |
| 树 | OR 分支、状态、父节点保留 | `hier_agent` | AND 分解、子区域组合与回传 |
| 关系核实 | 场景比对（bit-exact / math-eq） | | SAT / 穷举 / 时序等价证明 |
| 系统质量判定 | 场景 + 扫频 + slack / 缺口 | | |
| 近似点归因 | 模板版 DDC | 逐段加宽（不可靠） | 原语程序上按理想语义归因 |
| RTL 生成 | 确定性编译器 | | lowering agent + manifest |
| 忠实性检查 | 逐位对拍、握手与反压 | | 形式等价 |
| PPA | 面积、时序、功耗（翻转率 0.1） | | 门级功耗；时序不达标作为 OPEN 反馈 |
| Pareto 前沿 | 可行前沿（代理面积） | | 基于真实 PPA 的多目标前沿 |
| 终验 | 留出 + 统计复核 | | 与搜索完全隔离；门级回放 |
