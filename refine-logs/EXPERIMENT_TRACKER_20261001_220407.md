# 实验跟踪表

更新：2026-10-01。TODO 不代表已获执行许可；正式搜索须先完成协议冻结。

| Run ID | 里程碑 | 目的 | 系统/变体 | Split | 指标 | 优先级 | 状态 | 备注 |
|---|---|---|---|---|---|---|---|---|
| dev-full-ddc-v1-20261001 | M0 | 首次真实成本接入 | 首个 LUT+direct | 无场景 | 映射完成性 | MUST | FAILED | `$scopeinfo` 元数据触发 check；剩余3项未运行，失败保留 |
| dev-full-ddc-v2-20261001 | M0 | 固定 full-DDC 成本与重复 | LUT/direct、CORDIC/polyphase、compose/polyphase，首项重复 | 无场景 | 面积/单元/stat/连接hash | MUST | DONE | 4/4成功；首尾四项一致；独立复核无blocker；不是epsilon_A |
| fixed-main-v1-20261001 | M0 | 主场景接入与可比性 | 同三候选 | main36 | 最坏q、覆盖、饱和 | MUST | DONE | 108个评价；观察域无饱和；compose超q_budget约10.02倍，不能标为质量合格 |
| regression-B-C-D | M0 | 接口与错误路径回归 | 当前IR/指标/记录/关联 | 合成/mocks及只读C产物 | 单测 | MUST | DONE | 177 passed；不是177个研究实验；Black未完成 |
| action-contract-v1 | M1 | 共同动作、两动作patch、预算/锁图规则 | 同语言GP/staged/cost-first | 合成 | 公平性/覆盖 | MUST | TODO | 需先独立审查动作初始化和阶段掩码；不扩IR |
| area-calibration-extra | M1 | 补另外两固定候选的重复观察 | CORDIC/polyphase、compose/polyphase | 无场景 | 面积/计数/连接一致性 | MUST | TODO | 2次建议；不把观测差当分布上界，不自动执行 |
| pilot-joint-staged | M2 | 成本/失败率/预算可执行性 | joint vs staged，同GP引擎 | main36 | 运行成本/完整性/方差 | MUST | TODO | seed 11/29/47；12次提案每臂，合计72；不判S |
| formal-S | M3 | 联合决策收益 | joint/staged/cost-first；beam参照范围待审定 | main训练→历史heldout终考 | 预算余量、配对HV CI、regret | MUST | BLOCKED | 5seed；B按预声明pilot成本规则取32或64；还需动作/饱和/epsilon_A/统计冻结 |
| conditional-axis-ablation | M4 | 单轴能否解释收益 | NCO-only/FIR-only vs joint | 同上 | 前沿覆盖/regret | 条件 MUST | NOT_STARTED | 仅S1后 |
| conditional-LLM | M5 | proposer×反馈交互 | GP/LLM×numerical/satisfaction | 同上 | 交互与绝对收益/成本 | 条件 | NOT_STARTED | S1前不实现或调用LLM；另行冻结预算 |

## 当前结论

工程证据已经从“能生成RTL”推进到“真实全链面积 + 同三候选完整主场景质量”。但研究主张仍未成立：compose是当前明确的质量负例，尚无联合搜索结果或S0/S1。下一步是把同预算反事实比较落实为共同动作和强基线，不是继续微调这三个开发点。

## 反方复核后的规则进展

四组最小blocker已转为 `PILOT_RULES_v1.md` 与 `PILOT_MANIFEST_v1.json` 的具体草案：共同动作/锁图、失败与探索资格、72提案调度以及2B union澄清。尚待独立复核与代码/校准验收，execution_allowed=false；没有运行pilot。
