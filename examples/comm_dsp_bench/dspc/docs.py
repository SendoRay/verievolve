"""给 agent 读的原语文档（PRIMITIVES.md）。与 prog.py 的语义保持一致。"""

PRIMITIVES_MD = """# 原语参考（dspc）

候选程序写成 `def build(g, spec):`。`g` 是原语程序构造器，`spec` 给出任务参数（例如 `spec.output_bits`）。
可用的模块：`np`、`math`、`scipy`、`lib`（构造函数库，见文末）。

## 核心约定

- 每个信号带定点格式 `s<W>.<F>`（有符号）或 `u<W>.<F>`（无符号）：数值 = 整数码 × 2^-F。
- 每个信号带速率（相对输入样点率的有理数）。同速率的两个信号按样点序号逐一配对；常数可与任何速率组合。
  不同速率直接组合会报 `rate_mismatch`。
- **误差只能经由近似点进入**：`q`（舍入、饱和）、`const`（值不能精确表示时）、`lut`（查表）。
  其余原语都是精确的（全精度，不丢位）。
- 同一程序有两种解释：**定点解释**（实现，逐位整数）与**理想解释**（近似点取精确值：q 不舍入不饱和，
  const 取精确值，lut 取 fn(x)）。判定报告同时给出两者的质量：理想解释是“这个结构本身能达到的质量”。

## A 层：数值语义（决定逐位结果）

| 原语 | 含义 | 结果格式 |
|---|---|---|
| `g.input()` | 输入（实数接口返回 x；复数接口返回 (i, q)） | s(in_bits).(in_bits-1) |
| `g.output(*sigs)` | 输出；必须是 s(out_bits).(out_bits-1)，速率等于接口输出速率 | — |
| `g.const(v, w, f, signed=True)` | 常数（不可表示时为近似点） | (w, f) |
| `g.add(a, b)` / `g.sub(a, b)` | 加减，自动对齐小数点并扩 1 位 | 全精度 |
| `g.neg(a)` | 取负 | W+1 |
| `g.mul(a, b)` | 全精度乘 | Wa+Wb, Fa+Fb |
| `g.scale(a, c, bits=16)` | 乘实常数：c 量化为 bits 位有效位后全精度乘 | 全精度 |
| `g.shift(a, k)` | 乘 2^k，只移小数点，不产生硬件 | (W, F-k) |
| `g.q(a, w, f, rnd="round"/"trunc", ovf="sat"/"wrap", signed=True)` | **重量化（近似点）**。round = 加半个 LSB 后向下取整；trunc = 向下取整；sat 饱和；wrap 补码回绕（模运算语义，两种解释一致） | (w, f) |
| `g.cmp(a, b, op)` | 比较，op ∈ lt le gt ge eq ne | u1.0 |
| `g.abs(a)` `g.min(a, b)` `g.max(a, b)` | 精确 | 自动 |
| `g.select(c, a, b)` | c 非零取 a，否则取 b | 合并格式 |
| `g.bits(a, hi, lo)` | 取整数码的第 hi..lo 位 | u(hi-lo+1).0 |
| `g.band/bor/bxor(a, b)` | 无符号整数（F=0）上的位运算 | 无符号 |
| `g.rom(addr, values, w, f)` | 按整数地址查表 values[addr]（值不可表示时为近似点） | (w, f) |
| `g.lut(x, fn, addr_bits, w, f, mid=False)` | **函数查表（近似点）**：地址 i = (code − lo) >> (W − addr_bits)，lo 为 x 格式的最小码（有符号为 −2^(W−1)，无符号为 0）；表项 i 对应 x_i = (lo + i·Δ [+Δ/2]) · 2^-F，Δ = 2^(W−addr_bits)；理想解释为 fn(x) | (w, f) |
| `g.delay(a, n=1)` | 样点延迟 y[m] = a[m-n]，初值 0 | 同 a |
| `g.decimate(a, r, phase=0)` | y[m] = a[m·r + phase] | 速率 /r |
| `g.interpolate(a, n)` | 零值内插 | 速率 ×n |
| `g.repeat(a, n)` | 保持内插 y[m] = a[m // n] | 速率 ×n |
| `g.reframe(a, n_in, picks)` | 帧重排：每 n_in 个样点一帧，输出依次取 picks 中的位置（去/加循环前缀、位反序、串并转换） | 速率 ×len(picks)/n_in |
| `g.interleave([s0, s1, ...])` | 并串转换：k 个同速率信号交织，y[k·m + j] = s_j[m]（可重复）。与 reframe 配合表达块处理 | 速率 ×k |
| `g.state(w, f, init=0, like=sig)` + `g.close(s, nxt)` | 反馈：s[0] = init，s[m+1] = nxt[m]；nxt 必须与 s 同格式、同速率 | (w, f) |
| `g.integrate(a, w)` | 累加器（模 2^w）：**输出是加之后的和** y[m] = Σ_{k≤m} a[k]，= state + add + q(wrap)，返回 q 节点 | (w, Fa) |
| `g.counter(step, bits, like=sig)` | 无符号计数器：第 m 个样点为 (m·step) mod 2^bits | u(bits).0 |

## B 层：微结构承诺（不改变任何数值）

```python
with g.scope("hb3"):            # 命名分段；可嵌套
    ...
    g.commit(fold=8, mul_max=2) # 在当前分段上承诺
g.interface(latency_max=400)    # 顶层总延迟上限（时钟）
```

| 承诺 | 含义 |
|---|---|
| `fold=k` | 时分复用因子：该段运算单元由 k 个样点或通道共用（不能超过该段每个样点可用的时钟数） |
| `mul_max=m` / `add_max=a` | 运算单元数量上限 |
| `latency_max=L` | 该段延迟上限（时钟） |
| `storage="reg"/"srl"/"ram"` | 延迟线与帧缓存的存储方式 |
| `reset="none"/"sync"`, `warmup=n` | 数据寄存器是否复位；不复位时前 n 个输出不比较 |

只改 B 层的修改，整数模型不变，判定直接继承父节点的质量结论（T1）。承诺之外的微结构由 Lowering Agent 自由选择。

## 变换类别（判定按实际行为分类）

- **T1 逐位等价**：定点输出逐位相同（例如多相分解、I/Q 交织、只改承诺）。继承父节点全部质量结论。
- **T2 理想等价**：理想解释相同、定点不同，即只改了精度（位宽、截位、系数位数、查表大小）。结构余量不变。
- **T3 结构近似**：理想解释改变（换滤波器、FIR 换 CIC 等）。两种解释都重测。

## 构造函数库 `lib`（展开后仍是原语）

`lib.coef(g, c, bits)`、`lib.add_tree(g, terms)`、`lib.fir(g, x, h, coef_bits)`、
`lib.fir_decimate(g, x, h, r, phase, coef_bits)`（多相抽取，与 decimate(fir) 逐位相同）、
`lib.cadd/csub/cmul(g, a, b)`、`lib.cmul_const(g, a, c, bits)`、`lib.mul_j(g, a, sign)`、`lib.bfly2(g, a, b)`、
`lib.q2(g, a, w, f, rnd, ovf)`。复数用 (re, im) 二元组。
"""
