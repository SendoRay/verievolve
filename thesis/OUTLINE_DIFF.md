# 两份独立纲要的对比（2026-09-29）

- Claude 版：`OUTLINE_claude.md`
- Codex 版：Tin Can `msg_962f47905d234c7fad5d96b6`（写作时没看 Claude 版）

## 已经一致

- 错配（pass-rate ≠ 数值质量）只作动机，不称新定理，也不称「首次把误差放进适应度」；
- LLM 的角色是 **formula-conditioned architecture proposer**，不是裁判，也不是误差模型；它的价值只能由 2×2 交互项和结构覆盖证明；
- 主证据是 2×2 proposer × fitness 的 DiD：同预算、多 seed、held-out 场景、真实综合 PPA；
- 解析部分（A-op / A-bound / B、三契约、`r_η`）在正文最多占一节，长推导放附录；A-bound 不紧就撤掉主贡献地位；
- 「多公式的宽度 + 一条 DDC 链的深度」，不做 NCO-only，也不做完整收发机；
- 不做：零成本 / 加速卖点、H3、整链任意输入精确；纲要确认前不做实验。

## 分歧（需用户拍板）

| # | 问题 | Claude | Codex | 我现在的看法 |
|---|---|---|---|---|
| D1 | 贡献结构 | C1 评估器 / C2 机制 / C3 保证等级（附录） | C1 任务 + benchmark / **C2 方法 = LLM 结构提案器 + 带保证等级的 fitness** / C3 机制 + 系统 | **Codex 更好**：我的版本里 LLM 没进入「方法」，和用户说的「借用 LLM 的探索能力」对不上 |
| D2 | 生成形态 | 没写清 | typed design IR + 确定性 lowering 到 RTL；若只是模板参数就叫 architecture selection，不叫 RTL generation | 这是**用户必须决定**的：LLM 自由写 Verilog，还是在结构化 IR 里提议、由后端生成 RTL |
| D3 | benchmark | 现有 4 个 kernel（sincos / atan2 / cmul / llr）+ DDC | sincos / atan2 / **FIR·抽取器**（直接 / 对称 / 多相）+ DDC；cmul 只作 DDC 组件（direct/Karatsuba 在整数域逐位相同，不算数值结构多样性）；llr 有重尾且不成熟，不进主实验 | Codex 理由成立，但 FIR·抽取器的跨结构实现**仓库里还没有**，是新增工作量；来不及就换其他成熟的族，不能拿未验证的族凑数 |
| D4 | 2×2 阴性 | 降为「评估器 + benchmark + 负结果」 | 2×2 是 LLM 论文的 **go/no-go gate**：阴性就撤 LLM 标题；只有 numerical fitness 独立改变前沿、tiered evaluator 有独立收益、外部有效性成立这三条同时满足，才剩一篇 EDA 论文，否则只够硕论 / 开源报告 | 同意 Codex，更诚实 |
| D5 | 反馈内容 | 提出「只给标量 vs 给误差诊断」可能是 LLM 独有的优势 | 未涉及 | 可以作为一个消融，但会增加实验维度；是否纳入需要讨论 |
| D6 | 强基线 | 未列 | FloPoCo / SPIRAL 类 / 类内完整生成与字长优化，同口径比较 | 同意，必须有 |
| D7 | 标题 | Beyond Pass Rates: Structure-Aware Numerical Fitness for LLM-Driven Formula-to-RTL Evolution | VeriEvolve: Numerical-Contract-Guided LLM Exploration from DSP Formulas to Fixed-Point RTL | 倾向 Codex 的主语（LLM 探索）；若主实验靠 B 类，标题不能写 analytic |

## 合并后的建议骨架（待用户确认）

C1 任务 + benchmark → C2 LLM 结构提案器 + 带保证等级的数值 fitness → C3 2×2 机制 + DDC 系统案例；
2×2 作为 go/no-go gate。
