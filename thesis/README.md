# 博士学位论文工作区

**题目（暂定）**：通信 DSP 领域数学公式驱动的 Verilog 自动生成方法研究——证书化评估与质量多样性进化

**形式**：Markdown 主稿 + PNG 图表（matplotlib 生成，源自真实实验数据）
**署名**：占位符（XXX 大学 / 作者：XXX / 导师：XXX 教授 / 学科：信息与通信工程）

## 章节规划（六章，约 9~11 万字）

| 章 | 文件 | 内容 | 数据依赖 |
|---|---|---|---|
| 摘要 | abstract.md | 中英文摘要 | 全部 |
| 第一章 绪论 | chapter1.md | 背景意义、三条研究线现状与空白、研究内容、组织结构 | 文献调研（2026-09） |
| 第二章 相关理论基础 | chapter2.md | LLM 代码生成与 OpenEvolve、定点误差分析、ε-等价与证书、e-graph | 文献 |
| 第三章 CommDSP-Bench 基准 | chapter3.md | 设计原则、任务族、评估协议、审计与修复、106 实例回归 | AUDIT.md + regression |
| 第四章 证书化评估体系 | chapter4.md | 评估 oracle 层级、模分解引理、四族证书模型、模型-RTL 验证、重尾发现 | certfit 验证数据 |
| 第五章 证书携带的进化搜索与实验 | chapter5.md | E1 两臂对比（DeepSeek 真实 LLM）、最终重判主表、E3 等价图、E4 BER、E5 消融 | experiments_e1 |
| 第六章 总结与展望 | chapter6.md | 结论、创新点回顾、局限、未来工作 | — |

## 实验数据索引

- `examples/comm_dsp_bench/experiments_e1/`：E1 两臂运行 + analysis.json + fitness_noise.json + rejudge.json
- `examples/comm_dsp_bench/certfit/`：证书引擎（引理 + 四族模板）
- `examples/comm_dsp_bench/AUDIT.md`：任务审计
- `examples/comm_dsp_bench/regression_report2.*`：106 实例回归（修复后）

## 写作规范

- 所有实验数字必须来自仓库内真实运行产物，写作时引用 json 字段
- 图表编号：图 4.1 / 表 5.2 …；每图注明生成脚本
- 引用格式：[作者, 年份, arXiv ID]；文献表在 references.md
- LLM 后端如实标注：deepseek-flash（DeepSeek API）为 Arm 主后端
