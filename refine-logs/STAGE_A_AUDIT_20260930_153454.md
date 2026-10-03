# 阶段 A：typed IR 接入审计最终结论

- 完成时间：2026-09-30 15:34（本地时间）
- 范围：IR 身份、质量适配、综合缓存、运行/预算四域及独立复核、跨域完整性检查。
- 状态：**A 已完成；可据此准备 B 的最小代码计划，不代表 B 获准实施，不放行 C/R4 或正式搜索，不判 S0/S1。**
- 本轮有纯 Python 单测与临时 fixture/mock；没有运行 RTL 仿真、真实综合、正式场景 truth、搜索或 LLM 实验。
- 实现、冻结协议及原暂存区未改。主会话仅写研究记录；并行出现的用户笔记保留原样。

## 1. 宏观结论不变

近期任务是获得一次能决定联合结构/定点化路线是否继续的可信比较，不是扩建平台。先明确 S 比较命题，开发最小评价闭环；强非 LLM 正式验证有收益后，才研究 LLM 增量。

本文是工程条件清单，不替代 `FINAL_PROPOSAL.md` 的研究问题，也不把基础设施缺口当研究负结果。

## 2. 直接影响新接入的代码问题

| 问题 | 证据位置 | 最小处理 |
|---|---|---|
| 固定字段及零哨兵接受 bool/int 等类型别名 | `examples/comm_dsp_bench/search_ir/validate.py:54-61,83-86,98-99,153-165,198-217` | 按项目严格类型策略先验类型、再验固定值；signed 只收 bool；补原始 JSON 负例 |
| 枚举/depth 的 list/dict 泄漏 TypeError | 同文件 `:48-51,98-99` | 先验字符串/整数，再检查集合；统一带字段路径的 IRValidationError |
| 非有限 q 可被 max 忽略，结果依赖顺序 | `examples/comm_dsp_bench/chains/ddc/run_witness_v1.py:321` 的聚合路径 | 新公共评价边界拒绝 NaN/Inf、缺场景和不完整结果，不将异常候选记作有效 Q |

前两项可导致非法别名获不同结构 ID，但没有短样本数值错误或实际缓存污染证据。NaN 问题由合成数组复现；没有发现当前合法整数 IR 自然产生 NaN，也不据此否定历史 witness。

若新 adapter 不复用旧聚合 helper，可在独立新边界满足同一验收，不要求修改被历史指纹绑定的旧 runner。

## 3. 不能静默继承的两项契约

### 3.1 类型合法不等于部署 FIR 可行

IR 支持的低系数字长可能不满足旧链的通带/阻带掩码。类型校验允许它们本身不是缺陷：需在独立部署可行性阶段，针对实际量化系数检查既有掩码并记录来源与结果。

依据：`search_ir/validate.py:159-170`、`search_ir/lower_bittrue.py:132-136`、`chains/ddc/candidates.py:109-136`（均在 `examples/comm_dsp_bench/` 下）。不能通过抬高 schema 最低字长、缩小候选池来绕过这项区别。

### 3.2 新旧饱和计数范围不同

旧 `chains/ddc/fixed_chain.py:149-168` 在全部输入时刻计饱和；新 `search_ir/lower_bittrue.py:199-211` 只在保留抽取输出上计数。临时脉冲诊断出现保留输出逐位相同、计数不同。

这不是数值错误，不能为追平计数而强迫新实现计算不会输出的样点；但也不能将同名 `n_sat_fir` 直接接到旧的“非零即拒绝”规则并宣称契约未变。

**实施前需明确**：量化点、事件定义、预热/接受输入/有效输出/测量段范围、累加和输出是否分开计数，以及哪些计数影响硬可行性。本轮不替用户决定或改阈值。

## 4. 统一后的接入缺口

### 身份与结果封装

结构 hash 保持其结构身份职责。新 adapter 需绑定实际代码/系数、评价输入/FCW/参考/指标及综合 RTL/top/工具库脚本；结果回显并验证来源摘要。三个独立缓存系统不是必需，可以使用完整复合身份或不可变 run 上下文，第一版也可以禁用缓存。

注意：
- 运行时 FCW 属评价输入，不要求为每个 FCW 重综合同一 RTL。
- attempt/run 身份不是计算身份；将来缓存命中需生成属于当前 attempt 的结果 envelope。
- 不制造“RTL 含 manifest hash、manifest 又含该 RTL 字节 hash”的循环依赖。
- 实际执行内容不能仅用 git HEAD 或 dirty 标志代表，因为工作区可能有未提交源码。

### 提案账本与不可覆盖

parse 前登记原始提案、attempt_id 与一次预算占用；无合法 IR 时允许 candidate hash 为空。后续补充成功、重复或分阶段失败状态。

“一次提案算一次”不是每个阶段各扣一次；内部 retry/tool-call 另计成本。同内容再次提交是新尝试。第一版可以明确不支持 resume：失败 run 保留，同 run-id 不得重启覆盖。

旧 witness 已有独占 run 目录和 execution→preflight/输入摘要链；新 typed IR 尚未接入，不应抹去旧保护，也不应把它外推到新管线。

### 反馈与公共动作

正式比较前必须将私有审计记录与搜索器可见状态分离。只在 prompt 里删 q 不够：连续量仍可能经 selection、archive、特征、历史或 artifacts 影响 satisfaction 臂。投影应在这些搜索决策之前完成。

共同 schema 不等于共同动作语言。LLM 一次改多个子树、非 LLM 一次只能改一个参数，或者某方免费重采样非法动作，都会混淆比较。公共动作规则在 proposer 阶段验收；B 的固定 fixture 模式无需先实现全部搜索器和动作 API。

### 真实全链面积

新 IR 的层级 RTL 与旧 NCO-only 成本不是同一对象。C 前明确 full-DDC scope、top、flatten/层级统计、工具/库/脚本/约束及成功判据；先要求进程退出成功，再验证完整映射与面积。结构检查或旧 NCO-only 面积不能代替 R4。

## 5. 旧路径的条件性问题：避免牵动历史证据

| 路径 | 经 mock/fixture 核实的问题 | 影响边界 |
|---|---|---|
| `cert_evaluator.py:76-114` | 旧参数缓存不绑定生成物/综合依赖，可固化可选 ASIC 失败 | 新 adapter 不复用旧缓存；未证明历史面积受影响 |
| `run_witness_v1.py:198-211`、`run_s2.py:47-58`、`evaluator.py:422-435` | 有可解析 stat 时未拒绝非零退出 | 未来实际使用的后端必须修正成功判定；本轮未运行 Yosys |
| `prepare_witness_v1.py:248-251` | 准备入口可覆盖已有 preflight | 新版本使用独占路径；旧 execution 会拒绝摘要漂移 |
| `prepare_witness_v1.py:145-154` | 报告消费未严格核对完整候选、布尔 pass、零 mismatch/coverage | 当前历史报告实际匹配；不能由坏 fixture 推导历史造假 |
| `run_linear_baseline_v1.py:182-203` | 新输出路径下未验证 truth→execution 的绑定 | 默认 OUT 已存在会拒绝；仅未来复用且前置校验通过时可达；不否定已有 E1 |

以上路径均在 `examples/comm_dsp_bench/` 或其 `chains/ddc/` 下。没有必要为了 B 全面改写旧工具或历史 manifest；新隔离实现可避开这些问题。

## 6. 推荐的最小 B 工作包（未实施）

1. 先明确 S 的比较口径，以及继承哪些质量/场景字段、饱和统计域与新全链成本 scope。
2. 修复两项 validator 缺陷，补直接 JSON 负例。
3. 新增一个小运行层：开发 manifest/身份验证、固定 fixture 评价、append-only attempt 记录与独占输出。代码可按职责拆小文件，但不预先建设完整平台。
4. 初版禁用缓存、不支持 resume、不接 proposer；声明这些能力未启用。真实面积尚未产生时返回明确 unavailable/pending，不能用估算数填充。
5. 验收合法 fixture、非法 JSON/type、非有限质量、缺/重复场景、mock 阶段失败、重复提案、身份漂移、manifest 回显与拒覆盖。
6. 软件边界通过后，再单独提出 C 的小集合真实综合计划；后续 proposer/正式协议按既定顺序审阅，不在本次启动。

B 只需先确定开发字段及生命周期，不能要求正式预算、种子数、最终面积阈值都在开发评价器之前冻结。尚未生成的结果字段如实为空或 pending。

## 7. 本轮验证记录

- IR 域：限定纯 Python **20 passed、9 deselected**。
- 质量域：指标、少量场景元数据、FIR/schema 非 RTL 子集 **32 passed**。
- 预算域：schema 与指定 preflight/聚合/历史报告检查 **8 passed**。
- 综合域：从实际函数体提取的内存/临时目录 mock，以及身份摘要检查；**没有真实综合**。
- 测试集合有重叠，不相加成一次完整回归，也不复用此前 87 passed 冒充本轮结果。
- 完整命令、各域证据/反证与诊断限制保存于 `stage-a-audit-20260930_153454.json` 的 `verified[*].verification_commands/limitations`；未落盘的临时诊断脚本不是持久测试，未来修复仍须补回归。
- 现有部分历史引用链一致性已核对；这是文件一致性，不是新一轮 truth、模型—RTL或面积复验。
- 主会话检查原暂存区 diff SHA-256 始终为 `13008359d3f6c0389038fe223db0c304fed82ece67184b5087a78768b4b21e80`。`git diff --check` 与 `git diff --cached --check` 在前次记录检查通过，最终文件登记后再检查一次。

## 8. 最终状态

**A 完成；B 是下一份待审实现计划；C/R4、非 LLM pilot、正式搜索与 LLM 实验均未启动。**

最重要的成果不是发现更多修补项，而是把实施范围压缩为支撑核心研究比较的最小闭环，并明确哪些契约不能靠接代码默默改变。
