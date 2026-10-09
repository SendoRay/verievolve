# 我知道的 VeriEvolve

## 2026-10-08：公式到硬件的第一条完整开发路径

VeriEvolve 现在有一条可运行的 DDC 纵向路径：数学公式和使用要求先写成严格的 Formula Request；LLM
或传统方法再给出完整 Architecture Plan；确定性编译器把计划转换成现有 typed IR，并由同一份 typed IR
生成整数 bit-true 模型和 Verilog。

Architecture Plan 当前能联合选择正余弦结构（查表、CORDIC、粗查表加残差 CORDIC）、滤波抽取结构
（直接对称 FIR、多相 FIR）和相应定点参数。它不能携带任意 Verilog，因此 LLM 负责组合硬件知识，规则
检查器负责限制边界，确定性后端负责实现。

这条路径已经通过三类工程检查：整数模型与生成 RTL 逐位一致；输出反压时内部状态保持正确；生成 RTL
能够被 Yosys 综合。固定假 proposer 也验证了“非法计划 → 机器反馈具体字段 → 下一轮修复”的闭环，失败
尝试不会被免费丢弃。

这些结果证明生成流程已经可用，不证明 LLM 比传统搜索更好。下一步先在公开开发任务上接入真实 LLM，
改进提示和反馈；接口稳定后再冻结任务、留出集、预算、基线和成功判据，正式检验 LLM 是否更擅长提出
跨结构的硬件方案。

## 2026-10-08：DeepSeek 开发候选已完成真实映射

DeepSeek 在公开 DDC 开发任务上提出 16 级 CORDIC 加 16 位直接对称 FIR。这个方案的 typed IR、整数
模型和 Verilog 均已生成，97 个输入对应的 33 个有效输出与 iverilog 逐位一致；开发链级质量
`Q_dev=4.2987039978778864e-09`。

标准 600 秒成本评价只记录到 ABC 超时。保持 RTL、Nangate45 Liberty 和综合脚本不变，把开发诊断上限
延长到 1200 秒后，映射在 904.3758489999454 秒完成，面积为 `41425.51 μm²`，共 33012 个标准单元。
因此方案是可综合的；600 秒只是不足以完成这张无流水大组合网表的成本评价。

这次还暴露了当前 typed IR 的限制：LLM 可以选择 CORDIC 级数，却不能选择组合展开、流水或迭代复用。
后续若要让 LLM 真正优化 codegen，应把这些微结构加入公共语法，并让所有基线使用同一组选择。

## 2026-10-08：文章与系统共同约束实验

我们按文章主线推进系统与实验：先写问题、待验证主张和判断标准，再做对应实验。新想法先写成可检验
假设，探索与独立复验支持后再进入文章结论。主规划在 [chengzhy/iknow.md](chengzhy/iknow.md) §3–§7。

第一批可靠闭环已经实现：计划合法后会运行固定公开开发场景，质量超过 Formula Request 的显式上限时，
实测值和失败类别会反馈给下一轮提案；评价器自身异常记为不确定，不当成设计失败。该判断明确标为
`development_only`，不能替代 `Q_main`、部署验收或论文正式实验。面积和时序反馈尚未接入循环。

独立 RTL 验证器已改为按 `valid && ready` 事务收数，主动插入输入空隙和输出反压，并检查停顿时数据稳定与
有界进展。当前组合实现通过；真正的跨延迟验证要等流水和迭代实现加入。后续统一综合档案和预算，之后
才进入流水、迭代复用与约束时序。

## 2026-10-08：舍入名称与边界语义已经统一

新计划和新候选直接使用 `nearest_ties_to_pos_inf` 与 `floor`。旧 `rne` 实际是半值向正无穷，不是
ties-to-even；旧 `trunc` 对负数是向负无穷取整，不是向零截断。旧名称只用于读取历史产物，已落盘实验
不改写。

独立商余数参考还发现旧 RTL 在原位宽内加舍入半值可能先回绕。生成器现先符号扩展一位再加偏置，正负
半值、符号解释、饱和、模回绕和生成 RTL 都增加了边界回归；旧网表面积与新结果不得混合。该修复登记在
`examples/comm_dsp_bench/AUDIT.md` §8.17，不作为研究创新。阶段 B 下一步是统一档案、缓存、恢复、综合
反馈和预算。

旧 Stage C 面积与 pilot 仍可通过冻结 manifest 和 `legacy_v1` 只读回放审计，但当前缓存、校准会拒绝
这些旧 RTL 身份。也就是说，旧证据保留可查，不会被冒充为修复后实现的成本数据。

LLM 的两项研究分别检验：在共同实现空间里是否改善搜索，以及是否降低新增结构的开发与验证成本。
现有联合搜索负结果保留。固定场景的可复现计算与解析精确计算分别标记；模型和 RTL 对拍之外，还需
独立数学参考。近期先完成可靠闭环，所有后续实验绑定文章中的主张和明确的停止条件。

## 2026-10-08：创新方向探索与直接近邻

文献已覆盖多项基础能力：[Tomasovic 与 Sekanina, 2026, arXiv:2606.13089](https://arxiv.org/abs/2606.13089)
用通用 LLM 与协同进化生成近似乘法器，以全输入枚举计算误差，并优化误差—面积前沿；
[Cheng 等, 2026, arXiv:2608.07625](https://arxiv.org/abs/2608.07625) 用可执行架构表示连接规格与 RTL；
[Shi 等, 2026, arXiv:2609.21697](https://arxiv.org/abs/2609.21697) 将近似逻辑综合接入 HLS，包含子图划分、
误差模型和候选组合优化。相关工作需按具体方法比较，不能统称为二值正确性或采样适应度。

当前优先探索三个假设，均未获得新增实验支持，也未确认为文献空白：

1. **系统上下文驱动的跨模块结构改写**：允许改变公式的实现分解与量化位置，以最终输出质量验收。
   在 DDC 上可用“正余弦生成加复乘”与“直接旋转”的经典等价结构作为开发检查；创新须落在自动提议、
   适用条件判断和受限预算下的选择机制，并与包含这些经典结构的强基线比较。
2. **约束失败驱动的实现空间扩展**：区分参数未调好、当前结构受限和评估未知，再指导 LLM 引入新结构。
   空间不可行只在完整枚举或有效界支持的范围内声明。比较固定空间搜索、无诊断开放生成、带诊断开放生成；
   所有生成、失败、验证和综合成本计入预算，额外检查完整专家库基线，避免靠删掉好实现制造优势。
3. **新结构的误差分析自动组装**：从明确整数语义的数据流推导适用条件、误差界或精确量，而非每个模板
   手写评价器。先限于可组合的算术、量化和线性多速率片段；独立检查并保留未知状态，比较通用界和直接仿真
   的覆盖率、紧致度与总成本。此项技术风险最高，先做小范围可行性检查。

研究目标是约束下可验证、可扩展的硬件结构搜索。近期先检验跨模块改写是否有真实硬件收益，再独立检验
诊断反馈能否提高开放搜索效率；经典算法重现用于检查能力，不作为新算法贡献。正式实验冻结输入范围、
精度语义、吞吐及时序约束、工具档案、预算与留出任务，报告失败与负结果。

## 2026-10-08：复数旋转小实验草案

具体开发计划已补入 [chengzhy/iknow.md](chengzhy/iknow.md) §7.1，尚未运行。先做独立 RTL 任务，
复用仿真和综合检查，准备包含直接旋转的专家对照；再检查 LLM 能否正确连接、调整已有模块。
本轮仅评价数值误差、协议与综合面积，时序记为未完成。拟定上限为 8 个专家配置、6 次 LLM 提案和
14 次真实综合；预算属于草案，付费调用前确认费用。结果用于决定是否继续开放模块内部改写。

接入采用通用 `evaluator.py` 的任务注册和底层工具。现有测试台仍需补输出反压、无气泡连续接收，以及
分量均方根/最大误差检查，才能用于这项实验；这些检查尚未实现。

## 2026-10-08：复数旋转开始实测

8 个专家实现已通过同一组公开输入的误差、连续接收、反压及复位检查。首批 Nangate45 综合中，
直接旋转面积为 22899.408 μm²，查表加三乘法为 10300.052 μm²；改变计算分解不自动带来面积收益。
来源：当前 `da43` 工作区 `examples/comm_dsp_bench/experiments_rotation/mapped-smoke-v1-20261008/results.json`
的 `rows[].stat_reported_area_um2`；数值结果在该目录及 `mapped-experts-supplement-v1-20261008` 的
`numerical_validation/results.json`。这些是专家实现的开发实测，尚无 LLM 搜索结果，时序与留出测试未完成。

后续八项综合已全部完成，共 8 次真实综合，无失败或重跑；当前门槛下，八项中查表加三乘法面积最小。
完整对照与复现入口在上述 `da43` 工作区 `mapped-experts-supplement-v1-20261008/README.md`，
面积来源为同目录 `combined-results.json::rows[]`，仍不代表固定时钟约束下的最优实现。

独立审查后，运行器补齐每次评价的输入、RTL、数值、面积与预算证据关联，并在恢复和选型时重新核对。
可移植复现入口为 `rotation_replay.py`；上述工作区 `experiments_rotation/linked-evidence-v1-20261008.json::rows[]`
将既有数值和面积记录直接关联，未改原测量、未新增综合。当前只有专家验收；后续从已给直接旋转实现出发的
LLM 实验只能检验选型、连接或调参，不能称为发现该结构。

终验已接入同一总时限，每次调用前重算剩余时间；工具故障、超时及异常保留为未判定，不算设计失败。
修复记入当前 `da43` 工作区 `examples/comm_dsp_bench/AUDIT.md` §8.17；未启动真实留出测试或新增综合。

## 2026-10-08：复数旋转 LLM 延续开发结果
两轨迹共预约 6 个 API 槽位：5 个取得回答、1 个连接错误；4 个回答被接口校验拒绝，仅 LUT512 旧配置完成开发评价并复用旧面积。
五个回答的结构参数均已有专家配置，本轮没有得到新设计或面积改进；未新增综合，累计仍为原 8 次。
最终仍选专家 `lut256_three_multiply`（10300.052 μm²），独立 4096 输入 held-out 通过。
前三次调用后只修系统接口：理由改为非语义元数据、反馈压缩并显式给当前最佳；旧失败不重判。
来源：当前 `da43` 工作区 `experiments_rotation/llm-continuation-v2-20261008/{results.json,selection.json,held_out/result.json}`。
本轮受协议障碍与受限空间影响，不足以判断 LLM 搜索或结构生成总体有效性；无全域误差证明或 STA。

## 2026-10-08：首次真实 LLM 旋转开发运行

6 次尝试取得 5 份回答，均重复已有专家配置；4 次被接口元数据校验拒绝，1 次完成硬件评价，另 1 次网络失败。
第 3 次后修正说明文字与反馈接口，旧结果保留，未手改候选。本轮没有新增综合或面积改进，不足以判断结构探索能力。
最终仍选 LUT256 三乘法，面积 10300.052 μm²，独立 4096 输入留出检查通过；无 STA 或全域保证。
来源：`/Users/chengzhy/.codex/worktrees/da43/verievolve/examples/comm_dsp_bench/experiments_rotation/llm-continuation-v2-20261008/` 的
`results.json::{proposal_rows,accounting}`、`selection.json::candidate.area_um2`、`held_out/result.json::{row.passed,row.metrics}`。
后续以真实实验驱动候选表示、搜索与反馈的改进，不手工修补 LLM 候选来制造成功结果。

## 2026-10-08：通信复数旋转原生 RTL 实测

已让 LLM 直接写完整 Verilog，不再选择生成器参数。4 次调用中 2 次截断，2 份完整代码编译成功；
但连续与反压仿真均有 664 个输出不一致。反馈实测反例后，模型只删除注释、未改逻辑，候选没有人工修补。
两份均未达标，新增综合为 0；没有新面积或留出结论。来源为当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_rotation/raw-rtl-feedback-v1-20261008/README.md` 及其引用的
`call-01/result.json::evaluation.{failure_stage,simulations}`。当前真实障碍是失败反馈没有带来有效实现修改。

## 2026-10-08：六个通信 DSP 算子的真实短跑

使用现有 OpenEvolve、DeepSeek `deepseek-flash` 和采样适应度，对复乘、对称 FIR、NCO、atan2、
64QAM LLR、sin/cos 各运行 1 个 seed、3 次迭代。短跑直接产生 4 个有效新结构：复乘从四乘法改为
Gauss/Karatsuba 三乘法，ice40 面积 6836→5732（−16.14979520187244%），输出精度仍为 999；
FIR 用对称抽头预加把 16 个乘法器减到 8 个，面积 8474→4882（−42.388482416804344%），固定同一
输入复评时两者 SQNR 均为 85.1405 dB；NCO 用四分之一波对称和线性插值形成 71.3333 dB / 1024 的
高精度点，初始全周期表为 47.6082 dB / 136；sin/cos 用相邻表项插值形成 61.1054 dB / 2544 的
高精度点，初始为 24.8852 dB / 236。吞吐均未改变。

atan2 与 64QAM LLR 的三次生成没有直接超过初始设计，失败候选保留。随后只提取 LLR 候选的“利用
星座对称折叠距离计算”想法，重新推导分桶和符号恢复并独立实现；同一批 65,536 输入上，ice40 面积
5508→4552（−17.356572258533042%），SQNR 65.98770304804884→66.23029867051561 dB，吞吐不变。
因此当前 6 个族中已有 5 个形成有效新点，但 LLR 结果应明确记作“LLM 提议结构、实现代理修复并验证”，
不是模型一次生成成功。atan2 的 64 段表加线性插值在修正端点饱和后，ice40 面积 2294→2008，
SQNR 71.7024→71.5962 dB；但严格 Nangate 面积反而 2171.092→2230.410 μm²，所以它只改善当前
ice40 目标，在 ASIC 目标下被基线支配。这证明综合后端必须与最终优化目标一致，不能把一个后端的收益
直接外推到另一个后端。正在继续寻找无乘法、面向 Nangate 的 atan2 近似结构。

六项初始/候选又使用同一 Nangate45 Liberty 做严格完整映射：复乘 8785.182→7286.804 μm²
（−17.055742271474863%），FIR 12731.824→8422.624 μm²（−33.84589670733746%），LLR
4981.382→3933.874 μm²（−21.028461579537563%）；NCO 929.404→1214.556 μm²，sin/cos
496.622→2926.266 μm²，后两项确认是精度换面积而非面积改进。映射仍无 SDC/STA。
完整结果、范围限制和 RTL 哈希见当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_e1/live3_multitask_20261008/{results.json,README.md}`。这一轮最初是
单 seed、每任务三次迭代的开发检查；它证明跨多个算子存在结构跳变，但本身不能表述为统计优势。

## 2026-10-08：六算子三 seed 复现与严格面积

每个算子扩展到 seed 0/1/2、每 seed 三次迭代，共 18 个纳入比较的短跑。12/18 得到经完整评价的
改变设计：复乘 3/3、FIR 3/3、NCO 2/3、sin/cos 2/3、atan2 1/3、64QAM LLR 1/3。复乘和 FIR
反复重现三乘法与对称预加；NCO/sin-cos 反复生成查表插值的高精度高面积点。atan2 seed 1 直接生成
65 项表加 3 位线性插值，SQNR 71.6113 dB、ice40 1890、Nangate45 1905.89 μm²，相对基线严格面积
2171.092 μm² 降低 12.215143347218818%。LLR seed 2 共享重复最小值子表达式；固定同一输入时精度
与基线同为 65.98770304804884 dB，ice40 同为 5508，Nangate45 4981.382→4948.398 μm²。

NCO 与 sin/cos 最初 seed 1/2 被统一 0.2 级联门槛挡住基线完整评价，四个运行保留但排除；门槛降到
0.1 后另开新 run 重跑，避免把惩罚占位值当硬件结果。三 seed、每次三迭代仍只是开发级复现，不作
显著性或总体成功率外推；无 SDC/STA、功耗和布局布线。完整逐 seed 结果、排除理由与严格面积路径见
当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_e1/live3_multitask_20261008/multiseed_results.json`。

## 2026-10-09：补测 GF(2) 与长抽头算子

新增加扰器任务 `scrambler_gold_w32` 已真实验收：4096/4096 精确匹配，连续输入 II=1、延迟 1 拍，
带反压输出一致；严格 Nangate45 面积 583.87 μm²、338 个标准单元。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_benchmark/scrambler_gold_w32_baseline_20261009_attempt02/result.json`
及同目录 `manifest.json`。这是新任务的专家基线，无 STA、功耗或 LLM 搜索结论。

对现有 `crc16_step1` 与 `mfilt_L63` 各做 3 次 DeepSeek 原生 RTL 提案。CRC 三个改变候选均在固定
4096 输入和反压检查中精确通过，最佳严格面积 201.096→194.44600000000003 μm²；其结构把字更新
改写为 `acc XOR data` 后接 16 级展开多项式网络。63 抽头 ±1 匹配滤波把串行累加表达式改成平衡
加法树，精确通过，面积 26021.982→25944.044 μm²；后两次重复同一 RTL，说明该短跑很快陷入重复。
逐项证据与哈希在当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_e1/live3_uncovered_20261009/results.json::rows`。两项均为开发短跑，
不作统计优势主张；时序、功耗与布局布线未测。

## 2026-10-09：三族评价信号 pilot 与 atan2 口径勘误

在 112 个复乘、29 个 sin/cos、46 个 atan2 候选上，同时比较二值全通过、通过率、2048 点采样误差、
确定性误差评价，并用独立统一真值重评。strict all-pass 分别把 20、14、19 个候选压成同一档，但这些
候选的统一真值 SQNR 范围分别为 130.7363218609706–999.0、81.14744182654883–96.01438282969583、
77.66077844512309–92.4919135370825 dB，说明二值通过不能排序已可行设计。确定性评价对真值的
Kendall τ-b 分别为 0.9796215429403203、1.0、0.9798590130916416；2048 点采样也达到
0.967976710334789、0.9839315304278553、0.9899295065458208，并且三族都选中真值最优。因此当前
pilot 支持“二值信号丢信息”，但不支持“确定性评价在该采样预算下必然优于强采样”；下一步看冻结
预算曲线和多 seed 方差。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m3/fitness_signal_pilot_v3_20261009/results.json::families`。

实验同时发现 atan2 旧评价错误：任务角度域是 `[-pi,pi)`，旧 golden/普通 SQNR 却把圆周边界两侧
的码按直线相减，可能把相邻方向算成 65535 LSB。现已把 golden 的 `+pi` 归一到 `-pi`，并改用模
2^16 最短角度码差；新增 3 项边界回归通过。修复前 atan2 SQNR 只作历史诊断，后续正式实验需按新
口径重跑，不能沿用旧数字。

同一冻结候选池又完成 30 seeds × 4 档采样预算 × 3 族，共 360 个点。复乘在所有预算下均 30/30
命中统一真值最优；sin/cos 在 32 点时 29/30，其余 30/30；atan2 在 32/128/512/2048 点下分别为
11/30、12/30、11/30、16/30，而确定性评价为 30/30。atan2 的平均选型损失同时从
0.011955006917317709 降到 0.0030059814453125 LSB²，绝对值很小：这证明确定性评价在该族排序更稳定，
但尚不能声称有大的硬件收益。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m3/sampling_budget_curve_v1_20261009/results.json::families`。

## 2026-10-09：复乘的 100 MHz 约束映射开发检查

对已经通过功能复验的四乘法基线和三乘法复乘，在同一 Nangate45 typical 库、10 ns 目标、INV_X1
输入驱动和 10 fF 输出负载下重新映射。三乘法结构的标准单元面积为 7248.766 μm²，相比四乘法的
9049.586 μm² 减少 19.899473854384052%；ABC 组合延迟代理从 1.9609 ns 增至 2.46752 ns，增加
25.83609567035543%，两者均低于 10 ns 目标。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_system/timing_100mhz_cmul_dev_20261009/results.json::records`。
本机没有 OpenSTA；这些数只能表述为带驱动/负载约束的 ABC 映射与延迟代理，不能称为 STA、Fmax 或
布局布线结果。它说明结构改写带来的面积收益可能同时增加关键组合路径，后续正式 PPA 必须保留这两个维度。

同一约束又用于 16 抽头对称 FIR。16 乘法基线为 13016.710 μm² / 2.56771 ns，对称抽头预加的
8 乘法结构为 8529.556 μm² / 2.90048 ns：面积减少 34.472%，ABC 延迟代理增加 12.960%，两者
仍低于 10 ns 目标。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_system/timing_100mhz_fir_t16_c25_sym_dev_20261009/results.json::records`。
复乘和 FIR 两例都显示“减少乘法器可明显省面积，但可能拉长组合路径”；这是一项待在正式 STA 和更多结构上
复核的机制观察，不是两例即可成立的普遍定律。

## 2026-10-09：sin/cos 2×2 搜索 pilot

在同一个 29 点有限结构空间中，以 8 个新候选为每格预算，完成 LLM / 强类型化非 LLM 提议器 ×
Boolean / 确定性数值反馈的三 seed pilot；29 个点共享严格 Nangate45 面积映射。非 LLM 两格和
LLM+Boolean 均 3/3 完成；LLM+数值只有 1/3 完成，另外两次分别在 4/8、3/8 次有效评价后因连续
三次重复已评候选而终止，按提议器失败保留而未重跑。四格完整运行的相对最小合格面积损失中位数都为
0.26089474446213967，均未命中全空间最小面积；唯一完整配对 seed 的交互效应为 0，其余两 seed 因
LLM+数值格未完成而不能计算。53 次记录调用中 46 次得到 API 回答，估算费用 0.009475596 美元。
来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m4/cordic_sincos_2x2_pilot_v1_20261009/results.json::summary`。

该 pilot 支持“数值反馈提供排序”但不支持“现有 LLM 提议器能稳定利用它获得搜索收益”。它只覆盖一个
sin/cos 有限空间，而且确定性反馈与全域真值相同、不是分布独立的留出集；因此不能据此否定跨算子结构搜索，
也不能把 0 交互泛化。下一步应在更大的结构动作空间和其他算子上复核，同时把重复/无效提议率作为方法成本。

## 2026-10-09：修复后 DDC 系统主集重跑

修复评价器后重新运行 96 个 DDC 组合 × 36 个冻结 main 场景，共 3456 行，运行 15.6 秒。局部
L0 SQNR、L1 SFDR、L2 轨迹指标分别在 1、1、2 个场景出现显著错筛，对数为 8、8、16；强谱模型
L3 的平均 Kendall τ-b 为 0.9551，36 个场景中显著错筛为 0，top-6 对任一最优和全部并列最优的
保留率均为 1.0。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_system/s1_local_vs_system_witness_v2/results.json::{analysis.summary,rows}`
及同目录 `manifest.json`。

因此旧评价器下“420 对大规模错筛”的数字不能继续作为论文结论；在当前候选池和主场景上，强谱基线已
消除显著错筛。H1 若继续，增量应收窄到“结构变化后如何自动组装并验证这种强解析模型”，而不是声称
经典局部/谱模型普遍不足。manifest 还定义了 held-out/stress 场景，但本次 `results.json` 只包含
36 个 main 场景，不能把其余场景写成已运行。

## 2026-10-09：NCO / FIR 新 seed 的冻结复验

DeepSeek 采样适应度 seed 3、每任务 3 次迭代中，FIR 再次生成对称抽头预加结构；NCO 生成 64 项
四分之一波表加象限镜像。使用同一冻结输入复验后，FIR 初始与候选的 SQNR 均为
85.11902870962494 dB，严格 Nangate45 面积为 12731.824→8445.234 μm²，减少
33.668310212268096%。NCO 初始/候选分别为 47.608220266725986 / 41.68076867958056 dB，严格面积
929.404→682.290 μm²：面积减少 26.588437321121926%，SFDR 损失 5.927451587145427 dB，形成
新的 ASIC 精度—面积折中点。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_e1/live4_{fir_t16_c25_sym,nco_p24_t256}_armS_seed3/revalidation/`
下的 `numeric_*.json` 与 `mapped_*/result.json`。

NCO 同一候选在 ice40 口径是 136→444 LUT，若只看 FPGA 会被初始点支配；在 Nangate45 口径却节省
26.59% 面积。综合后端会改变候选是否位于前沿，正式实验必须按目标平台分别重评，不能用一个后端的
排序代替另一个。具体原因是初始全波表在 ice40 使用了 2 个 `SB_RAM40_4K`，而四分之一波候选主要映射
为逻辑；Nangate45 的完整标准单元映射没有同样的存储器代价模型。

## 2026-10-09：atan2 2×2 搜索 pilot

在 46 点 atan2 有限结构空间中，以模 2^16 最短角度码差为唯一误差口径，完成 LLM / 强类型化非 LLM
提议器 × Boolean / 确定性数值反馈的三 seed pilot。46/46 个候选通过严格 Nangate45 映射。非 LLM
Boolean 三次相对面积损失为 0.10493088059214095、0.10612822466528793、0.10612822466528793；
非 LLM 数值反馈为 0.10612822466528793、0.10612822466528793、0，其中一次命中全空间最小合格面积。
LLM+Boolean 3/3 完成，损失为 0、无 strict-feasible 设计、0.040491999564602255；LLM+数值仅 1/3
完成，该次损失 0.24001306193534355，另两次在 4/8、6/8 次评价后因连续重复已评候选终止且未重跑。
因此没有 seed 同时具备四格完整且可行结果，交互效应不可计算。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m4/atan2_2x2_pilot_v1_20261009/results.json::summary`。

本轮 49 次 API 调用全部得到响应，包含 7 次重复提议，估算费用 0.011371968 美元。它与 sin/cos pilot
共同表明：当前 LLM 数值反馈格的主要问题是提议器重复追逐已评候选，而不是评价器没有连续排序信息。
这是两个有限空间上的一致机制迹象，但正式交互结论仍需能完成四格的协议与更大结构空间验证。

## 2026-10-09：DDC held-out 与 stress 边界

修复后的同一 DDC 协议又运行 held-out 32 场景（3072 行）和 stress 9 场景（864 行），每场景均为
96 个组合且无运行失败。held-out 中 L0/L1/L2/L3 均为 0 个显著反转，τ-b 分别为
0.9054/0.8939/0.8947/0.9575；stress 中 L0/L1/L2 分别在 2/9 场景出现 336 个显著反转，
τ-b 为 0.8874/0.8726/0.8766，最大记录真值反转约 2.30 dB，而 L3 仍为 0 个显著反转、
τ-b=0.9590。所有 split 的 top-6 都完整保留真值最佳点。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_system/s1_ddc_{heldout,stress}_20261009/results.json::analysis`。

失效边界由此收窄为强 alias/blocker 压力下的简单局部指标；强谱模型在 main、held-out、stress 三个
split 都未出现超过 1 dB 门槛的显著错筛。后续增量应检验结构变化后能否自动构建和验证强谱模型，不能把
经典强模型从基线中省略，也不能用 stress 的 336 对反转外推普通场景。

## 2026-10-09：复乘 40 次真实搜索的双后端复验

DeepSeek 采样适应度在 `cmul_w16_free` 上运行 40 次迭代，17 次产生可评价候选、23 次失败按原样保留。
最终候选在 65536 个冻结输入上保持零误差和 II=1；相对四乘法初始实现，ice40 从 6836 降到 5618，
Nangate45 从 8785.182 降到 7896.210 μm²，但流水延迟由 1 增至 2。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_e1/e1_cmul_w16_free_armS_seed1/revalidation/summary.json`，文件
SHA-256 为 `8c0671656c4efe438254772f63f7aff15557214330b8df03a3a9475e8955bd0e`。

与同次运行中已有的 Gauss 三乘法候选相比，最终候选在 ice40 小 114（1.9888346127006282%），但在
Nangate45 大 654.892 μm²（9.04382323770341%），并多一拍延迟。结构上它把三个 17×16 乘法改为
两个 16×16 加一个 17×17，同时增加乘积流水；Nangate 映射的 `DFF_X1` 从 67 增到 165，而 ice40
面积指标没有计入这些触发器，导致排序反转。因此该次搜索证明的是 FPGA 目标下找到改进，不是跨工艺最优；
后续适应度必须显式绑定目标工艺、寄存器成本与延迟，所有候选也必须在共同后端重评。

## 2026-10-09：FIR 同口径 2×2 结构搜索

在 20 点冻结空间（direct / 对称预加 × 5 档系数小数位 × trunc/RNE）上完成 3 个配对 seed 的 M4
终止实验。Boolean 与 numerical 使用同一个 FIR 输出风险：前者只给“解析 SQNR ≥ 60 dB”，后者给
完整解析误差能量与 SQNR；终验在独立 seed 的 32768 点输入上，用同一 Q9.30 输出误差和连续系数参考
重算 SQNR。20/20 个候选均通过 257 点 RTL bit-true 对拍和严格 Nangate45 映射，面积范围为
4917.276–13220.466 μm²。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m4/fir_2x2_v2_20261009/{candidate_pool,rtl_validation,area_cache}.json`。

强类型化非 LLM 提议器的 Boolean / numerical 两格均 3/3 完成；对应 held-out hypervolume 分别为
[0.5638074790476909, 0.47910784535154327, 0.5750598831330295] 和
[0.3862070994139518, 0.47910784535154327, 0.5750598831330295]。直接 DeepSeek 提议器的两格均
0/3 完成：27 次 API 成功响应中有 18 次重复已评候选，六格都按预定规则终止，故没有完整配对 seed，
交互效应不可估计。这个负结果定位的是当前直接 LLM 提议协议不能稳定花完预算，不是 FIR 结构空间或
解析反馈失败。来源：同目录 `results.json::summary`；结果 SHA-256 为
`14fce07ea2573dd0bdf08bc4f5130b32f814399a0145a320ac85283f141abdc8`。

此前 v1 使用“逐系数最大误差 ≤ 8 LSB”作为 Boolean 门，与输出 SQNR 终验不是同一指标，已保留为
诊断产物且不得用于 2×2 交互结论；v2 未覆盖 v1，并把 Boolean 改成同一解析输出 SQNR 的阈值。

## 2026-10-09：自由 RTL 路线的开发止损点

在修正 cascade 门槛后，`cordic_sincos` 初始设计可正常评价为 24.9139 dB、ice40 面积 236、吞吐
0.9082；随后 DeepSeek 自由 RTL 变异连续 8 次均未形成可解析候选，其中 4 次无有效代码、4 次无有效
diff，没有候选进入仿真或综合。该开发运行按预设止损原则人工中止，初始设计仍被导出为 best；日志为当前
`da43` 工作区 `examples/comm_dsp_bench/experiments_e1/e1gatefix_cordic_sincos_armS_seed1/logs/`
`openevolve_20261009_100604.log`，SHA-256 为
`b759e98f15be0e7701846915200a0a9bb97a89a01fa108314e02a3bb8dfa1083`。

这只说明当前自由文本协议在该次运行中没有把模型回答变成硬件候选，不能据此否定结构搜索或其他算子。
后续计算转向已能稳定生成、验证和综合候选的参数化结构空间；该失败保留为结构生成轨的负结果，不再通过
反复修改 API 输出提示来消耗主要实验预算。

## 2026-10-09：层级动作提议器补完 FIR / NCO 2×2

把 DeepSeek 的输出从 candidate id 缩减为通用结构/参数动作，再由冻结执行器按“最早访问父点、候选参数
规范序、索引”展开合法未访问邻居；重复动作只要仍有邻居就继续展开，非法或耗尽动作在同一步确定性
fallback，不增加搜索预算。强非 LLM 对照使用同一动作集和同一执行器，仅以 UCB1 选择动作。单 seed
smoke 与正式 3 paired seeds 分目录、分开计费；正式 FIR/NCO 各 12/12 格完成，每格均为 8 个唯一新候选。

正式结果中，FIR 的 hierarchical LLM Boolean / numerical held-out hypervolume 分别在三个 seed 恒为
0.5212938995155353 / 0.47910784535154327，UCB 两格均为 0.3862070994139518；预定义交互均为
−0.042186054163992015。NCO 的交互分别为 −0.010711896547582977、0.000509468517105538、
−0.011404462704826646，均值 −0.007202296911768029。96 次正式调用中 95 次 API 成功；FIR 一次调用失败
按冻结 fallback 展开，47 次重复动作均正常得到新候选。正式费用估算为 FIR 0.01198218 美元、NCO
0.012099636 美元。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m4/hierarchical_pilot_v1_20261009/{fir,nco}/results.json::summary`；
结果 SHA-256 分别为 `c113961a3f84bc8c70308428651ccf8ed7b083ae6e8798a8cfb31bdafe509f46` 和
`1476aac610e6d12bb2b88693769a72ebf610ac1fe71a3e5e0d4113f7cca1b645`。

这说明层级动作协议解决了直接 id 提议器因重复而不能花完预算的问题，但本 pilot 不支持“连续解析反馈
提高 LLM 相对强非 LLM 搜索收益”：两个任务的平均交互都为负。FIR 的三 seed 轨迹相同，NCO 也高度
集中，反映冻结 20 点空间、确定性展开和无 provider seed 使独立运行多样性有限；不能把 3 个 seed 当成
广泛统计结论。NCO 的交互主终点预先冻结为 held-out MSE—面积归一 hypervolume，参考点是冻结 20 点池
两轴最大值的 1.05 倍，避免未访问 strict-feasible 点时相对面积损失为空；原正式 v2 终验字段仍全部保留。

## 2026-10-09：NCO 同口径 2×2 结构搜索

在 20 点 LUT / CORDIC 冻结空间上，以 24 位任务相位累加器全域的 raw sine-only 误差为统一口径，
完成 3 个配对 seed 的 M4 运行。Boolean 只暴露“全域最坏误差 ≤ 8 Q1.15 LSB”，numerical 暴露
全域闭式 MSE / SQNR；终验独立冻结 7 条未见 FCW 轨迹，每条 16384 点。20 个生成 RTL 的严格
Nangate45 面积为 606.214–2837.156 μm²；面积最小的 held-out 合格点为 candidate 8，面积
1584.562 μm²，终验 SQNR 82.11419685540314 dB、最差 SFDR 96.18661475855552 dB。

强类型化非 LLM 提议器两种反馈均 3/3 完成且全部命中该点。DeepSeek Boolean 为 0/3 完成，
DeepSeek numerical 为 1/3 完成且该次命中；48 次调用含 30 次接受、17 次重复和 1 次截断无效，
估算费用 0.008787455999999999 美元。由于没有四格均完成的 seed，交互效应不可估计，不能把
“numerical 提高 LLM 相对收益”写成结论。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m4/nco_2x2_pilot_v2_20261009/results.json::summary`，结果
SHA-256 为 `c3d1f7f8ee32d77c66b191c1f95d06b987b852f754f022c496cfe94ee5ef8b49`。

此前 v1 错用了 32 位、全局复增益校正后的 I/Q 联合量，而任务接口是 24 位累加器的 raw sine，
因此 v1 只保留为诊断产物；v2 未覆盖 v1，并把训练与终验统一到任务接口。三个代表结构的全 2^24
状态暴力复核与闭式 MSE/WCE 一致，现有 NCO RTL/映射测试 35 项通过。

## 2026-10-09：复乘同起点 2×2 pilot

`cmul_w16_free` 的 v1 从 strict-infeasible candidate 17 起步，12 格虽都花完 8 次新候选预算，却均未
访问 20 个 strict-feasible 点，因此封存为诊断，不用于交互结论。正式 v2 改从可信的全精度 direct
candidate 0 起步；112 个 v1 严格 Nangate45 作业逐项身份重绑，110 个映射成功，candidate 64/65
均在冻结 600 秒上限超时并统一从四格邻域及终考分母排除。主效用为全成功池归一化的
log1p(frozen-truth MSE)—面积二维 hypervolume，因而每条轨迹始终有定义。

v2 中非 LLM Boolean / numerical 与 LLM Boolean 均 3/3 完成，LLM numerical 为 2/3；seed 20261023
首步连续三次重复 candidate 0 后按协议保留为 proposer failure，未重跑。两个完整配对 seed 的交互为
−0.3313157511640996 和 0.08593341695621726，均值 −0.12269116710394118，不能支持“连续数值反馈稳定
提高 LLM 相对强非 LLM 收益”。47 次 API 调用均成功响应，含 7 次重复，估算费用 0.010700028 美元。
来源：当前 `da43` 工作区 `examples/comm_dsp_bench/experiments_m4/cmul_2x2_pilot_v2_20261009/`
`results.json::summary`；结果 SHA-256 为 `da23297fb96d427f29f24fd9f7064b8e13d5336c819ae8163d3cbdfc9fb72bd2`。

## 2026-10-09：公式到 2:1 FIR 抽取器运算图

DeepSeek 从冻结的 16 抽头 Q15 FIR 公式直接生成受限运算图，再由确定性 lowerer 生成
2:1 valid/ready RTL；模型没有选择预列 FIR 模板，也没有写自由 Verilog。V1 暴露了“串联
delay 与绝对 delay 等价却被拒绝”的前端问题；V2 仅归一化 rooted-at-x delay 链，不补节点、
不改系数或算术。8 次新调用中 3 个不同图通过独立 129 输入/57 输出逐位检查、5 周期反压保持和
strict Nangate45 映射。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m5/fir_decim_graph_v2_20261009/results.json`，结果 SHA-256 为
`086d8834b7916b44b6e6d1f47cce1bc3ed56b4a3149358f34f893942f250d0fd`。

三个模型图都形成 8 个常系数乘法的对称预加结构，映射后的归一网表与强专家对称预加基线相同，
面积均为 8787.310000000001 μm²；专家 direct 为 12913.768000000002 μm²，奇偶抽头代数分组为
12736.878 μm²。因此这次证据支持“公式→运算图”在一个仓库原未实现任务上跑通并匹配强专家，
不支持“发明新 FIR 算法”、“超过强专家”或单任务泛化主张。

## 2026-10-09：max-log 64QAM LLR 同口径 2×2

`llr_64qam_snr20` 的冻结 evaluator 语义是 `2*sigma2*raw_LLR` 的 Q8.8 归一化软信息，不是任务卡
原先字面所写的未缩放 raw log LLR；任务卡已补明这一点，评价器和历史产物未改。正式 v2 对
direct absolute、shared pairwise-square、folded absolute 三类 max-log 结构、4 档输入截位与
trunc/RNE 共 24 点，以同一个 `sigma2=0.01` normalized exact log-sum-exp 参考计算 6 字段最差
SQNR。numerical 是冻结有界 65,536 点确定性格点退化层，不称解析模型；Boolean 是同一指标
`>=65 dB` 的单阈值，终验用独立同规模格点。

24 个候选的完整 65,536 单轴码 RTL/模型对拍均为零 mismatch。strict Nangate45 面积有 16 项
成功；shared-square 08--11 的独立 retry 均在 600 秒 timeout，12--15 未再启动，8 项都从搜索和
终验分母剔除。其余空间中 4 个 cell（typed/DeepSeek × Boolean/numerical）均 3/3 完成且命中
candidate 2，面积 4133.64 μm²、独立终验最差字段 SQNR 66.8730762075287 dB；三 seed 交互均为
0，因此没有反馈×提议器收益证据。51 次 DeepSeek 调用全 API-ok，3 次重复，估算费用
0.009898686 美元。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m4/llr_maxlog_2x2_v2_20261009/results.json::summary`，SHA-256
为 `b85edf911f342c73c34107a0370e51eb2f37cfec974126592afac02923cda597`。结论只适用于冻结有界
Q4.12 域与 max-log 类，不外推无界重尾输入、correction 结构、时序/功耗或布局布线。

## 2026-10-09：NCO 受限结构分解闭环是负结果

DeepSeek 不见候选 id、不写 RTL，只输出 quadrant-reduced LUT 参数或显式 CORDIC micro-rotation
分解；确定性 legalizer 仅按结构参数绑定已验证 20 点，随后复用全 `2^24` raw-sine 解析误差和逐
SHA/contract 核验的 strict Nangate45 面积。3 个 paired seed、每 proposer 8 步中，typed 搜索
3/3 找到最低面积 held-out 合格项；DeepSeek 24/24 API-ok，但仅 3 accepted、20 duplicate、1
schema rejected，每 seed 只新增 candidate 5，0/3 合格。LLM-minus-typed held-out hypervolume
差为 −0.12511529148659495、−0.12427213030899253、−0.12427213030899253，均值
−0.12455318403486。来源：`experiments_m5/nco_decomposition_v2_20261009/results.json`。

这支持的分工是：LLM 用于提出真正新结构，解析/确定性方法负责局部精度搜索；不支持在受限局部
空间用 LLM 替代 typed 搜索。正式 v1 的 4 次输入超限只作 runner 诊断，不计模型失败。

## 2026-10-09：公式运算图扩展到真实 `cmul_w16_free`

V3 绑定仓库原任务卡的 `a/b/c/d` 端口和 33 位输出；符号验证器逐节点证明双线性系数正确、
39 位中间值不溢出，并证明最终值适配 33 位。8 次新 DeepSeek 调用产生 2 个不同的合法四乘图，均通过
257 向量逐位检查、5 周期反压和 strict Nangate45，面积均为 8781.724 μm²。来源：当前 `da43`
工作区 `examples/comm_dsp_bench/experiments_m5/cmul_graph_v3_real_task_20261009/results.json`，结果
SHA-256 为 `77f4ae4cbd98f54519354e696d65116dbc536627e5e7dc06e3c5d3c7af165607`。

模型图与专家四乘基线的映射网表相同；专家串行重结合 Gauss 为 7320.852 μm²，加强的
`p_sum-(p_ac+p_bd)` Gauss 为 7312.606 μm²。因此这次把“公式→运算图”能力扩展到了第二个公式任务，
但本批没有形成三乘结构，未匹配最强 Gauss 基线。早期使用 39 位外部接口的 V1/V2 只作开发诊断。

## 2026-10-09：生成结构内的非均匀精度形成解析质量—真实面积闭环

在 DeepSeek 生成的 FIR 对称预加图内，对八组系数独立清除 `{0,2,4,6}` 个幅值低位（向零截断）。
精确输入矩给出零采样方差的 MSE/SQNR；65,536 个原始分配中有 3,008 个达到 60 dB。冻结选择的
25 个候选全部通过数值核对、RTL 对拍、反压和 strict Nangate45 映射。门槛下观察到的最佳非均匀点为
61.748809831750904 dB、7428.316000000001 μm²；最佳可行统一 drop=2 为 70.22668161702408 dB、
8144.388000000001 μm²，观察面积差 716.0720000000001 μm²（8.792213730485336%）。来源：当前 `da43`
工作区 `examples/comm_dsp_bench/experiments_m5/fir_nonuniform_precision_v2_20261009/results.json`，SHA-256
为 `809b852898a9440801e2ecca5e02dea63b32ca09d1a711c3e7c19be77a6fffc9`。这只是一个生成结构、固定
输入分布和 25 点真实映射 shortlist 内的单次综合结果；不能写成 7,776 个有效点上的全局物理最优，
且尚未验证时序、功耗和布局布线。

由这条结果得到的系统分工是：LLM 负责跨结构跳变并输出可验证的运算图；解析误差模型在每个合法图内
穷举或优化精度分配；真实综合只评估解析前沿的少量点。不要再要求 LLM 同时猜结构、截位和 RTL 细节。
跨算子复核后，正收益目前仍只出现在上述 FIR 个例：cmul 的非均匀分配未胜最强统一 Gauss，NCO 与
atan2 的有限已知空间里 LLM 都输给类型化搜索或枚举。因此系统应把“小空间局部优化”确定性交给解析
方法，把 LLM 预算只用于产生现有有限空间之外的结构；后者仍需更多算子给出正证据。

## 2026-10-09：atan2 公式到受限运算图未命中冻结全空间前沿

真实 `atan2_w16` 上，DeepSeek 8 次真实回答均合法，但按节点语义去重后仅 6 图、2 次改名重复；
86 个冻结合法 ratio-LUT/CORDIC 图全部完成确定性 2^20 Sobol bit-true 采样和 strict Nangate45，
形成 18 点 Pareto，模型命中为 0。call 2 虽比初始 RTL 小，仍被同精度的 `space-40` 严格支配，
因此这是负结果，不支持有限空间内的 LLM 搜索优势。来源：
`experiments_m5/atan2_graph_v2_real_task_20261009/results.json`，SHA-256
`82f28dbd4f6bb17f6c3ec6c2b4ce2127a1269ac4211e718208ea3b96da61c857`。

## 2026-10-09：cmul 非均匀乘积截位未击败最强统一基线

在已有 DeepSeek 四乘 direct 图与专家三乘 Gauss 图内，确定性分配器枚举 1,500 个
`drop∈{0,2,4,6,8}`、RNE/trunc 点；共享输入误差项只有在左右变换均通过模 256 双射枚举后才按零
协方差合成。140 dB 门槛下 621 点可行，冻结 shortlist 的 39/39 点完成 bit-true 与 strict
Nangate45。最强统一点是 Gauss/trunc/(6,6,6)：141.1638655334897 dB、
6973.1900000000005 μm²；最佳非均匀 shortlist 点是 Gauss/trunc/(6,4,6)：144.40805318392196 dB、
7010.962 μm²，面积反而大 37.771999999999935 μm²（0.541674613770741%）。因此本冻结口径是负结果；
但 generated direct 内部非均匀点 8398.95 μm² 比其统一点 8432.2 μm² 小 33.25 μm²，跨结构仍输
Gauss；同 Gauss/lowerer 下 exact 7312.606 到 uniform approximate 的面积差为 339.416 μm²。
“最佳”仅指映射 shortlist。来源：`experiments_m5/cmul_nonuniform_precision_v1_20261009/results.json`，
SHA-256 `f27802a48e012dd50e08b7f893879ba41f0c4aa75524e56dfbef392b55efbd29`。

## 2026-10-09：atan2 同预算搜索基线进一步否定有限空间内的 LLM 优势

在已完成严格 Nangate45 映射的 86 个 atan2 图上，以相同面积/确定性精度口径做离线搜索重放；
DeepSeek 的 8 次真实提议只形成 6 次不同评价，超体积为完整空间的 0.8512944410797141，且 18 个
全局 Pareto 点命中 0 个。256 个固定种子下，8 次有放回随机提议的 Pareto 命中率为 0.84375，
平均超体积比例 0.8569587769647288；8 次离散 ParEGO 的命中率为 0.8359375，平均超体积比例
0.8505009468759035。LLM 的超体积仅高于或等于 0.2890625 的随机运行；它与 ParEGO 的均值近似，
但前沿命中明显更差。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m5/atan2_search_baselines_v1_20261009/results.json`，SHA-256
`1fb889564c925a24ad77c87e25115db0861b4a5fde642e1855e73e4b4da691ab`。这是单任务冻结有限空间的
负结果，不外推到新结构生成；它把后续 LLM 试验范围进一步限定为“扩展实现集合”，而不是已知参数
空间调参。

## 2026-10-09：DDC 八项评价器修复改写了 H1 证据口径

折叠索引、SFDR 载波主瓣、预测/真值口径、`worst_drop`、NCO 两字段 SQNR、
tau-b/ties、QPSK 功率和 desired-only AWGN 定标已统一；主结果使用 raw 实现误差，
aligned 值只作敏感性诊断。修复后的 main/held-out/stress 新目录均保留了完整 JSON；
L3 功率和预测在三个分区的显著反转数都为 0，而 stress 下 L0/L1/L2 各有 336 对。
来源分别是当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_system/s1_local_vs_system_witness_v2/results.json::analysis.summary`、
`s1_ddc_heldout_20261009/results.json::analysis.summary` 和
`s1_ddc_stress_20261009/results.json::analysis.summary`。

因此历史 420 对 L3 错筛必须留在诊断历史中，不再用于支撑 H1；目前更窄的可复现
观察是“强干扰 stress 下频率盲局部指标仍会反转，但当前校正的 L3 没有”。新旧运行
的场景集和口径不同，不能把汇总差值当作单项修复的因果效应；三个新结果也都是
单次冻结运行，不支持统计显著性主张。

## 2026-10-09：NCO 同预算随机基线确认 LLM 受限搜索明显落后

在同一个 20 点冻结 NCO 空间、同一个初始点和 8 次提议预算下做 4,096 个固定种子重放。DeepSeek
三次运行都只新增 1 个不同候选，held-out 超体积均为 0.6338405101618746；8 次有放回随机提议平均
新增 6.41943359375 个候选，平均超体积 0.7270597502584534，只有 0.03076171875 的随机运行不超过
LLM。8 次不重复随机评价的平均超体积为 0.7374193303727139；typed 搜索三次约 0.7581--0.7590，
仍是最强。来源：`experiments_m5/nco_random_baseline_v1_20261009/results.json`，SHA-256
`d8f03a19e99d616e3c9d028b61edf6d5cff5e6be6685c517c9d975216d03705a`。这进一步排除“LLM 在已知小
空间里提高搜索效率”的主张，不否定它生成空间外新结构的可能性。

## 2026-10-09：Gold scrambler 补成三个真实结构点，但面积排序依赖后端

32-bit Gold 任务现有独立 recurrence、fresh-seed 刺激、全部 31 个 `c_init` 基向量和 exact-match。
单拍 GF(2) 全展开、50 拍复用 `A^32`、逐位递推在 4096 输入与随机反压下均零 mismatch。对应
ice40 `LUT4+CARRY` 为 119/118/106，strict Nangate45 为 583.87/900.144/634.144 μm²；中间点被
支配，逐位点只在 FPGA 口径更小。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_benchmark/scrambler_gold_w32_architectures_v5_20261009/results.json`，
SHA-256 `99735d03d4d7ff17e9def1a2dbc891769e813045418b4e4f42588370a0e2151c`。这说明 GF(2) 操作数或
单一 FPGA 资源不能代理 ASIC 面积；仍无时序、功耗或布局布线结论。

## 2026-10-09：DDC 修正后的机制是场景化混频误差，不是级间互相关

77 场景×96 候选的独立分解将链路误差闭合为 `P(u)+P(v)+2ReE[u*conj(v)]`，
最大样点残差为 `2.290287721145337e-16`。stress 中 L0/L1/L2 的 336 个唯一反转对全部由
`P(u)` 主导，修正后 L3 对 336/336 恢复正确顺序。FIR 边界在冻结暖机段后无可测影响；
alias 副本不相干化的最大点误差小于 `0.118 dB`；去掉级间交叉项虽有最大
`1.5741077728829893 dB` 的点误差，但在 1 dB 双边规则下未产生反转。

因此 H1 现在的实证边界是：频率盲局部指标会漏掉强 alias 场景中的误差传递，但当前
修正的 L3 已足以排序冻结池；不能再主张“经典功率和模型在这些场景中失效”。
真实数字见当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_system/p0_2_ddc_mechanism_v2_20261009/results.json::closure`、
`analysis` 和 `rows`。

## 2026-10-09：同一 cmul 参数空间的三路真实 DeepSeek seed-1 对照已完成

在同一个 `cmul_w16_free`、同一 seed、40 轮下，解析适应度 C、同一参数化空间的采样适应度 CS、
以及自由 Verilog 采样 S 均完成真实 DeepSeek 调用。C 最终为 999 dB / 5780 LUT / 7295.05 μm²；
CS 为 999 dB / 5780 LUT；S 为 999 dB / 5732 LUT。这个单 seed 只说明 C/CS 的表示空间可以做
干净适应度对照，S 的面积差只能作自由实现集合参考，不能当作解析适应度的因果收益。三份
`best_program_info.json` SHA-256 分别为 C `e63c90097389d76d746446f00e2e902b71d19d4fe1b0f7dae0f1fa9ea2a9fe86`、
CS `54cc1931333ab0385fdb4d15793108796968fb1ac681dd795cb632f6129bc9ea`、
S `13955edde7771c245725b3b8ce9ea2948fa9ba731bf8f2eba8cc37e41cf64e90`。

## 2026-10-09：DDC48 100 MHz 约束批次完成，但本机没有 STA

冻结 48 个 DDC 组合完成真实 Nangate45 映射：41 个成功、7 个在 600 秒上限超时；成功面积为
26670.224--38990.812 μm²。ABC 约束延迟代理中 37 个达到 100 MHz、4 个未达到，代理延迟为
2498.44--10305.56 ps。capability probe 证明本机没有可用 OpenSTA/STA，因此 WNS/TNS 和真正的
timing_target_met 全部 unavailable；这些结果只能用于“ABC 约束代理”开发分析，不能写成 STA 收敛。
来源：当前 `da43` 工作区 `experiments_system/timing_100mhz_ddc48_v1_20261009/results.json`，
SHA-256 `7fa6cb03a2815e8b6f7782ede19b37f4918d6e8301143177aa4af39b6a248c4a`。

## 2026-10-09：atan2 同预算离散进化补齐后，LLM 仍未证明有限空间优势

在冻结的 86 点 strict Nangate45 空间上新增 256-seed 离散进化重放。8 次评价时，离散进化的
全局 Pareto 命中率为 0.71875、平均完整空间超体积比例为 0.7854148405804178；DeepSeek 的 8 次
提议命中率为 0、超体积比例为 0.8512944410797141，高于或等于 0.734375 的离散进化运行。
这说明单看超体积会掩盖“没有找到真实前沿”，也说明传统进化本身并非自动优于 LLM；但结合随机与
ParEGO 的更高前沿命中，仍没有证据支持 LLM 在已知有限空间调参。LLM 的待验证价值应限于扩展实现
集合。来源：当前 `da43` 工作区
`examples/comm_dsp_bench/experiments_m5/atan2_search_baselines_v2_20261009/results.json`，SHA-256
`60e6af097b7ae43dd7e5b77aaf693a9800bbf435818844f2a7d971011f8ea8ad`。
### P1-1 QNTF 控制（2026-10-09）

已运行 `experiments_system/p1_1_qntf_powerfold_v1_20261009/results.json`（SHA256 `9f4a68944ca6063d002f863cf5bcb0185346f72e3ff79fe2e436d374aa2b89ca`，manifest `f07e0796630c5706737b6916122e77cb5cd469cab8c9a4a20fdfb66777cf4253`）：7392 行（77 场景×96 候选）。QNTF 风格 power-fold 控制的精确功率恒等式闭合最大残差 `1.5626874120572496e-16`；stage-uncorrelated 预测相对 P0-2 truth 的平均差 `-0.09610462907438881 dB`，最大绝对差 `1.5741077728829893 dB`。这只是可复现的 QNTF 控制/消融，不是完整 Nicholas 一阶杂散模型，因此 P1-1 尚未关闭。
### 当前三条可检验命题（2026-10-09）

1. **联合设计优于强分阶段方法吗？** 同时选择算法结构、精度和微架构，是否比“先定结构，再调精度和流水”得到更好的实现。
2. **LLM 能找到满足约束的近似变换吗？** 从数学公式出发，不局限于完全等价变换，提出误差达标且硬件代价更低的实现。
3. **经过验证的失败原因反馈，能让 LLM 搜得更好吗？** 在相同提案、评价和工具预算下，带经过验证原因的反馈是否比只给数值更能促使结构调整并找到更好的实现。

后续实验结果必须明确属于哪条命题；单个算子跑通只算能力/工程检查，不能直接支持上述任一命题。
### FFT64 架构能力检查（2026-10-09）

冻结同一 1024 行输入，对 radix-2 single-butterfly 与 radix-4 three-multiply 分别做连续流和反压流检查：两种结构均为 1024 accepted/received、协议无错误；连续延迟分别为 256 与 112 周期，反压测试实际覆盖 ready-low 最长 58 周期、输出停顿最长 32 周期。Nangate45 两个 mapped-area 作业均在 ABC 映射阶段超时，没有合格面积或时序数字；因此这里只记为结构/协议能力检查，不做面积排名。产物目录：`experiments_benchmark/fft64_architectures_v1_20261009/`。
### DDC 直接复数旋转原型（2026-10-09）

新增的是跨节点实现：不先生成 `sin/cos` 再复乘，而是用全 32 位相位直接 CORDIC 旋转复数输入。独立整数模型与生成 RTL 已在边界/随机向量逐码对拍。冻结 8192 点相位轨迹上，16 级的 RMS 为 `(re=0.43343096501240347, im=0.44322944386315694)` LSB、最大误差 `(1.6779327659933188, 1.7623551043761836)`；18 级 RMS `(0.29573987147401604, 0.294163266439884)`、最大 `(0.7737202793723554, 0.7735425253595167)`。12 级严格 Nangate45 映射在 `300.0103735839948 s` 超时，16/18 级未启动，不存在面积排名。它证明“可用近似变换组件”而非“LLM 已发现它”或“联合搜索已获胜”。来源：`experiments_system/direct_rotation_proto_v1_attempt2_20261009/interrupted_results.json`，SHA256 `ea17918263f6963f77487bf37c6b6fdb617bb20fb938990cbe38b3a95fe6d0b2`。
### 流水化 DDC 直接旋转：真实可综合点（2026-10-09）

同一直接 CORDIC 递推改成可停顿的“每级一步”流水后，严格 Nangate45 映射不再超时：12/16/18 级面积依次为 `15335.964000000002`、`19744.914`、`21756.938000000002 μm²`，真实映射时间约 3.20/3.84/4.04 秒。16 级数值为 RMS `(0.43343096501240347, 0.44322944386315694)` LSB、最大 `(1.6779327659933188, 1.7623551043761836)`；18 级 RMS `(0.29573987147401604, 0.294163266439884)`、最大 `(0.7737202793723554, 0.7735425253595167)`。它是可进入联合结构—精度—微结构空间的真实组件点；尚未接入完整 DDC FIR，也没有与匹配的全链基线、LLM 或 held-out 比较。来源：`experiments_system/direct_rotation_pipeline_v1_20261009/results.json`，SHA256 `2e40eef2977c7ff17455e6e584577946e2e3da81cebaf744b1bcc593e4805640`。

### DDC 直接旋转接入真实全链（2026-10-09）

直接旋转已接入真实的“混频—33 tap FIR—R=2 抽取”流式链；检查器也显式记录抽取后的输出事务数，连续与反压 RTL 对拍均通过。冻结 36 个主场景上，9 级是最低已测的质量可行点：最坏对齐误差 `4.317071147544789e-06`、混频/FIR 饱和均为 0；严格 Nangate45 映射面积 `42320.866 μm²`、实际映射时间 `259.40822320804 s`。这使直接结构成为可搜索的真实全链点，但它尚未纳入旧的强分阶段空间，且面积并不自动优于旧结构；不构成联合设计、LLM 或 held-out 结论。来源：`experiments_system/direct_ddc_fullchain_v1_stage9_20261009/results.json`，SHA256 `e66dfb22e3814851900731b7359718eb918183dea0777acd45d39afc697ee632`。

把 9 级结构的内部 guard bits 从 6 联合降到 2 后，最坏误差仍为 `4.31551032597555e-06`，面积降至 `41134.240000000005 μm²`（减少 `1186.6259999999966 μm²`，映射 `218.06766900001094 s`）。这是实际精度—微结构优化，但仍未优于旧强结构空间，不能替代联合/分阶段的共同搜索对照。来源：`experiments_system/direct_ddc_fullchain_v1_stage9_g2_20261009/results.json`，SHA256 `d76cd9b586295148d32f0b6f5debba7b38d7a467c665ac32a21f8394045524e6`。

冻结 36 主场景的 25 点直接旋转网格（级数 8–12 × guard 2–6）已完成；以 `stages×(16+guard_bits)` 仅作综合前筛代理，质量可行前沿从 9级/2bit 到 12级/6bit。代理不是面积，后续只对前沿点做严格映射并接入共同 H2 对照。来源：`experiments_system/direct_ddc_joint_grid_v2_20261009/results.json`，SHA256 `5d9dc1b11ea2e145301e3f4d1af3667a66af91d0aedc849d0ca178ce5cb4a8e7`。

前沿复核的 10级/2bit 点把误差降至 `1.119742089405182e-06`，但严格面积为 `42134.4 μm²`，高于 9级/2bit 的 `41134.240000000005 μm²`；故它只保留为精度端点，不是低面积选择。来源：`experiments_system/direct_ddc_fullchain_v1_stage10_g2_20261009/results.json`，SHA256 `8ec7b34b090173ef90170444f1e89ffd23f6378f989bd03f878faf6c5b29d642`。

与既有固定强全链基线按同一主场景 Q/严格面积字段做的 H2 核对显示：9级/2bit 和 10级/2bit 直接旋转均被 LUT 基线 `9d32c952...` 支配（基线 Q=`2.0606135458920818e-07`、面积=`38346.294 μm²`）。这是直接 CORDIC 结构轴的负结果，不是 H2 总结；后续必须探索更强近似分解并做完整联合/分阶段实验。来源：`experiments_system/h2_direct_vs_fixed_v1_20261009/results.json`，SHA256 `91a87fc4162f0b684aa76ab472ca10a50f0e99e1fa6ab7e4f1e277019d7db759`。

### 并行 FIR 结构生成基线（2026-10-09）

同一轮真实 DeepSeek 八次调用在冻结 16-tap FIR 算术图上均被验证器拒绝（字段、延迟状态、精确冲激响应或死节点），因此没有 LLM 候选进入面积比较；专家 direct/polyphase/symmetric-preadd 的严格 Nangate45 面积为 `12913.768`/`12736.878`/`8787.310000000001 μm²`。这定位当前问题在“完整状态图”的提议表示，不能据此否定 FIR 结构或近似变换；下一轮应冻结延迟状态，只让模型搜索配对、系数、归约和精度。来源：当前 `da43` 工作区 `examples/comm_dsp_bench/experiments_m5/fir_decim_graph_parallel_v1_20261009/results.json`，SHA256 `14b2252418cdffe460ec07dde0ecdee7d286f055db52c6e09e7fa0ff38229618`。

对同一 FIR 契约仅做延迟链的语义保持规范化后，8 次真实调用有 2 个合法图；两者都独立重构了 8 乘法器对称预加法，严格面积均为 `8787.310000000001 μm²`，与强专家相同。它说明 LLM 能从公式重构已知结构，且表示影响合法率（0/8→2/8）；尚无超过专家、近似变换或反馈优势结论。来源：当前 `da43` 工作区 `examples/comm_dsp_bench/experiments_m5/fir_decim_graph_parallel_normalized_v1_20261009/results.json`，SHA256 `3bb0975dd94af8416380a073171305e77cb62e96519346e044882287b4583913`。

### 当前旋转专家重建（2026-10-09）

在当前源码与冻结输入上，8 个旋转专家均通过数值和连续/反压协议检查；7 个取得有效 Nangate45 面积，最低仍为 `lut256_three_multiply=10300.052 μm²`。`sincos18_three_multiply` 的面积映射超时，故该档案不是完整八专家面积基线，不能直接启动要求八项均合格的 LLM continuation。来源：当前 `da43` 工作区 `examples/comm_dsp_bench/experiments_rotation/current_experts_parallel_v3_20261009/results.json`，SHA256 `ad5ac87a8a8a72cb8b54f4d1b58317fd3b389619a565323a278237a40603fcb7`。

### 失败原因反馈的复乘配对检查（2026-10-09）

同为 8 次 DeepSeek 调用、同一公式/验证/面积预算时，反馈与无反馈各有 2 个合法图；无反馈组生成并严格映射出 Gauss 三乘法 `7294.518 μm²`，反馈组两个合法图均为四乘法 `8781.724 μm²`。因此本单批次不支持“失败原因反馈更好”；提供方无可复现 seed，且 token/费用略不同，不能外推成统计结论。来源：当前 `da43` 工作区反馈 `examples/comm_dsp_bench/experiments_m5/cmul_graph_parallel_v1_20261009/results.json`（SHA256 `492e7da64baf17db2c4d75a1a8955dc8410a6afe5855da3fc59373b55161358b`）；无反馈 `examples/comm_dsp_bench/experiments_m5/cmul_graph_no_feedback_parallel_v1_20261009/results.json`（SHA256 `1794bc5309c73ece834a03bad6fa0b34dd40bee79b762f12fa76247eda1aa903`）。

### 联合设计框架改造（2026-10-09）

`da43` 新增任务无关的联合候选 IR：一个候选同时表达运算图、逐节点定点格式、舍入/溢出、流水级、资源组和冻结质量门。结构验证只检查图和实现语义，不再要求逐节点等价于参考公式；候选是否可接受由独立实测指标过质量门决定，因此允许误差达标的近似实现进入搜索。通用运行层把 `invalid_structure`、`quality_failed` 与 `tool_failure/timeout/unknown` 分开，并分别记录提案、评价请求、真实工具执行、重复和 cache 命中；反馈/无反馈两臂共享相同指标与预算事件，只差是否返回经过验证的失败原因。首个 CMUL 适配已能把结构和每个乘法器的独立截位一次性转换为解析误差评价与 RTL；尚未产生新的真实 LLM/面积结论。未判定的工具结果不会写入候选真值缓存。定向测试 `47 passed`（`tests/test_joint_design_ir.py`、`tests/test_joint_search.py`、`tests/test_joint_cmul.py`）。

### CMUL 非均匀精度相对强均匀基线的负结果（2026-10-09）

当前 `da43` 中两种冻结结构的 39 个候选全部完成严格 Nangate45 映射。在 SQNR≥140 dB 下，强均匀基线是 Gauss sum-recombine、三乘法均截 6 bit、trunc：SQNR `141.1638655334897 dB`、面积 `6973.1900000000005 μm²`；非均匀 shortlist 最好点为截位 `(6,4,6)`、trunc：SQNR `144.40805318392196 dB`、面积 `7010.962 μm²`，反而多 `37.771999999999935 μm²`。因此这个冻结空间不支持“逐乘法器非均匀精度优于强均匀调参”；它只否定该局部轴，不否定扩大结构与微架构后的联合设计命题。来源：`examples/comm_dsp_bench/experiments_m5/cmul_nonuniform_parallel_v1_20261009/results.json`，SHA256 `b7297271830172486da9a04f7f36e3010aac667d2bedce03e6f305a8c5e66882`。

### CMUL 联合候选真实 v1 暴露表示瓶颈（2026-10-09）

当前 `da43` 中反馈/无反馈各 8 次真实 DeepSeek 调用均为 0 个合法候选、0 次综合。反馈组 8 次 provider 均成功，错误从顶层字段、节点字段、非法 op 和拓扑逐步推进到最后两次的公式不匹配；无反馈组 7 次成功、1 次 API 错误，7 个成功响应全部停在顶层字段错误。它只说明验证原因改变了修正轨迹，不能支持“反馈找到更好实现”。根因是 v1 要模型重复输出固定 input/output/register 外壳；v2 改为系统生成外壳，模型只给内部算术 DAG、输出绑定和逐乘法精度。来源：反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_feedback_v1_20261009/results.json`（SHA256 `c02c049e53ae86b0b2eb985c4c642bffe933de8a72c112c329204aa9909bd899`）；无反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_no_feedback_v1_20261009/results.json`（SHA256 `710f0e6af71e36279cd7f24e6132db0d050959ba72e3fbdbf405bb67001e13ae`）。

### CMUL 算术 body 表示的真实 v2 结果（2026-10-09）

当前 `da43` 把固定外壳移出 LLM 输出后，反馈组合法率从 0/8 升到 6/8（4 次真实映射、2 次 cache 命中），无反馈组从 0/8 升到 2/8（2 次真实映射）。但 8 个合格响应全部仍是四乘法、零截位的精确实现；反馈组面积均为 `8781.724 μm²`，无反馈最好为 `8776.936 μm²`。所以 v2 证明简化表示能显著提高可执行候选率，却没有产生满足约束的近似搜索结果，也不支持反馈得到更优硬件。进一步诊断发现 prior feedback 没有携带“哪个结构/截位产生了这些指标”，且 prompt 没明确质量约束下最小面积目标；v3 将补候选摘要、优化目标和内部/端口命名隔离。来源：反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_feedback_v2_20261009/results.json`（SHA256 `3e06e4889d4e13ea7a944eb3370377f67c62b1a7209b7f1e3138c8dd67b59ff4`）；无反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_no_feedback_v2_20261009/results.json`（SHA256 `5af5ee477f30c0a5e42731a0de46ad722bf72898b2b65e9039221f4803f0e2d3`）。

### CMUL v3 首次得到 LLM 约束内近似实现（2026-10-09）

当前 `da43` 的 v3 把候选结构/精度摘要与实测值一同回送，并明确“SQNR≥140 dB 下最小面积”。标记为反馈的这一批中，前 5 次有效调用依次选择零截位、全乘法截 2/4/6 bit、再重复 6 bit；对应 SQNR `999.0/169.31465971748335/157.60227215487066/145.71630489408446 dB`，严格面积从 `8781.724` 降到 `8432.2 μm²`。这首次证明 LLM 能从公式与反馈轨迹给出满足冻结误差门的近似实现，但仍弱于强 Gauss 均匀基线 `6973.1900000000005 μm²`。无反馈批前 5 次有效调用全部保持零截位、面积 `8781.724 μm²`；但反馈批在近似点出现前没有非空失败原因，两批差异不能归因于“验证失败原因”，H3 仍未成立。第 6–8 次两组都因 prompt 保留全部历史而触发 client 8000-token 保守上限；这是运行层问题，不是候选失败，v4 改为只回送最近 3 次并保持完整档案。来源：反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_feedback_v3_20261009/results.json`（SHA256 `46294dfee5c4e35351b9276090e423e24b64cc5242020680ea870e7d883b3e46`）；无反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_no_feedback_v3_20261009/results.json`（SHA256 `04dea010b685dd1730cdbfd3f31773d97901716d18c6c13cfd32deb0c9fd5022`）。

### 联合框架扩到 FIR（2026-10-09）

当前 `da43` 的第二个算子适配已接通 direct/polyphase/symmetric-preadd 三种 FIR 结构、逐常数乘法系数精度、解析 MSE/SQNR 与近似 RTL；解析结果和既有独立 FIR 精度模型逐字段对照。冻结 16 级 accepted-sample 延迟、R=2 相位/暖机和弹性输出外壳，不支持的资源共享/额外流水会明确拒绝。当前通用 IR 尚无原生 constant/delay，适配器暂以 virtual inputs 表示并在 lower 时固化，不能把这当作最终通用表示。联合框架定向测试共 `66 passed`；`joint_fir.py` SHA256 `eea7aa03db10e801285a571c5fa7fd5f9f3ea2cc243f311bdd53fb11ea04cc79`。

### CMUL v4 完整 8+8 联合搜索（2026-10-09）

当前 `da43` 的最近 3 次历史窗口使两组 8 次 provider 调用全部完成。反馈组最好可行点为四乘法统一 RNE 截 6 bit：SQNR `145.71630489408446 dB`、面积 `8432.2 μm²`；无反馈组最好点为非均匀 RNE `(2,6,2,6)`：SQNR `148.72028783896465 dB`、面积 `8505.882000000001 μm²`。两组都证明 LLM 会在 140 dB 门内提出近似实现；本批反馈组面积低 `73.6820000000007 μm²`，但其最佳点发生在任何失败之前，不能归因于失败原因。发生质量失败后，反馈组又经历一次质量失败和一次格式失败，最后回到重复的截 4 点；无反馈组则连续恢复出两个可行非均匀点。因此这个单批次仍不支持 H3 的因果主张，也都没有击败强 Gauss 均匀基线 `6973.1900000000005 μm²`。来源：反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_feedback_v4_20261009/results.json`（SHA256 `fe5aad52ab177dea29e9dd9f671abbafffe954a690af891603a2722f973cb92a`）；无反馈 `examples/comm_dsp_bench/experiments_m5/joint_cmul_no_feedback_v4_20261009/results.json`（SHA256 `4c85757ee6ba12e3428db42170c082f4ea24fd6c8871cdaa8383fc0d572b14b3`）。

### 实验反复失败的根因诊断与主线重构（2026-10-09）

回看 M4/M5 全部 pilot 后的判断：失败主要来自实验设计与命题错位，不是 LLM 无用。① 多数 LLM 对照放在 20–86 点可穷举的冻结空间里，枚举、typed 搜索或随机方法按构造就会赢，这类实验无法支持命题 1–3，应停止。② 表示错位：命题 2 是“LLM 发现变换”，系统却让 LLM 直接输出最终设计（候选 id、参数、整图或自由 RTL），结果不是重复就是非法；应改为让 LLM 提出带适用条件的改写，由工具应用改写、解析精度优化器在图内细化。③ 任务缺少余量：Gauss 复乘、对称预加、LUT/CORDIC 都是教科书结构，专家基线已经包含，没有可发现的空间；需要先做“余量 oracle”，由专家手工联合设计，证明在强分阶段方法之外确实有收益。④ 微架构（流水、迭代复用）尚未进入 IR，没有 STA，大组合网表还会让 ABC 超时，所以命题 1 中的“微架构”目前无法检验。⑤ 统计功效不足：单批 8 次调用、3 seed、每次约 0.01 美元，反馈消融的单批负结果（cmul）只能算噪声。旧的联合 vs 分阶段正式结果 HV 差为 0.008，95% CI [-0.020, 0.042]，n=5；它是功效不足，而不是证伪。
文献（详见当次调研）：最接近的工作是 A2H-MAS（MATLAB 通信链 → HLS 加位宽 DSE）、AlphaEvolve、ASPEN/EggMind（LLM 引导 e-graph 等价改写）、Sekanina 组 PPSN'26（LLM 近似乘法器）、EvolVE/COEVO/Alpha-RTL（RTL 层 PPA 进化）。检索中没有发现“公式起点 + 等价/近似统一改写 + 系统级误差预算 + 可靠误差裁决 + 失败原因反馈消融”的组合。建议主线是：命题 2 作为方法核心，命题 1 作为动机和主结果，命题 3 作为消融。

### 联合 IR v2 原生状态与常量（2026-10-09）

当前 `da43` 的通用候选已原生支持定点 `constant` 和按 accepted transaction 推进的 `delay`，参数与 schema 版本均进入语义哈希；旧 v1 候选只读兼容且固定哈希不变。FIR 外部输入现在只有真实 `x`，15 级历史和系数都由原生节点表达，系数截位也归属 constant，不再使用 virtual inputs。direct/polyphase/symmetric-preadd 的解析误差和 RTL 路径保持通过；联合 IR、搜索状态机、CMUL、FIR 及冻结 FIR 模型回归为 `98 passed in 1.32s`。这关闭了此前记录的表示边界，但还不是 FIR 的真实 LLM 搜索结论。来源代码 SHA256：`joint_design_ir.py=b75270566c3d432f11a9b1a32e4cb970b5167da12a1cbee10178b73bfa5b824c`，`joint_fir.py=8f2b921b3e9c21224d84736f913f32188623083ad63d642618f5e64e4f6bf2cc`。

### 联合框架扩到第三个算子 sin/cos（2026-10-09）

当前 `da43` 的 `joint_sincos.py` 已把 quarter-wave LUT/迭代 CORDIC、相位精度和微架构放进同一候选，结构验证与 65536 个相位码的确定性 SQNR 评价分离；未支持的流水结构明确拒绝。定向测试 14 项通过；这是第三个算子适配能力，不是实际 LLM 搜索或面积结论。来源代码 SHA256 `5647a3cb32bdc492afed4eeda5a5498c802922f8bae7b417f4978c6006a651ef`。

### FIR 联合搜索真实配对结果（2026-10-09）

当前 `da43` 修正 DeepSeek 输出 token 上限后，反馈/无反馈两组各 8 次真实调用均全部完成；每组 3 个合格精确候选、5 个结构或解析拒绝、3 次严格 Nangate45 映射。反馈组最好是直接型 `12875.198 μm²`，无反馈组重构出对称预加 `8787.310000000001 μm²`。全部合格点均为零截位、`sqnr_db=999.0`，所以它证明第二个算子的真实联合闭环已跑通，却没有得到 FIR 近似点，也不支持“失败原因反馈更好”。单批结果不能作统计结论。来源：反馈 `examples/comm_dsp_bench/experiments_m5/joint_fir_feedback_v2_20261009/results.json`（SHA256 `41761bb9b4e7e41d59f674a17627e5a63144226f17d3b4376c3bd6d67b497b9a`，manifest `737796ba9c7a67a0095f02b55c326f56e950bf48bcd424a998b95aad1f96d9a8`）；无反馈 `examples/comm_dsp_bench/experiments_m5/joint_fir_no_feedback_v2_20261009/results.json`（SHA256 `030aed1bf11d2ba0b4fe8410b9e51bff7d36e276190d81104794bcbb0e4f817c`，manifest `fdc879917a3f77ab3bbcec1b2dc5fa24368db7bf4514e4b75a7e929dfdb7cc94`）。联合回归 `123 passed in 1.55s`。

### sin/cos 失败原因反馈的单批机制证据（2026-10-09）

当前 `da43` 的两组第一次都因 LUT 算法对象含多余字段而被拒。带验证原因组随后 7/7 修正为合格候选并完成严格映射，跨越 LUT 和迭代 CORDIC；最好点是 12 级资源复用 CORDIC，全 65536 相位码最差分量 SQNR `70.91879659925395 dB`、最大误差 `18.609095504759807 LSB`、II=14、面积 `1827.6860000000001 μm²`。无原因组 8/8 都停在结构错误，0 次数值评价、0 次综合。这是“验证原因能把重复非法提案变成可执行候选”的单批机制证据，但 provider 无可复现 seed，不能当统计结论；CORDIC/LUT 又是已给算法族，因此也不是新算法发现或相对强基线胜利。来源：反馈 `examples/comm_dsp_bench/experiments_m5/joint_sincos_feedback_v1_20261009/results.json`（SHA256 `927ed67dc06b0a0cc7c99e19b9472c7df4db6c9814ba44dbe5bc0d40b4f00f6e`，manifest `f46f55862bda14fcd0568b2aa1e9b3e1c777c79364f9d1d70d307ddd26bbd6f2`）；无反馈 `examples/comm_dsp_bench/experiments_m5/joint_sincos_no_feedback_v1_20261009/results.json`（SHA256 `7849c89264c2b27df86149c47aa0e7bb8dcfb97eead5ec7ac316857f50398bf5`，manifest `f0134ce049d5bc624597157058bd6d036b5c9921428c4742d0acbc06f0830ca6`）。全联合回归 `130 passed in 1.60s`。
