# 执行 RESEARCH_PLAN 第一阶段（P0 预实验启动）

依据计划 §6.1（两周预实验）、§11（第一阶段待办）、§9.3（先修最小子链路径上的数值模型）。探索已确认：common.py 两处 bug 已定位；DDC 代码不存在需新建；本机无 EDA 工具需先安装。

## 第 0 步：环境准备
`brew install yosys icarus-verilog verilator`（标准开源 EDA 工具，仓库 evaluator 本身依赖）。装完用 `python evaluator.py <design.v>` 跑通单测，记录单次仿真/综合耗时。若安装失败，按计划 §6.1 允许，只报告数值预实验状态。

## 第 1 步：修复复乘误差矩 + 建立穷举回归（§9.3 第 1 行）
- 修 `certfit/common.py`：`_residue_dist` 将 A≡0（r=0）与奇数残差类分离；`cmul_exact_err_moments` Karatsuba 分支修正相关项处理（im=ad+bc 中 ad⊥bc 的正确卷积结构，以代码实读为准）。
- 新建 `regression_cmul_moments.py`：小位宽全枚举 vs helper 逐点一致（drop × rounding × structure 矩阵）；代数等价结构在相同输出量化下误差矩必须相等。
- 验收：drop=1、half-up 时 helper = 穷举 = 0.375。
- 更新 `make_figures.py` fig_lemma 数据源、在 AUDIT.md 登记修复及受影响的论文数字。

## 第 2 步：冻结 DDC 子链（新建 `chains/ddc/`，§9.2 布局精简版）
- `ref_chain.py`：float64 参考链 = 复混频（理想 sin/cos）→ 接收 FIR → 抽取；输入为 QPSK/RRC 场景 + 干扰 + 噪声（seed 冻结）。
- `fixed_chain.py`：整数 bit-true 定点链（NCO 相位截断/LUT 插值/CORDIC、复乘截断、系数量化/累加位宽/舍入），位语义对齐既有 design_gen/tpl_*。
- `scenarios.py` + manifest JSON：3 类场景（无强干扰 / 带外干扰 / 近抽取混叠边界）× 多频移/幅度，参数按参考链可行工作区间确定，先冻结后评估。
- `metrics.py`：逐级局部 SQNR/SFDR（逐字段最差口径）、系统 EVM（相对同输入浮点参考，冻结对齐并报告原始偏置）、带内误差。

## 第 3 步：候选池与实验 S1（§6.1 第 4–10 天）
- `candidates.py`：6 NCO × 8 FIR × 2 复乘 = 96 组合；功能检查后全组合 × 全场景数值评估。
- 对照模型：局部 SQNR、SQNR+SFDR、经典频谱加权（FIR 响应加权 + 抽取混叠项）。
- 产出：排序反转清单、候选保留率、动机图 1（局部排序 vs 系统 EVM）；数据存 `experiments_system/s1_local_vs_system/`。

## 第 4 步：硬件初步（§6.1 第 11–14 天，工具就绪时）
- 冻结子集 24–48 组合走 yosys + Nangate45 综合面积（只称综合结果，不称物理实现）。
- 分阶段筛选 vs 全枚举参考最优的初步对照；联合搜索框架留待下轮。

## 第 5 步：文献对照（§11 前两项，后台并行执行）
核对 R1–R8 直接相关算法；追踪多速率量化误差、NCO 杂散建模、接收机字长优化、层次化 DSE 先例。产出 `thesis/LIT_GAP.md`（已有方法—当前限制—拟验证差距表，重点检查是否已有上下文相关候选筛选）。

## 第 6 步：汇总
`experiments_system/P0_REPORT.md`：动机图数据、失败实例、按 §6.3 规则给出继续/收窄判定；更新 AUDIT.md 与 RESEARCH_PLAN 待办勾选。

## 明确不做（本轮）
tpl_llr 聚合不一致、e4_ber、cmul task golden 刻度问题（不在最小子链路径，按 §9.3 只登记）；OpenROAD 物理实现（macOS 无 P&R 流程）。不做 git commit。

## 验收标准
- 回归通过：helper = 穷举（0.375 基准），等价结构误差矩一致。
- S1：96 组合 × ≥3 场景数据落盘、seed/manifest 冻结可复现。
- LIT_GAP.md 覆盖 R1–R8 + ≥4 条新追踪文献。
- P0_REPORT.md 给出明确的继续/收窄建议。