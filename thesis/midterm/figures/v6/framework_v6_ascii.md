# 框架图 v6 草图（ASCII，待确认）

用等宽字体查看（VS Code 打开本文件即可；预览模式下代码块也是等宽）。确认后再画 drawio 版。

```text
      Stage 0                   Stage 1                    Stage 2                  Stage 3                 Stage 4
  Task Preparation          Primitive Design           Candidate Check            RTL Lowering         Synthesis & Output
====================    ========================    ======================    ====================    ====================

+------------------+    +----------------------+    +--------------------+    +------------------+    +------------------+
|  Task Contract   |    |  Design Agent (LLM)  |    |    1. Legality     |    | Frozen Contract  |    |     Real PPA     |
+------------------+    +----------------------+    +--------------------+    +------------------+    +------------------+
| F ideal function |    | REWRITE: structure   |    | type / rate check  | +->| interface, quant.| +->| synthesis + STA  |--+
| Q quality bound  |--->| TUNE: bits, rounding,|--->| verify declared    | |  | state, latency/II| |  | area/timing/power|  |
|   (metric, tol.) |    |   pipelining, reuse  |    | relation: bit-exact| |  | resources        | |  +------------------+  |
| I interface +    |    +----------------------+    | / math-eq / approx | |  +------------------+ |           |            |
|   PPA target     |         ^                      +--------------------+ | p         |           | R         v            |
+------------------+         |  select parent                 |            | a         v           | T+------------------+  |
         |                   |                                v            | s+------------------+ | L|   Pareto Front   |  |
         v              +----------------------+    +--------------------+ | s|  Lowering Agent  | |  +------------------+  |
+------------------+    |  AND/OR Search Tree  |    | 2. System Quality  | |  |    |        ^    | |  | FEASIBLE nodes:  |  |
| Initial Program  |    +----------------------+    +--------------------+ |  |    v        | fix| |  | quality vs. PPA  |  |
+------------------+    | node = a complete    |    | SNR / EVM / BER    | |  |  Fidelity Check  |-+  +------------------+  |
| direct transl.   |--->|   primitive program  |    | within tolerance?  |-+  | RTL == candidate |             |            |
| = tree root      |    | OR : alternative     |    | bit-exact edits:   |    |  (bits + txns)   |             v            |
+------------------+    |      edits of region |    | inherit parent     |    +------------------+    +------------------+  |
                        | AND: sub-regions     |    +--------------------+                            |   Final Check    |  |
                        |      built together  |              |                                       +------------------+  |
                        | BROKEN / OPEN /      |              | fail:                                 | unseen scenarios |  |
                        | FEASIBLE / VERIFIED  |              | BROKEN or                             | no feedback      |  |
                        +----------------------+              | OPEN + gap                            +------------------+  |
                                   ^                          |                                                |            |
                                   |                          |                                                v            |
                                   |                          |                                       +------------------+  |
                                   |                          |                                       |      Output      |  |
                                   |                          |                                       +------------------+  |
                                   |                          |                                       | Verilog + report |  |
                                   |                          |                                       +------------------+  |
                                   |                          |                                                             |
                                   +--------------------------+----------- feedback: node state + measured PPA -------------+
```

## 读图顺序

1. **Stage 0**：Task Contract 给出 F（理想功能）、Q（质量约束：指标 + 容差）、I（接口 + PPA 目标）。由 F 直译出 Initial Program，作为搜索树的根节点和基线。
2. **Stage 1**：Design Agent 从 AND/OR Search Tree 里选一个父节点（select parent），用 REWRITE 或 TUNE 改出一个新候选。
   - 树的每个节点 = 一份完整原语程序；
   - OR = 同一区域的不同改法（互为备选）；AND = 一次分解后必须一起实现的子区域；
   - 节点状态：BROKEN / OPEN / FEASIBLE / VERIFIED。
3. **Stage 2**：新候选先过 1. Legality（类型/速率检查 + 核实声明的关系），再过 2. System Quality（SNR/EVM/BER 是否在容差内）。
   - 通过（pass）→ Stage 3；
   - 不通过 → 记为 BROKEN 或 OPEN（附缺口），经底部反馈总线写回树；
   - 已核实的 bit-exact 修改直接继承父节点的质量结论，不重测。
4. **Stage 3**：通过的候选冻结为 Frozen Contract；Lowering Agent 在契约内写 RTL，由 Fidelity Check 检查 RTL 与候选逐位、按事务一致。不一致就在框内局部修复（fix），不回到树。
5. **Stage 4**：RTL 做综合与 STA，得到真实 PPA（同时经反馈总线写回树）→ 在 FEASIBLE 节点中取质量–PPA 的 Pareto Front → Final Check 用搜索从未见过的场景复测，结果不回传 → 输出 Verilog 和报告。

## 相对旧图的改动

- 主流程只有一条，从左到右；回到树的反馈合并成底部一条总线。
- Stage 3 的局部修复画成循环框（参照 HINT 的 Verify & Debug Loop）。
- bit-exact 继承不再画单独箭头，写在 System Quality 框内。
- 删除 Faithful RTL 框和 M1/M2a/M2b/M3 标签；三个方法的对应关系改写在图注中：
  Method 1 = Stage 1 中被修改的原语程序；Method 2 = 检查 1、2 与 Fidelity Check；Method 3 = AND/OR 树及其反馈回路。
- drawio 版：五列统一浅底色 + 灰色表头，放大字号。

## 待你确认

1. Stage 4 的 Final Check 是否保留？（作用：用未见过的场景复测且不回传，防止设计“背题”。）
2. Task Contract → Design Agent 的箭头（智能体能看到契约）是否保留？
3. Stage 名称 *Candidate Check* / *RTL Lowering* 是否可以？
