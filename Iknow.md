
❯ 所以我没看懂 我们现在的 创新点是设计叙事  是什么？  然后到底现在是什么样的 你不需要和原来做对比 你跟我讲清楚就可以啦

先说结论：这篇论文要解决一个很常见的问题。工程师把数学公式做成硬件时，习惯按单个模块的误差指标来挑实现，但放进整条通信链路以后，这样挑出来的设计可能是错的。我们的办法是直接用整条链的质量和硬件成本来评判候选，让 LLM 帮忙在大量"怎么实现"的组合里找更好的设计。

1. 用一个例子说清楚问题

以接收机里的数字下变频（DDC）为例，链路是：

输入信号 → 乘 NCO 产生的正弦（混频）→ FIR 滤波 → 抽取降采样 → 输出，测 EVM

NCO（数控振荡器，也就是正弦发生器）有好几种硬件做法：查表（LUT）、CORDIC、多项式近似，每种还能调位宽和舍入方式。

工程上常见的选法是：只看 NCO 自己的误差指标（比如 SQNR），挑达标而且面积最小的那个。

问题在于，误差除了大小还有形状：
- 查表的误差往往集中成几根尖峰（杂散），落在特定频率上；
- CORDIC 的误差分布更散。

这些误差经过混频、滤波、抽取之后，只有落进有用频带的部分才会伤害最终的 EVM；抽取还会把带外误差折叠回带内。并且接收机调到哪个频道，杂散就跟着移到哪里。

结果可能是：设计 A 的 SQNR 比 B 好，放进链路后在实际要用的那些频道上，EVM 反而比 B 差。按模块指标选，就选错了。

2. 我们的办法

1. 评判标准换成整条链的质量加上硬件成本。 事先定好实际部署规格（有哪些频道、滤波要求、抽取率），用逐位精确的整链仿真算质量，再用综合结果算面积等成本。
2. 在一个统一的设计空间里同时搜索三件事：
   - 公式怎么分解（数学上等价的不同写法）；
   - 用什么近似硬件来实现（查表、CORDIC、多项式，以及它们的参数）；
   - 定点怎么做（位宽、舍入、饱和）。
3. 分工：
   - e-graph 负责保证数学变换是严格等价的，属于基础设施；
   - LLM 负责提出新结构，并根据误差诊断做修改，这对应你说的"借用 LLM 的探索能力，把公式变成硬件"；
   - 同时用传统搜索（GP 等）在同样的预算下做对照。

3. 创新点

从强到弱有三条，每条都要靠实验来证：

#: ①
创新点: 指出并量化"按模块指标选实现会选错"
说明: 找出真实的反例，并证明它确实导致了更差的设计选择；再弄清楚这种错误什么时候靠经典频谱分析就能预测，什么时候必须考虑定点的舍入和饱和。后一种情况如果成立，就是评价方法上的贡献
────────────────────────────────────────
#: ②
创新点: 以整链质量为目标的联合搜索
说明: 把公式分解、近似硬件、定点实现放在一起搜，比"结构固定只调位宽"或"只做等价改写"的现有工具找到更好的"质量–面积"折中点
────────────────────────────────────────
#: ③
创新点: LLM 的作用
说明: 在这个开放的结构空间里，LLM 比同预算的传统搜索更有效。这一条完全待证：如果实验显示 LLM
没有额外收益，就不写这条

有些东西不算我们的创新，因为别人已经做过：误差频谱会和滤波器相互作用，这是老结论；e-graph 加近似算子也已有人做（Chassis）。我们的不同之处在于，同时具备这几样：硬件近似结构、逐位精确的定点实现、多速率的整条链路、真实综合成本，以及 LLM。

4. 论文的叙事线

1. 动机： 通信硬件从公式到 RTL，大家按模块指标挑实现。用 DDC 的例子说明这样会选错。
2. 洞察： 决定系统质量的是模块误差的形状，而形状取决于实现结构和部署规格。
3. 方法： 以整链质量和成本为目标，联合搜索分解、近似实现和定点方案，由 LLM 提出结构。
4. 实验：
   - 反例：证明按模块指标确实会选错；
   - 由弱到强的几种误差预测方法：看哪种能解释这个错误；
   - LLM 和传统搜索的同预算对比；
   - 换一条链路验证结论能否迁移。
5. 诚实边界： 做出来是哪种结果，就写成哪种论文。这些分支事先定好，不事后挑。

5. 现在的状态和下一步

- 目前只完成了纸面设计：问题定义、证据标准、基线、结果分支都和 Codex 对齐了。没有写代码，也没有跑数。
- 下一步建议先做纸面预测：把 DDC 的部署规格定死（哪些频道、滤波要求、抽取率、质量阈值），然后先在纸上推出哪两种 NCO 实现最可能出现"模块指标好、整链反而差"。推得通，再修评估器、跑实验。

如果这个故事你觉得对，我就按这个方向开始做纸面预测；如果哪里听起来不像真问题，直接指出来。
---

## 2026-09-29 DDC 纸面预测对照（Claude × Codex）

详见 `thesis/WITNESS_PREDICTION_DIFF.md`。一句话：**误差阈值定下来后，只有低精度的 NCO 才可能出现"模块指标好、整链反而差"。**

- 阈值：整链实现误差让 SNR 多损失约 0.1 dB 算"工程上有意义"，判定阈值取它的十分之一。
- 现有 6 个 NCO 里，高精度的几个（n3–n6）互相差得太小（小于阈值 20 倍以上），大概率测不出有意义的反转。
- 纸面机制：接收机调到某些频道时，相位截断产生的杂散正好落进信号带，不需要外加干扰；平均看却大多落在带外。所以"平均好"不等于"最坏频道好"。
- 已定口径：整链误差按输出样点算；只用一个部署契约（可调谐接收机，9 个频点取最坏）；相位偏置用前导段估一个复数校正（相当于接收机的相位恢复）。
- 撤回的想法：CORDIC 误差近似白噪声（未证）；强干扰场景（没有标准依据）；指定某一对候选当反例（改为按规则配对、盲看结果）。
- 待你拍板：① SFDR 是否加入局部指标；② 是否在实测前冻结扩展候选池（多种尺寸的查表和 8–12 级 CORDIC）。
- 2026-09-29 你已拍板：① SFDR 现在加入（DDS 专用指标），前提是先修测量 bug、单独定容差；② 扩展候选池实测前冻结，含 7–12 级 CORDIC 和多种尺寸查表，共 20 个候选。下一步：Codex 起草冻结版预测 `thesis/WITNESS_FROZEN_DDC_v1.md`，我审，审完才修评估器。
- 2026-09-29 审 Codex 的冻结版预测 `thesis/WITNESS_FROZEN_DDC_v1.md`：暂不同意冻结，退回 2 个问题——① 相位校正系数用"只有期望信号的参考"去估，会把噪声和干扰混进误差，量级超过判定阈值，改为用同输入的浮点参考估；② "按局部指标选出的设计"没定义，改为"局部指标–面积前沿上的点被整链质量–面积严格支配"。另外纸面上已能算出配对规则会选"8 级 CORDIC vs 512 点查表"，我预测这一对**不会**出现有意义的反转（置信度低到中），要求登记。
- 2026-09-29 Codex 已按复核意见修订冻结候选稿：复标量改为只在前导段相对同输入完整浮点参考估计，保证零实现误差时校正系数严格为 1；decision witness 明确定义为局部指标–面积前沿被整链质量–面积前沿严格支配，质量差至少达到工程阈值。另冻结了数值等价候选的配对去重、`nearest` 实际为地址向下取整的语义、有限记录 SFDR 的报告边界，以及“8 级 CORDIC vs 512 点查表大概率不发生有意义反转”的纸面预测。等待 Claude 二次审阅后才正式冻结。
- 2026-09-29 Claude 二次审阅通过；最后一项是把主 decision witness 的选择集写死为“现有 6 点 + v2 20 点”的 26 个实现并集，两个分池结果只作辅助，P0/P1 仍各自在自己的池内判定。该条件已补入，`thesis/WITNESS_FROZEN_DDC_v1.md` 现已正式冻结；后续若变更协议必须新建版本，不能覆盖。
- 2026-09-29 二审冻结稿：之前两个问题都已改好。只剩一句要补——判断"选错设计"时，在哪个候选池里比（建议：现有 6 个 + 新增 20 个合在一起比，两个池也各自单独报告）。Codex 补上这句，冻结稿即生效，之后才开始修评估器。另外发现 `AGENTS.md` 里写的还是旧方向，和已批准的新方案冲突，需要更新。
- 2026-09-29 评估器修复（我负责"场景"部分）：新建场景集 `ddc-witness-scen-v1`（主 36 / 留出 32 / 压力 9），旧场景逐位不变、旧结果不作废。三处修正：① QPSK 功率注释写错（实为 0.5），只改注释不改波形，避免移动 ADC 电平；② 噪声按"期望信号"定 30 dB、不把干扰算进去，而且按 Codex 的要求在**DDC 输出端**成立（输入端相当于约 24.4 dB），这样才和"30 dB 背景下 0.1 dB 损耗"的阈值推导一致；③ 期望信号 / 干扰 / 噪声三个分量单独暴露，随机种子由场景内容派生（含版本号），不依赖排列顺序。9 项单测通过，77 个场景都没有触发削顶缩放。
- 2026-09-29 评估器第一阶段完成：修正抽取折叠 preimage；SFDR 改为已知载波消除后的复残差测量并用已知杂散校准；主误差统一为前导段复标量对齐、desired-only 输出功率归一；NCO 轨迹按复序列计算；排序新增 tau-b、边界并列完整保留和正确 kept/dropped 标签；reference 与候选共用整数 FCW。场景与指标共 16 项单测、旧链 smoke 均通过，未跑 truth。正式运行仍卡在两项：完整 accumulator-domain `M_core` 和预注册 v2 20 点池，未完成前不能把新 S1 当论文证据。
- 2026-09-29 v2 候选池已按冻结协议登记：4 个 nearest LUT、10 个 linear LUT、6 个 7–12 级 CORDIC，共 20 点；与旧 6 点合成主判定的 26 个实现。CORDIC 合法范围正式放宽为 7–20，并以单测锁定。当前正式 truth 只剩一个主要 gate：公平的完整 accumulator-domain `M_core`，以及随后对 20 点做模型/RTL 等价验证。
- 2026-09-29 完整 accumulator-domain `M_core` 已实现：不枚举 2³² 状态，而利用候选只读高 B 位的结构，按相位 bin 精确合并；复增益/MSE 用几何和，WCE 用区间端点，last-bit 命中率用整数相位域二分计数。nearest LUT、linear LUT、CORDIC_7 已在 2¹⁰–2¹² 缩位宽域与全状态 brute force 对拍一致。正式 truth 现在只剩 20 点模型/RTL 等价验证与全尺寸容差校准这道 gate。
- 2026-09-29 Codex 交叉审通过场景修复，并完成集成：主实验改用新场景集（结果写入新目录，旧结果不覆盖）；参考链也改用与电路相同的取整频率字；"只含期望信号"的分母已接好。联合单测 16 项通过。仍未跑正式实验，还差两块：① 新增 20 个候选（含 7 级 CORDIC），我提议由我负责；② 在完整相位累加器域上重算局部指标、做底噪校准，提议由 Codex 负责。等 Codex 确认分工。
- 2026-09-29 审 Codex 写的局部精度指标（在全部 2^32 个相位状态上精确算 SQNR / 最大误差 / 末位正确率）：公式正确，我另用 6 种配置暴力枚举对拍，结果全部吻合，无阻断问题；待补三处：未校正版本、与主链 NCO 共用同一段代码、单测覆盖更多配置。顺带发现我的纸面估算有偏差：512 点查表实测 44.6 dB（我当时估 49.0），7 级 CORDIC 实测 41.0 dB（与估算相符）。因此冻结稿预测的"8 级 CORDIC vs 512 点查表"这一对很可能在配对阶段就被规则淘汰，按规定只登记"纸面对被证伪"，不重新挑选。
- 2026-09-29 上述复核的三个非阻断项已补齐：`M_core` 同时报 raw SQNR/WCE/last-bit（只作敏感性），理想码舍入/正满幅饱和口径已冻结；缩位宽暴力对拍覆盖 nearest、linear、CORDIC_7、`phase_bits<16` 与 `bin_size=1`，另用 2^16 点锁定主链和指标函数的 accumulator→signed-angle 映射。正式 truth 仍等待 v2 20 点 RTL 逐位等价与全尺寸容差校准。
- 2026-09-29 复核正式 runner 时发现一个尚未越过的边界：`run_s1.py` 仍是历史 6 NCO × 8 FIR × 2 CMUL 的旧 S1 展开，而冻结 witness 要求 26 个 NCO、固定下游实现。现有脚本的场景/指标修复有效，但在候选集与固定变量对齐前只能作诊断，不能运行或引用为正式 truth。
- 2026-09-29 v2 RTL gate 已通过：20 点逐候选穷举高位相位字，连同旧 6 点的联合报告为 26/26 `mismatch=0`（`experiments_system/nco_rtl_equiv_v1/report.json`）。完整映射识别出 4 个非单例等价类；它们只在主 pair 选择时合并，面积/Pareto 仍保留。场景、指标、RTL 联合回归 42 passed，旧链 smoke PASS。下一道 gate 是正式 26-NCO/固定下游 runner 与 `q_cal`，不是直接跑旧 `run_s1.py`。
- 2026-09-29 正式预检 manifest 已生成但 truth 仍锁住：26 个 NCO，下游固定 `f1_c16+c1_exact_rne`，场景版本与 RTL 报告哈希入档；exact-representable 零误差例给出 `q_cal=0`、`epsilon_Q=2.32929922807541e-6`。`preflight_manifest.json` 显式写 `truth_runner.allowed=false`，直到专用 26-NCO/固定下游 runner 完成并校验 manifest。联合回归 45 passed。







• 还不是正式论文实验，现在处于“实验前验收”的最后阶段。

  已经完成的是工程验证：

  - 场景与指标评价器修复；
  - 26 个 NCO 候选池冻结；
  - 解析局部指标与缩位宽穷举对拍；
  - 26/26 个候选的模型—RTL 全映射逐位一致；
  - 单测与 smoke test 通过。

  正式实验前还差两件事：

  1. 新建正式 witness runner：必须是“26 个 NCO + 固定 CMUL/FIR”，不能直接使用旧的 run_s1.py（它仍是 6×8×2 的旧
     实验）。

  2. 冻结并校验 runner manifest 与 q_cal：明确固定下游配置、测量区间、复标量对齐、候选池摘要、场景版本及零误差
     底噪。

  这两项通过后，才进入真正的实验环节：

  - 跑 36 个主场景；
  - 计算局部指标与链级最坏 NMSE；
  - 做候选配对、排序反转和 Pareto 决策损失判断；
  - 再根据结果决定进入 E0、E1 还是 E2 分支。

  所以准确说：研究方向和实验协议已经定了，评价基础设施基本验收完毕；现在正站在正式实验入口，但还不能直接拿旧脚
  本跑数。


› 那你说说 我们整个研究方向是什么  要做哪些实验  如果有ascii 流程图 具体是那些


• ## 一句话方向

  借助 LLM 的结构探索能力，把通信 DSP 数学公式变成定点 RTL；但不再用“测试是否通过”或单模块 SQNR 判断设计好坏，
  而是按真实部署契约下的整链数值质量与综合面积进行搜索。

  暂定论文问题可以表述为：

  > 在结构异构、带滤波和抽取的通信 DSP 链中，局部数值指标是否保持系统级设计排序？如果不保持，怎样用结构感知的
  > 链级评价信号指导公式到 RTL 的联合搜索？

  核心不是简单地“把精度加入 fitness”，而是：

  > 候选误差的频谱形状与下游多速率处理相互作用，局部指标可能选错硬件结构。

  例如两个 NCO 总误差功率相近，但：

  - LUT 截断误差可能形成与 FCW 相干的杂散；
  - CORDIC、插值 LUT 产生另一种相干误差谱；
  - FIR 会压制一部分频率；
  - 抽取会把另外一些误差折叠回通带。

  因此局部 SQNR 更好的实现，进入 DDC 后可能反而具有更差的链级实现 NMSE。

  ———

  ## 整篇论文的逻辑

  数学公式 + 部署契约
          │
          ▼
  ┌─────────────────────────────┐
  │ 精确公式变换层               │
  │ e-graph / verified rewrites │
  │ 只放实数语义严格等价的变换   │
  └──────────────┬──────────────┘
                 │ 等价分解族
                 ▼
  ┌─────────────────────────────┐
  │ 近似硬件实现空间             │
  │ LUT / 插值 / CORDIC / Poly  │
  │ 字长 / 舍入 / 饱和 / 截断    │
  └──────────────┬──────────────┘
                 │
         LLM / GP / MCTS 提案
                 │
                 ▼
  ┌─────────────────────────────┐
  │ 确定性 lowering              │
  │ typed IR → bit-true RTL      │
  └───────────┬─────────────────┘
              │
        ┌─────┴─────────┐
        ▼               ▼
  链级数值评价       Yosys/Nangate45
  Q：系统误差       area：综合面积
        └─────┬─────────┘
              ▼
         (Q, area) Pareto 前沿
              │
              ▼
  判断 LLM 是否找到传统搜索未找到的结构

  其中各部分身份是：

  - e-graph：保证数学变换的精确性，是基础设施，不单独作为创新。
  - LLM：提出开放、组合式的结构变换，并读取误差诊断修改结构。
  - 定点误差评价：告诉搜索“哪些近似在系统契约下是有价值的”。
  - 真实综合：独立提供硬件成本，不能用误差模型顺便估面积。

  ———

  # 三项核心贡献

  ## 贡献一：证明局部指标可能导致真实设计决策错误

  不是只展示两个候选排序不同，而是同时要求：

  1. 局部指标出现严格反转或信息塌缩；
  2. 在相同硬约束和成本口径下，局部指标选择的实现产生可测 regret；
  3. 或者该实现被链级 (Q, area) 前沿严格支配。

  这是论文的“问题实例与损失”。

  ## 贡献二：结构感知、契约感知的公式到 RTL 搜索

  联合搜索：

  - 数学分解；
  - 近似实现结构；
  - 定点策略；
  - 最终 RTL 的面积—质量折中。

  评价分为三层，不强行把所有东西叫“解析”：

  整数域精确计算
      │ 能精确算的局部算子
      ▼
  结构特异的线性传播
      │ 保留复残差、互谱、FIR/抽取相干传播
      ▼
  确定性 bit-true 链级评价
        处理 round / trunc / saturation / 交叉项

  ## 贡献三：检验数值反馈是否真正释放 LLM 的结构探索能力

  这条完全由实验决定，不预设为真。

  若 LLM 没有比 GP/MCTS 更好，就不声称 LLM 有独特收益。

  ———

  # 第一阶段：DDC witness 实验

  固定链路：

  QPSK + AWGN + blocker
            │
            ▼
         ADC Q1.11
            │
            ▼
    候选 NCO（唯一变化项）
            │
            ▼
   固定 CMUL：c1_exact_rne
            │
            ▼
     固定 FIR：f1_c16
            │
            ▼
         2:1 抽取
            │
            ▼
  链输出 implementation NMSE

  候选池为冻结的 26 个 NCO：

  - 历史候选：6 个；
  - v2：20 个；
  - 结构包括 nearest-LUT、linear-LUT、CORDIC 7–12 级；
  - 精确数值等价候选只在 pair 选择时合并，面积分析仍全部保留。

  部署场景：

  9 个 FCW
   ×
  4 种场景
   ├─ clean
   ├─ OBB 0.300 MHz, -3 dB
   ├─ OBB 0.420 MHz, -3 dB
   └─ alias-edge 0.555 MHz, -3 dB
   =
  36 个主场景

  另外保留：

  - 32 个 held-out 场景；
  - 9 个 +6 dB stress 场景；
  - held-out 和 stress 不能用于寻找主反例。

  ———

  ## 局部指标

  核心通用指标 M_core：

  - calibrated complex SQNR；
  - WCE；
  - last-bit accuracy。

  DDS 专用指标 M_DDS：

  - 九个 FCW 上的 worst SFDR。

  冻结容差：

   指标                    容差
  ━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━
   SQNR                 0.10 dB
  ───────────────────  ─────────
   WCE                    1 LSB
  ───────────────────  ─────────
   last-bit accuracy      2^-32
  ───────────────────  ─────────
   SFDR                 0.25 dB

  ———

  ## 系统级真值

  主质量指标不是总接收 EVM，而是：

  > 候选定点链输出相对同输入 float 参考链的 aligned implementation NMSE。

  具体口径：

  - 前导段只估计一次全局复增益；
  - 数据段不重新拟合；
  - 分母使用 desired-only 参考输出功率；
  - 对 36 个场景的线性 NMSE 取 worst；
  - 报告时才转换成 dB。

  这样 AWGN 不会把 NCO 实现差异淹没。

  ———

  ## 反转判据

  对任一局部指标 m：

  局部指标认为：A 明显优于 B
  m(A) + εm < m(B)

  但整链契约认为：A 明显差于 B
  Q(A) > Q(B) + εQ

  这是 strict reversal。

  另一种是 collapse：

  |m(A)-m(B)| ≤ εm
  但
  |Q(A)-Q(B)| > εQ

  真正的 decision witness 还要加入面积：

  局部指标—面积前沿选出的实现
                   │
                   ▼
  在链级 (Q, area) 上被另一个候选严格支配

  ———

  # 第二阶段：解释反转机制

  采用由弱到强的基线梯子：

  ① 总误差量
     SQNR / WCE / last-bit
                │
                ▼
  ② DDS 经典模型
     SFDR / Nicholas / phase-truncation spur / folded QNTF
                │
                ▼
  ③ candidate-exact linear-reference
     真实复残差 + 相干 FIR/抽取传播
     保留 alias preimage 和互谱
                │
                ▼
  ④ full bit-true chain
     加入 CMUL/FIR round、trunc、sat 和交叉项

  可能出现三种有意义的结果：

  - ①失败、③成功：问题真实，但经典线性传播足够解释。贡献落在自动组装结构特异模型和联合搜索。
  - ③失败、④成功：round/saturation residual 及交叉项是必要机制，这是最强的评价方法贡献。
  - 所有局部指标都不失败：登记负结果，停止扩张这个主张。

  alias 本身是已知现象，不作为创新。

  ———

  # 第三阶段：系统级联合搜索

  前两阶段证明问题真实后，再做搜索实验：

  公式分解
    × 近似原语
    × 定点参数
    × 系统部署契约
          │
          ▼
  搜索 (Q, area) Pareto 前沿

  强基线包括：

  - 固定结构只调字长的 WLO/fxpopt 式流程；
  - 小空间穷举；
  - GP；
  - beam search；
  - MCTS；
  - iterative ILP；
  - LLM 提案。

  所有方法统一预算，失败提案也计入预算。

  ———

  # 第四阶段：LLM 机制实验

  主实验是完整 2×2：

   提案器           satisfaction/test-pass 反馈    数值质量反馈
  ━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   LLM              LLM + Boolean fitness          LLM + numerical fitness
  ───────────────  ─────────────────────────────  ─────────────────────────────
   强非 LLM 搜索    GP/MCTS + Boolean fitness      GP/MCTS + numerical fitness

  核心统计量是 difference-in-differences：

  LLM 在数值反馈下的增益
  -
  非 LLM 在数值反馈下的增益

  第五臂：

  LLM + 数值标量
  vs
  LLM + 数值标量 + 误差诊断

  如果要声称“诊断特别适合 LLM”，还要补：

  GP/MCTS + 数值诊断

  否则只能说诊断对搜索有效，不能说是 LLM 特有能力。

  ———

  # 第五阶段：迁移验证

  DDC 只是第一条机制链。若 DDC gate 成立，再选至少一条不同的通信多速率链，例如：

  - DUC / CIC / 多相插值；
  - channelizer / polyphase filter bank；
  - OFDM FFT/twiddle 精度链；
  - 同步或信道估计链。

  进入主实验的算子必须满足：

  - 至少两个真实算法分解类；
  - 精度可谈判；
  - 可生成 bit-true RTL；
  - 有强基线；
  - 能定义真实系统契约；
  - 可以获得综合面积。

  完整 SDR/3G/4G/5G catalog 用于说明覆盖面，不要求每个算子都跑完整搜索。

  ———

  # 总实验顺序

  [0] 文献与问题定位
            │ 已完成
            ▼
  [1] 冻结契约、候选池、阈值和预测
            │ 已完成
            ▼
  [2] 修评价器 + 模型/RTL 全空间对拍
            │ 基本完成
            ▼
  [3] 正式 26-NCO / 固定下游 runner + q_cal
            │ 当前所在位置
            ▼
  [4] 跑 36 个主场景，寻找 mechanism/decision witness
            │
            ├─ 无反转 ───────────────▶ 停止该论文主张
            │
            ▼
  [5] 用 ①→④ 基线梯子解释机制
            │
            ▼
  [6] 26 点真实综合，计算 (Q, area) 前沿与 regret
            │
            ▼
  [7] 开放结构空间联合搜索
            │
            ▼
  [8] LLM × feedback 的 2×2 + 诊断第五臂
            │
            ▼
  [9] 第二条通信链迁移验证

  所以现在真正要做的不是盲目“大规模跑实验”，而是先完成第 3 步的正式 runner 和底噪校准，然后按冻结协议运行第 4
  步。只有第 4 步找到超过工程阈值的真实决策损失，后面的搜索和 LLM 实验才有坚实基础。


## 2026-09-30 独立只读审查：正式 witness runner 与实验口径（verievolve 臂）

结论：**无 blocker**，预检 manifest 与冻结稿逐项对得上，可进入正式 runner 实现。要点：

1. **固定下游 f1_c16+c1_exact_rne 隔离成立**：同 x_adc、同整数 FCW（共享接口条件）、下游取注册池保真度最高组合（wc16/精确 int64 累加/rne/无丢位），把下游算术底压到最低，ε_Q=2.3e-6 量级可分辨 NCO 差异。q 含 NCO×下游非线性交互是协议本意（E1/E2 分支），不算混杂。
2. **饱和实测为零**：/tmp 只读诊断，77 冻结场景 × 2 代表候选（n4、v2_cordic8），n_sat_mix=n_sat_fir=0；混频预削波峰值比最大 0.806（≈1.9 dB 余量，alias +6 dB stress）。机制：场景 scale 规则保证 |x|<1，本轮 77 场景全部未触发 0.95 归一化分支。注意安全性来自场景缩放而非数据通路——静态 4 个角点状态本会饱和（worst_exact_abs=2^16=2×满幅），runner 必须逐候选×场景记录 n_sat 并对 main 断言为 0。
3. **q_cal=0 校准只覆盖平凡路径**（identical-reference 走 array_equal 快捷分支；y_des_ref=y 使 desired-only 分母路径未被检验）。不阻塞：aligned_impl_error 无大数相减抵消结构，float64 底噪比 ε_Q 低 9 个数量级。truth 前建议补三个校准例（已知 g≠1、已知小误差功率、y_des_ref≠y_ref），只加测试不改冻结值。
4. **manifest 唯一 truth 前必补项：面积/综合口径**（冻结稿 §5.3 要求的 Yosys 版本、liberty 哈希、综合脚本、top module 全缺）。建议主口径 NCO-only：固定下游是常数偏移，(Q,area) Pareto 支配关系对常数平移不变，两种口径 decision witness 数学等价，但 NCO-only 才有可解释的量纲。另有 6 项建议补：代码/文档 sha256、P_c/M_c 测量段索引、局部指标表先冻结、SFDR 记录长度、环境版本。
5. **SFDR（9 FCW worst）与 Q（36 场景 worst）聚合轴不同是设计使然**：一个无 blocker 维度一个有，正是 H1 检验对象。runner 必须输出两个 worst 的 argmax；Q 在线性域取 max、SFDR 在 dB 域取 worst，不许混域。
6. 核对通过：77 场景 key/seed 与 spec 派生 0 不一致；worst_drop/tau-b/折叠索引/QPSK 功率/AWGN 口径五项修复均在；单测 23 passed；AUDIT §8.4/8.5 登记完整；等价类 22 组（4 非单例）。

## 2026-09-30 正式 runner 与面积 gate 已实现（未跑 truth）

- `run_witness_v1.py` 采用双阶段：`prepare` 先冻结 local/SFDR、Q-blind pair、NCO-only Nangate45 面积并签发 execution manifest；`truth` 只能读取该 manifest 与显式新 `run-id`。历史 `run_s1.py` 继续禁用。
- preflight 已补唯一必需缺口：Yosys 版本、Nangate45 liberty/脚本哈希、top=`nco_map`、主成本=NCO-only；全链成本只作 context。并补协议/代码指纹、P/M 段、SFDR 长度/窗、Python/NumPy/SciPy 环境。
- truth schema 记录线性 q、复增益、p_ref、饱和、预削波峰值、argmax；main 判定先落盘再允许 heldout/stress。main/heldout 饱和即停；decision witness、reversal/collapse、三分池前沿和 SQNR regret 机械生成。
- 已补 g≠1、小误差功率、desired-only 分母三类校准测试；相关回归 52 passed。仅做一次临时 NCO-only 综合 smoke 验证面积解析，没有生成 `frozen_inputs_v1`，没有运行 chain truth；`preflight_manifest.json::truth_runner.allowed` 仍为 false。

## 2026-09-30 冻结输入已生成（仍未跑 chain truth）

- `frozen_inputs_v1` 已锁定 26 点 local/SFDR、NCO-only area 与 190 对 Q-blind pair 表，execution manifest 哈希复验通过；只有 execution manifest 放行正式 truth，preflight 本身仍保持 false。
- 冻结规则选中 `v2_lut512near_b16` vs `v2_cordic8_b16`；实算 calibrated SQNR 为 44.58824775500641 / 46.976135312974534 dB（差 2.387887557968128 dB）。nearest512 的 49.0 dB 纸面估计在 selection stage 被证伪，但规则仍选中同一对，未重选。
- 两端 9-FCW worst SFDR 为 47.81666971005927 / 47.84500439065506 dBc，落在 0.25 dB 并列容差内；只有跑出主契约 Q 后才能判断 collapse/reversal。
- NCO-only mapped area 共 26 点，范围 368.41–3809.918 μm²；pair 两端 820.61 / 1584.03 μm²。190 对中 11 eligible、113 超 3 dB、66 同结构类。所有数字均来自 `experiments_system/ddc_witness_v1/frozen_inputs_v1/*.json`；`runs/` 尚不存在。

## 2026-09-30 formal DDC truth 首轮结果

- `formal-v1-20260930` 完成 26×77=2002 行；main/heldout/stress 为 936/832/234。全程 CMUL/FIR 饱和为 0，最大预削波峰值比 0.8078684061765671。产物在 `experiments_system/ddc_witness_v1/runs/formal-v1-20260930/`。
- legacy 6 点四项都无 failure；v2/26 点出现超 ε 的 strict reversal（SQNR/WCE/SFDR）与 last-bit collapse，所以不是 E0。但四项 `decision_witness` 全为 false：机制存在，尚无设计损失。
- 共同 strict witness 是 CORDIC7 局部更好、nearest256 链级 Q 更好；相对 n1 的 ΔQ=4.968561768671522e-6>ε_Q。不过两者 Q 都是预算的约 4.7–4.9 倍，且 CORDIC7 不处于造成选择损失的位置，只能作 mechanism witness。
- 冻结主 pair LUT512 vs CORDIC8 的 |ΔQ|=1.447473447272321e-6<ε_Q，固定预测阴性，不重选。SQNR≥S* 辅助选择 `v2_lut1024lin_b10` 的 quality/area regret 都为 0。
- 下一步不是搜索/LLM，而是先用既有 ε_Q 冻结基线③ Gate A/B，再跑 candidate-exact linear-reference；过则 E1，不过再做④判 E2/E3。

## 2026-09-30 强线性基线③通过：Evaluation axis = E1

- 运行前先冻结 `thesis/BASELINE3_PROTOCOL_DDC_v1.md`：Gate A 用既有 ε_Q，Gate B 用 top-{1,3,5} regret / 预算违约 / 已登记 failure 解释率；stress 不参与 gate。
- ③使用候选 bit-true NCO、本场景 x_adc、固定 f1_c16 量化系数的线性 FIR、相干抽取，排除 CMUL/FIR round/sat。结果在 `ddc_witness_v1/baseline3_v1/results.json`。
- Gate A 过：main+heldout 1768 点 max |q3−qtrue|=8.962187760598898e-8，仅为 ε_Q 的 3.8476%；三结构类都过。
- Gate B 过：top-1/3/5 regret=0，false-feasible=0，tau-b=1.0，26 个登记 failure 全解释。因此是 E1：经典结构特异相干线性传播已经足够，不能声称新误差理论，④无需为本批结果启动。
- 论文现在真正的 gate 是 S1：是否能把这种结构特异的链级 fitness 自动装配进开放结构搜索并改善前沿。当前固定 26 点无 decision witness，不能说局部指标已造成设计损失。

## 2026-09-30 S1 开放结构搜索协议开始落地

- 新增 `thesis/SEARCH_PROTOCOL_v1.md` 草案。当前工作不是在 26 点 NCO 池上继续跑进化，而是先冻结真正组合式的 F2.5 typed design IR、共同动作集、feedback 对照、公平预算与 S1 停止条件。
- 最小主空间为 A1 NCO + A3 FIR/decimator + A2 DDC：NCO 至少 LUT/CORDIC 两类，FIR/抽取至少 direct-symmetric/polyphase 两类；LLM、GP、beam/MCTS 共用相同 IR、合法动作、lowering 和预算。
- 主 satisfaction 对照定义为逐场景 `1[q_c <= q_budget]` 的 pass count，而不是对近似实现必然退化的 bit-exact 全失败；numerical 臂观察连续 `Q=max q_c`。这样只改变反馈信息量，不改变候选语义或场景。
- 搜索前先过 R1–R5 表示 gate；S1 要求 held-out truth 上出现超过 `epsilon_Q`/`epsilon_A` 的新 Pareto 点，且多种子 hypervolume 差置信区间为正。S0 时停止 LLM 独特性与第二条链扩展。
- e-graph 仅作精确重写基础设施与后续消融，不阻塞 typed AST v1；真实 LLM 后端只在非 LLM pilot 和 S1 gate 之后接入。
- 自检补上 R6：IR 不能只是“每级选一个模板”。至少用 `exp(jθ)=exp(jθ_coarse)exp(jθ_residual)` 支持 coarse-LUT 与 residual-CORDIC/poly 的通用组合，并保留一个未手工登记结构验证 lowering；若新增组合仍需按候选名写专用分支，就不算开放结构空间。
- 实现盘点显示主要缺口不在 OpenEvolve，而在表示与 lowering：现有 NCO/FIR 都由参数字典和整段 generator 驱动，FIR 还把 `prod_drop==0` 与对称结构隐式耦合。首批工作包按 schema → NCO 旧实现等价 smoke → 未注册 phasor-compose → direct/polyphase FIR → DDC evaluator → 非 LLM 强基线推进；S1 之前不接真实 LLM。
- WP1 首版已落到 `examples/comm_dsp_bench/search_ir/`：统一 JSON-shaped typed IR、严格字段/类型/rate/契约校验、忽略非语义 metadata 的稳定 SHA-256 结构身份，以及 leaf LUT/CORDIC、phasor-compose、direct-symmetric/polyphase FIR 构造。未知字段和契约漂移直接拒绝，避免用隐藏 candidate selector 绕过开放空间。
- `tests/test_search_ir_schema.py` 覆盖叶子结构、未注册 LUT+CORDIC 组合树、hash 稳定性/语义敏感性、契约漂移和 v1 组合深度边界；与 DDC 相关回归合计 57 passed。环境未安装 Black，已用 `py_compile`、100 列检查和 `git diff --check` 验证。
- WP2 NCO leaf smoke 已落地：`lower_bittrue.py` 与 `lower_rtl.py` 只按 IR node kind 把 LUT/CORDIC 叶子映射到现有 bit-true 模型和 `nco_map` RTL，不读取候选名；结构名由语义 hash 生成。随机 accumulator 对拍和既有 26 点 RTL 等价回归合计 62 passed。`phasor_compose` 当前显式拒绝 lowering，等其 coarse/residual 位语义冻结后再做 WP3，避免无声回退成叶子模板。
- `phasor_compose` 的候选位语义已写入搜索协议：32 位相位按最近 coarse 格点分解，残差唯一落在 `[-S/2,S/2)`，coarse/residual 子节点各自输出 Q1.15 phasor，再做显式复乘、右移舍入和 Q1.15 饱和。精确性只属于相位分解恒等式，子原语与组合乘法仍计实现误差。
- WP3 首个未注册组合结构已闭环：通用 `phasor_compose` lowering 生成 coarse-LUT + residual-CORDIC 的整数模型和层次化 RTL，不按候选名写专用分支。相位 split 的 modulo 恒等式与 centered residual、组合乘法均有测试；`rne`/`trunc` 两种模式在随机 accumulator 和 coarse 边界点上经 Icarus 逐位一致，生成 RTL 通过 Yosys `synth -top nco_map; check`。搜索 IR + DDC 相关回归现为 65 passed，单独 schema/lowering 含综合为 14 passed。
- WP4 的两个 FIR/R=2 结构已独立落地：direct-symmetric 在对称预加乘积后量化，polyphase 在逐 tap 乘积后分别做偶/奇支路求和；无 product drop 时两者逐位等价，有 drop 时能产生结构特异误差。两种流式 RTL 在 `rne/trunc`、product drop、有限 accumulator 配置上均与各自 Python 模型对拍，Yosys `hierarchy/proc/opt/check` 通过；相关 DDC/IR 回归 81 passed。
- 通用 FIR 完整 `synth` 单测在 110 秒内未完成并被人工中止，不登记为失败，也不冒充正式面积证据。R4 的“可综合 + 面积”仍须用冻结 Nangate45 脚本、结构 hash 缓存和明确超时正式执行；当前只证明前端可展开、结构检查通过且仿真位一致。
- WP5 已完成最小整链闭环：`emulate_ddc_candidate` 与 `lower_ddc_rtl` 共用 typed IR 和 32 位可编程 FCW，覆盖 NCO→固定 exact/rne CMUL→FIR/R=2。叶子 LUT+direct FIR 与未注册 LUT/CORDIC compose+polyphase FIR 两个完整候选在 97 拍随机输入上经 Icarus 逐位一致，并通过 Yosys 结构检查；IR/DDC 相关回归 85 passed。
- 这一步仍不产生研究数字：没有跑冻结 77 场景、没有综合 Nangate45 面积、没有接搜索器或 LLM。下一 gate 是把 candidate manifest 接进冻结契约 evaluator、冻结全链综合缓存键，再做 R4 正式面积与非 LLM pilot。

## 2026-09-30 S1 接口背压闭环

- 自检发现前一版生成 RTL 只有 `in_valid`，没有完整的 ready/valid 语义；这不满足 P2，因此在进入搜索前补齐一深度输出弹性缓冲。FIR 与完整 DDC top 现在都有 `in_valid/in_ready/out_valid/out_ready`，输入状态、相位累加器和 FIR 延迟线只在 `in_valid && in_ready` 时推进。
- 新增真实停顿测试：在第一个有效 DDC 输出保持 `out_ready=0` 三拍，验证 `in_ready=0`、输出数据稳定且下一输入未被提前接受；恢复后继续输入，输出序列与 bit-true Python 模型逐点一致。direct-symmetric 与 polyphase 两个候选均通过（2 passed）。
- valid/ready 修复后的 FIR/DDC 回归为 21 passed；仍未跑冻结 truth、Nangate45 面积或任何搜索实验。下一步仍是 candidate manifest/evaluator 接口与冻结综合缓存键，之后才做 R4 正式面积和非 LLM pilot。
- 随后完整相关回归（search_ir schema/lowering/FIR/DDC、DDC metrics/scenarios、witness preflight、NCO RTL equivalence）共 87 passed，未启动冻结 truth、Nangate45 面积或搜索实验。
