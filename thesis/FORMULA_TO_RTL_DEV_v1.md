# Formula → Architecture Plan → typed IR 开发说明 v1

- 日期：2026-10-08
- 状态：**方法开发中，不是正式实验协议**
- 目标：建立“数学公式与使用要求 → LLM 结构规划 → 可检查 typed IR → 数值模型与 Verilog”的最小闭环。

## 1. 三层表示

```text
Formula Request
  数学数据流、输入输出格式、采样率、质量上限、综合后端
        │
        ▼
Architecture Plan
  选择数学分解、硬件结构和定点参数；不允许任意 RTL
        │
        ▼
verievolve-search-ir-v1
  由确定性 lowering 产生，继续复用 bit-true、RTL 与综合后端
```

第一版只做 DDC 纵向切片。Formula Request 显式表示：32 位相位递推、复指数、复乘、33-tap FIR 和
二倍抽取，以及 Q1.11 输入、Q1.15 输出、链级 NMSE 上限和面积后端。公式本身不选择 LUT、CORDIC、
直接 FIR 或多相 FIR。

Architecture Plan 是 LLM 与非 LLM proposer 共用的完整规划语言。一个计划可以同时选择粗查表+残差
CORDIC 和多相 FIR，因此不再受旧 `proposal_contract.py` 的 1–2 个局部动作限制；但所有选择仍必须来自
同一个经过验证的构件库，不能夹带 Verilog、任意子树或隐藏字段。

## 2. 当前可规划构件

- 正余弦：quarter-wave LUT、rotation CORDIC、粗 LUT + 残差 CORDIC；
- 滤波抽取：直接对称 FIR、二相 polyphase FIR；
- 数值参数：表深、插值、相位位数、CORDIC 级数、分割位、系数字长、乘积裁剪、累加位宽和舍入。

计划携带 Formula Request 的 SHA-256。公式、质量上限或部署后端变化后，旧计划不能误用于新任务。
自然语言 rationale 不影响计划或候选的硬件身份。

## 3. 结构化反馈

编译入口只有两种结果：

```json
{"status":"ok","formula_sha256":"...","plan_sha256":"...","candidate_sha256":"..."}
```

或：

```json
{"status":"rejected","error":{"code":"...","path":"...","message":"...","detail":{}}}
```

后续 LLM repair loop 只接收这类机器生成反馈，不从异常堆栈猜测。每次 rejected 也要计入正式预算。

## 4. 开发与正式实验的边界

当前允许修改 Formula/Plan schema、构件库、提示信息和反馈格式，运行只用于开发，不作论文统计结论。
开发依次完成：

1. D0：严格 Formula/Plan schema 与确定性 lowering；
2. D1：每个结构族生成 bit-true 与 RTL，并做逐位一致验证；
3. D2：使用固定假 proposer 验证“拒绝 → 结构化反馈 → 修复 → 成功”的闭环；
4. D3：在公开开发任务上接入真实 LLM，记录首次成功率和修复轮数；
5. D4：接口稳定后，另写正式协议，冻结任务、held-out、预算、基线和判据。

正式实验必须让 LLM、GP、beam/MCTS 和随机方法使用同一 Formula Request、Architecture Plan 语法、
构件库、评价器和失败计费。开发结果不得冒充正式优势。

当前 D0、D1、D2 已实现。由 Formula Request 和完整 Architecture Plan 产生的多结构候选，已经进入原有
DDC 回归：整数 bit-true 输出与生成 RTL 逐位一致，流式输出阻塞时状态保持正确，并通过 Yosys 结构综合。
D2 的 provider-neutral 控制循环也已由固定假 proposer 验证：首个非法计划计入预算，第二次调用收到机器
生成的字段路径与错误码后修复成功；预算耗尽时所有失败提案仍完整保留。

下一步是 D3。它只属于方法开发：在公开任务上接入真实 LLM，观察合法率、首次生成成功率、修复轮数和
候选多样性。D3 结果不用于证明 LLM 优势；只有接口稳定并完成 D4 的任务、预算、基线和判据冻结后，
才能开展正式比较。

首次真实开发试跑使用 DeepSeek 官方 API。修正混合结构能力清单后，模型一次生成了 16 级 CORDIC 加
16 位直接对称 FIR 的合法计划；该计划通过 bit-true/iverilog 对拍和开发链级质量检查。Nangate45 ABC
综合在 600 秒开发上限内超时，未产生面积数字。结果目录为
`examples/comm_dsp_bench/experiments_system/formula_to_rtl_dev/dev-ddc-deepseek-20261008b/`。
这只是 D3 的工程反馈，不是 LLM 优于其他提议器的证据。
