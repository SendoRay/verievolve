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

### 转向大链与通用框架 dspgraph（2026-10-09）

单算子小空间（20–86 点）里，联合设计没有跨级收益，LLM 也赢不了穷举，所以三个命题一直拿不到正证据。实验对象因此改为多级接收链：NCO 混频 → CIC → 若干 FIR/半带抽取，R=16–96。按用户要求，系统重构成通用框架 `examples/comm_dsp_bench/dspgraph/`（da43 工作区）：
- **积木只登记一次**。每个积木声明参数 schema、逐位模型、理想模型、可选 LTI 频响、代价和 RTL；参数带角色标签 structure/precision/micro。
- **链是数据**，即规格加积木列表计划；搜索、反馈、归因、RTL 拼接、综合都不针对具体链写代码。
- **分阶段与联合只差在按角色分阶段优化还是同时优化**，命题 1 因此在任何链上都有统一定义。分阶段基线依次做：理想算术下按实现损失预算选结构 → 精度坐标下降 → 逐块选最小代价的微架构，剩余预算继续细化次优结构。
- **SNR 门槛 = 理想接收机 ADC 上限 − 允许的实现损失（1.5–2.5 dB）**。原先用固定门槛时，阻塞音强 40 dB 让任何实现都不可行。
- **工程检查**：两种计划的 NCO、CIC、折叠/并行 FIR 逐块 RTL 与整链 RTL 均与逐位模型零失配；CIC 与仓库原模型逐位一致（`tests/test_dspgraph.py` 共 7 项）。
- **LLM 提议器的提示词由积木库自动生成**。反馈分三档：标量、指标、经验证原因（来自确定性重算的误差来源占比、结构不足还是系数量化、饱和位置）。实测每次调用约 3 秒、0.0008 美元。


## 2026-10-09：文献调研——LLM 写硬件程序的 harness 什么最有效

一次性写完整程序、只看最终指标，是文献里最弱的设置。证据最强的三类改动是：让模型能运行、测试并查看
中间信号的多轮反馈（AutoChip 约 65%→89%，KernelBench 中 R1 在 10 轮反馈后 fast_1 从 36% 提到 72%）；
大量便宜采样加选择和定向修复的进化搜索（REvolution 用 DeepSeek-V3 在 RTLLM 上 64%→88%）；以及先生成
结构 IR、再分模块实现。对不熟悉的 DSL，PyHDL-Eval 中 GPT-4 Turbo 写 Verilog 通过 72%，写 Python 嵌入式
HDL 只有 30–62%；补示例、检索文档和编译反馈能明显缩小差距。完整文法约束本身几乎不提高语义正确率
（GeoQuery 60.7%→61.1%）。

对本项目的启示：先做单级可运行的检查工具，在生成过程中报告位宽和速率域错误并提供中间信号的 SNR，
再进入多轮修复和进化搜索。

## 2026-10-09：转向大链与“LLM 写构造程序”架构；首轮对照

架构说明见 [chengzhy/ARCHITECTURE.md](chengzhy/ARCHITECTURE.md)。代码在 da43 工作区 `examples/comm_dsp_bench/dspgraph/`。规格只给数学公式和指标；LLM 用约 20 个与算子无关的定点原语写 `build(g, spec)` 程序，系统负责编译成 Verilog、逐位仿真、裁判打分。裁判只看输入输出，在 3 个强阻塞音下要求 SNR ≥ 理想接收机 − 1.5~2.5 dB。所有变换都发生在 LLM 写的程序里。工程检查：多相、分时复用、CIC 回绕、75 位宽设计的 RTL 与整数语义逐位零失配。

试点结论（DeepSeek，每组 80 次调用，2 规格 × 2 种子）：
- 每次一次性写完整新程序，成功率很低：旧 harness 9/80 达标，但最好结果相对“照公式直写”起点面积降了 79%（r16n）和 52%（r32w）。
- 加编译修复、自动截位、中间信号探针后反而只有 1/80；换 v4-pro 也是 1/80。不达标的程序大多差 10 dB 以上，属于结构写错。
- 开启思考模式时，2 万 token 都花在推理上，没有输出代码。
- 失败的最大单一原因是 62 位上限，这是 int64 实现带来的假约束，现已改为任意精度、上限 128 位。
- 成功的轨迹都是在已达标程序上做小改动。

据此改用 OpenEvolve 做 diff 式进化：从达标的直写程序出发，种群加选择（与 AlphaEvolve、REvolution 一致）。NVIDIA 的 arXiv:2609.28908 研究的是验证调试任务的 harness 自动进化，与本项目问题不同，但印证了两点：harness 对结果影响大；关键约束应写进代码执行，而不是靠提示词。

### 2026-10-10：三命题首批结果（dspgraph 多级接收链）

**命题 1（联合 vs 按角色强分阶段）**：专家模板空间，6 个开发规格 × 5 种子，每次 400 次评价，共 29 对。联合/分阶段面积几何均值比 0.90，联合在 11/29 对中更好，Wilcoxon p=0.95，总体不显著。差异按规格分化：窄带规格上分阶段的中位数更小（r16n 59k vs 72k；r64n 39k vs 53k）；宽带规格上分阶段不稳定，联合明显更好（r32w 中位 563k vs 271k；r64w 496k vs 121k）。结论只能写成“联合在难规格上更稳”，不能写成“联合普遍更优”。产物：`experiments_dspgraph/p1_template_dev_v1_20261009/results.json`。

**命题 2（LLM 从公式出发找变换）**：OpenEvolve diff 进化，从“照公式直写”起点出发，200 次迭代，单种子，3 个规格跑完。代理面积相对起点降 86–93%，RTL 对拍全部零失配。真实 Nangate45 综合：
- r16n：LLM 82.1k μm²，专家最好 33.3k–36.5k（LLM 约差 2.3 倍）；
- r16w：LLM 114.5k，专家 102.3k–112.5k（接近）；
- r32w：LLM 的设计在输入速率上做长 FIR，综合 50 分钟超时；专家 118k–135k。

LLM 自己找到的变换有：四分之一波查表镜像、对称预加、多级抽取、缩短位宽、乘法器分时复用。没找到的有：CIC、半带、多相。另外 3 个规格因 DeepSeek 余额耗尽（402）中断，已标 INCOMPLETE。

**命题 3（反馈消融）**：未完成，余额耗尽，目录标 ABORTED。

**代理面积与真实面积**：在同一规格内排序一致，但代理把全速率常数乘 FIR 高估了 2–3 倍，最终结论必须以真实综合为准。

## 2026-10-10：中期报告写法（讨论稿）

参照上科大中期报告（31 页、13 图 1 表）的结构：一 背景/现状/动机，二 阶段性成果（核心设计、框架实现、实验），三 进展与问题，四 计划，五 成果。图要多，目标约 15 张图表。两张主图最关键：
- 通信收发链路的算子图，框出本课题主实验 DDC（NCO→混频→CIC→半带→补偿 FIR→抽取），并标出前期做过的单算子；
- 系统架构图，讲清四件事：LLM 输入（公式、指标、原语说明、当前最好程序与反馈），LLM 输出（用原语写的 `build(g, spec)` 程序），数学变换发生在 LLM 改程序这一步，系统固定部分（编译器、裁判、诊断、综合）。
问题部分如实写：LLM 没有找到 CIC、半带和多相；r16n 真实面积比专家差约 2.3 倍；命题 2 只有单种子和 3 个规格；命题 3 未完成。
- 参考稿 main.pdf（未发表，**不能引用或对比**，只借鉴思路）：公式 → e-graph 等价重写 → 位宽优化 → 时序调度 → RTL，在 5G NR 接收链上演示；LLM 只提议重写规则，验证等价后才采用。可借鉴的思路都要以公开文献为出处（egg、Coward'22、FloPoCo、区间算术）：区间算术自动定位宽、时序感知的流水插入、等价变换与近似变换分开处理、近似方法的 Pareto 图、按级汇总表、覆盖整条接收链。图 1 和图 6 可参照它的版式。
- 中期初稿已写：`thesis/midterm/MIDTERM_REPORT_v0.md`（17 图 6 表，标注每张图的数据状态）。写作方式：以正收益为标题——相对直写起点降 86–93%；r16 宽带与专家分阶段只差 1.9%；宽带规格联合比分阶段的中位面积小 52–76%。差距写成改进方向，数据不删、不改阈值。已请实验会话 multistage-ddc-receiver-chain 补：6 规格 × 3 种子、进化曲线、演化路径、同预算 LLM vs 非 LLM、从专家起点继续进化、领域知识增强。
- 实验方复核（2026-10-10）：代理面积严重高估查找表。structonly 在 r16n 上代理面积降 46%，真实综合只降 2.2%，所以相对直写降 86–96% 只能当搜索过程指标，结论以真实综合为准。搜索把 SNR 裕量压到 0.2–0.3 dB，LLM 和专家设计在留出场景上各有 1 个不达标（差 0.4–0.5 dB），目前只能写“在搜索场景上达标”。LLM 从专家起点出发基本没有改进。命题 3 初步：加诊断档的面积几何均值 0.109，只给分数档 0.131，6 对中 5 对更好，p≈0.22。

### 2026-10-10：裁判 v1 的漏洞与代理面积偏差，三命题需重跑

留出复核发现两个评价器问题，v1 下的命题 1/2/3 数字因此都不能作最终证据。
- **规格漏洞**：裁判 v1 每个场景只有 3 个阻塞音，两个搜索场景合计 6 个频点，搜索只在这些频点上做抑制。把全部最优设计放到留出场景上：命题 1 的 59 个设计只有 10 个达标，最差 −34.5 dB；命题 2 从直写起点 6 个里 1 个达标。产物：`experiments_dspgraph/holdout_check_v1_20261010.json`。
- **代理面积高估查找表**：“只接受结构性改动”时，LLM 在 r16n 上把四分之一波表换成粗表加移位加线性插值，代理面积 −46%，真实 Nangate45 综合只有 −2.2%（33,280 → 32,559 μm²）。变换是真的，RTL 零失配，但收益主要来自定价偏差。
- **已修**：裁判 v2 让阻塞音覆盖全部混叠频带（每带 2 个随机频点，总功率不变），直写起点的搜索裕量与留出裕量一致（如 1.78 对 1.74 dB）。代理单价改用真实综合校准。
- **v1 下仍值得记的观察**（待 v2 复核）：给 LLM 参数化的专家模板时，它几乎只改参数，结构改动很少；在 harness 里强制“只改参数不接受”后才出现结构变换。命题 3 的 6 对里“验证过的原因”有 5 对更好，不显著。
- **教训**：最优设计必须同时在留出场景上复核；面积结论只能用真实综合；搜索会利用评价器的任何漏洞，对 LLM 和传统搜索都一样。
- **裁判 v1 有漏洞（2026-10-10）**：每个场景只有 3 个阻塞音，两个搜索场景合计只检验 6 个频点。参数搜索和 LLM 都学会了只在这几个频点上抑制。留出复核结果：分阶段 7/30 达标、联合 3/29、LLM 1/6，最差差 34 dB。命题 1/2/3 的 v1 面积数字全部作废。裁判 v2 让阻塞音覆盖全部混叠带（12–57 个随机频点，总功率不变），直写起点的搜索裕量与留出裕量一致（1.78/1.74 dB）。中期报告把这件事写成评价器设计上的一项发现（2.3.3），三个问题都在 v2 下重跑。仍然成立的结论：逐位对拍零失配、一次性生成 9/80 和 1/80、LLM 自主写出的变换（定性）。
- 参考 CktFormalizer/CKTLean（港大，Lean 4 嵌入式带类型 HDL + Agent）：位宽写进类型，编译期就拦截错误；流程覆盖生成、等价证明、综合、OpenROAD 布局布线和 DRC/LVS，PPA 闭环中失败就回滚并保留最好版本。他们的基线是同模型、同预算直接写 Verilog，消融是固定 Agent、只换底层基础设施。可以借鉴：同预算直接写 Verilog 的基线；通过率漏斗表（合法→逐位一致→搜索达标→留出达标→综合→布局布线）；OpenROAD 补时序；对等价变换做形式化等价检查。区别在于，他们证明的是对自然语言规格的位级等价，本课题允许近似变换，按链级 SNR 判定。
- **主对照更换（2026-10-10，用户同意）**：专家模板改作参考上限，不再当主对手。主表改为：B1 LLM 直接写 Verilog（同模型、同预算、同反馈），B2 开源 HLS 综合直写 C，B3 非 LLM 随机程序变异（评价次数相同），对比本方法。指标为搜索和留出场景的达标率、真实综合面积、达到专家水平的比例。附加消融 K：提示词中加入多速率结构知识。方案已发给实验会话。
- **v2 初步结果（2026-10-10）**：用 52 个设计的真实综合校准代价模型，留出集 Spearman 从 0.57 升到 0.987，误差中位 2.3%；旧模型把查找表高估约 12 倍。同为 120 次评价时，本方法最优面积为直写起点的 0.14–0.37，随机数值变异为 0.77–1.00。留出复核和真实综合待做。B2 HLS 暂缓：Bambu 只提供 x86_64 版本，本机是 arm64。余额 ¥7.25：够跑 K，B1 要充值约 ¥25–30。

### 2026-10-10：修复评价器后（裁判 v2 + 面积校准）的三命题结果

评价器修订：阻塞音覆盖全部混叠频带；代理面积单价用 52 个设计的真实综合校准（留出 Spearman 0.57 → 0.987，误差中位 2.3%）。所有最优设计报告搜索裕量、留出裕量和真实面积（Nangate45，快速 ABC），汇总在 da43 `experiments_dspgraph/main_table_v2_20261010.json`。

- **命题 2（本方法 M：OpenEvolve diff 进化，120 次迭代，单种子）**
  - 6 个规格的校准面积相对“照公式直写”几何均值 0.131；真实面积降 71.5–89.0%（5 个规格已出真实面积）。
  - 同预算非 LLM 程序搜索：数值变异 0.871、原语结构变异 0.884。
  - 但只达到专家模板最优（R）的 19–84%（R/M），没有超过教科书结构；留出场景 M 4/6 达标，R 也是 4/6。
  - RTL 对拍全部零失配。
- **命题 1**：v2 下结论反转，同 400 次评价时强分阶段显著优于联合（几何均值比 1.22，6/30，p=0.0004）。只限于本模板空间和简单进化的联合搜索。
- **命题 3**：verified 0.131、metrics 0.152、scalar 0.251；verified 对 scalar 6 对中 5 对更好，方向支持反馈有用，但样本少、不显著。
- **K（多速率知识写进提示）**：单种子，没看到收益，LLM 仍不采用 CIC。
- **工程**：超长加法需要分组生成，否则 Yosys 递归过深。

**下一步**：补种子（需充值），B1 LLM 直接写 Verilog 对照；B2（HLS）在 arm64 上不可行。
- **v2 主结果（2026-10-10，单种子，Nangate45 快速 ABC）**：本方法真实面积相对直写起点降 71.5%–89.0%（5 个规格；r64w 起点在补测）。同为 120 次评价，校准面积比的几何均值：本方法 0.131，随机数值变异 0.871，随机结构变异 0.884。留出场景达标：本方法 4/6，专家模板 4/6。本方法达到专家面积的 19%–84%。命题 2（v2）：按角色分阶段显著优于联合，30 对中 24 对，p=0.0004，与 v1 结论相反。命题 3：加诊断比只给分数面积再减 48%，5/6 对，p≈0.11。领域知识增强单种子未见收益，但 LLM 开始用多相分解。余额约 ¥3。
- 祖先链：r32w 的路径为 多相（未达标）→ 两级抽取 0.243 → 四分之一波 + 8×2×2 0.138 → 缩短字长 0.129；r64n 的路径为 相位截短 + 级联抽取 0.184 → 0.114 → 0.107。面积主要靠结构变换降下来，进化可以经过不达标的中间设计。r64w 直写起点真实面积 2,559,706 μm²，本方法降 88.4%。
- B1 已就绪：直写 Verilog 起点与 naive.py 逐位等价，起点真实面积 661,986 μm²（通用乘法器 + ROM，比原语版的 425,644 大），因此要按各自起点报相对降幅，同时报绝对面积。约 ¥20，需要 8–12 小时。命题 2 的留出规格复验在后台跑。
- **B1（LLM 直接写 Verilog）已就绪，未运行**：
  - 起点 `seeds/naive_verilog.v` 与直写程序逐位一致（完整场景 1376/1376）。
  - 允许用 `@py`/`@hex` 做离线计算，与本方法用 scipy 设计系数对等。
  - 面积用真实快速映射：起点 661,986 μm²，本方法的直写起点为 425,644 μm²，因此 B1 按自身起点报降幅。
  - 等充值（约 ¥20）。
- **调试教训**：iverilog 的 `@(*)` 对数组元素不敏感；Verilog 饱和常数不能写成 `-22'sd2097152`，要用十六进制位模式。
- **命题 1 留出规格复验**：在 6 个从未用过的规格上，结论与开发规格一致。分阶段 vs 联合几何均值比 1.26，联合只在 7/30 对更好，p=0.0006。结论限定为“本模板空间内，同预算下按角色分阶段优于简单进化的联合搜索”。产物：`experiments_dspgraph/analysis_p1_heldout_v2_20261010.json`。
- 命题 2 留出集复验结论复现：联合/分阶段几何均值 1.26，分阶段在 23/30 对更优，p=0.0006（开发集为 1.22，p=0.0004）。结论只限于本模板空间和简单进化的联合搜索。
- 命题 2 留出集复验结论复现：联合/分阶段几何均值 1.26，分阶段在 23/30 对更优，p=0.0006（开发集为 1.22，p=0.0004）。结论只限于本模板空间和简单进化的联合搜索。

## 2026-10-11：主线重定与数据集/实验清单

用户指出原三个问题不成主线。新主线：通信链路的最优硬件来自跨算子、允许近似的数学变换，规则编译器和 LLM 写 RTL 都找不到。三个挑战对应三个设计：
1. **表示**：LLM 改的是原语构造程序，不是公式，也不是 Verilog。数学变换在这一层是小幅程序修改。用 B1 直接写 Verilog 来验证。
2. **整链最优**：单算子最优不等于整链最优，误差预算应在级间重新分配。新实验 E2.1：逐级最优再拼接，对比整链优化。
3. **搜索效率**：进化式 diff + 经验证的诊断 + 分工（LLM 定结构，确定性工具定位宽和复用）。原“联合 vs 分阶段”的结果变成分工的依据。

数据集与实验清单见 `thesis/midterm/DATASET_AND_EXPERIMENTS.md`：梳理了 3G/4G/5G/Wi-Fi/SDR 的链路和 16 类算子；比特级处理（CRC、加扰、交织）必须逐位正确，不在范围内。数据集分三层：单算子 106 个实例（已有）；链 A DDC（已完成）、链 B DUC、链 C OFDM 接收内环；扩展层（同步环、Rake、MIMO）。API 预算：第一批约 ¥50，全部约 ¥115。
- 用户对数据集的三点修正（2026-10-11）：(1) 规格统一为三元组：数学公式 F + 指标 M + 允许空间 T。各类任务用各自领域的指标（SFDR、SNR、EVM/ACLR、NMSE、BER 损失），格式统一，裁判可通用。(2) 评价改为：质量作为约束（落在允许空间内），代价报告 PPA 三项并比较 Pareto 前沿（超体积、支配关系、固定约束下的单项指标）。目前只有面积，时序和功耗待补。(3) 链路从 3 条扩到 8 条：A 接收 DDC（已完成）、B 发射 DUC、C OFDM 发射、D OFDM 接收内环、E 突发同步前端、F 多相信道化器、G WCDMA Rake 支路、H 分数倍重采样。8 条全是前馈结构，共 54 个规格，约 2–3 周、¥200。
- **通用框架要求（2026-10-11，用户）**：不要一条链一条链地改系统，架构应能适配通信算子和链路。方案：同一段原语程序有两种解释，浮点解释是公式，定点解释是硬件。新增一条链只写一份约 30 行的规格文件（理想版程序、参数、接口、信号名、指标名、允许空间）。直写起点由理想版加区间分析自动生成；测试信号和指标做成库；门槛按理想成绩减允许损失自动算；提示词自动拼；专家参考改为可选，任何 Verilog 都能接到同一裁判；用 `scope` 自动切出每级子规格。需补：内插和按帧处理原语、数学级运算。新实验：接入成本、跨链迁移。重构约 3–5 天，FFT 按帧处理最不确定。
- 通用框架可行性评估（实验会话）：可行，约 6–8 个工作日，分四步：拆裁判并用链 A 回归 → 浮点解释、数学级运算库、自动生成起点 → 内插和 DUC → 按帧处理和 FFT。两处修正：参考 = 理想版作用在干净输入上，上限 = 理想版作用在带损伤输入上的得分；理想版要用数学级运算库写，每个运算带浮点语义和默认的直写定点展开。已通用的部分：原语、编译器、进化驱动、Verilog 评价通路。绑定 DDC 的部分：裁判、规格结构、提示词、编译器的输入输出接口。第二条链选 DUC。最大风险是直写 FFT 的规模：64 点约 1.6 万个常数乘法，无法做真实综合。

### 2026-10-11：逐级最优 vs 整链优化（E2.1/E2.2）与时序

规则在运行前冻结（da43 `experiments_dspgraph/e21_stagewise_v1_20261011/FROZEN_RULES.md`）：把系统允许的实现误差按平均（规则 A）或 7:3（规则 B）分给各算子，各算子按局部指标取最小代价，再拼成整链。面积为 Nangate45 快速 ABC 的真实面积。

- **窄带规格**：逐级设计能达标，但面积大。达标版对比，整链优化省面积 36%（r16n）、42%（r32n）、37%（r64n）；裕量拉平到约 0.1 dB 的只有 r16n 一个点，仍省 19%。r32n 按规则 A 原样拼接不达标（−0.53 dB）。
- **宽带规格**：三个规格上逐级设计都找不到达标解。局部指标严格时模板内无解；统一放宽到刚好有解时，整链已不达标（−0.6 到 −2.5 dB）。整链优化在同一空间里能找到达标解。这部分是规则外补充，报告需注明。
- **E2.2**：整链最优解的误差里，ADC 加结构的基线占 56–75%；实现误差里多数规格 NCO 占大头（7–36%），CIC 字长和系数量化多在 2% 以下，明显偏离平均分配。
- **代价**：整链优化把裕量压到接近 0，6 个最优解里有 2 个在留出场景上不达标；逐级达标版留出全部达标。
- **时序**（ABC stime，无线负载；要做缓冲和门尺寸调整，否则高扇出会让延迟虚高上百倍）：18 个设计的关键路径都在 2–3.5 ns（284–507 MHz），这条链上 PPA 基本由面积决定。本机没有 OpenSTA，也没有功耗工具。
- **E2.1 逐级最优 vs 整链（2026-10-11，裁判 v2，规则运行前冻结）**：逐级设计是把系统误差预算分给各误差源，每级按局部指标取最小代价。窄带 3 个规格上，逐级设计达标但面积更大，整链优化省 36%（r16n）、42%（r32n）、37%（r64n）；裕量拉平到约 0.1 dB 的只有 r16n，整链仍省 19%。宽带 3 个规格上，逐级设计在模板范围内无解，规则外放宽到有解时整链已不达标。注意：整链最优的裕量接近 0，有 2 个留出不达标；逐级达标版留出全部达标。E2.2：整链最优解的误差份额明显偏离平均分配，5/6 个规格里 NCO 占实现误差的大头（7%–36%），CIC 字长和系数量化几乎不占。
- **时序（ABC stime，sized，Nangate45，不含 clk-to-q 和建立时间）**：直写 284–354 MHz，本方法 382–507 MHz，专家 359–412 MHz。18 个设计的关键路径都在 2–3.5 ns，面积差近两个数量级，所以链 A 上的 PPA 比较基本由面积决定。本机没有 OpenSTA；功耗估算要 1–1.5 天，放到论文阶段。
- 中期报告 v1 已按新主线重写：`thesis/midterm/MIDTERM_REPORT_v1.md`（20 张图、18 张表；v0 保留）。结构为核心问题 → 三个挑战 → 三个设计（原语表示、整链规格与评价、进化 + 诊断 + 分工）→ 数据集 → 按挑战组织的实验。用户已充值并批准：B1、分工混合、补种子、留出规格、通用框架重构前三步已发给实验会话。
- **中期报告 v2（精简版，2026-10-11）**：`thesis/midterm/MIDTERM_REPORT_v2.md`，10 张图、8 张表、4 组公式（DDC 定义、优化问题与门槛、等价/近似变换、误差预算分配）。图由 `thesis/midterm/figures/make_data_figures.py` 和 `make_diagrams.py` 生成：通信链路图、系统架构图、方法细节图、动机柱状图、主结果、面积–时序散点、裕量散点、演化路径、逐级 vs 整链、进化曲线。
- **分工混合实验是负结果**：LLM 用 60 次迭代定结构，再做 60 次确定性位宽下降，结果不如 LLM 做满 120 次（混合/M 几何均值约 1.11，9 对中 3 对更好）。结论：与专家的差距是结构性的，不是位宽没调好。在 M 最优上追加位宽下降还能降 1%–13%，可作收尾步骤。设计三因此只保留“进化 + 诊断反馈”，不再主张分工。
- **通用框架第 1 步完成**（独立目录 `dspgen/`）：裁判拆成信号库、参考、指标库；链 A 的 12 个规格用 6 行理想版函数描述。三条回归全部通过：60 组门槛逐位相同；18 个设计重新打分完全相同；自动生成的直写起点与手写起点一致。B1 在跑，很慢（每次评价约 6 分钟，预计 12 小时以上）。
- **链 B（DUC）已接入通用框架（2026-10-12）**：规格文件有效代码 20 行，写规格约 2 分钟；另有约 15 分钟是一次性补齐的通用能力（内插原语、复数接口、上变频、带通指标、基带信号库、自动测试平台），后续链路可复用。自动生成的起点 3 个规格全部达标，RTL 零失配，链 A 回归仍全过。链 B 上的 M 运行中（约 ¥5）。种群前沿导出工具已就绪。A 组累计花费约 ¥15；B1 很慢，前 3 个规格还要 10 小时以上。

### 2026-10-12：反馈消融补满 4 个种子；通用框架接入链 B（DUC）

- **E3.2 反馈消融**（3 规格 × 4 种子，120 次迭代）：面积相对直写起点，只给分数 0.224、给指标数值 0.134、指标加诊断 0.137。
  - 指标对分数：11/12 对更好，p=0.001。
  - 诊断对指标：p=0.52，没有额外收益。
  - 结论改为：数值反馈显著有用，额外的诊断归因在本链上无增益。
- **E3.4 分工混合**（LLM 60 次 + 确定性位宽下降 60 次，对比 LLM 120 次）：负结果，几何均值比 1.11，只有 3/9 更好。与专家的差距是结构性的。位宽下降适合当收尾，能再降 1–13%。
- **通用框架 dspgen**（da43 `examples/comm_dsp_bench/dspgen/`）：
  - 链路 = Task 规格。规格由三部分组成：理想版程序（数学级运算，同时具备采样和音调域解析两种解释）、信号库名、容限。门槛和直写起点自动生成。
  - 链 A 回归三条断言全部通过：60 组场景逐位一致；18 个已有设计的成绩完全相同；自动生成的直写起点与手写版逐位等价。
- **链 B（DUC）接入**：规格文件 20 行（不含注释），约 2 分钟；另外一次性补齐通用能力约 15 分钟，包括内插、实/复接口、实带通指标、按接口生成测试平台。
  - 本方法 120 次迭代后，真实面积降 45–50%，RTL 零失配。
  - 留出场景 1/3 达标，仍是裕量压到接近 0 的问题。
- **反馈消融 4 种子（2026-10-12）**：只给分数 0.224，给指标数值 0.134，再加诊断 0.137。指标数值比只给分数面积降约 40%，11/12 对更好，p=0.001。诊断相对指标数值无差异（p=0.52）。报告改为“数值反馈显著，额外诊断无收益”。链 B 上 M 的真实面积降 45%–50%，RTL 零失配，留出 1/3 达标（另两个差约 0.2 dB）。链 B 还没有专家模板。
- “M 最优 + 位宽下降”的收尾数据：搜索裕量被压到 0.0003–0.036 dB，留出场景只有 4/9 达标（r64w 差 −1.57 dB）。结论：位宽下降必须配合安全裕量才能用。链 B 专家模板已建（补偿 FIR → 半带 → CIC 内插 → 1/4 波 NCO），宽精度手扫时在 l8、l16 上已经比 M 小；正式搜索需 4–5 小时。A5 安全裕量两条链都在跑。
- **E4.2 主表补到 3 种子**：18 个运行全部达标，降幅中位数 68.1%–92.3%，留出 13/18 达标（不达标集中在 r16n 和 r16w），达到专家面积中位数 20%–40%。**A5 链 A**：搜索要求裕量 ≥0.3 dB 后，r16n 和 r16w 的留出都转为达标（+0.57/+0.16 dB），未见面积代价（2 规格 × 1 种子，初步）。
- **B1 第一个规格（r16n）**：直接写 Verilog 降 77.6%（661,986→148,167 μm²），留出达标，没有做多级抽取。最优面积比 M 中位数大约 20%，比 M 最好种子大 3.4 倍；每次评价约 6 分钟，M 约 1–3 秒。只有 1 个规格，不能下结论。**A5 链 B**：l8、l16 留出转为达标；两条链共 4 个原本不达标的规格全部转为达标，面积变化 −25% 到 +14%，无一致方向。花费约 ¥65，余额 ¥39.3。
- **E4.2（主表补到 3 个种子）**：6 个规格上，真实面积相对直写起点降幅的中位数为 68–92%，达到专家水平的比例中位数为 0.20–0.40。留出场景 13/18 达标，不达标的集中在 r16n 和 r16w。
- **A5（搜索时要求 0.3 dB 安全裕量）**：两条链上共 4 个原本留出不达标的规格，全部转为达标；面积变化在 −25% 到 +14% 之间，没有一致的代价。每个规格只跑了 1 个种子，属初步结果。
- **“M 最优 + 位宽下降”**：下降把裕量压到约 0，留出只有 4/9 达标。因此收尾的位宽下降必须配合安全裕量。
- **B1（LLM 直接写 Verilog）首个规格 r16n**：相对自身起点降 77.6%，降到 148,167 μm²，留出达标，与 M 相当。“原语表示优于直接写 Verilog”暂无证据，等其余规格。B1 每次评价约 6 分钟，M 是秒级。
- **链 B 专家模板**（补偿 FIR → 半带 → CIC 内插 → 四分之一波 NCO）已建，宽精度手扫 3 个规格可达标；正式搜索在跑。
- **两层框架与验证方式讨论（2026-10-12，待用户与导师拍板）**：(1) “分阶段优于联合”和“分工混合是负结果”并不矛盾。错的是按固定预算切分、把结构提前冻结。建议设计：结构在外层由 LLM 持续探索；每个结构候选先做小预算的确定性位宽和复用调优，再参与比较；精度阶段发现结构不行时可以回退。(2) 近似变换不声称形式化证明误差，分层保证：RTL 与程序逐位一致；等价变换做形式化等价检查；线性部分的纹波和混叠由系数解析计算频响；量化噪声用解析模型加区间算术；系统指标靠全频带干扰仿真、留出场景和 0.3 dB 安全裕量。(3) 核心定位候选：LLM 的价值在于“不需要专家先写结构”，而不是“超过专家”。
- **立论逻辑复盘（2026-10-12）**：“允许近似变换”并非独有，Sekanina 组（PPSN'26）已用 LLM 进化近似乘法器并超过 EvoApproxLib，但误差只在单算子上度量。我们独有的是“系统级容差 + 跨算子分配误差预算”。如果最优解就在可检索的模板里，检索加参数搜索就够了；LLM 搜索必要的前提是“模板外存在更好的解”，这一点尚未证明。原语语言是设计选择，不是贡献（会被问为什么不用 HLS 的 ap_fixed）。建议支点：① 系统级容差的问题定义（式 7）；② 可信的系统级判定；③ 以检索模板为起点、LLM 做结构改写，对照“同模板 + 参数搜索”。决定性实验：E3.6(2) 从专家起点出发的两层搜索 vs 只做内层调优，另加非 2 的幂倍率规格。待用户确认是否换支点。
- **E3.6 两层搜索已启动**：协议冻结在 `e36_twolevel_v1_20261012/FROZEN_PROTOCOL.md`。每个达标候选最多做 5 次评价的内层调优。专家起点用 R03（裕量 ≥0.3 dB 中面积最小者，比 R 大 7%–71%），结果同时报相对 R03 和相对 R。另设“只做内层调优、无 LLM”的对照。预计 5–8 小时，约 ¥30，余额 ¥39。
- **题目与主线定稿（2026-10-12，用户）**：题目是“基于大语言模型的通信算法硬件设计自动化方法研究”。贡献写成三问三答，并串成一条线：Q1 LLM 在什么表示上设计 → 原语级可执行表示；Q2 LLM 的近似设计怎样才算可接受 → 系统级容差判定；Q3 怎样高效找到好设计、超过专家 → 两层进化搜索。前一个方法是后一个的前提；通用框架是横跨三者的能力。报告 v2 的 1.3 节、2.2–2.4 节和图 3 已按此改写。
- **E3.6(2) 结论（2026-10-12）：从专家模板出发时，LLM 只调参数、不改结构。**两层搜索 ÷ R 的几何均值 1.11，只有 r32w 更小（−7.3%）；相对只调位宽和复用为 0.951（5/6），但增益来自调抽头数等结构参数。6 个规格中 4 个代码结构不变，2 个各改 1 行。留出达标：两层 5/6，R 4/6。“LLM 超过专家”目前不成立。留出规格上 M 6/6 达标，降幅 40.5%–92.5%。链 B 的 R 为 32k/65k/46k，M 达到专家的 59%/33%/20%；链 B 上分阶段 vs 联合不显著，命题只限链 A。报告问题三已收回“超过专家”的表述。

### 2026-10-12：两层搜索（E3.6，从专家起点）与留出规格、链 B 专家参考

- **E3.6 实验 (2)**：外层 LLM 改写，内层确定性位宽/复用调优，每个候选最多 5 次评价，搜索裕量 ≥ 0.3 dB。从 R03（≥0.3 dB 裕量的专家最优）出发：
  - 相对 R：真实面积几何均值 1.11，只有 r32w 一个规格面积更小（−7.3%）。
  - 相对“只调优”：0.95，5/6 更小。
  - 留出达标：两层 5/6，R 4/6，只调优 3/6。
  - LLM 的最终程序结构几乎没变（0–2 行），收益来自调模板里的抽头数等结构参数。拿到参数化模板时，LLM 实际上是参数优化器，没有产生模板外的新结构。
- **E4.3（6 个留出规格上的 M）**：全部找到达标设计，真实面积降 40–93%；达到专家水平的比例 0.14–0.26；留出场景 4/6 达标（无安全裕量）。
- **链 B 专家参考 R**：达到专家水平的比例，l4 为 0.59，l8 为 0.33，l16 为 0.20。链 B 上分阶段与联合对比，联合 5/8 更好，与链 A 方向相反（样本少），命题 1 结论限定在链 A。
- **口径调整（2026-10-12，用户）**：“专家模板”是 Claude 写的，不再称为人类专家，而是归入 LLM 方法本身（架构师模式：LLM 读规格、写参数化结构，系统搜参数并做系统级判定）。唯一的人类对照是接入开源 Ettus USRP 的 ddc_chain.v，走 B1 的 Verilog 评价通路。前提条件：必须证明 LLM 只看规格（提示词不出现 CIC/半带）就能独立写出这类结构，否则不能把模板算作自动化产出。已派 H1（USRP 基线）和 A1（架构师模式独立复现）。
- **更正（用户）**：不设单独的“架构师模式”，而是并入 VeriEvolve 主流程。初始化时，LLM 只看规格生成 K 个参数化结构程序，和直写起点一起组成初始种群；外层同时用 diff 和整程序重写；内层在候选自己声明的参数范围内做确定性搜索（含抽头数），取代原来的 tune。已派实验会话在 dspgen/ 中实现，并做链 A 正式运行。报告 2.4 节已同步改写。
- **H1 开源 USRP DDC（EttusResearch/fpga@287ad57）**：在 12 个规格上全部不达标（搜索裕量 −8.9 到 −70 dB）。原因是固定的 4 阶 CIC 加两级半带抑制不了全混叠带的强阻塞。去掉阻塞音后，R≥24 的规格正常；R=16 的 3 个规格无有效输出，原因待查，可能是接法问题。结论：通用固定结构不适用，需要按规格定制；面积不可比。**统一系统**已在 dspgen/ 实现并冻结协议：K=4 个结构生成，diff 与整程序重写按 3:1 混用，内层在候选声明的 SPACE 内做坐标搜索（≤8 次评价）。v4-pro 开思考模式会把 token 耗尽而不出代码，改用非思考模式并要求先写分析。余额 ¥194。

- **H1 R=16 异常已查清（2026-10-12）**：USRP 本身工作正常，问题出在评测对齐。叠加检验各级误差约 1e-3，系统线性；多音逐音增益起伏 0.12 dB，残差 −72 dB，相位严格线性。根因是裁判只搜索 d≥0 的时延（从首个有效输出起算），而 USRP 的 out_valid 要等流水线灌满才拉高，R=16 时等效时延约为 −3 个输入样点，落在搜索范围外。输出前补 8 个零（只平移时间原点）后 SNR 为 46.8 dB。H1 已按此口径重跑（v3）。教训：接入外部设计时，要先检查"首个有效输出"的时间约定。

## 2026-10-12 晚：统一系统、H1/H1b、E3.6 实验 1、B1 收尾

- **统一系统 v1**（链 A 的 6 个开发规格，种子 0，花费约 ¥33）
  - 结构生成：LLM 只看规格，6 个规格各生成 4 个方案。构造通过 15/24（r64n 为 0/4），初始达标 0/24。
  - 进化 120 代后，6/6 搜索达标，留出 6/6 达标（裕量 0.66–1.28 dB），RTL 零失配，关键路径 2.3–2.8 ns。
  - 面积不行：真实面积 27–53 万 μm²，相对直写起点降 35–82%，是 M 中位数的 2.1 倍（几何均值），R/统一 中位数为 0.11。
  - 最优设计来源：3 个来自结构生成方案，2 个来自直写起点，1 个无法追溯。
  - 结论：从规格直接生成结构这条路，目前在"稳"（留出全过）上有优势，在"省"上明显落后于 M 和专家模板。
- **E3.6 实验 1**（两层搜索，从直写起点出发，12 个运行）
  - 留出达标 11/12，好于 M。
  - 面积是 M 同种子的 1.46 倍（几何均值），只有 5/12 更小，p=0.13，差异不显著。
  - 两层搜索的主要收益是稳健性（同时带 0.3 dB 安全裕量），不是面积。
- **B1**（LLM 直接写 Verilog）
  - 有效结果：r16n 降 78%，r16w 降 60%，r64n 降 65%，留出都达标，但面积是 M 的 1.2–5.1 倍。r32n 只有起点达标。
  - r32w、r64w 的直写起点综合超过 900 s 被判无效，种群中没有达标程序。
  - 直接写 Verilog 慢，且整体面积更差，支持"原语表示"这一层。
- **H1b**（USRP 结构不变，用线性规划重设计半带系数并扫描 CIC 阶数 3–8）：12 个规格全部仍不达标，裕量 −8 到 −28 dB。
  - 即使允许逐音补偿（均衡后 SNR）也只有 36–56 dB，低于要求的 47–66 dB。
  - 线性规划给出的阻带下限是 −51 到 −65 dB，要求约 −72 到 −90 dB。瓶颈是 7 抽头和 31 抽头半带的滤波能力，以及没有 CIC 滚降补偿级；只调参数无法达标，必须改结构。
- **统一系统 v1 结果（2026-10-12）：没做到。**面积是 M 中位数的 2.1 倍，只有 R 的 8%–32%（R/U）。LLM 只看规格写的 24 个结构中，初始达标 0 个，裕量 −77 到 −112 dB；r64n 的 4 个全部构造失败。抽查发现基础错误：系数按峰值归一化导致增益不为 1，符号可能也反了，更像接口约定错误而非能力不足。修复轮可能只修构造失败、不看指标。最终裕量 0.37–1.34 dB，没用掉。tones.py 有除零和溢出警告待查。结论：DeepSeek 在当前 harness 下不能从规格独立写出模板级结构，“模板是 LLM 产出”暂不成立。已请实验会话做不花 API 的诊断。花费 ¥33.4。
- **harness 问题确认（2026-10-12，读 dspgen/structgen.py）**：(1) 修复轮只处理构造失败，SNR 差 100 dB 的程序被当作成功接受，这是 bug；(2) LLM 不能运行自己的程序、看中间信号；(3) 提示词缺干扰频段和功率、信号幅度、理想上限，也缺能正确运行的约定示例。用户判断：问题在 harness 而非模型；kernel agent 能写好，是因为有“运行—观察—修改”的循环。已派任务：把结构生成改为带工具的多轮 agent 循环（run、probe、freqz、面积分解，最多 12 轮），并做对照：裸对话 / 现 structgen / 新 agent 循环 / Claude agent 上界，规格为 r32n 和 r64w，K=3，约 ¥20。
- **KDA 启示（NVlabs/kda，2026-10-12）**：KDA 不是一个 agent 框架，而是“编码 agent（Claude Code）+ 任务契约（目标、约束、验证命令、晋级标准）+ 领域工具（Nsight 分析、KernelWiki）+ 计划 → 小步迭代 → 每步验证 → 记录候选”。用这套做法的方案拿到 MLSys Kernel Contest 第 1–3 名。我们之前的错误：围绕弱 API 模型自建一次性生成、只修编译错误、信息不全的 harness，没有把评价器做成 agent 可调用的工具。VeriEvolve 的正确形态：把规格契约、系统级裁判、原语编译器、探针、频响、综合做成工具，交给编码 agent 使用；进化种群作为外层可选。
- 已建工具 `/Users/chengzhy/verievolve_tools/agent_tool.py`（eval/probe/freqz/direct/api/spec，一次评价约 1.5 s）和契约工作区 `/Users/chengzhy/verievolve_agent_ws/dev_r32_narrow/`（CONTRACT.md 等）。启动了一个不带先验上下文的 Claude 子 agent，只看契约设计 r32n，最多 60 次评价，用来和 M（92k）、R（29k）比较。
- **structgen 失败诊断（实验会话，不花 API）**：可构造的 15 个程序中，NCO/混频实现错误 10 个（本振偏离 f_if 5–33 个通带宽度；常见原因是 counter 位数与 32 位 fcw 不匹配、LUT 取址错），增益/格式/符号错误 5 个，滤波能力不足 0 个。构造失败 9 个，其中约一半修复轮被 harness 浪费在 API 瞬时错误、格式拒绝和无代码块上。tones.py 的警告是 Accelerate BLAS 对复数 matmul 的误报，重算最大差 5.6e-17。内层调优加到 60 次仍是 M 的 1.2–3.4 倍，差距在结构。整程序重写达标率 23%，diff 是 40%。(d) Claude 上界改由全新子 agent 做，实验会话的上下文已被污染。

## 2026-10-13：结构生成失败归因与 harness 修正
- **24 个结构程序失败归因（未调用 API）**
  - 能构造的 15 个全部是功能/约定错误，没有一个是滤波能力不足。
  - 其中 10 个是 NCO/混频实现错误（等效本振离 f_if 有 5–33 个通带宽度），5 个是增益过小、饱和或 I/Q 符号错误。
  - 即使去掉干扰只输入期望信号，SNR 也只有 −50 到 +9 dB。
  - 构造失败的 9 个中约一半是 harness 造成的：API 瞬时错误被计为修复轮；"必须写字面量 SPACE/P"的格式拒绝。
  - 修复环节只处理构造失败，能构造但指标极差的程序从不反馈。旧提示词还缺少定点/计数器约定（GENERAL）、理想上限和约定示例。
- 内层搜索：LLM 声明的 SPACE 很粗，±1 邻域很快停在局部最优；加做位宽下降后裕量才用到约 0.3 dB，面积仍是 M 的 1.2–3.4 倍。
- 整程序重写：达标率 23%，diff 为 40%；重写占约 1/4 迭代。
- numpy matmul 警告是 Accelerate BLAS 误报，结果与逐项求和差 <1e-16，不影响打分（notes_blas_warnings.md）。
- probe_tones 修了两个 bug：单音幅度过大导致饱和；f_off=0 时两个基函数重合，造成假的 6 dB 纹波。
- 新建 dspgen/agent.py（多轮工具循环：eval/probe/freqz，与 Claude agent 共用 agent_tool.py），E-H 四种用法对照已冻结协议并启动。
- **Claude 子 agent 中间结果（r32n，只看契约）**：达标设计代理面积 18,896（裕量 0.50 dB）。M 为 92k，模板 R 约 29k（校准口径）。结构是它自己找到的：6 阶 CIC 一次抽取 32、K3 补偿 FIR、Hogenauer 剪枝、抽取后 I/Q 交织复用梳状器和补偿器；它还自己做了面积单价标定（cal01/02）。注意 g.q 的文档里有“CIC 寄存器”字样，属于轻度结构提示泄露。待做真实综合、留出复核和 RTL 对拍后才能引用。
- **Claude agent 的设计过程是逐步推导的，不是一次写出**（r32n，读 candidates.jsonl）：先标定原语单价 → c02 用 CIC N5 + 补偿，相位截断杂散把阻塞搬进带内（−8.9 dB）→ 改用 Taylor 插值 NCO → 发现剪枝 bug，并区分是 NCO 还是剪枝的问题 → 剪枝过狠 → N5 混叠边缘不够 → c09 用 N6 首次达标（27.3k）→ Hogenauer 剪枝 → I/Q 交织复用 → 补偿器用 LS + CSD → 首梳状器做两相位，N5 也能达标 → c18 为 15,270（裕量 1.86 dB）。共 18 个候选，其中 8 个未达标。轨迹图见 thesis/midterm/figures/fig_agent_trace.png，对应用户手绘的“步骤—分数”图。
- **Claude agent（只看契约）r32n 最终结果（2026-10-12）**：代理面积 12,644.5，裕量 0.385 dB，纹波 0.023 dB，用了 41 次评价。对比：直写 781k，模板 R 约 29k，M 约 92k；比模板小约 2.3 倍（代理口径，待真实综合）。结构：Taylor 插值 NCO（128 点表）；5 级 CIC 抽 32，其中一级盒长 41，把零点移到第 1 混叠带边缘，最坏混叠 −74.9 dB，优于标准 6 级；I/Q 交替复用低速部分；梳状级合成 (1−z⁻²)⁴；7 抽头 LS+CSD 补偿器；截断偏置合并为一个常数补偿。它自己总结的设计知识：相位截断杂散偏移约 1/32，会把阻塞搬进带内；裁判按整个输出带计噪声；饱和逻辑每处约 100 面积，回绕免费。风险：积分器最高位按测试信号峰值设，溢出会回绕成乱码，留出场景是关键检验。已交实验会话做 final_eval。
- **DeepSeek 跑在 Claude Code 框架里**：通过 DeepSeek 的 Anthropic 兼容接口（api.deepseek.com/anthropic，deepseek-v4-pro / flash / chat 均可用）驱动 `claude -p`，配置隔离，工具受限，工作区独立（dev_r32_narrow_deepseek）。脚本：/Users/chengzhy/verievolve_tools/run_cc_deepseek.sh。目的是做“模型 × 框架”的 2×2 对照。
- **2026-10-12 用户要求停止全部实验。**已停 DeepSeek-in-Claude-Code 运行：最好结果 c12 104k，裕量 1.67；CIC 方案差 16–17 dB 未调通。已通知实验会话停止全部任务。最终对照：DeepSeek 在旧循环中没有有效设计，在 Claude Code 中做到 104k；Claude 在 Claude Code 中做到 12.6k（代理口径，final_eval 未做）。
- **2026-10-13 用户要求停止全部实验**
  - E-H 的 (a)、(c)、(c60)、(c) v3 已跑完；收尾评估和 (d) 的同口径评估都没有做。
  - 代理面积初步结果：
    - (a) 裸对话 0/6 达标；
    - (c60) r32n 的最优达标面积 22.1 万，r64w 为 121.7 万；
    - (c) v3 r32n 最优 49.6 万。
  - 都远大于 (d) Claude 子 agent 在 r32n 上的 1.26 万（代理面积、未验证）。这表明差距主要在模型/agent 能力，而不是工具。
  - 余额 ¥145.35。
- **全部实验已停（2026-10-12）**：实验会话没有正在运行的任务，清理了 17 个残留孤儿进程，停止说明见 eh_agent_v1_20261013/STATUS_user_stop.md。E-H 代理面积（未收尾）：裸对话 0/6 达标；DeepSeek 在自建 agent 循环中给 60 次调用，r32n 最好 22.1 万，r64w 最好 121.7 万。DeepSeek 在 Claude Code 中做到 r32n 10.4 万，只花约 ¥1.09；Claude 在 Claude Code 中 1.26 万。未完成：E-H 收尾、Claude final.py 的同口径评估。DeepSeek 余额 ¥145.35。
- **最接近的竞品是 MathSynth（2026-10-12，ucasproposal-master/ref/main_副本.pdf，匿名投稿）**：数学表达式 + 误差容限 → e-graph（代数恒等式 + 多项式/CORDIC/查表近似规则）→ 字长优化 → 调度 → MLIR → Verilog，演示了 7 级 5G NR 接收流水线。和我们的差异：(1) 误差界逐函数施加（max|f−f̂|），各级分别编译，没有系统级指标，也不跨级分配误差预算；(2) 变换空间来自人工规则库，LLM 只提局部重写规则，其中 55% 通过验证，且大多与已有规则重合；(3) 资源用 FPGA 估计值，不是综合结果。它在讨论里写明“LLM 的独特价值是提出 FFT 基数、FIR 结构这类算法分解”，并列为未来工作，这正是我们的主线，**用户明确要求：报告和论文中一律不得引用或提及 MathSynth**，它只作为了解竞品的内部参考。
- **中期报告 LaTeX 版（ucasproposal-master/Tex/Mainmatter.tex，共 34 页）**：写法向模板靠拢，用成段论述。背景先抽象出“链路 = 级联算子 F=f_m∘…∘f_1”，归纳三个共性（实现自由、近似可接受、级间耦合 e_out≈Σg_i·e_i），DDC 只作为例子；数据集单独成节（筛选原则、三层结构、8 条链路分三类、指标表、测试场景、当前实验链路 A/B）。相关工作新增 SkyEgg、EggMind、近似电路进化（EvoApprox、Tomasovic & Sekanina 的提示/模板协同进化）、CktFormalizer、Harness 进化。
- **封面标题两行（2026-10-12）**：在 ucasproposal.cls 中新增 `\titlesecond{}`，封面上方空白由 195pt 改为 165pt；Frontinfo 中题目拆成“基于大语言模型的通信算法 / 硬件设计自动化方法研究”。

## 2026-10-13：判定器是否要按算子逐个写（与“解耦算法”是否矛盾）
- **结论：不矛盾。**要解耦的是“实现结构”（CIC 还是多相、CORDIC 还是查表），不是“任务规格”。“什么算合格”本来就属于问题定义（式 7），任何方法都要写，KernelBench 也要给每个 kernel 配参考实现和容差。
- **判定器分三层**：(1) 通用引擎，所有任务共用：浮点参考与候选同激励运行、RTL 与程序逐位对拍、留出场景、安全裕量、阈值比较；(2) 指标库，有限且可复用：时域误差功率比（SQNR/NMSE/EVM/带内 SNR 实为同一公式，只是作用域不同）、频域指标（SFDR/ACLR/纹波）、任务级指标（BER 处 SNR 损失，需要接下游）；(3) 任务契约，是声明式数据而不是代码：参考模型、激励/场景生成参数、指标名、容差 Δ。
- **统一写法**：M = Φ(y_impl, y_ref; 激励)，T 为“M ≥ M_ideal − Δ”或“≤ 理想 + Δ”。“相对理想浮点实现”这一形式让容差与算法无关。
- **系统级判定让判定器数量不随算子数增长**：一条链只在链路输出端设一个判定，中间算子不单独设判定，误差预算由搜索在算子之间分配。逐算子设误差界恰恰是 MathSynth 一类方法的做法（内部参考，不引用）。
- **诚实的边界**：每条新链路仍要写一份契约（参考模型 + 场景 + 指标选择），这部分是人工的；可以论证其成本远低于写结构，且可由 LLM 从标准文本起草、人工审核。待做的佐证实验：统计链 A/B 判定代码中通用部分与契约部分的行数比；用同一引擎接入第三条不同类型的链（如 NCO 或 FFT），只新增契约。

## 2026-10-13：算子粒度与链路粒度的研究定位
- **通信 DSP 的自然工程粒度是“链路由算子/模块级 RTL 拼成”。**常见工程不会把整条接收机写成一个巨大 Verilog 文件，而是把 NCO、混频、CIC/FIR/半带、抽取、FFT、均衡、同步、解调、LLR 等做成模块，再在顶层连接。论文中的“链路”应理解为可综合的模块网络和系统级验收，而不是单文件巨型 RTL。
- **VeriEvolve 最合适的定位是：算子/子链级生成，链路级判定。**单算子实验证明系统能产生结构跳变；DDC 这类子链实验证明系统能在级间分配误差预算并选择结构。不要主张自动生成完整基站/终端协议栈，也不要只停留在孤立算子。
- **论文表述建议**：先列有限但覆盖关键结构的算子族，再展示 2--3 条典型子链。贡献落在“从数学规格和系统容差生成可综合通信 DSP 子链/模块网络”，而不是“穷尽所有通信算子”。

## 2026-10-13：链路也是算子，设计对象由边界而非公式大小决定
- 数学上，整条链 `F=f_m∘…∘f_1` 本身就是复合算子；“算子”和“链路”不是互斥类别，而是不同抽象层。仅给一个公式不足以确定要生成哪部分硬件。
- 每个任务必须额外声明四个边界：**可变子图**（哪些节点允许搜索）、**冻结上下文**（其余级采用固定 RTL 还是理想/逐位模型）、**质量观测边界**（在哪个输出计算 SNR/EVM/BER）和**成本统计边界**（综合哪些模块）。系统不能靠 LLM 从公式中猜这些边界。
- 因而有三种不同任务：单算子局部验收；单算子放入冻结链路上下文后做端到端验收；整条子链联合生成。第二种必须给出前后级语义，但前后级不一定都要提供 RTL，只有计入成本或需要逐位接口验证的部分才必须硬件化。
- 当前 `dspgraph` 的 `build(g,spec)` 实际上把整个 DDC 子链作为可变设计对象，链末输出作为质量边界，整图作为成本边界；`scope` 目前主要用于面积和诊断分组，不能替代可信的搜索/所有权边界。后续任务 schema 应显式加入上述四个边界，不能用 LLM 自命名的 `scope` 决定研究口径。

## 2026-10-13：基带数据集定位复核
- 当前已实现内容应称为**通信 PHY 数值算子与数字前端子链 benchmark**。DDC/DUC 是真实、有工程意义的数字前端设计任务，但不能单独代表完整基带；现阶段不得写成“完整基带设计”或“完整收发链”。
- 中期报告表中的 8 条链是数据集规划，不是 8 条均已完成的数据。当前只有 DDC、DUC 接入，且二者同属前馈多速率滤波类；OFDM、同步、相关/合并等另外两类仍缺实证。因此“覆盖 3G–5G、Wi-Fi”只能描述任务来源规划，不能描述已验证覆盖。
- 106 个参数化实例的统计独立性主要是 7 个算子族，而不是 106 个互相独立的问题。训练/开发与留出不能随机拆同模板参数点；正式泛化应至少按未见规格、未见参数区间、未见场景分布和未见结构类别分别报告。
- “全部前馈”是首版编译器的合理范围约束，却排除了真实基带中的反馈同步、AGC、帧控制和自适应处理。突发同步还含检测、条件状态与帧级语义，不能仅按无条件算子级联处理。
- 硕士论文的最小可信补强不是追求 8 条都做浅，而是在 DDC/DUC 之外完成至少一条结构不同的块处理或判决链（优先 OFDM 接收内环），再增加一条同步/相关链；另设一个小型端到端 PHY 锚点，用标准参数和 CFO、多径、噪声等损伤验证 EVM/BER。若时间不足，就收窄标题与主张，不用规划数量替代完成度。

## 2026-10-15：工业系统中的 DSP 需求与本文对象
- 外部产品和开源实现确认，当前 DDC/DUC 确实是工业通信 DSP：AMD RFSoC DFE 把 channel filter、DUC/DDC、mixer、resampler 等列为硬化 DFE IP，并把 FFT/iFFT、PRACH 单列为 Low-PHY IP；ADI AD9208 的片上 DDC 是 NCO/混频器加多级半带抽取 FIR；Ettus USRP 的 `ddc_chain.v` 也是相位累加/CORDIC、CIC 与半带抽取链。本文不是“像 DSP”，而是在生成真实 DSP 数据通路。
- 客观的无线 PHY DSP 至少包含四种不同工作负载：(1) 连续流多速率前端：DDC/DUC、CIC、半带/FIR、重采样、信道化；(2) 块变换：FFT/iFFT、CP、资源栅格；(3) 估计与线性代数：同步相关、信道估计、ZF/MMSE 均衡、波束赋形/MIMO；(4) 软信息与编码：解映射/LLR、LDPC/Polar。另有 AGC、载波/定时跟踪和帧控制等状态/反馈逻辑。
- VeriEvolve 当前最匹配的是第 (1) 类，并已触及 NCO、复乘、FIR 的结构与定点联合设计。它足以支撑“通信数字前端 DSP 自动设计”，但若题目和结论写“通信基带 DSP”，至少还应以第 (2) 或第 (3) 类的一条异构子链验证表示和方法，而不是继续增加同类 DDC 参数点。
- 数据集选择应按**计算形态和硬件约束覆盖**，不是按 3G/4G/5G 名称凑模块：连续流/块处理、单速率/多速率、前馈/反馈、规则 MAC/矩阵运算、近似容忍/逐位精确，以及吞吐、延迟、动态重配置。标准名称只负责提供真实参数和场景，不能替代结构多样性。

## 2026-10-13：智能体 r32n 设计完成验证；中期报告按三方法重写
- **Claude 子 agent 的 r32n 最终设计（final.py）已验证**：搜索裕量 +0.38 dB，留出场景裕量 +0.55 dB（达标），RTL 与整数模型 400/400 零失配，真实面积 14,315 μm²（快速 ABC）。OpenSTA PPA（2 ns 时钟，全局翻转率 0.1）：14,639 μm²、423 MHz、4.78 mW；对比进化搜索 M 93,689 / 104 MHz / 32.0 mW，模板 R 27,345 / 250 MHz / 9.66 mW。结果文件：`verievolve_agent_ws/final_eval_r32n/result_v2.json`。
- **编译器修复**：1 位信号原来声明为标量，`bits(x,0,0)` 生成的 `x[0:0]` 在 iverilog 下报错（Yosys 能过）。现在 `sdf._decl` 对所有信号都声明位宽范围；dspgraph 回归 7/7 通过。
- **报告口径（用户要求）**：参考 CktFormalizer 的组织方式，三个方法改为“原语表示与编译器 / 系统级容差验证（逐位等价 + 容差等价 + 场景覆盖）/ 智能体式生成与 PPA 优化闭环（带接受与回到父节点规则）”。智能体结果表述为“本框架下的智能体”。没做的实验在表中留空。图的源码和数据都在 `thesis/midterm/figures/src/`，每张图一个脚本，数据直接写在脚本里。

## 2026-10-14：E-Syn 对 VeriEvolve 的位置
- E-Syn（DAC 2024）在布尔组合逻辑层用 e-graph 保留精确等价形式，再用启发式与随机采样生成候选池，用 XGBoost 预测映射后面积/时延并择优。其“超过 100 个样本”指每次提取的候选池大小，不是训练量；回归模型实际用 50,000 个随机组合逻辑电路训练，面积/时延预测 R 值为 0.76/0.78。
- 对我们有价值的是两点：一是作为每个已验收 RTL 候选之后的**精确等价后端优化**；二是借鉴“多样化候选池 + 便宜代理排序 + 少量真实综合”来减少 PPA 评价成本。它不搜索近似结构、定点误差预算或链级通信质量，因此不能取代 VeriEvolve 的原语搜索和系统级容差判定。
- XGBoost 只能做调度/预筛，不得作为论文面积或时延结论；最终 PPA 仍必须来自同一真实综合流。若引入 E-Syn，必须对所有对照方法的 RTL 统一使用，否则会把后端优化收益误计为上层搜索收益。
- 可选最小试验（未启动）：从 DDC/DUC 的冻结候选中按结构分层抽取少量设计，在同一 Nangate45 库和时序约束下对比 ABC 与 ABC+E-Syn，检查收益是否稳定跨结构存在，并记录 e-graph 膨胀、提取时间及状态边界处理。该试验只回答“后端是否值得加入”，不作为解析误差模型或 LLM 收益的证据。

## 2026-10-15：LLM 驱动的自适应粒度搜索原型与首次开发试跑
- 已实现首版层次搜索控制器 `examples/comm_dsp_bench/dspgen/hier_agent/`：从原语程序的 `g.scope` 自动提取节点，动态记录位宽、小数位、符号、速率域、时延和 held 接口；候选动作包括 `EXPAND / DECOMPOSE / FUSE / TUNE`，所有子候选必须回到整链根节点验收，并按固定 0.3 dB 裕量保留条件 Pareto 前沿。完整程序根节点只追加、不覆盖，避免固定树丢掉已有最好结构。
- 用已验证的 r32n 最终程序做单次开发性回放，根节点完全复现代理面积 `12644.504730327071`、搜索裕量 `0.38498454318239084 dB`、纹波 `0.023450838715012492 dB`。当前 Codex agent 连续提出 7 个参数动作：两条更便宜分支分别因根裕量不足被剪掉；`mix_w=14` 后把 CIC 剪枝目标收紧到 `-112 dB` 可恢复裕量但面积升高；改为给 NCO 校正系数加一位得到裕量 `0.47856915132619093 dB`、面积 `12707.393301555183`，形成高精度前沿点；`P=6,D=7` 虽降到 `12595.995753830184`，但裕量为 `-1.2241000698796825 dB`，失败。未找到比原根节点更小且满足 0.3 dB 契约的新设计。
- 这次只证明数据结构、动态契约、分支保留、根级剪枝和跨节点预算回流能运行，**不能证明算法优于扁平 agent**：仅 1 个规格、1 次人工引导式 agent 轨迹，使用搜索场景和代理面积，新候选尚未做留出、RTL 对拍及真实综合。精确记录在 `examples/comm_dsp_bench/experiments_hier_agent/r32n_codex_v3/state.json`。
- 负诊断：对作用域统一加宽 4 位不是可靠的单调误差归因；外层 `nco` 加宽反而使裕量从 `0.38498454318239084` 降到 `-5.209942904083235 dB`。因此该量只记为 intervention response，后续解析展开策略必须基于显式噪声增益/边界误差模型，不能把 scope widening 当成误差贡献。

## 2026-10-15：控制、协议与状态机的职责边界
- 三者不是三选一。VeriEvolve 生成的是**可集成、可综合并通过链级验收的 DSP 模块或子链**；仅输出语法正确的 Verilog 不算完成。
- 原语编译器应机械生成支持范围内的局部控制：流式 `valid/ready`、复位、反压保持、流水有效位传播、固定倍率的多速率使能、迭代原语的局部计数与状态，以及原语间的位宽/速率/延迟连接。它不应让 LLM 每次重新发明这些协议细节。
- 任务作者暂时提供并冻结系统壳与契约：时钟/复位域、顶层端口、输入输出场景、配置寄存器或常量、参考模型、质量阈值和成本统计边界。AXI/总线封装可作为库适配器，不作为搜索贡献。
- 当前明确不自动生成完整 MAC/PHY 协议栈、跨时钟系统、多模式运行时重配置、帧调度，以及含捕获/跟踪/失锁恢复的复杂同步控制器。它们可以作为冻结上下文，或以后单独定义状态型原语和任务契约后逐步纳入，不能默认由现有前馈数据流编译器“自动做好”。
- 验收至少包含四层：Verilog 可编译；接口事务与反压正确；整数模型/RTL 一致且链路质量达标；在统一约束下得到真实 PPA。只有四层都通过，才能称为一个有效硬件设计。

## 2026-10-15：链路数据集不再扩项，按计算形态收敛主实验
- 当前文档口径有一处不一致：旧规划 A--H 是 8 条，中期报告表 4 加入 Viterbi 链 I 后实际是 9 条，但进展表仍写 8 条。后续应统一为“9 条候选链路”，并区分候选目录与已完成主实验，不能把规划数当完成数。
- 9 条候选已经超过论文所需，不再新增链路或为数量补算子。论文证据应按计算形态选代表，而不是把全部候选浅跑一遍：A/B 共同覆盖连续流多速率；C 或 D 覆盖块处理与 FFT；I 可作为带状态的数据通路扩展。A/B 虽是两条链，但不能算两类独立泛化证据。
- 建议核心集为 A 接收 DDC、B 发射 DUC、D 的受限 OFDM 接收内环；D 固定同步与导频条件，把 FFT、信道估计/均衡和 LLR 中明确声明的子图设为可变对象。若 D 工程量过大，以 C OFDM 发射作为块处理保底。I Viterbi 是加分项，不应阻塞前三类证据完成。
- F 多相信道化器与 D 都含 FFT，可留作迁移/留出；H Farrow 与 A/B 同属多速率滤波，增量有限；G Rake 可作为领域扩展，不是主张成立的必要条件；E 突发同步需要条件状态和检测语义，应等状态型契约成熟后再做。
- 单算子不再追求数量。现有 7 族用于单元验证已足够；只补所选链路必须的新能力：FFT 蝶形、块缓存/重排与帧语义，复数 MAC/倒数或除法；只有启动 I 时才补加比选和幸存路径存储。CRC、加扰、交织等逐位精确模块可作为固定上下文，不列入近似搜索对象。
- 验收优先级是“少而深”：每种计算形态有多个规格、未见规格/场景留出、多种子、同预算强基线、RTL 对拍和统一约束 PPA。三到四条深度完成的异构链路，比九条只有一次运行的链路更能支撑通用性主张。

## 2026-10-15：从软件背景理解项目的前置知识
- 通信 PHY 不是单纯 bit 转换：bit 是首尾，中间主要处理经采样的实数/复数 I/Q 波形。时域与频域是同一信号的两种表示，本项目的 DDC 主案例可归纳为混频搬移、低通抑制混叠和抽取降低采样率。
- Verilog 描述并行存在的组合逻辑、寄存器及其连接，不是普通顺序程序。时钟的核心是给并行电路提供统一状态提交边界；延迟、吞吐率和发起间隔需分开理解，`valid/ready` 只在时钟边沿上同时为真时完成一笔样本交易。
- 读懂当前论文的最小知识集分三层：必须掌握同步 RTL、定点语义、流式握手、仿真/综合/时序区别、采样与混叠、I/Q 与 DDC、质量指标及 PPA；方法层再学 CIC/半带/多相、NCO/CORDIC/LUT、FFT、调制/LLR/BER、IR/编译验证与 Pareto/消融/留出；射频电磁细节、完整编解码、3GPP 全条款和 P&R 可暂缓。
- 学习应紧贴项目：先用最小 RTL 看时钟与握手，再手算定点边界，用 Python 单音同时看时域/FFT，然后走通 DDC 的 NCO--混频--滤波--抽取，最后回到原语表示、系统容差验证和 agent PPA 闭环。详细地图和 15 道边界诊断题已整理到根目录 `讨论.md`。

## 2026-10-15：核心讨论稿重构后的待统一点
- 根目录 `讨论.md` 已从历史对话日志重构为“数据集--指标--表示--验证--搜索--架构--实验”的问题稿；后续讨论中的控制/状态边界、大变换与小 diff、近可行前沿、FFT 结构发现与原语膨胀风险已归入对应标题。
- 当前中期报告称“16 个通用原语”，但表中枚举的名称按字面计数并不一致；`mac` 若只是乘加组合应为可展开函数，若承载分时复用、累加状态和调度语义则可作为微结构原语。代码和论文需统一口径。
- 方法三此前存在“外层 LLM 结构 + 内层确定性参数”与节点级层次智能体两套口径。下一节将两者收拢为同一个待验证方法，并保留宏观结构动作尚未实证的证据边界。

## 2026-10-15：方法三的概念收缩
- 原语是最小整数/RTL 语义的叶子，不是 LLM 搜索节点。搜索节点改为带位宽、速率、延迟和协议契约的类型化区域/原语子图，根节点才做链末通信质量验收。
- 方法三对外只保留两类动作：区域级 `REWRITE` 负责算法分解、融合和数据流重写，参数级 `TUNE` 负责位宽、截位、缩放、流水和复用。`EXPAND/DECOMPOSE/FUSE/SCHEDULE` 只是 `REWRITE` 的提示词或结果标签，不分别声称创新。
- 当前不声称严格 AND/OR 搜索；在独立子问题前沿能够正确组合之前，使用“基于类型化区域的自适应粒度搜索”。现有 `hier_agent` 主要只跑过 `TUNE`，宏观结构发现仍是待验证能力。
- 论文不需把 Pareto、树搜索、近可行档案和各个动作都包装成新发明；整体主张是在类型化原语程序上，用系统级容差反馈指导结构重写与定点调优。
- 方法三的最小证据是同模型、同反馈、同评价预算对比平坦 ReAct、仅 `TUNE`、`REWRITE+TUNE`，报告根级留出通过率、可行前沿、PPA、多种子方差和结构类之外的新实现。若无可重现收益，正文退回已验证的两层搜索。

## 2026-10-15：框架 v3（原语 + 有效反馈 + LLM 驱动搜索）
- 实现清单与结论见 `讨论归纳.md` 第 11 节。进化（OpenEvolve）不再作为方法或基线。
- 方法一：原语文档分为核心（RTL 字级 / DSP 语义 / 接口）、便利原语（列出等价组合）、工具；新增核心原语 `g.ram`（单写单读、先读后写、复位清零，整数模型 / RTL / 门级逐位一致）；`dspgen/record.py` 记录类型化数据流图并导出（含语义哈希）。去掉 `g.q` 文档中的“CIC 寄存器”提示，帧与时钟域原语进入 agent 文档。
- 方法二：`dspgen/contract.py` 声明式契约（边界、输入类与数值包络、安全裕量、时钟、预算）自动生成 agent 工作区；统一终验 = 搜索 + 留出 + 30 个新随机场景统计复核（Clopper–Pearson 95% 上界）+ RTL 对拍 + 2–2.5 ns 下 PPA。`dspgen/symbolic.py`：区间范围检查；链路 A 全频带扫频（真实定点实现，按包络取幅度），恢复 alias_min_db 约束。按分组的误差归因放弃：有意的误差相消（常数补偿截断偏置）使“加宽某组”不等于理想化，r32n 加宽后 SNR 反降 59.6→53.2 dB。
- PPA 流程修正：扇出 >16 的网插 BUF_X4 缓冲树（ZipCPU 由假 57 MHz 恢复到 745 MHz；r32n 面积 +1.9%、频率不变）；功耗改用门级仿真翻转率（r32n 9.6 mW，约为全局 0.1 估算的 2 倍）；门级网表输出与整数模型对拍。
- 方法三：`agent_tool archive add/show/verify`（父子关系、REWRITE/TUNE、BROKEN/OPEN/FEASIBLE/VERIFIED、缺口 v、可行与近可行前沿、连续 4 次 TUNE 无改进提示 REWRITE）。
- 数据集：链路 C `ofdm_tx64_q{64,256,1024,4096}`（802.11a/g 参数，IDFT+CP，EVM 门槛 = 对应标准门限 −10 dB）；现实性变体 `real_r32_narrow`、`real_r64_wide`（单个 45 dB 窄带调制干扰，Δ=0.5 dB，纹波 0.1 dB，14 位输入；理想上限 45–49 dB）。
- 基线：USRP 接入 v3（`dspgen/baselines/usrp.py`，r32n 复现裕量 −8.87 dB）；ZipCPU 64 点 IFFT（LGPL，按生成规则配置 + 最省外壳，`dspgen/baselines/zipcpu_fft.py`）在 q1024 上 EVM −54.3 dB、面积 99.9k–107.2k μm²、745/729 MHz、仿真功耗 26.2–28.8 mW；直写 Verilog 评价命令 `veval/vppa`。FloPoCo 需 Docker 守护进程或本机编译外部代码，待用户同意。
- 实验 A（OFDM 发射 q1024）与 B（real_r32_narrow）已用 Claude agent 启动，结果待补。

## 2026-10-16：总体架构与方法三口径收敛
- 当前主链统一为：带显式设计/观测/成本边界的任务契约 → 独立理想参考与原语直写起点 → 智能体以 `REWRITE/TUNE` 修改完整原语程序 → 编译器生成带类型数据流图、逐位整数模型和 RTL → 构造检查、整数模型/RTL 逐位对拍、链级容差与场景覆盖、统一约束 PPA 四级判定 → 可行/近可行档案与 Pareto 前沿 → 数值诊断反馈、保留分支或回到父节点 → 留出终验与可复现设计包。
- 方法三统一为反馈驱动的双粒度智能体搜索。`REWRITE` 复制父节点的完整程序，在独立工作副本中经过多次小编辑和工具调用完成区域级算法分解、替换或融合，最后把完整程序作为一个结构子节点登记；因此大变化按语义和拓扑跨度定义，不按文本 diff 行数定义。`TUNE` 保持算法分解、区域连接和外部接口不变，通过 AST 精确修改显式参数映射，形成可测量局部质量--PPA 灵敏度的参数子节点。
- 两类动作走同一条根级验收路径。候选按 `BROKEN/OPEN/FEASIBLE/VERIFIED` 管理，父节点始终保留；近可行节点可继续调优，可行节点沿局部斜率压缩，连续四次 `TUNE` 无改善或诊断指向结构瓶颈时转为 `REWRITE`。当前已实跑 7 个 `TUNE` 子节点，`REWRITE` 的决定性对照仍待完成，不能把大结构发现写成已验证结论。
- 解析误差模型位于候选内部的调优、筛选与诊断路径；最终可接受性由接回冻结上下文后的链级指标决定。除非跨节点组合模型已经独立验证，不把当前整链场景评价称为“整链解析适应度”。
- 总体图应同时画出两条不同的可信性关系：RTL 与声明整数语义之间要求逐位一致；近似实现与理想公式之间只要求系统指标落入允许空间。二者不能合并成“形式等价证明”。
- 中期报告图表字体统一为 `PingFang SC`（苹方-简），代码片段保留 `Menlo`；`font_config.py` 从 macOS 的 TTC 字体集中精确抽取并注册简体字面，PDF 使用可嵌入字体，避免回退到日文字形、`ArialUnicodeMS` 或 Type 3。当前图已按该口径重画；框架 v5 另提供逐对象可编辑的 `figures/v5/fig_framework_v5.drawio`。
- `fig_agent_trace` 的外部参考只保留绿色的“固定结构参数调优”：29.2 千 μm²，是真实综合面积，仅作为量级参考；蓝色智能体轨迹仍是代理面积，两者不能作为同口径严格比较。

## 2026-10-16：框架 v3 第一轮实验（统一 verdict 判定 + 树搜索档案）
- 方法二统一入口 `dspgen/verdict.py`：约束（场景仿真、扫频）/目标/诊断；门槛由实现预算 p=0.1 推出；变换类别 equiv/math/approx 由 agent 声明、框架核实（`dspgen/claims.py`）；L2 隐藏集自动调度；实验变体 full/flat/score/verilog 与调用日志。
- 结果（同判定、同综合、同仿真功耗）：链路 C 任意输入 22,860 μm²/13.7 mW vs ZipCPU 99,905/28.8；1024QAM 输入（映射器融合）14,291–14,351 μm²；链路 A 45 dB 强干扰 28,855–32,092 μm²/9.8–11.1 mW，USRP 66,643/26.7 且不达标，教科书 + 贪心字长 86,947/53.4 且时序差 0.17 ns。
- 已知缺陷：自动 L2 把隐藏集松弛返回给 agent（F2），使平坦 agent 对照不成立；`mac(share>1)` 不给乘法器插流水；ppa 无分段面积。改进清单见 `讨论归纳.md` 第 12 节。

## 2026-10-16：用分配律统一“原语—变异—指标—验证”的最小口径
- `a·(b+c) ⇌ a·b+a·c` 是带适用条件的数学重写规则，不是原语；`add/mul/quantize/register` 才是具有明确整数与 RTL 语义的叶子原语，整个 `y=a·(b+c)` 是被设计和评价的算子。
- 搜索只保留两类对外动作：`REWRITE` 在类型化区域上做分配/提取、结构替换或融合；`TUNE` 不改数学分解，调整位宽、截位、舍入、流水与复用。一次变异只是从父候选产生一个子候选，是否更好由后续评价决定。
- 指标属于任务契约和整个算子/链路，不是原语自带的“分数”。节点局部误差只用于诊断；候选验收看根约束下的 SQNR/EVM/BER 等质量与统一综合得到的 PPA，并保留 Pareto 折中。
- 可信性必须拆开：形式证明或穷举可检查“精确重写在所声明的位宽/溢出条件下成立”；整数模型与 RTL 要求逐位一致；带截位、舍入或近似的实现与理想公式通常不等价，只能由冻结的容差指标判定是否可接受。解析误差模型输出确定性误差数值或界，不等于形式等价证明。

## 2026-10-16：对当前流程的客观判定
- “契约→类型化原语程序→REWRITE/TUNE→整数模型与 RTL→链级容差→真实 PPA→档案与反馈”的分层在工程上合理：生成、实现正确性、近似可接受性和成本评价没有混成一个分数，且所有候选回到同一根契约验收。
- 当前仍是有效的研究原型，不是已闭环的“形式验证自动设计系统”：`equiv` 只在搜索场景与额外随机场景上逐位比对，`math` 是加宽后的数值检验，两者都不是全输入形式证明；整数模型与 RTL 也主要是逐候选对拍。
- 现有方法优势尚不能作结论：第一轮隐藏集数值曾泄漏给 agent，平坦 agent 与完整方法的调用预算不对齐，同预算消融未完成，每链只有少量运行。当前安全表述是“流程能生成、验收并归档有效设计”，不是“该搜索已证明优于强基线”。
- 下一个决定性顺序：隔离终验集并冻结反馈协议→修正编译器/PPA 已知缺口→对无状态精确重写加 SAT/穷举校验→同模型、同信息、同预算重跑直写 Verilog/只给分数/平坦 agent/仅 TUNE/简单搜索基线→多种子和未见规格终验。

## 2026-10-16：唯一主流程的逻辑定稿（暂不启动实验）
- 输入不是一条孤立公式，而是“理想公式 + 任务契约”。契约同时固定接口、输入类、冻结系统上下文、观测点、容差指标及 PPA 目标；公式只回答“理想上算什么”。
- 中间表示是完整的类型化原语程序。原语是带明确整数、时序和 RTL 语义的叶子；数学恒等式是重写知识；FIR/CORDIC/FFT 等是原语子图或可展开的构造；它们不应再混称为同一层的“原语”。
- 搜索动作和语义关系是两个正交维度。动作只有 `REWRITE`（改数学分解、拓扑、状态、速率或融合）与 `TUNE`（保持分解与连接，调位宽、量化、流水、复用等）；每次动作另声明 `bit-exact`、`math-equivalent` 或 `approximate`。REWRITE 可以是精确或近似，TUNE 也可以是精确（如只插流水）或近似（如截位），不得将动作名称当成正确性等级。
- 候选先经过构造与类型检查，再核实它声明的变换关系，然后由同一原语程序生成整数 bit-true 模型与 RTL。变换核实、模型--RTL 一致和近似--理想公式的容差验收是三条独立的可信性关系，不存在一个“形式证明”同时覆盖三者。
- 解析误差模型和节点局部指标用于 TUNE、廉价筛选和失败定位；只有在跨节点组合关系已被独立验证时，才能替代整链验收。最终可接受性一律回到冻结根契约的链级指标，成本一律回到统一后端的 PPA。
- 每个子候选是一份完整程序，与父候选并存；状态只表示构造失败、近可行、搜索集可行与独立终验通过。搜索保留质量--PPA Pareto 折中，以数值约束缺口和成本变化反馈下一次 REWRITE/TUNE；LLM 只提议，不担任裁判。
- 三个方法不是并列拼盘：原语表示与编译器使候选可执行与可比；系统级容差验证使近似候选有可靠的接受规则；反馈驱动的 REWRITE/TUNE 智能体在前两者上搜索质量--PPA 折中。因果链是“先能表示，再能判定，才能搜索”。

## 2026-10-16：核心主张再收缩（最新 arXiv 对照）
- 最简核心问题不是“LLM 如何生成等价 RTL”，而是：**LLM 如何在通信系统容差内主动改变计算本身，同时保证候选的 RTL 实现忠实、系统质量可接受且 PPA 可比。**
- 对外主张建议压成两句：“VeriEvolve 将通信算法及部署容差编译为可执行的定点硬件搜索问题，使 agent 能联合改写算法结构、数值精度和微结构。系统独立验证‘RTL 忠实实现候选’与‘候选满足部署容差’，再用真实 PPA 反馈搜索系统质量--成本前沿。”
- 2025--2026 年直接近邻已分别覆盖常规组件：[HINT, 2026, arXiv:2608.07625](https://arxiv.org/abs/2608.07625) 已做可执行硬件意图 IR 与 RTL lowering；[CktFormalizer, 2026, arXiv:2605.07782](https://arxiv.org/abs/2605.07782) 已做类型化硬件表示、证明反馈和 PPA 闭环；[SymRTLO, 2025, arXiv:2504.10369](https://arxiv.org/abs/2504.10369) 已做 LLM 重写、符号推理和形式等价；[Dr. RTL, 2026, arXiv:2604.14989](https://arxiv.org/abs/2604.14989) 已做工具落地的 agentic PPA 闭环；[COEVO, 2026, arXiv:2604.15001](https://arxiv.org/abs/2604.15001) 已做连续正确性反馈与多目标 Pareto RTL 进化。因此不得把 IR、形式反馈、agent 闭环或 Pareto 任一项单独当作新颖点。
- 近似计算一侧也已很强：[Tomasovic 与 Sekanina, 2026, arXiv:2606.13089](https://arxiv.org/abs/2606.13089) 已用 LLM 与共进化搜索近似乘法器的误差--面积折中；[Shi 等, 2026, arXiv:2609.21697](https://arxiv.org/abs/2609.21697) 已在给定误差界下联合高层与逻辑级近似。VeriEvolve 的增量不能只写“允许近似”，而要落在**部署链路的通信质量契约、跨算子结构/误差预算联合搜索，以及“实现忠实性”与“系统充分性”的双重判定**。
- [Gideoni 等, 2026, arXiv:2602.16805v2](https://arxiv.org/abs/2602.16805) 表明代码进化中搜索空间与评价设置可能比复杂搜索器更重要。因此“树搜索、Pareto 档案、REWRITE/TUNE 调度”应是可替换实现，不应抢占论文中心；论文中心应是它们共同依赖的“可搜索容差语义”。

## 2026-10-16：最小任务卡与唯一闭环
- 用户侧输入收缩为一张任务卡：（1）理想功能：数学公式或可执行参考；（2）硬件边界：端口、定点格式、时序/速率协议；（3）设计目标：“输入条件 + 观测点 + 指标 + 门槛”组成的质量要求，以及 PPA 偏好。场景生成、seed、留出、指标实现、工艺库和工具参数属于系统内部 harness，不再并列写成用户或 agent 的多个输入。
- 系统首先将理想功能按默认实现库直译为一份保守、可执行、不追求最优的初始原语程序；它同时是语义起点、工程基线和首个搜索父节点。
- agent 不是 LLM 之后的另一个模块；agent = LLM 提议器 + 验证/综合工具 + 候选档案 + 循环策略。它每轮选一个父候选，用 `REWRITE` 改结构或用 `TUNE` 改数值/微结构，产生完整子程序。
- 方法二是分层判定而不是单一二值门：构造或实现语义错误的候选才真正驳回；合法但质量未达标的候选保留为近可行节点，并返回每项约束还差多少；质量达标的候选进入真实 PPA。为避免昂贵综合浪费，未达标候选默认只看廉价代价诊断，只对质量可行或近前沿候选做真实综合。
- 两类反馈共同驱动下一轮：判定器返回构造错误或质量约束缺口；综合工具返回面积、时序、功耗与瓶颈。质量离门槛近时优先 `TUNE`，诊断指向结构地板或 PPA 不良时优先 `REWRITE`，父候选始终保留。
- 循环终止后，工具层对选定前沿做独立终验。产品视图输出一份按用户偏好选中的主 Verilog，同时附上少量质量--PPA 备选与可复现报告；研究视图报告完整的前沿，不用一个人工加权总分隐藏折中。

## 2026-10-16：IR 到 Verilog 的编译器边界
- 业界通常不是把数学表达式直接打印成 Verilog，而是分层下降：高层数据流/行为 IR → 类型与位宽确定 → 算子合法化和结构展开 → 调度、资源绑定及流水寄存器插入 → 显式模块/组合逻辑/寄存器/FSM 的低层硬件 IR → SystemVerilog AST/文本。CIRCT 的典型路径是 FIRRTL → HW/Comb/Seq/SV → `ExportVerilog`；XLS 则把 IR 调度成含流水级、寄存器和端口的 block IR 后生成 Verilog。
- 编译难度取决于 IR 与 RTL 的语义距离。顺序 C/纯数学 IR 缺少并行度、位宽、周期、状态和接口，需要完整 HLS；若类型化原语程序已经显式给出定点类型、拓扑、状态、速率、量化和微结构选择，后端主要是确定性的规则下降、时延/协议对齐与代码发射。
- VeriEvolve 不应悄悄让编译器替 agent 做设计搜索。agent 显式选择算法结构、位宽/量化、流水和复用；编译器负责类型检查、宽度扩展与截位语义、原语展开、依赖/速率/延迟检查、局部控制及握手生成，并由同一候选产生 bit-true 模型和 RTL。编译器可提供明确默认值，但所有会改变质量--PPA 的选择必须在 IR 中可见、可改、可追溯。
- 方法一因此应表述为“面向 agent 的类型化原语语言与确定性编译器”，而不只是“有一个 IR”。论文必须给出原语语义、类型规则、lowering 规则、状态/复位/握手与多速率处理、扩展新原语的成本，以及编译器正确性验证。仅靠同一套 lowering 同时生成模型和 RTL 存在共因错误，仍需独立理想参考、原语级穷举/形式检查和模型--RTL 对拍。
- 编译器工作量本身不自动构成创新；可主张的增量应是：把 agent 可编辑的定点、多速率、状态/流式语义稳定地编译成可验证 RTL，同时让近似决策保持显式，并支撑系统容差反馈下的跨结构搜索。若只覆盖硬编码 DDC 模板，应如实称领域编译器或生成器，不能声称通用硬件编译器。

## 2026-10-16：RTLScout/Spire 的真实 IR→Verilog 路径
- RTLScout 是 agent 评价与优化框架，不是统一 IR 编译器：`language=verilog` 时 agent 直接写 `.v/.sv`；`spirehdl` 或 `amaranth` 时，框架运行候选 Python 文件，让对应 HDL 后端写出固定的 `design.v`，随后统一交给 Verilator、CEC 和 Yosys/OpenROAD 评价。
- Spire 通过 Python 运算符重载在 elaboration 时构造有精确位宽的表达式 DAG 和 `Component`，再收集所有从端口可达的信号，展平为低层 `Netlist`。这个 IR 已含 input/output/wire/reg、驱动表达式、寄存器初值与显式 next-state，因此不需要从数学公式推断周期调度。
- 发射前可运行常量/布尔化简、结构 CSE、mux 树平衡、宽度隔离及可选算术/AIG 优化；随后 emitter 机械输出端口和 wire/reg 声明，用 `assign` 输出组合驱动，并把寄存器驱动集中为带 clock/reset 的 `always` 块。换言之，它能直接打印 Verilog，是因为 IR 已经接近 RTL，而不是因为省略了一个神奇的高层综合步骤。
- 流水寄存器、FSM 和主要时序结构在 Spire 源程序中显式创建；RTLScout 的 agent 或库负责选择这些结构，编译器不把任意组合公式自动调度成流水/握手电路。Spire 源码还明确警告部分可选化简尚未验证有符号语义，说明 IR 后端同样必须做独立等价或对拍验证。
- 对 VeriEvolve 的启示：可借鉴“agent 写小型硬件 DSL → elaboration 得低层网表 → 确定性 emitter”的浅编译路线，不必自建通用 HLS。我们的新增负担在 Spire 之外：显式定点量化、速率域/延迟、流式协议、DSP 构造，以及独立 bit-true 模型和系统容差判定；这些语义必须在原语程序或 lowering 中明确，不能期待普通网表 IR 自动补出。

## 2026-10-16：自研编译器的当前收敛顺序
- 当前不替换编译器，也不继续扩实验；先将方法一冻结为“面向 agent 的类型化原语语言与确定性编译器”。管线固定为：原语程序 → elaboration → 带 `signed/W/F/rate/latency/reset/state` 的语义 IR → 合法化与规范化 → 显式 reg/mux/counter/RAM/control 的微结构 IR → 独立整数模型与 Verilog 后端，并保留源节点到 RTL 的 provenance。
- 第一优先是语义完整性：定义无复位数据寄存器及暖机/valid 规则；按 `(clock, ratio, phase)` 规范化并复用速率域；允许带时序/速率语义的值经明确边界适配接到顶层输出；补位逻辑和带进位/借位加减。它们决定哪些硬件能够被正确表达。
- 第二优先是确定性 lowering：把 `delay` 规范化到唯一的寄存器链表示，避免与 `delay_line` 产生非语义性的面积差；把 `mac(share>1)` 的 `II、乘法器延迟、流水级、累加与输出延迟` 变成显式参数，由 agent 选择、编译器机械生成调度与 valid 对齐，不能静默猜测。
- 第三优先是反馈可定位：每个 IR 区域携带稳定 source/scope ID 到 RTL 名称、综合网表 cell 和 timing endpoint。综合跨区共享使“分段真实面积”通常不可严格相加，因此报告可归属、共享和未归属三类诊断面积；最终 PPA 仍以完整扁平设计为准，保持层次结果只用于定位。
- 每项修改用编译器验收而非新研究实验约束：原语级穷举/等价检查（适用时）、模型--RTL 逐位对拍、状态/复位/反压/多速率组合回归，以及 lowering 后规范 IR 检查。P0 语义稳定之前暂停用 agent 结果支撑搜索优越性，否则会把编译器缺陷或偶然 lowering 计为搜索收益。

## 2026-10-16：从手写原语编译器转向“可验证的 LLM lowering”
- 更合适的折中不是裸 LLM 直接从公式写 RTL，也不是继续扩张完整手写 lowering，而是保留一个小而确定的语义内核：原语 schema、类型/定点/速率/状态检查、可执行整数模型和冻结契约；由受限 lowering agent 把已验收的原语程序实现为 RTL，并以独立检查闭环修复。
- 两个 agent 阶段必须隔离：设计 agent 用 `REWRITE/TUNE` 改算法结构、精度和显式微结构承诺；lowering agent 只能在冻结候选的接口、状态、量化、latency/II、reset 和资源承诺内选择 RTL 编码。若要改变这些承诺，必须退回设计阶段产生新候选，不能在 lowering 中静默重解释。
- 每次 lowering 输出 `RTL + implementation manifest + source/scope 标注`，随后经过编译/lint、模型--RTL 数据与事务时序一致性、结构承诺检查、系统容差和真实 PPA。省掉的是大量逐原语 Verilog emitter 与特殊情况工程，不是语义定义和验证；验证工作反而成为可信性的中心。
- 这一路线能直接缓解当前缺口：无复位寄存器、MAC 共享流水、delay 实现和位逻辑可由 LLM 灵活实现；速率域身份、顶层边界、量化、warm-up/valid、资源数和时序契约仍由确定性 checker 约束；PPA 分段映射仍需 harness 根据 scope 标注和综合网表实现，不能交给 LLM 自报。
- 文献上，[HINT, 2026, arXiv:2608.07625] 已明确采用 LLM 友好的可执行硬件意图和 agentic RTL lowering，而非传统确定性 IR passes；[AI as a Compiler, 2026, arXiv:2609.36800] 在 Triton→PTX 中展示 AI lowering，但其成果依赖扩展后的强验证环境；[CktFormalizer, 2026, arXiv:2605.07782] 则代表类型化语言加确定性编译/证明的另一端。因此“LLM as compiler”本身已有强近邻，VeriEvolve 的增量必须落在通信 DSP 的定点/多速率/系统容差语义，以及设计搜索与受约束 lowering 的双环分离。
- 同一原语候选可能被随机 lowering 成不同 RTL。论文必须预先规定：把这些视为候选之下的“实现子节点”，单独计入调用/验证/综合预算并保留谱系；不能挑最好一次却把成本算成一次，也不能把 lowering 的随机 QoR 收益误归因于上层 REWRITE/TUNE。

## 2026-10-16：方法一的正式表述建议
- 方法一建议命名为：**可执行 DSP 原语契约与验证驱动的智能体 RTL 降低（Executable DSP Primitive Contracts with Verification-Guided Agentic RTL Lowering）**。正式文本不用宽泛的“LLM as compiler”，因为这会让人误解为以概率模型取代全部编译语义和正确性责任。
- 方法一的核心问题是：手写原语后端覆盖有限且把自身 lowering 偏置固化到所有候选；直接公式到 RTL 又把结构决策、数值语义和低层编码混在一起。本文把类型化原语程序冻结为可执行实现契约，由 lowering agent 在显式的接口、`signed/W/F`、量化、状态、速率、reset、latency/II 和资源承诺下生成 RTL，并通过方法二的独立一致性检查后才接受。
- 方法一可主张两项贡献：（1）面向通信 DSP 的可执行原语契约，使算法结构、定点精度、微结构承诺与最终 RTL 编码解耦；（2）受约束的 agentic lowering 协议及实现谱系，使同一语义候选能够产生多个 QoR 不同的 RTL 实现，同时禁止 lowering 静默改变候选语义。LLM 会写 Verilog本身、IR 本身或 agentic lowering 本身都不是单独的新颖点。
- 与 HINT 的分界必须明确：HINT 已做可执行硬件意图和 agentic RTL lowering；VeriEvolve 的增量在通信 DSP 的定点/多速率语义、允许近似的部署容差，以及“RTL 对候选必须忠实”和“候选对理想功能只需系统充分”的双关系。方法一产生前一关系所需的契约，方法二执行两层判定，方法三在契约候选与其实现子节点上搜索。
- 当前“LLM lowering 效果好很多”只记录为用户的开发观察；在冻结模型、prompt、调用/修复/综合预算以及同一任务集前，不写成优于手写编译器或直接 RTL 的正式结论。后续必需的路线对照是直接 RTL、手写确定性 lowering、契约约束 LLM lowering三者，并分别报告覆盖率、验收率、修复成本、PPA 和模型/RTL失配类型。

## 2026-10-16：方法一最终收缩为原语表示
- 方法一只主张原语表示，不再把自研编译器或 LLM lowering 本身列为贡献。建议一句话：**我们提出一种面向通信 DSP 的可执行类型化原语表示，将算法结构、定点精度、速率/状态与微结构约束显式化，使 LLM 能在可检查的语义空间中生成和优化 RTL。**

## 2026-10-16：与师兄讨论后冻结的框架图口径
- 输入压缩为“理想公式 + 任务契约（接口、系统容差、PPA 目标）”；设计 agent 在可执行类型化原语表示上执行 `REWRITE/TUNE`。LLM as Compiler 是把冻结原语候选实现为 RTL 的机制，不属于方法一的独立贡献。
- 方法二先区分 `bit-exact / math-equivalent / approximate`。逐位等价检查通过时，子候选继承父节点的系统质量结论，只重新检查 RTL 实现与 PPA；检查失败或本来就非逐位等价时，统一进入 SQNR/EVM/BER 等系统质量判定。
- 非逐位等价候选满足容差则进入 RTL 实现；近可行候选以 `OPEN` 保留并返回质量缺口供后续调优；非法或无恢复潜力的候选才舍弃。RTL 还需单独满足对原语候选的逐位与事务语义忠实性，再做真实 PPA 和 Pareto 归档。
- 图中明确两条不同的可信性关系：**RTL 对原语候选要求逐位/事务忠实；原语候选对理想公式只要求满足部署系统容差。**框架图源文件为 `thesis/midterm/figures/fig_llm_lowering_flow.drawio`，展示版为同目录 PNG/PDF。

## 2026-10-16：方法三保留 AND/OR 树，但不混同普通候选谱系
- “设计—实现双环”和“AND/OR 树”不是替代关系：双环区分原语设计与 RTL 实现，AND/OR 树负责设计外环中的区域分解、备选分支、父节点选择和评价回传；同一冻结契约的多个 RTL 也是实现层的 OR 子节点。
- 严格定义：OR 节点是带边界契约的待实现区域，不同 REWRITE/TUNE 是备选；AND 节点是一次分解后必须共同实现并装配的全部子区域。每个组合必须物化为完整原语程序并回到链路根做系统质量判定，不能把局部 SQNR/Pareto 简单相加。
- 当前 `archive.py` 和 `hier_agent` 已有追加式候选树、OR 分支、区域边界、父节点保留和根级评价，但尚未实现独立子区域前沿的自动组合与严格 AND 回传。因此当前只能称 AND/OR 搜索协议原型；贡献三需同预算对比 best-of-N、平坦 agent、OR-only 树和完整 AND/OR 树后再决定是否保留为论文结论。

## 2026-10-16：总架构图只画事实层的主流程
- 总图采用按执行顺序排列的阶段列，只回答“任务输入→原语级设计→候选判定→RTL 实现→PPA/选择→输出”。AND/OR 树、G0--G5 分支和逐位等价继承规则分别放到方法三、方法二细节图，不在总图前置展开。
- 当前仓库没有名为 `Verification Harness` 的独立系统部件；实际存在的是 `task.py`、`stimuli.py`、`metrics.py`、评价器与终验脚本。总图不得为了仿照参考版式虚构一个 harness 模块，Stage 0 只保留用户任务契约。
- 图的分工固定：`figures/v5/fig_framework_v5` 是唯一总架构图；`fig_llm_lowering_flow` 降为分层判定/反馈的细节草图，不再与总图并列代表系统架构。

## 2026-10-16：三项中期贡献的代码与文献复核
- 中期主线可定为：可执行的显式近似表示；系统容差与实现忠实性的分层判定；质量诊断驱动的设计与实现双环搜索。已有原型可支撑阶段汇报，搜索效率与 PPA 收益仍需同预算消融验证。
- “误差只从 q/const/lut 进入”只描述同一结构的定点化偏差；REWRITE 换滤波器或结构仍会改变理想解释，结构近似也必须显式登记并接受链级容差判定。RTL 的“零误差”指相对冻结候选不增加数值偏差，另需满足事务与时序契约。
- 文献边界：[Cheng 等, 2026, arXiv:2608.07625v2](https://arxiv.org/html/2608.07625v2) §4.1 已包含实现局部修复、架构变更返回前段及可选综合反馈，不能把双环分流本身当独立新意；[Shi 等, 2026, arXiv:2609.21697](https://arxiv.org/html/2609.21697v1) 已按全局误差界联合高层与逻辑近似，也不能笼统声称已有近似工作只看局部误差。[Gideoni 等, 2026, arXiv:2602.16805v2](https://arxiv.org/abs/2602.16805v2) 的 10 月更新进一步要求复杂搜索与简单基线公平比较。
- 证据边界：`dspc/judge.py::g1` 除相同 A 层哈希外依赖有限输入比较，T2 使用浮点误差阈值，不能当全输入数学等价证明；`g2` 是场景执行与扫频，不等于总体解析误差计算。`dspc/conform.py::check` 是向量对拍，当前忽略多余输出且延迟仅作提示，完整协议忠实性仍需补齐。`tests/test_dspc_judge.py::test_bug_invisible_on_search_scenarios_is_caught` 可作分层验证的机制案例，不代表完整漏检率评估。
