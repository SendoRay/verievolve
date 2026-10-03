
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

## 2026-09-30 宏观主线复核：先证明设计收益，再扩实现

- 研究目标不是补齐“IR+LLM平台”，而是检验固定通信任务、数值契约与提案预算下，联合结构/近似/定点化能否改善质量—真实综合面积选择；typed IR 与模型—RTL闭环只是比较资格。
- 已只读核对正式 `main_decision.json::metrics.*.pools.union26.decision_witness` 均为 false，辅助 SQNR 选择两类 regret 为 0；`baseline3_v1/results.json::gate_a.pass/gate_b.pass` 均为 true，支持 E1。当前是“机制存在、经典基线足够、设计损失未证、开放搜索尚未验证”，不能报 S0/S1。
- 搜索草案存在比较层级待澄清：目标涉及强通用搜索，但 S1 具体判据主要比较 staged/cost-first。若用 GP 执行联合搜索，就不能再声称击败同配置 GP；建议 S 先固定强非 LLM 引擎检验“联合修改 vs 分阶段锁定”，LLM 增量留到 L。此为待审建议，未改冻结协议。
- 区分表示可达集合、决策/反馈、提议器三个变量；同一空间与评价下，算法改变的是有限预算发现的前沿，不是真实 Pareto 集合。WLO 强基线应允许系统级质量约束；numerical/satisfaction 检验信息量，不等于局部/系统评价对照。
- 最小顺序：明确比较命题→补最小可信闭环→非 LLM 正式 S 检验→仅 S1 后测 L。新 FIR 不自动继承旧 E1，旧 NCO-only 面积不代替全链成本，已被查看的历史 held-out 不称全新盲测。
- 详见 `refine-logs/FINAL_PROPOSAL.md`；本轮仅本地材料与既有产物的内部独立复核，未做外部评分/全面查新，未跑新实验或改实现。工程 A 审计另行收敛。






▎ 草案把“联合决策优于分阶段流程”和“搜索算法优于同语言 GP”混在了一起。如果用 GP 执行联合搜索，就不能再拿同配置 GP 当被击败的基线。

我的建议是：

1. 主问题先固定为联合决策的价值：用同一个强非 LLM 搜索引擎，比较“结构与定点化共同修改”和“先锁结构、再调字长”。
2. 只补支撑这项比较的最小闭环：可信整链质量、真实全链面积、公平预算与可追溯结果，不扩平台。
3. 正式结果支持收益后，再检验 LLM 增量；否则接受负结果，不靠扩任务寻找阳性。

实际证据仍是：E1、存在机制反转、旧池无已证决策损失；开放结构搜索尚未判定。 工程通过不等于 S1，未完成也不等于 S0。

完整建议已保存到：
- refine-logs/FINAL_PROPOSAL.md
- 精简认识已追加到 Iknow.md:584

这些是待审建议，不是协议冻结。实现与原暂存区未改；工程 A 审计仍在收敛，未启动仿真、综合或搜索。

✻ Waiting for 4 background agents and 1 dynamic workflow to finish

✻ Waiting for 4 background agents and 1 dy

## 2026-09-30 工程 A 已返回部分：优先最小开发闭环

- IR 身份域确认两个校验缺陷：固定字段/零哨兵接受 bool/int 等类型别名，导致同数值实现出现不同结构 ID；枚举/depth 的 list/dict 输入泄漏 `TypeError` 而非 `IRValidationError`。位置为 `search_ir/validate.py:48-61,98-99` 等；不是 hash 算法错误，也没有已发生搜索缓存污染的证据。限定纯 Python 测试为 20 passed、9 deselected，不能当 RTL/综合复验。
- 第一版 B 可以更小：固定少量 IR fixture、独立开发 manifest、公共评价适配和校验前记账；先禁用缓存、明确不支持 resume、同 run-id 拒绝重启。无需先实现三套缓存、所有 proposer/action API 或冻结正式预算/seed，避免“等实验校准才能开发评价器”的循环依赖；启用这些能力前再验收。
- 旧 witness 已有独占 run 目录和 execution→preflight/输入 hash 链；不能说全仓库没有身份保护。新 typed IR 尚未接入，故完整上下文/账本/回显是 missing-gate，而不是现有正式搜索已漏计预算。
- 旧 helper 的四项条件性缺陷已用临时 fixture/mock 复核：preflight 可覆盖、RTL 报告消费校验不足、baseline 缺 truth→execution 输入绑定、综合 helper 未检查非零退出码。它们只约束未来复用路径；当前历史引用链匹配，不能据此否定既有 witness/面积/E1。B 可新增独立 adapter，避免修改历史证据链上的旧工具。
- 预算域限定测试为 8 passed（含只读历史报告检查）；与 IR 域测试存在重叠，不累加为统一回归数。本轮没有新仿真、综合、truth 或搜索。其余领域与跨域完整性结论尚未全部汇总，本节不代表整个 A 已完成或 B/C 获准实施。

## 2026-09-30 工程 A 最终汇总完成（不自动进入 B）

- 四域及跨域完整性复核已完成，详见 `refine-logs/STAGE_A_AUDIT.md`。可以据此准备最小 B 代码计划，但 C/R4、正式搜索和 S0/S1 均未获验收；不改历史 witness、原暂存代码或冻结协议。
- 新增接入边界：IR 类型合法不等于 FIR 满足既有通带/阻带掩码；新旧 `n_sat_fir` 分别按保留抽取输出/全部输入时刻计数，保留输出相同也可能计数不同。必须明确部署可行性与饱和事件统计域，不能接同名字段就声称继承契约。
- 新评价器应拒绝非有限 q 和不完整场景；旧聚合已由合成数组复现 NaN 的顺序依赖，但没有证据表明历史合法候选已触发。旧模板缓存也有生成/综合依赖失效与可选后端失败固化问题，新管线不宜直接复用。
- satisfaction 投影需在 selection/archive/历史/特征和 prompt 之前隔离连续质量，不能仅删返回字典中的 q。共同 JSON schema 不保证动作公平；这些在接 proposer 前验收，固定 fixture 的 B 不必先实现全部动作 API。
- attempt 在 parse 前登记，整次提案只计一次而非各阶段分别扣；缓存计算身份与当前 run/attempt 封装分开，manifest/RTL 摘要避免循环引用。B 可先无缓存、无恢复、无 proposer；未产生的面积明确 unavailable，随后另做真实全链综合计划。
- 本轮各域限定测试分别为 IR 20 passed/9 deselected、质量 32 passed、预算 8 passed；相互重叠不相加。综合仅临时 mock/摘要检查，没有运行仿真、综合、truth、搜索或 LLM 实验。原暂存区 diff SHA-256 与开始一致。


## 2026-09-30 搜索协议独立复核与工程提交边界

- 当前一层 phasor-compose 超越候选编号枚举，但仍是有界语法组合空间；R6 证明构造能力，不证明搜索收益，也不支撑任意递归结构发现主张。
- satisfaction 是同一数值契约的阈值反馈消融，不等于复现 COEVO test-pass；须冻结反馈为 verdict 向量还是 pass count，并在 selection/archive/history 等决策入口之前隔离连续质量。
- SEARCH_PROTOCOL §6.2 正式冻结还须指定预算网格、基线前沿合并规则、固定 HV 坐标/归一化/reference point/可行域和 seed 级置信区间。HV 改善不保证各预算无损失，另报预算网格 regret/覆盖；held-out 不用于选点调参。
- 最小 NCO+FIR 空间足以做受限联合搜索 pilot；联合收益需与 staged、NCO-only、FIR-only 同预算比较，不能把 direct/polyphase 的相同数值输出当作数值多样性。上述要求不放行正式搜索。
- 本轮仅复跑待提交 DDC/FIR 测试：21 passed；暂存区格式检查通过。没有新场景 truth、真实面积或搜索结果。7 个已暂存文件可作为 WP5 工程检查点申请提交，未暂存研究记录不夹带，commit 仍待用户确认。

## 2026-10-01 阶段 B 最小开发评价闭环（实现与回归）

- 新增 `search_ir/evaluate.py` 与 `dev_run.py`：固定合成输入经同输入参考链/desired-only 分母/前导 LS 对齐得到 `Q_dev`，检查输出 sequence tags、有限质量、完整 case 覆盖及实际 FIR 掩码。该结果不叫 `Q_main`，不判 S0/S1。
- 修复 IR 固定字段的 bool/float 别名和容器枚举异常；合法结构 hash 不变。原始提案在 parse 前登记一次预算占用；重复与失败都计数。运行目录、候选/结果只写一次；上下文或执行异常封闭运行，不提供缓存、恢复、proposer 或真实综合。
- manifest 绑定实际输入/reference/desired 数组快照、FCW/测量索引、源码、系数、阈值来源和环境；结果回显身份，缺项/漂移/错误聚合均拒绝。satisfaction 开发接口只暴露 pass count，不代表含 selection/archive 的正式 R5 已通过。
- mixer 饱和统计含全部接受输入，FIR 统计含实际保留有效输出，均包含前导；FIR 累加/输出事件合计，不冒充旧全输入时刻统计。正式部署可行性保持 pending，mask 失败明确 failed；area 为 unavailable，不复用历史 NCO-only 面积。
- 最终回归 `python -m pytest -q tests/test_search_ir_*.py tests/test_ddc_metrics.py`：131 passed；包含短合成用例、mock 与已有 RTL 回归，未运行正式场景 truth、真实面积或搜索。`git diff --check` 通过。Black 本地未安装，下载执行被权限策略拒绝，自动格式化未完成。
- 独立只读复核发现评分接口的整数 dtype 会在能量/相关积处静默溢出（int8 100/101/102 反例）；已在信号入口统一提升为 complex128，码字/tag 保留整数，补 6 种 dtype 对照回归。此前复数 fixture 结果不受影响。复核未发现固定 fixture 主路径阻断问题；B 软件闭环已实现，尚不放行 C/R4 或正式搜索。

## 2026-10-01 阶段 C 固定候选 full-DDC 综合

- 目的仅为建立可信全链成本，不判 S1，不研究迭代 CORDIC/流水/吞吐微结构；有疑问时先回看设计文件的“验证什么、为何验证、采用什么方式”，避免把平台建设代替决定性实验。
- 公共 `dev_fixtures.py` 复用三份原开发候选，并进入阶段 B/C 源码身份。所有 candidate hash、RTL hash、33 个整数 FIR 系数及 mask 在综合前冻结；Yosys/ABC 均以记录过版本和 SHA-256 的绝对路径调用。单元计数从 JSON top.cells 取得，与 stat/Liberty 交叉核对；面积来自实际库单元面积之和。
- 初次 `dev-full-ddc-v1-20261001` 的首项在 238.6 秒后因两个 `$scopeinfo` 元数据被严格 mapped check 拒绝，后续未执行。失败现场保留；修订只清理该类来源元数据，其他未映射检查保留。v2 候选与 RTL hash 全部不变。
- `experiments_search/stage_c/dev-full-ddc-v2-20261001/results.json`：LUT+direct 30454 cells / 38346.294 µm²；CORDIC+polyphase 45094 / 55954.164；compose+polyphase 47141 / 58284.058。第四次重复 LUT 的面积、单元类型/数量、stat 摘要与规范化连接哈希均一致。规范化忽略来源/实例名但保留 Yosys 信号 ID，不是形式等价证明。
- 以固定 manifest 逐项调度，单项超时上限 600 秒且清理整个任务进程组；已开始、失败或完成的任务均不得重试。一次重复仅为本机可复现性检查，不冻结 epsilon_A。包含旧失败共 5 次真实综合尝试，成功批次为 4 次；没有悄悄抹去失败或缩小候选集。
- 综合前相关回归 163 passed；未运行主场景质量、held-out 或搜索。独立证据复核仍在进行。下一步针对同三候选验证冻结主场景，仍不能由面积数据单独推断设计收益。

## 2026-10-01 阶段 D 主场景接入与下一项决定性比较

- C 的独立复核已完成：四份产物无 blocker，已记录源码/工具/输入/映射单元/统计/重复摘要全部匹配；不把后加无关文件当历史漂移。
- `experiments_search/stage_d/fixed-main-v1-20261001/results.json` 完成同三候选 3×36=108 个完整主场景评价。LUT+direct 的 Q=2.0606135458920818e-7；CORDIC+polyphase 为5.632159149410971e-8；compose+polyphase 为2.3350081597469695e-4，约为 q_budget 的10.0245倍。三者观察域饱和均为0；mask/接入通过不等于质量预算合格。
- compose 超预算是要保留的负例，不修改原fixture救结果；可组合、可综合不自动带来质量或面积收益。本轮不读取held-out，不重综合，不判S/L。相关回归177 passed，覆盖合成/mock和只读面积证据关联；Black仍未运行。
- 新实验路线图见 `refine-logs/EXPERIMENT_PLAN.md` / `EXPERIMENT_TRACKER.md`。主检验固定同一强非LLM引擎，比较joint与强staged/WLO及cost-first；不能把联合GP击败“同配置GP”当命题。共同动作/饱和门槛/epsilon_A/预算与统计仍待审查冻结，72提案pilot尚未运行。

- 下一轮反方复核指出：共同GP只能直接检验交错/锁图策略；两基线各B次的union实际为2B。已在草案改为两项B对B主比较，union仅辅助；动作继承、两步patch顺序、族锁定/平局、超预算探索资格、失败与统计都写入 `PILOT_RULES_v1.md` 和禁执行的机器清单。accumulator_bits=0为哨兵，不能只靠相邻步跨越无效饱和带，故共同数值动作保留全域跳转。72提案pilot尚未启动，仍须规则复核与实现/校准验收。

## 2026-10-01 对 DDC 整链结果的现实判断

- “使用整条链评价”只是把目标函数放到正确上下文，并不会自动产生更优设计。当前 DDC 的 NCO→CMUL→FIR→R=2 在观察域无饱和，主体近似线性；此前强线性基线③又已完整解释固定池排序，因此强结构—数值耦合的先验概率已经下降。
- 三个开发点没有形成收益证据：LUT 与 CORDIC 的 Q 分别只有预算的约 0.00885/0.00242，明显过度供给精度；compose 则约为预算的 10.0245 倍且面积最大。当前缺的是贴近质量边界的低成本点，而不是再增加链长度。
- joint-vs-staged pilot/正式 S 尚未运行，所以现在不能判 S0；但若公平正式比较仍为 S0，应如实接受“该 DDC 契约下误差近似可分、分阶段流程足够”的边界，不通过事后收紧 q_budget、制造饱和或追加任务追逐阳性。第二条链若开展，必须基于预先声明的真实非线性/状态耦合问题，而不是因 DDC 阴性临时换题。

## 2026-10-02 两臂 pilot 实现、校准与一次中止

- 共同动作/选择/驱动已实现：两臂独立PCG64同seed初始化；1/2步patch可重放，结构族在第6次后锁定并保留当前本族最佳，超质量预算个体可探索但不进合格前沿；质量逐次重算，仅缓存成功面积，预算由DevRun的attempt_started统一计数。
- 首轮补重复 `pilot_calibration/fixed-repeat-v1-20261002` 两项全部一致；工程阈值按事前规则为1%参考面积=383.46294 µm²，不是观测差的概率上界。
- 独立复核发现初始缓存的工具链身份缺口：历史结果自洽不等于能挂到当前工具hash。`paired-pilot-v1-20261002` 已按SIGTERM停止并保留incomplete（计费8次、7条完成记录、1条在途），没有当作完成pilot或用于S判定。当前工具未变，不能由该条件性缺陷推断既有C面积错误。
- 修复为：从历史contract计算初始cache key，必须等于当前工具/库/脚本/RTL key才能导入；worker固定cwd=BENCH；生成后立即保存提案并在中止时记录在途状态。补相应回归后完整相关测试232 passed。代码身份改变后使用新run-id补重复，不覆盖原校准/中止记录；pilot-v2尚未启动。

- 修订版补重复v2已通过，缓存/worker局部复核闭合；`paired-pilot-v2-20261002`现已在6小时上限内运行72提案。首个seed的第6次结构锁定及已完成动作回放/预算前缀已核对，没有根据中途胜负调整规则；正式S/L仍为N/A。

## 2026-10-02 04:04 两臂pilot完成与描述性负信号

- v2完整72提案，每seed/arm12；57成功、15非法。72次RNG/状态回放、39次有效变异、2052个质量行、37份实际面积来源核对通过。34次非缓存综合，p90=423.91秒，总墙钟2.121小时；按事前成本规则正式预算取B=32。
- q_budget内最小面积三seed均staged更低：joint相对改善率−2.740%、−3.545%、−0.742%，均值±样本标准差−2.342%±1.443%。这是12提案/3seed/main-only的描述，不判S0，不声称整个Pareto前沿支配；不会为救阳性改动作/阈值。详见refine-logs/PILOT_ANALYSIS.md。
- 下一步先补37个实际有效候选的模型—RTL验证，再冻结/执行正式B32必要条件；暂不接LLM或换第二条链。

## 2026-10-02 13:12 正式必要条件运行

- 正式代码与两份协议已在数据前提交834d449；最终284回归，独立复核无blocker。37候选的21种NCO全映射（1376256相位）及192输入的正负饱和/背压验证均通过。
- 已启动`formal-necessary-v1-20261002`：5个固定seed、joint/staged各32提案共320，最长12小时；完整main后锁集合再held-out。cost-first全部代码/配置已冻结但尚未执行。必要条件失败才按注册规则记操作性S0，不等同普遍无效；当前无S结论。

## 2026-10-02 正式运行中止与主线重新对齐

- `formal-necessary-v1-20261002` 在第 179 个提案发现新 `linear -> quad` 候选的模型—RTL不一致后按协议中止为 `inconclusive`；未读取 held-out，不能记为 S0。根因定位为 quad RTL 舍入表达式的 signedness 污染，负二次项被逻辑右移，最大产生 512 LSB 偏差；旧失败产物保留。
- 72 提案 pilot 的三个 seed 均由 staged 得到更低的预算内最小面积，是需要正视的描述性负信号，但不是正式结论。更重要的是，joint/staged 只检验搜索调度，不回答项目最初的 LLM 命题。
- 回看 `thesis/PROPOSAL_v1.md` §4.3 与 `thesis/SEARCH_PROTOCOL_v1.md` §3–4 后，下一工程目标改为 proposer-neutral 的 typed-IR action program：LLM 与强非 LLM proposer 必须共享同一 IR、合法动作、lowering、评价预算和失败计费。公开 action intent 不携带 RNG state、before/after 或 provenance；这些由执行层派生和记录。
- quad 修复须先完成回归与独立复核，但不自动重跑 320 提案。GP joint/staged 保留为强基线；论文的决定性实验仍是 proposer×feedback 的 2×2，以及可选的诊断反馈消融。只有该统一接口通过验收后才接真实 LLM，避免继续用基础设施或 GP 调度实验替代“借用 LLM 探索能力把数学公式变成硬件”的研究问题。
- ZCode 分工已校准：00:17 的 `msg_63c0ebaa` 实际落到旧的 `sess_bff62...` 窗口而非用户当前的 `verievolve`；该窗口未产生回复或代码，Codex 已终止仍等待它的持久发送器，避免双臂并发改同一批文件。用户当前 `verievolve` 会话被改派为唯一实现臂，任务仍是先复核 quad signedness，再实现 proposer-neutral 严格 JSON action-program 层；Codex 只做方向与验收。正式 truth、综合、formal rerun、held-out 和协议修改继续冻结。

## 2026-10-03 typed-IR 提案接口实现（verievolve 臂，用户改派执行）

- 新文件：`search_ir/proposal_contract.py` + `tests/test_search_ir_proposal_contract.py`（512 用例 passed；相邻全量回归 638 passed，含 quad signedness 定向回归 74 passed）。未改 actions.py、未扩大动作集合、未提交 git。
- 公开意图层设计：意图只有 `{kind, path}`，仅 `change_interpolation`/`numeric` 加标量 value；before/after 在执行时基于中间候选树内部派生，每步复用 `actions._apply`（含逐级 validate）；四个结构动作的 after 由 `_structure_after` 确定性生成；numeric 的 mode/direction 属 GP 抽样 provenance，公开层拒绝，内部按字段合成 jump/uniform/toggle 仅满足 `_apply` 回放校验。
- 公平性不变量：结构动作与 GP 确定性默认逐位一致；numeric value 与 GP jump/uniform/toggle 可达值域相同 → 两类 proposer 一步可达邻域一致，LLM 无法借公开层扩大动作空间。
- GP adapter：50 seeds × 3 相位 × 3 开发候选，propose→program→apply_program 与原候选逐位相等、candidate_hash 相等、JSON 规范往返逐字节稳定；公开投影是多对一（neighbor/jump 同值同 intent），原始日志在 GP 侧保留备审计。
- quad signedness 复核（A 项）：修复在位，`test_ddc_quad_signedness.py` 覆盖 5 depth × 9 phase_bits 全 65536 高位相位字的 iverilog 模型-RTL 对拍 + 非 quad 生成与修复前提交字节一致。
- 协作教训：tincan 会话名会漂移——原 Codex 协调会话退出后 "claude" 名被 sess_75ffdb28 顶替；send_peer 带 expect_id 才能防止投错人。black 本机（python3.10）不可用，风格手动对齐，待有 black 的环境复跑。

## 2026-10-03 项目进度快照（状态核查，未运行新实验）

- 项目处于“DDC 工程闭环与非 LLM pilot 已完成，核心公平对照尚未完成”的阶段。正式运行原始终态为 inconclusive、S/L=N/A、cost-first=not-run；quad 修复报告通过不代表正式比较已重跑成功。
- 评价证据仍为 E1：经典强线性模型解释固定池反转，实际设计损失未证；pilot 的 staged 优势只是描述性负信号。旧算子级真实 LLM 实验不能替代新 DDC 同 IR、同动作、同预算的 proposer×feedback 2×2。
- 状态入口存在滞后：EXPERIMENT_TRACKER 仍留“运行中”快照，SEARCH_PROTOCOL 的实现进度也落后于 C/D 实物；应优先读原始终态、勘误与 Iknow 最新记录。六章论文正文仍主要承载旧算子级实验与旧术语，不等于最新主线已经成稿。提案接口新文件已在工作区出现，但未提交，不能混同已验收的正式搜索。

## 2026-10-03 formal S 重跑前审计（verievolve 臂）

- 真实进度比"从 WP6 开始"更靠前：WP6 引擎（joint/staged/cost-first）已实现，**pilot 已按冻结规则跑完**（PILOT_RULES_v1，B=12×3 seeds×2 臂；结论=joint 无正面面积信号，-2.342%±1.443% 描述统计；正式建议 B=32×5 seeds），WP8 formal S 协议已冻结（FORMAL_S_PROTOCOL_v1.json，sha b6766909 未变）。
- 首次 formal 执行在 proposal 179 因 quad RTL signedness bug 中止（inconclusive，非 S0）；erratum（FORMAL_BACKEND_ERRATUM_v1）预注册了重跑纪律：37 个 pilot 候选全无 quad 叶子、RTL hash 不变（warm cache 兼容）、旧 quad 面积作废、新 readiness v2 + 新 run-id 完整重执行。
- 重跑唯一卡点 = `FORMAL_S_READY_v2.json`（当前 runner 硬校验当前源码 digest c43b6046…；与中止 run 相比漂移 5 文件：rtl_gen 修复、formal_run 修订、provenance/validate_main 修订、proposal_contract 新增）。修复后的全量测试记录缺失（现有 FORMAL_TESTS 是修复前 digest），当前树实测 848 passed。
- 墙钟风险（pilot 实测外推）：stage1 320 attempts ≈ 9–13h，冻结 stage_wall_limit=43200s 触线即 inconclusive；stage2 条件性另 12h。
- 与 goal 的 WP6 清单差异：枚举切片、beam/MCTS 未实现——frozen protocol 只有 joint/staged/cost-first 三臂（pilot rules 明示"不前置 beam"）；增臂=协议变更，须用户拍板。

## 2026-10-03 formal S 指导口径（运行中只读核查）

- `formal-necessary-v2-20261003b` 是冻结的 **必要条件 + 条件性 cost-first** 检验：stage1 比较同一 GP 状态机下 joint 交错搜索与 staged 锁图策略；必要条件失败足以按预注册短路为操作性 S0，不能外推为联合搜索普遍无效。
- runner 若最终写出 S1，只表示通过 `FORMAL_S_PROTOCOL_v1` 内的 staged 与 cost-first 两项门槛；总体 `SEARCH_PROTOCOL_v1` 仍列有可枚举切片、beam/MCTS 等强基线且自身标为草案。论文口径必须区分“runner S1”与“总体 Search-axis 证据闭合”，后者不能在缺失基线未冻结补齐前宣称完成。
- 当前 formal 状态机直接调用 `actions.propose`，没有把 GP 提案实际重放经过 `proposal_contract`。这不破坏本轮 joint/staged 同动作内核比较，但 512 用例只证明可无损投影/重放，不能替代后续 L gate 的运行时公平性；进入 proposer×feedback 前，两类 proposer 必须统一走公开 action-program 执行路径并继续按 parse 前计费。

## 2026-10-03 formal S 判定 S0（Search axis 终止）

- `formal-necessary-v2-20261003b` 完整执行（320/320 计费，7.08h）：**joint-vs-staged 必要条件失败**——HV 差 bootstrap 95% CI [−0.0196, +0.0418] 含 0，工程命中 seed 2/5（要求 ≥3）。按预注册 stop rule 判 **S0**，cost-first 未触发，L/D=N/A。
- 诚实细节：joint 在 seed 101（省 2761 μm²）和 307（省 805 μm²）确实找到超 ε_A 的更优面积点，但 3/5 seed 上劣于或平于 staged——改进不可靠，不能表述为统计结论。
- 论文定位落到预注册组合 **E1 + S0**：机制 witness（局部指标不保序+③全解释）+ benchmark + evaluator + 搜索轴诚实负结果；不报告 LLM 独特性，不换链挑阳性。
- 协作纪律生效案例：readiness v2 签发 → 判定 → thread.12c 里程碑汇报，全程 send_peer 带 expect_id。

## 2026-10-03 LLM 在 VeriEvolve 中的角色边界

- “局部指标不保序”不是说单个算子不如整条电路，而是说按算子接口处的 SQNR/WCE 排序，经过混频、滤波和抽取后不一定保持；E1 又说明当前 DDC 的反转可由 candidate-exact 线性传播解释。
- 系统分三层：typed IR/原语库规定**能构造什么**，链级 bit-true + 综合规定**什么设计好**，proposer 规定**下一次试什么**。LLM 只属于 proposer 层，不能替代原语库、合法性检查、lowering、评价器或综合。
- 当前公平协议固定同一 IR 和动作空间，所以 LLM 只能改变候选提议分布（利用公式、契约和诊断选择动作），不能在正式运行中自行扩展语法。若它只是从手写模板/候选库中选项，研究上等价于更昂贵的检索器，没有独特贡献。
- LLM 只有在巨大组合空间、有限评价预算、跨未见公式/约束迁移时，能以同预算稳定提高样本效率或产生库中未枚举但语法可构造的组合，才有可测价值；须与静态库/检索、GP、beam/MCTS 同语言比较。
- 当前 S0 使 L/D=N/A：仓库没有证据证明 LLM 在这条 DDC 搜索线上有收益。若未来重新研究 LLM，应作为独立 v2 预注册：冻结 held-out 公式/约束、共同原语库与动作、统一失败计费，比较 best-HV-vs-evaluations、首个可行点时间、有效提案率、结构新颖性与跨任务迁移，不能作为挽救 v1 S0 的追加实验。
