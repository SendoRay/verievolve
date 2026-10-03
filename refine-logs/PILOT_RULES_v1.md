# 两臂 pilot 的动作、锁图与失败规则 v1

- 日期：2026-10-01
- 状态：**实现规格草案，尚未启动 pilot**。与 `PILOT_MANIFEST_v1.json` 一同审查；不能凭此声称 S1。
- 回应独立反方的四组 blocker；不增加基线、代理模型或新 IR 节点。
- 收窄关系：这是旧 `SEARCH_PROTOCOL_v1.md` 正式搜索前的两臂可执行性 pilot，不承诺尚未实现的任意量化点移动，不前置 beam 或 LLM。

## 1. 要检验的变量

两臂都用同一 GP/NSGA-II 式引擎、种群上限8、同一初始3候选、同一完整main36评价和full-DDC面积。变量是：joint 始终允许结构/数值动作混合；staged 前半仅结构，后半锁结构族仅数值。

因此该对照直接检验的是**交错修改/锁图调度策略**，不能单独证明结构—数值参数协同，更不代表所有WLO。两轴必要性留给S1后的单轴消融。

## 2. 共同初始条件与标识

- 初始候选按 `dev_fixtures.development_candidates()` 顺序，三个hash见机器清单；各臂均占3次提案预算。
- 无效/重复提案均计预算；重复不重复插入种群，缓存仅省时间，不返还预算。
- 全部排序以 `(rank升序, crowding降序, candidate_hash字典序)` 确定。同一hash只保留一个种群/档案条目。
- 非支配排序使用原始有限 `(Q_main, area)`，精确比较，不在搜索选择中使用epsilon模糊排序。
- crowding 每个目标按 `(值, hash)` 排序；该目标极差为0时不贡献距离；否则首尾为infinity、内部累加相邻差/极差。infinity只用于选择内部状态，不作为质量/面积输出。
- tournament 从合格父代中不放回取2个，按上述序取胜；仅1个时直接选它。选择算法两臂一致。

## 3. 结构族键与锁定

结构族键是以下字段的规范JSON/hash：
- NCO根kind；leaf的kind及LUT interpolation；compose的两支kind及各自LUT interpolation；
- FIR kind。

不含 depth/stages/phase_bits/split_bits/rounding/系数位宽/乘积丢位/累加位宽。这些是 primitive 内数值参数，staged仍可优化，不能把WLO弱化为只调几个bits。

在计入第6次提案后锁定（pilot B=12，初始化也计入前半）：
1. 取结构阶段所有已评价且通过物理/数值有效性检查的候选，不只末代；允许Q超预算。
2. 计算共同rank/crowding序；每个结构族取排在最前的一个代表；按代表序保留至多3族。
3. 数值阶段种群保留当前属于所选族的成员，并补入缺失族的既有代表；不重新评价、不返还预算。按共同序截到8，且每个选中族至少保留一个代表。
4. 第7次起按所选族固定顺序轮转。只在该族成员里做相同tournament；新子代只能属于该族，否则当次非法。
5. 种群截断同样保留每族至少一个代表；其余名额按共同rank/crowding填充。joint不额外加族锁定。这种迁移/保留规则属于明示的锁图策略，不声称干预只改变一个布尔开关。
6. 若无有效父代，运行终止为inconclusive；不注入免费新种子。

## 4. 可重放动作

每次提案先抽patch长度：1或2，各1/2。顺序应用；第二动作的合法位置按**中间树**解析。任一步非法即整次提案失败、预算占1，不重采样；抵消回到原候选则按重复提案处理。

joint 每步抽结构/数值族各1/2；staged只用当前阶段允许族。所有实际动作记录类型、JSON路径、原值/新值和RNG状态，不能只保存自然语言描述。

### 4.1 结构动作（等概率选择以下5种）

| 动作 | 路径与继承规则 |
|---|---|
| swap_leaf | 从当前叶子路径字典序列表均匀选；LUT↔CORDIC。继承phase_bits。新LUT取depth256/linear，新CORDIC取stages12；删除旧类别专属字段 |
| change_interpolation | 从现有LUT叶子中均匀选；在其余nearest/linear/quad中均匀选；保留depth/phase_bits；无LUT则非法 |
| wrap_compose | 仅根为leaf可用；coarse复制原根，residual固定使用已有第二初始点的CORDIC12/b16原语，split_bits=8、rne/sat；不允许嵌套 |
| unwrap_compose | 仅根为compose可用；固定保留coarse叶子，将其恢复为读取完整相位的root；这是近似实现替换，不标记精确等价 |
| swap_fir | direct-symmetric↔polyphase；保留所有数值字段及类型，按新kind添加/移除phases=2 |

默认原语来自已有初始LUT/CORDIC定义，不按奖励选默认值。原有低级数compose fixture仍保留原配置；构造器产生的是新的candidate hash，不回写旧fixture。

### 4.2 数值动作

从当前树存在的数值参数路径中均匀选择一个：叶子的depth/stages/phase_bits，compose的split_bits/product_rounding，以及FIR coefficient_bits/product_drop/accumulator_bits/rounding。

- rounding切换到另一合法值。
- accumulator_bits 的0是无限精度哨兵，不是普通邻接数值：从其余 `{0}∪[20,48]` 均匀抽取。
- 其他有序参数：80%相邻档±1（方向各1/2，越界记失败），20%从其余全部合法值均匀跳转。depth按现有五档顺序。
- 加入全局跳转是为避免合法参数区间被mask失败或饱和区间隔断；相同算子用于两臂，不是奖励后的特例。
- 范围不变，来自现有schema；不允许任意移动量化点、输出格式或改变饱和策略。

## 5. 评价资格与失败处理

1. schema/动作错误：当次失败、计1，不进入种群。
2. FIR mask失败：当次部署无效、计1，不综合、不进入种群。
3. 主场景观察域的任何mixer/FIR饱和：当次无效、计1，保留计数与质量诊断，不进入种群。域为全部接受的mixer输入/实际保留有效FIR输出，均含前导；明确区别于旧全输入时刻FIR计数。此规则须作为搜索专用契约审阅，不篡改旧witness。
4. 有限Q但Q>q_budget：可以参与探索种群与完整探索档案；不能进入质量预算合格前沿。原compose按此统一规则处理，不删除它的历史记录。
5. 单候选600秒综合timeout：记录candidate resource failure，计1，不伪造area，不进入种群；允许下一提案。全局墙钟触顶导致的中断不是该候选独有失败，整次pilot记incomplete。
6. 环境/源码/输入身份漂移、意外评价异常、意外lowering/综合非零退出：保留失败尝试并停止pilot排查，不用惩罚分伪装可比较结果。
7. 最终输出集合：全部已评价候选中通过上述硬检查且main Q≤q_budget者的main非支配archive，不限末代种群。该集合/hash必须在任何held-out调用前固化。
8. pilot根本不访问held-out，不作S判定。未来终考只评价已固化列表，不从其他候选补点；held-out不合格的点可以被终考判无效，但不得据此重新搜索。

## 6. 调度与预算

- PCG64；seed=11、29、47；每seed两臂各12提案，合计72，初始化各占3。
- 同seed按proposal index交错执行两臂；第1/3个seed joint先，第2个seed staged先。每次只执行一个真实综合任务，不并发占满本机。
- 共享只读初始C/D缓存；后续精确缓存只在提交了完全相同身份的候选后返回结果，不能枚举其他臂已发现的候选或共享archive。
- 所有尝试都保留；缓存命中仍计1。墙钟不是此pilot的算法胜负判据，报告缓存顺序造成的时延差，不声称公平墙钟加速。
- 全局6小时上限；每次启动前检查剩余时长。触顶则保留已完成/在途状态，整个pilot=incomplete，不只比较完成更多的臂。
- p90成本样本：所有实际发起、非缓存的综合尝试；包含候选timeout，以600秒作为截尾值；普通成功取实际wall秒数。mask/schema失败不属于综合样本，系统性中止则不能选正式预算。
- p90用`numpy.quantile(method="higher")`。少于10个有效综合成本样本或p90>90秒，正式预算建议B=32；否则64。只按成本选，不按谁赢选。

## 7. 正式统计澄清（不在pilot中检验）

- 每个基线各用B；其前沿union累计用了2B。union只能标为更强组合参照，不叫与joint B同预算。
- 建议将主S比较改为两个明确的B对B对照：joint–staged、joint–cost-first。两者都超过预注册工程余量和HV标准才记S1；2B union单列辅助结果，不冒充一个B预算算法。这是正式运行前的草案澄清，不是看搜索结果后改判据。
- 每个seed用各自终考前沿的归一化HV。两项配对差各做10000次bootstrap；PCG64 seed271828；百分位使用`numpy.quantile(method="linear")`，95%区间下界均>0。两项同时要求成立，禁止只报告显著的一项。
- 至少3/5seed满足工程点条件；允许不同seed命中不同预登记网格，但须逐seed列明，不声称某一固定预算稳定改善。每个被计作成功的seed，在同一网格上必须胜过两个B预算基线的相应有限最优值。
- 空可行集：HV=0，预算格点最优值=null、regret=null并另报覆盖。没有有限参照不计作“超过epsilon”的数值改善，不填巨大常数。完全相同数值保留ties，展示按hash稳定排序。
- A_ref=38346.294 µm²。建议epsilon_A=383.46294 µm²（1%），**仅在另两固定候选的补重复校准通过后生效**；若重复不一致，停下来诊断，不扩大epsilon掩盖问题。已观察重复漂移不是概率分布上界。
- q_budget/epsilon_Q/HV坐标与预算网格沿用实验计划草案，不按pilot奖励改变。

## 8. 开跑前检查

- [ ] 本规则与机器清单完成独立复核，尤其默认值与锁图干预的命名边界
- [ ] actions实现/可重放与上下界测试
- [ ] 双臂种群、族锁定、平局、档案和预算一致性测试
- [ ] 非有限质量、失败/timeout、缓存身份、全局中止测试
- [ ] 另两固定候选补重复校准完成；记录epsilon_A是否生效
- [ ] 生成不可覆盖pilot运行manifest，才启动72提案；当前execution_allowed=false
