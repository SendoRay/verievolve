# 中期报告图表源码

每张图一个独立脚本，数据以字面量写在脚本顶部的 `# ===== 数据（可直接修改） =====` 区块中，不读取任何外部文件。

```bash
cd thesis/midterm/figures/src
python fig_main_area.py        # 生成单张图
for f in fig*.py; do python $f; done   # 全部重画
```

输出：`figures/<名字>.png` 和 `.pdf`，同时把 pdf 复制为 `/Users/chengzhy/ucasproposal-master/Img/mid_<名字>.pdf`（LaTeX 直接引用）。共用的配色、字体和保存函数在 `style.py`。

字体口径：普通图文统一使用 `PingFang SC`（苹方-简，macOS 的标准简体中文界面字体）；Linux 和 Windows 分别回退到 `Noto Sans CJK SC`、`Microsoft YaHei`，最后才回退到 `Hiragino Sans GB`。代码片段使用 `Menlo`。`font_config.py` 会从系统 TTC 字体集中精确注册简体字面，`style.py` 以嵌入字体的 PDF 输出，避免 Matplotlib 静默回退到日文字形、Arial Unicode MS 或生成 Type 3 字形。

| 脚本 | 论文中的图 | 数据来源（抽取时） |
|---|---|---|
| `fig1_comm_chain.py` | fig:chain 通信收发链路（已重画为 U 形，只标数字前端） | 示意图 |
| `fig2_system.py` | fig:system 系统架构 | 示意图 |
| `fig3_method.py` | fig:method 计算图、原语 IR 与后端 | 示意图 |
| `fig4_motivation.py` | fig:motivation 直写 vs 教科书结构面积 | `main_table_v2_20261010.json` |
| `fig_main_area.py` | fig:mainarea 链 A 主结果面积 | `main_table_v2_20261010.json` |
| `fig_scatter_margin.py` | fig:margin 搜索/留出裕量，裁判 v1/v2 | `margin_pairs_v1_v2_20261010.json` |
| `fig_scatter_area_timing.py` | fig:timing 面积–关键路径 | `timing_summary_v1_20261011.json` |
| `fig_c1_lineage.py` | fig:lineage 演化路径 | `ancestry_M_r32w_r64n_v2_20261010.json` + 实验汇报 |
| `fig_c2_stagewise.py` | fig:stagewise 逐级 vs 整链、误差份额 | `e21_stagewise_v1_20261011/E21_summary.json`、`error_shares_E22_normalized.json` |
| `fig_c3_curves.py` | fig:curves 同预算进化曲线 | `curves_M_B3_v2_20261010.csv`（只保留最优值变化点） |
| `fig_c3_feedback.py` | 反馈档位消融 | `groupA_v1_20261011/A3_feedback_4seeds_analysis.json` |
| `fig_agent_trace.py` | 编码智能体在本框架工具上的设计轨迹（R32 窄带） | `/Users/chengzhy/verievolve_agent_ws/dev_r32_narrow/candidates.jsonl` |
| `fig_ppa_r32n.py` | R32 窄带 5 个设计的 PPA（OpenSTA） | `/Users/chengzhy/verievolve_agent_ws/ppa_r32n/summary_fast.txt` |

实验 JSON/CSV 位于 `/Users/chengzhy/.codex/worktrees/da43/verievolve/examples/comm_dsp_bench/experiments_dspgraph/`。旧的 `../make_*.py` 仍保留，它们直接读这些文件。

口径说明：
- `fig_agent_trace` 的面积是代理模型估计；两条参考线是真实综合面积。达标判断含 0.3 dB 安全裕量（c31 裕量 0.261 dB 记为未达标）。
- `fig_ppa_r32n`：Yosys + 快速 ABC 映射到 Nangate45 typical，OpenSTA 做时序与功耗，时钟 2 ns，全局翻转率 0.1（不是基于仿真的翻转率）。
