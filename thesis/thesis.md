# 通信 DSP 领域数学公式驱动的 Verilog 自动生成方法研究
## ——证书化评估与质量多样性进化

> 学位类型：工学博士　　学科：信息与通信工程
> 作者：XXX　　导师：XXX 教授　　单位：XXX 大学
> （署名为占位符，交付后自行替换）

---

**目录**

- 摘要（中/英）：abstract.md
- 第一章 绪论：chapter1.md
- 第二章 相关理论基础：chapter2.md
- 第三章 CommDSP-Bench：公式驱动的通信 DSP 硬件基准：chapter3.md
- 第四章 证书化评估体系：chapter4.md
- 第五章 证书携带的进化搜索与系统实验：chapter5.md
- 第六章 总结与展望：chapter6.md
- 参考文献：references.md
- 附录 A：探索性预实验与设计决策依据
- 附录 B：可复现性索引（脚本与数据清单）

**图表索引**（PNG 于 figures/，由 examples/comm_dsp_bench/make_figures.py 生成）

- 图 3.1 stream_v1 流式握手时序（make_figures: fig3_1）
- 图 3.2 基线回归修复前后对比（fig3_2）
- 图 4.1 模分解引理与确定性积分的一致性（fig4_1_lemma.png ✓）
- 图 4.2 平滑族新鲜种子重评噪声（fig4_2_noise.png ✓）
- 图 4.3 证书-采样散点：平滑族 vs 重尾族（fig4_3_scatter.png ✓，数据 e2b_scatter.json）
- 图 5.1 两臂 Pareto 前沿对比 2×2（fig5_1_fronts.png ✓）
- 图 5.2 重判一致性散点（fig5_2_rejudge.png ✓）
- 图 5.3 E3 综合预算-前沿质量曲线（fig5_3_e3_nav.png ✓）
- 图 5.4 E4 位宽决策：BER 证书 vs SQNR 门槛（fig5_4_e4_ber.png ✓）

---

# 附录 A　探索性预实验与设计决策依据

以下预实验在正式实验设计定稿前完成，用于约束实验设计，其数据不进入主表
（manual 模式的应答器为确定性脚本，可复现但不代表真实 LLM 能力）：

1. **混合变异机制**（SPEC v0.4）：同一 checkpoint 起点的三组 52 迭代消融，
   diff-only / 全重写 / 混合(50%) 的超体积分别为 0.3550 / 0.4543 / 0.4579——
   确立正式实验统一采用混合模式。数据：ablation_results.json。
2. **结构跳变预演**（SPEC v0.3）：从 76.9 dB 天花板出发的 8 次全重写迭代产出
   4 个算法族、单迭代 +17 dB——确立了"算法类地板"假说与模板空间的动机。
3. **两级翻译基线**（B2，two_stage_baseline.py）：公式→浮点→无反馈定点化→RTL
   的单点产出 61.1 dB/2538 LUT，对照联合搜索同面积 +33 dB——两级流程的
   结构性损失的量化证据。

# 附录 B　可复现性索引

| 产物 | 路径 | 说明 |
|---|---|---|
| 基准规范 | examples/comm_dsp_bench/SPEC.md | v1.0，含版本记录 |
| 任务审计 | examples/comm_dsp_bench/AUDIT.md | 三层审计与修复清单 |
| 任务族生成器 | task_family_gen.py / family_baselines_gen.py | 110 实例与基线 |
| 评估器（L1 采样） | evaluator.py | Arm S 口径 |
| 证书引擎 | certfit/（common + 四族模板） | L2/L3 层 |
| 证书评估器 | cert_evaluator.py | Arm C 口径 |
| 消融评估器 | e5_cs_evaluator.py | Arm CS 口径 |
| E1 运行/分析 | run_e1.py / analyze_e1.py / rejudge_e1.py | experiments_e1/ |
| E3/E4/E2b | e3_nav.py / e4_ber.py / e2b_scatter.py | 同上 |
| 图表生成 | make_figures.py | thesis/figures/ |
| 回归报告 | regression_report.json | 106 实例（run4 口径） |
| LLM 后端 | DeepSeek deepseek-flash（OpenAI 兼容） | key 不入库 |

**LLM 使用声明**：E1/E5 进化实验共约 500 次 deepseek-flash 调用（思维链开启）；
所有 prompt 与应答原文在 experiments_e1/*/ 下留档。

---

# 附录 C　任务卡与核心代码摘录

本附录给出基准任务卡与证书引擎核心代码的真实摘录（完整文件见仓库），
供审阅者核对"规范→评估→搜索"链路的实现形态。

## C.1 任务卡示例：cordic_sincos（进入 LLM prompt 的规范全文）

```yaml
spec_version: 1
task: cordic_sincos
spec: |
  实现一个正弦/余弦函数发生器：给定角度 z，输出 sin(z) 与 cos(z)。
  接口为流式握手协议（valid/ready）。输入 z 为 16 位有符号数，
  线性编码角度：角度（弧度）= z * pi / 2^15，即 z 的取值范围
  [-32768, 32767] 对应 [-pi, pi)。
  输出 sin_out 与 cos_out 均为 16 位有符号数，格式为 Q1.15 定点。
  复位释放后，每当 in_valid 与 in_ready 同时为高的时钟上升沿，DUT 采样一组输入；
  对应的输出应在 out_valid 为高时给出。每组输入恰好产生一组输出，顺序保持。
  设计目标：在精度（相对浮点参考的 SQNR）、综合面积、吞吐三者之间
  探索不同的折中点，不同折中点都有价值。
io_protocol:
  base: stream_v1
  inputs:
    - {name: z, width: 16, signed: true, format: "signed 线性角度, [-pi, pi)"}
  outputs:
    - {name: sin_out, width: 16, signed: true, format: "signed Q1.15"}
    - {name: cos_out, width: 16, signed: true, format: "signed Q1.15"}
golden:
  stimulus: {distribution: uniform_angle, samples: 65536, seed: fresh_per_eval}
metric: {type: sqnr}
constraints: {}
```

规范中**没有出现任何算法名词**（CORDIC/查表/插值均未提及）；"不同折中点都有
价值"是唯一的口径提示，不泄露任何实现路径。

## C.2 证书引擎核心：残差分布的赋值分解（common.py 摘录）

```python
def _residue_dist(s: int, nbits: int) -> np.ndarray:
    """A = a·c 的残差分布 P(A mod 2^s)，a,c 独立均匀于 2^nbits 个连续整数。
    精确性条件：s ≤ nbits-1。由 (ν(a),ν(c)) 赋值混合给出：
      ν(a)=j, ν(c)=k, j+k<s → r 均匀分布于 ν(r)=j+k 的残差类
      j+k ≥ s 或 a≡0 → r = 0"""
    size = 1 << s
    r = np.arange(size, dtype=np.int64)
    lowbit = np.bitwise_and(r, -r)
    nu = np.zeros(size, dtype=np.int64)
    nz = r > 0
    nu[nz] = np.log2(lowbit[nz].astype(np.float64)).astype(np.int64)

    pnu = np.array([2.0 ** -(j + 1) for j in range(nbits)] + [2.0 ** -nbits])
    dist = np.zeros(size, dtype=np.float64)
    for j in range(nbits + 1):
        for k in range(nbits + 1):
            p = pnu[j] * pnu[k]
            t = j + k
            if t >= s:
                dist[0] += p            # A ≡ 0 (mod 2^s)
            else:
                mask = (nu == t)
                dist[mask] += p / float(mask.sum())
    return dist


def cmul_exact_err_moments(drop: int, mode="rne", karatsuba=False):
    """输出量化误差的精确矩（引理 4.1/4.2）。关键点：Q(v) 的误差只依赖
    v mod 2^drop，而 v mod 2^drop 的分布是乘积残差分布的**圆卷积**。"""
    distA = _residue_dist(s=drop, nbits=16)
    distV2 = _circular_conv(distA, distA)          # re = A − B
    re_mean, re_mom2 = _phi_moments_over_dist(distV2, drop, mode)
    if karatsuba:
        distA17 = _residue_dist(s=drop, nbits=17)  # P1 = (a+b)(c+d)
        distV3 = _circular_conv(_circular_conv(distA17, distA), distA)
        im_mean, im_mom2 = _phi_moments_over_dist(distV3, drop, mode)
    ...
```

## C.3 生成的 RTL 示例：证书参数点 so=8, sd=2, trunc, karatsuba

由 `tpl_cmul.generate_verilog()` 从参数生成（与整数域模型逐位对应，经 4.4 节
的 0/65536 失配验证）：

```verilog
// certfit 参数化复数乘法器 so=8 sd=2 mode=trunc structure=karatsuba
    wire signed [16:0] a_e = a + 17'sd128;      // RNE 预加半
    wire signed [8:0]  a_h = a_e >>> 8;         // 操作数丢 8 位
    ...
    wire signed [17:0] pac = $signed(a_h) * $signed(c_h);
    wire signed [18:0] sab = $signed(a_h) + $signed(b_h);
    wire signed [37:0] p1  = sab * scd;         // Karatsuba 中项
    wire signed [34:0] re_pre = (pac_x - pbd_x) <<< 16;
    wire signed [34:0] im_pre = (p1_x - pac_x - pbd_x) <<< 16;
    wire signed [34:0] re_q = (re_pre >>> 2) <<< 2;   // 输出丢 2 位（截断）
```

该设计（so=8, sd=2）的证书值 45.15 dB，RTL 实测 45.17 dB，面积 1884 LUT
（全精度基线 6828 LUT 的 27.6%）——"精度-面积可谈判"的一手例证。

## C.4 实验产物的可复现性索引

| 数据 | 文件 | 生成脚本 |
|---|---|---|
| 两臂前沿与 HV 曲线 | experiments_e1/analysis.json | analyze_e1.py |
| 重判一致性 | experiments_e1/rejudge.json | rejudge_e1.py |
| 证书-采样全空间扫描 | experiments_e1/e2b_scatter.json | e2b_scatter.py |
| 导航预算曲线 | experiments_e1/e3_nav.json | e3_nav.py |
| BER 选型 | experiments_e1/e4_ber.json | e4_ber.py |
| 重评噪声 | experiments_e1/fitness_noise.json | e2a_fitness_noise.py |
| 全量回归 | regression_report.json | regression_all.py |
| 图表 | thesis/figures/*.png | make_figures.py |
