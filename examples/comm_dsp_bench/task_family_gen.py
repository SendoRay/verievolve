#!/usr/bin/env python
"""CommDSP-Bench 任务族生成器（两层规模的第二层：参数化实例，一键 100+）

对每个核心原语定义参数网格，自动生成完整任务实例：
  tasks_gen/<family>/<instance>/task.yaml       任务卡（进 prompt 的数学规范）
  tasks_gen/<family>/<instance>/initial_program.v   朴素基线（参数化直接型实现）
  （golden 与激励按 family 注册到 evaluator 的分发表，参数从 task.yaml 读取）

设计依据：tasks_v2_design.md + 同类基准调研（进化深度层 10 精任务 +
泛化层 100+ 实例，双口径规模）。

用法：
  python task_family_gen.py --list            # 列出全部族与实例计数
  python task_family_gen.py --emit            # 生成全部实例文件
  python task_family_gen.py --emit --family crc --sample 2   # 只生成抽样
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "tasks_gen"


# ---------------------------------------------------------------------------
# 通用：task.yaml 模板
# ---------------------------------------------------------------------------

def task_yaml(name, spec, inputs, outputs, dist, samples, metric_type, params,
              timeouts=None):
    ins = "\n".join(f"    - {p}" for p in inputs)
    outs = "\n".join(f"    - {p}" for p in outputs)
    to = timeouts or {"L1": 5, "L2_sim": 30, "L2_synth": 300}
    p_str = "\n".join(f"    {k}: {json.dumps(v)}" for k, v in params.items())
    return f"""# CommDSP-Bench 生成实例（任务族第二层）：{name}
# 由 task_family_gen.py 自动生成；golden/激励由 evaluator 按 family 分发

spec_version: 2
task: {name}

spec: |
{spec}

dut_module: top

io_protocol:
  base: stream_v1
  inputs:
{ins}
  outputs:
{outs}
  extensions: []

golden:
  stimulus:
    distribution: {dist}
    samples: {samples}
    seed: fresh_per_eval
  reference:
    impl: "float64（evaluator 按 family 注册分发，参数见 metric.params）"

metric:
  type: {metric_type}
  params:
{p_str}

constraints: {{}}

timeouts:
  L1: {to['L1']}
  L2_sim: {to['L2_sim']}
  L2_synth: {to['L2_synth']}
"""


# ---------------------------------------------------------------------------
# 族 1：CRC（exact_match；宽度 × 步进）
# ---------------------------------------------------------------------------

# 3GPP 多项式：CRC24A=0x864CFB(24)，CRC16=0x1021(16)，CRC8=0x07(8)，CRC32=0x04C11DB7(32)
CRC_POLYS = {
    8:  ("0x07", "x^8+x^2+x+1"),
    16: ("0x1021", "x^16+x^12+x^5+1"),
    24: ("0x864CFB", "TS 38.212 CRC24A"),
    32: ("0x04C11DB7", "x^32+x^26+x^23+x^22+x^16+...+1"),
}

def gen_crc_task(width: int, step: int) -> tuple:
    poly_hex, poly_desc = CRC_POLYS[width]
    name = f"crc{width}_step{step}"
    spec = f"""  实现流式 CRC-{width} 校验器（3GPP 风格：MSB-first、非反射、初值全 0）。

  生成多项式：g(x) = {poly_desc}（十六进制 {poly_hex}）。
  输入为 16 位数据字流。每接收一个数据字后，输出"从复位起、包含当前字在内的
  全部数据位"的累积 CRC-{width} 值。
  数据以 MSB-first 顺序进入寄存器：每个字的高位（bit15）最先处理。"""
    params = {"width": width, "poly": poly_hex, "step_hint": step}
    return name, task_yaml(
        name, spec,
        ["{name: data, width: 16, signed: false, format: 'unsigned 字流'}"],
        [f"{{name: crc, width: {width}, signed: false, format: 'unsigned 累积 CRC'}}"],
        "uniform_words", 8192, "exact_match", params,
    )


# ---------------------------------------------------------------------------
# 族 2：调制/LLR 软解调（精度可谈判；阶数 × SNR）
# ---------------------------------------------------------------------------

def gen_llr_task(bits_per_sym: int, snr_db: int) -> tuple:
    M = 4 ** bits_per_sym // 2  # bits=1→QPSK(4), 2→16QAM(16), 3→64QAM(64), 4→256QAM(256)
    mod_name = {1: "QPSK", 2: "16QAM", 3: "64QAM", 4: "256QAM"}[bits_per_sym]
    name = f"llr_{mod_name.lower()}_snr{snr_db}"
    sigma2 = 10 ** (-snr_db / 10.0)
    spec = f"""  实现 {mod_name} 软解调器（bit-level LLR 计算，Gray 映射，TS 38.211 §5.1.3 风格）。

  输入为均衡后的星座点 (i_in, q_in)（Q4.12，值域约 ±{2**bits_per_sym}）。
  输出 {bits_per_sym * 2} 个比特的对数似然比（LLR），每个 16 位 signed（Q8.8）。

  参考定义（LLR 的精确语义，实现方式不限）：
  对比特 b（0..{bits_per_sym * 2 - 1}），设 S_b=1 为标准 {mod_name} Gray 星座中
  该比特为 1 的星座点集合，S_b=0 为该比特为 0 的集合（星座按 ±1/±3/.../±{2**bits_per_sym - 1} 奇数格点，I/Q 独立映射）：
    LLR_b = ln( sum_{{s in S_b=0}} exp(-|y - s|^2 / (2*sigma2)) )
          - ln( sum_{{s in S_b=1}} exp(-|y - s|^2 / (2*sigma2)) )
  其中 sigma2 = {sigma2:.6g}（SNR = {snr_db} dB 下的等效噪声方差，任务锁定）。
  正 LLR 表示比特更可能为 0（对数似然比按"0 假设 - 1 假设"定义）。

  注意：实现可采用任何数学等价或近似形式（如 max-log 近似）；精度按输出
  与浮点参考的 SQNR 评估。"""
    params = {"bits": bits_per_sym, "snr_db": snr_db, "sigma2": sigma2,
              "gray": "standard_38211_style"}
    return name, task_yaml(
        name, spec,
        ["{name: i_in, width: 16, signed: true, format: 'signed Q4.12'}",
         "{name: q_in, width: 16, signed: true, format: 'signed Q4.12'}"],
        [f"{{name: llr{i}, width: 16, signed: true, format: 'signed Q8.8'}}"
         for i in range(bits_per_sym * 2)],
        "qam_awgn", 65536, "sqnr", params,
    )


# ---------------------------------------------------------------------------
# 族 3：FIR（精度可谈判；抽头 × 截止 × 对称性）
# ---------------------------------------------------------------------------

def gen_fir_task(taps: int, cutoff: float, symmetric: bool) -> tuple:
    name = f"fir_t{taps}_c{int(cutoff*100)}{'_sym' if symmetric else ''}"
    k = np.arange(taps)
    h = 2 * cutoff * np.sinc(2 * cutoff * (k - (taps - 1) / 2))
    if symmetric:
        h *= 0.54 - 0.46 * np.cos(2 * np.pi * k / (taps - 1))
        h /= h.sum()
    else:
        w = 0.54 - 0.46 * np.cos(2 * np.pi * k / (taps - 1))
        h *= w
        h /= h.sum()
    h_list = [float(x) for x in h]
    coef_lines = "\n".join(f"  h[{i}] = {x!r}" for i, x in enumerate(h_list))
    sym_note = "线性相位（对称）" if symmetric else "非对称（Hamming 窗通用设计）"
    spec = f"""  实现 {taps} 抽头低通 FIR 滤波器（截止频率 {cutoff}*fs，{sym_note}）。

  精确系数（连续浮点，定点化策略不限）：
{coef_lines}

  输入 x 为 16 位 signed Q1.15；输出 y 为 40 位 signed，刻度 Q9.30
  （y_val = y/2^30 = sum_k h[k]*x_val[n-k]，历史初始为零）。"""
    params = {"coefficients": h_list, "taps": taps, "cutoff": cutoff,
              "symmetric": symmetric}
    return name, task_yaml(
        name, spec,
        ["{name: x, width: 16, signed: true, format: 'signed Q1.15'}"],
        ["{name: y, width: 40, signed: true, format: 'signed Q9.30（全精度）'}"],
        "gaussian_white", 65536, "sqnr", params,
    )


# ---------------------------------------------------------------------------
# 族 4：相位/atan2（精度可谈判；字长 × 输入象限全/半）
# ---------------------------------------------------------------------------

def gen_phase_task(w: int) -> tuple:
    name = f"atan2_w{w}"
    spec = f"""  实现复数辐角提取器：输入复数 (i_in, q_in)（{w} 位 signed Q1.{w-1}），
  输出 atan2(q, i) 的定点角度 theta（{w} 位 signed 线性编码：
  theta_val = theta/2^{w-1} * pi，范围 [-pi, pi)）。

  atan2 语义：输入象限完整保留（区别于折叠的 atan(q/i)）。原点附近行为
  按 theta=0 处理即可（激励避免纯原点）。"""
    params = {"width": w}
    return name, task_yaml(
        name, spec,
        [f"{{name: i_in, width: {w}, signed: true, format: 'signed Q1.{w-1}'}}",
         f"{{name: q_in, width: {w}, signed: true, format: 'signed Q1.{w-1}'}}"],
        [f"{{name: theta, width: {w}, signed: true, format: 'signed 线性角度码'}}"],
        "uniform_complex", 65536, "sqnr", params,
    )


# ---------------------------------------------------------------------------
# 族 5：NCO（SFDR；相位宽 × 表深）
# ---------------------------------------------------------------------------

def gen_nco_task(pw: int, tbl: int) -> tuple:
    name = f"nco_p{pw}_t{tbl}"
    spec = f"""  实现数控振荡器：{pw} 位相位累加器 + sin 输出（16 位 Q1.15）。
  FCW 为 {pw} 位无符号，归一化频率 = fcw/2^{pw}；每输入握手拍相位累加 FCW
  并输出 sin(2*pi*phase/2^{pw})。

  表深 {tbl} 点仅为基线实现参考（直接 {tbl} 点最近邻表）——实现方式完全
  自由（对称压缩/插值/CORDIC 等），频谱纯度按 SFDR 评估
  （worst-case，7 段 FCW 扫描，见 metric.params）。"""
    params = {"phase_bits": pw, "baseline_table": tbl,
              "fcws": [179, 392, 780, 1600, 3400, 5600, 7900],
              "segment_len": 8192, "transient": 64, "mainlobe_bins": 8}
    return name, task_yaml(
        name, spec,
        [f"{{name: fcw, width: {pw}, signed: false, format: 'unsigned'}}"],
        ["{name: sin_out, width: 16, signed: true, format: 'signed Q1.15'}"],
        "nco_fcw_sequence", 7 * 8192, "sfdr", params,
    )


# ---------------------------------------------------------------------------
# 族 6：相关器/匹配滤波（SQNR；序列长 × 扰动）
# ---------------------------------------------------------------------------

def gen_corr_task(seq_len: int) -> tuple:
    # m 序列（x^7+x^4+1，周期 127），与 5G PSS 同族但长度参数化
    # 序列从任一非零状态出发截取 seq_len 项（127 以内天然无重复）
    reg = [1] * 7
    seq = []
    while len(seq) < seq_len:
        nb = reg[6] ^ reg[3]
        seq.append(1 - 2 * reg[6])
        reg = reg[1:] + [nb]   # 左移：丢最老位，新位进末位
    S = seq[:seq_len]
    S_str = ", ".join(f"{v:+d}" for v in S[:16]) + ", ..." if seq_len > 16 else ", ".join(f"{v:+d}" for v in S)
    name = f"mfilt_L{seq_len}"
    spec = f"""  实现滑动互相关器（匹配滤波）：对复数输入流 r[n]（i/q 各 16 位 Q1.15），
  输出 c[n] = sum_k S[k] * r[n-{seq_len - 1}+k]（k = 0..{seq_len - 1}），
  即与固定实值 ±1 序列 S 的滑动相关（{seq_len} 项，含复数乘）。

  序列 S（任务给定，±1 值）：
  S = [{S_str}]
  （完整 {seq_len} 项的精确值以 metric.params.sequence 为准，输入为激励流，
  输出 c_re/c_im 为 24 位 signed Q9.15。）

  相关窗对齐约定：输出 c[n] 对应"以 r[n 结尾的最近 {seq_len} 个样本"与
  S 正序的内积。"""
    params = {"sequence": S, "length": seq_len}
    return name, task_yaml(
        name, spec,
        ["{name: i_in, width: 16, signed: true, format: 'signed Q1.15'}",
         "{name: q_in, width: 16, signed: true, format: 'signed Q1.15'}"],
        ["{name: c_re, width: 24, signed: true, format: 'signed Q9.15'}",
         "{name: c_im, width: 24, signed: true, format: 'signed Q9.15'}"],
        "complex_stream", 32768, "sqnr", params,
        timeouts={"L1": 10, "L2_sim": 60, "L2_synth": 300},
    )



# ---------------------------------------------------------------------------
# 族 7：复数乘法（精度可谈判；位宽 × 舍入模式）
# ---------------------------------------------------------------------------

def gen_cmul_task(w: int, rnd: str) -> tuple:
    name = f"cmul_w{w}_{rnd}"
    out_w = 2 * w + 1
    rnd_note = {
        "trunc": "直接截断到输出位宽（可舍弃低位）",
        "round": "含舍入到最近",
        "free": "输出为全精度宽（{} 位，定点化策略完全自由）".format(out_w),
    }[rnd]
    ow = out_w if rnd == "free" else w
    spec = f"""  实现复数乘法器：计算 (a + j*b) * (c + j*d) 的实部与虚部。

  输入 a/b/c/d 为 {w} 位 signed（Q1.{w-1}）；输出 y_re/y_im 为 {ow} 位 signed。
  {rnd_note}。精度按与浮点参考的 SQNR 评估（相对全精度参考）。"""
    params = {"width": w, "rounding": rnd}
    return name, task_yaml(
        name, spec,
        [f"{{name: {n}, width: {w}, signed: true, format: 'signed Q1.{w-1}'}}"
         for n in ["a", "b", "c", "d"]],
        [f"{{name: y_re, width: {ow}, signed: true, format: 'signed'}}",
         f"{{name: y_im, width: {ow}, signed: true, format: 'signed'}}"],
        "uniform_iq", 65536, "sqnr", params,
    )

# ---------------------------------------------------------------------------
# 族注册与网格
# ---------------------------------------------------------------------------

FAMILIES = {
    "crc": {
        "desc": "CRC 族（exact_match）：宽度 × 步进提示",
        "grid": [(w, s) for w in [8, 16, 24, 32] for s in [1, 2, 4, 8, 16]],
        "gen": lambda w, s: gen_crc_task(w, s),
    },
    "llr": {
        "desc": "软解调族（sqnr）：调制阶 × SNR",
        "grid": [(b, snr) for b in [1, 2, 3, 4] for snr in [10, 15, 20, 25, 30]],
        "gen": lambda b, snr: gen_llr_task(b, snr),
    },
    "fir": {
        "desc": "FIR 族（sqnr）：抽头 × 截止 × 对称",
        "grid": [(t, c, sym) for t in [8, 16, 32, 64, 128]
                 for c in [0.15, 0.25, 0.4] for sym in [True, False]],
        "gen": lambda t, c, sym: gen_fir_task(t, c, sym),
    },
    "phase": {
        "desc": "atan2 族（sqnr）：字长",
        "grid": [(w,) for w in [12, 14, 16, 18, 20, 24, 28]],
        "gen": lambda w: gen_phase_task(w),
    },
    "nco": {
        "desc": "NCO 族（sfdr）：相位宽 × 基线表深",
        "grid": [(p, t) for p in [20, 24, 28, 32] for t in [64, 256, 1024]],
        "gen": lambda p, t: gen_nco_task(p, t),
    },
    "mfilt": {
        "desc": "匹配滤波族（sqnr）：序列长",
        "grid": [(L,) for L in [15, 31, 63, 127, 255]],
        "gen": lambda L: gen_corr_task(L),
    },
    "cmul": {
        "desc": "复数乘法族（sqnr）：字长 × 舍入模式",
        "grid": [(w, r) for w in [8, 12, 16, 20] for r in ["trunc", "round", "free"]],
        "gen": lambda w, r: gen_cmul_task(w, r),
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--family", default=None)
    ap.add_argument("--sample", type=int, default=0, help="每族抽样 N 个（调试）")
    args = ap.parse_args()

    total = 0
    for fam, cfg in FAMILIES.items():
        grid = cfg["grid"]
        if args.sample:
            grid = grid[:args.sample]
        names = []
        for params_tuple in grid:
            name, yaml_text = cfg["gen"](*params_tuple)
            names.append(name)
            if args.emit and (args.family is None or args.family == fam):
                d = OUT / fam / name
                d.mkdir(parents=True, exist_ok=True)
                (d / "task.yaml").write_text(yaml_text)
        total += len(names)
        print(f"{fam:8s} {cfg['desc']:36s} -> {len(names):3d} 实例")

    print(f"\n合计: {total} 实例")
    if args.emit:
        print(f"输出目录: {OUT}/<family>/<instance>/task.yaml")


if __name__ == "__main__":
    main()
