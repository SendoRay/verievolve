"""
CommDSP-Bench evaluator (PoC: cmul anchor task)

流程（SPEC.md §7）:
  stage1 (L0+L1): 编译检查 + 256 样本冒烟仿真（粗 SQNR 门槛）
  stage2 (L2):    65536 样本全量仿真 + Yosys ice40 综合（面积）

仿真后端: Icarus Verilog 优先，Verilator (--binary) 后备。
面积口径: ice40 LUT+CARRY 计数（PoC；Nangate45 ASIC 口径后续补充，见 SPEC §5.4）。

运行独立测试:
  python evaluator.py initial_program.v
"""

import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import yaml

from openevolve.evaluation_result import EvaluationResult

# ---------------------------------------------------------------------------
# 任务加载
# ---------------------------------------------------------------------------

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
TASK_NAME = os.environ.get("COMMDSP_TASK", "cmul")

SQNR_CAP_DB = 999.0
# combined_score 归一化常数（实测校准：朴素 4 乘法器基线 = 6828 LUT+CARRY）
PRECISION_REF_DB = 120.0   # SQNR 饱和点
AREA_REF_LUT = 7000.0      # 面积归一化参考（朴素基线量级）
SMOKE_SAMPLES = 256
FULL_SAMPLES = 65536
BUBBLE_PROB = 10           # 1/10 概率插入输入气泡拍（SPEC §4.2）


def _load_task() -> dict:
    path = TASKS_DIR / TASK_NAME / "task.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Task spec not found: {path}")
    with open(path, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 激励与 golden model（注册点：新任务在此注册，见 SPEC §10.1）
# ---------------------------------------------------------------------------

def _stimulus_uniform_iq(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """16 位有符号均匀随机，4 字段一组"""
    rows = []
    for _ in range(n):
        rows.append([rng.randint(-(1 << 15), (1 << 15) - 1) for _ in range(4)])
    return rows


def _stimulus_uniform_angle(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """16 位线性编码角度均匀随机，[-pi, pi)，1 字段一组"""
    return [[rng.randint(-(1 << 15), (1 << 15) - 1)] for _ in range(n)]


def _stimulus_gaussian_white(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """高斯白噪声（σ=9000），16 位有符号，1 字段一组（滤波器类任务）"""
    rows = []
    for _ in range(n):
        v = int(round(rng.gauss(0, 9000)))
        rows.append([max(-(1 << 15), min((1 << 15) - 1, v))])
    return rows


def _stimulus_nco_fcw_sequence(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """NCO FCW 序列：segment 段内恒定 FCW，每拍一组输入（当前 FCW），1 字段一组。

    FCW 集合与段长在 task.yaml metric.params 中锁定（旧版从 params 直接读；
    新版按相位位宽缩放到全幅）。"""
    params = (task or {}).get("metric", {}).get("params", {})
    seg_len = int(params.get("segment_len", 16384))
    fcws = params.get("fcws", [1000000])
    pw = int(params.get("phase_bits", 24))
    rows = []
    for i in range(n):
        seg = min(i // seg_len, len(fcws) - 1)
        f = int(fcws[seg])
        # 归一化频率缩放：fcw 值为 /2^20 归一化 → 按相位位宽放大到全幅
        f_full = (f << (pw - 20)) if pw > 20 else (f >> (20 - pw))
        rows.append([f_full & ((1 << pw) - 1)])
    return rows


def _stimulus_uniform_words(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """均匀随机 16 位无符号字（CRC/加扰族）"""
    return [[rng.randint(0, 0xFFFF)] for _ in range(n)]


def _stimulus_uniform_complex(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """均匀幅角复数（atan2 族）：幅值 0.2–1.0 均匀，避免纯原点"""
    w = int((task or {}).get("metric", {}).get("params", {}).get("width", 16))
    half = 1 << (w - 1)
    rows = []
    for _ in range(n):
        ang = rng.uniform(-math.pi, math.pi)
        mag = rng.uniform(0.2, 1.0) * (half - 1)
        i = int(round(mag * math.cos(ang)))
        q = int(round(mag * math.sin(ang)))
        rows.append([max(-(half), min(half - 1, i)), max(-(half), min(half - 1, q))])
    return rows


def _stimulus_qam_awgn(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """QAM 星座 + AWGN（LLR 族）：随机比特→Gray 星座→加噪，Q4.12 输入刻度"""
    params = (task or {}).get("metric", {}).get("params", {})
    bits = int(params.get("bits", 3))
    sigma2 = float(params.get("sigma2", 0.01))
    sigma = math.sqrt(sigma2)
    half_b = bits  # 每轴比特数
    # 标准方形 QAM Gray 映射（每轴独立，奇数格点 ±1,±3,...）
    def axis_gray(val_b: int, nb: int) -> float:
        # val_b: nb 位整数 → Gray → 格点
        g = val_b ^ (val_b >> 1)  # binary->gray
        # gray 码到 PAM 幅度：标准映射（位高位定符号，低位镜像）
        amp = 0
        for k in range(nb):
            bit = (g >> (nb - 1 - k)) & 1
            if k == 0:
                sign = -1 if bit else 1
            else:
                # 后续位：幅度折叠（标准 Gray PAM）
                amp |= bit << (nb - 1 - k)
        # 幅度取奇数值：amp ∈ {0..2^(nb-1)-1} → 2*amp+1，符号在最前
        return sign * (2 * amp + 1)
    rows = []
    for _ in range(n):
        bi = rng.randint(0, (1 << half_b) - 1)
        bq = rng.randint(0, (1 << half_b) - 1)
        si = axis_gray(bi, half_b)
        sq = axis_gray(bq, half_b)
        yi = si + rng.gauss(0, sigma)
        yq = sq + rng.gauss(0, sigma)
        sc = 4096.0  # Q4.12
        i16 = int(round(yi * sc))
        q16 = int(round(yq * sc))
        rows.append([max(-32768, min(32767, i16)), max(-32768, min(32767, q16))])
    return rows


def _stimulus_complex_stream(n: int, rng: random.Random, task: dict = None) -> List[List[int]]:
    """复数高斯流（匹配滤波族）：白噪声复样本，Q1.15"""
    rows = []
    for _ in range(n):
        i = int(round(rng.gauss(0, 9000)))
        q = int(round(rng.gauss(0, 9000)))
        rows.append([max(-32768, min(32767, i)), max(-32768, min(32767, q))])
    return rows


def _golden_cmul(rows: List[List[int]]) -> np.ndarray:
    """float64 全精度复数乘法，返回 (n, 2)。尺度 = DUT 原始整数（SQNR 尺度无关）"""
    arr = np.array(rows, dtype=np.int64)
    a, b, c, d = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    y_re = a.astype(np.float64) * c - b.astype(np.float64) * d
    y_im = a.astype(np.float64) * d + b.astype(np.float64) * c
    return np.stack([y_re, y_im], axis=1)


def _golden_sincos(rows: List[List[int]]) -> np.ndarray:
    """sin/cos float64 金标，返回 (n, 2)。尺度 = Q1.15 整数刻度（SQNR 尺度无关）

    角度编码：z 为 signed 16 位线性编码，theta = z * pi / 2^15，范围 [-pi, pi)。
    """
    arr = np.array(rows, dtype=np.int64)
    theta = arr[:, 0].astype(np.float64) * (np.pi / 32768.0)
    sin_q = np.sin(theta) * 32768.0
    cos_q = np.cos(theta) * 32768.0
    return np.stack([sin_q, cos_q], axis=1)


def _golden_nco(rows: List[List[int]]) -> np.ndarray:
    """NCO 金标：24 位相位累加 + sin，返回 (n, 1)，Q1.15 整数刻度。

    相位从 0 开始；每拍相位加上该拍采样的 FCW，输出 sin(2*pi*phase/2^24)。
    """
    arr = np.array(rows, dtype=np.int64)
    phase = np.cumsum(arr[:, 0]) & 0xFFFFFF
    sin_q = np.sin(2.0 * np.pi * phase / 16777216.0) * 32768.0
    return np.stack([sin_q], axis=1)


def _golden_fir(rows: List[List[int]], h: List[float]) -> np.ndarray:
    """FIR 金标：连续系数 float64 卷积（零初始历史），返回 (n, 1)。

    输出刻度：y_ref = 2^30 * Σ h[k]*u[n-k]，u = x/2^15（与任务规定的 Q9.30 输出一致）。
    """
    u = np.array(rows, dtype=np.float64)[:, 0] / 32768.0
    hc = np.convolve(u, np.array(h, dtype=np.float64))[: len(u)]
    return np.stack([hc * (1 << 30)], axis=1)


_STIMULUS_IMPLS = {
    "uniform_iq": _stimulus_uniform_iq,
    "uniform_angle": _stimulus_uniform_angle,
    "gaussian_white": _stimulus_gaussian_white,
    "nco_fcw_sequence": _stimulus_nco_fcw_sequence,
    "uniform_words": _stimulus_uniform_words,
    "uniform_complex": _stimulus_uniform_complex,
    "qam_awgn": _stimulus_qam_awgn,
    "complex_stream": _stimulus_complex_stream,
}
_GOLDEN_IMPLS = {
    "cmul": _golden_cmul,
    "cordic_sincos": _golden_sincos,
    "nco": _golden_nco,
}


# ---------------------------------------------------------------------------
# Testbench 生成（stream_v1 协议，SPEC §4）
# ---------------------------------------------------------------------------

def _gen_testbench(task: dict, n_samples: int, bubble_period: int) -> str:
    io = task["io_protocol"]
    inputs, outputs = io["inputs"], io["outputs"]
    module = task.get("dut_module", "top")

    in_decls = "\n    ".join(
        f"reg  {'signed ' if p.get('signed') else ''}[{p['width'] - 1}:0] {p['name']};"
        for p in inputs
    )
    out_decls = "\n    ".join(
        f"wire {'signed ' if p.get('signed') else ''}[{p['width'] - 1}:0] {p['name']};"
        for p in outputs
    )
    scan_fmt = " ".join(["%h"] * len(inputs))
    write_fmt = " ".join(["%h"] * len(outputs))
    in_args = ", ".join(p["name"] for p in inputs)
    out_args = ", ".join(p["name"] for p in outputs)
    ports = ["clk", "rst_n", "in_valid", "in_ready"] + [p["name"] for p in inputs] + \
            ["out_valid", "out_ready"] + [p["name"] for p in outputs]
    inst = ",\n        ".join(f".{p}({p})" for p in ports)
    timeout_cycles = 40 * n_samples + 8000  # 迭代型设计（如多周期 CORDIC）留余量

    return f"""`timescale 1ns/1ps
module tb;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg in_valid = 1'b0;
    wire in_ready;
    {in_decls}
    wire out_valid;
    reg out_ready = 1'b1;
    {out_decls}

    integer fin, fout, fmeta;
    integer i, code, wait_count;
    integer received = 0;
    integer cycles = 0;
    reg handshake;

    {module} dut(
        {inst}
    );

    always #5 clk = ~clk;

    // posedge 采样握手结果（避免与驱动进程竞争）
    always @(posedge clk) begin
        handshake <= rst_n && in_valid && in_ready;
        if (rst_n) cycles <= cycles + 1;
    end

    // negedge 收集输出（此时 DUT 的 NBA 更新已稳定）
    always @(negedge clk) begin
        if (rst_n && out_valid && out_ready) begin
            $fwrite(fout, "{write_fmt}\\n", {out_args});
            received = received + 1;
        end
    end

    // 驱动进程（negedge 对齐）
    initial begin
        fin = $fopen("stimulus.txt", "r");
        if (fin == 0) begin
            $display("TB_ERROR: cannot open stimulus.txt");
            $finish;
        end
        fout = $fopen("output.txt", "w");
        fmeta = $fopen("meta.txt", "w");
        // 复位两个周期
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);

        for (i = 0; i < {n_samples}; i = i + 1) begin
            code = $fscanf(fin, "{scan_fmt}", {in_args});
            if (code != {len(inputs)}) begin
                $display("TB_ERROR: stimulus exhausted at %%0d", i);
                $fwrite(fmeta, "0 %%0d\\n", received);
                $fclose(fout); $fclose(fmeta); $fclose(fin);
                $finish;
            end
            in_valid = 1'b1;
            @(negedge clk);
            while (handshake !== 1'b1) @(negedge clk);
            in_valid = 1'b0;
            // 输入气泡拍（SPEC §4.2：L2 层 10%）
            if (({{$random}} % {bubble_period}) == 0) @(negedge clk);
        end
        $fclose(fin);

        // 等待全部输出或超时
        wait_count = 0;
        while (received < {n_samples} && wait_count < {timeout_cycles}) begin
            @(negedge clk);
            wait_count = wait_count + 1;
        end
        $fwrite(fmeta, "%0d %0d\\n", cycles, received);
        $fclose(fout);
        $fclose(fmeta);
        $finish;
    end
endmodule
"""


# ---------------------------------------------------------------------------
# 仿真后端
# ---------------------------------------------------------------------------

def _detect_backend() -> Optional[str]:
    if shutil.which("iverilog") and shutil.which("vvp"):
        return "icarus"
    if shutil.which("verilator"):
        return "verilator"
    return None


def _run_icarus(workdir: str, files: List[str], timeout: int) -> Tuple[bool, str]:
    try:
        p = subprocess.run(
            ["iverilog", "-o", "sim.vvp"] + files,
            cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
        if p.returncode != 0:
            return False, p.stderr[-2000:]
        p = subprocess.run(
            ["vvp", "sim.vvp"], cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
        if p.returncode != 0:
            return False, p.stderr[-2000:]
        return True, p.stdout[-2000:]
    except subprocess.TimeoutExpired:
        return False, "simulation timeout"
    except FileNotFoundError as e:
        return False, str(e)


def _run_verilator(workdir: str, files: List[str], timeout: int) -> Tuple[bool, str]:
    try:
        p = subprocess.run(
            ["verilator", "--binary", "--timing", "--top-module", "tb",
             "-Wno-fatal", "-o", "simv"] + files,
            cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
        if p.returncode != 0:
            return False, (p.stderr or p.stdout)[-2000:]
        sim = Path(workdir) / "obj_dir" / "simv"
        if not sim.exists():
            sim = Path(workdir) / "simv"
        p = subprocess.run(
            [str(sim)], cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
        if p.returncode != 0:
            return False, (p.stderr or p.stdout)[-2000:]
        return True, p.stdout[-2000:]
    except subprocess.TimeoutExpired:
        return False, "simulation timeout"
    except FileNotFoundError as e:
        return False, str(e)


def _run_sim(workdir: str, program_path: str, timeout: int) -> Tuple[bool, str]:
    backend = _detect_backend()
    if backend is None:
        return False, "no simulation backend found (need iverilog or verilator)"
    files = ["tb.v", program_path]
    if backend == "icarus":
        return _run_icarus(workdir, files, timeout)
    return _run_verilator(workdir, files, timeout)


# ---------------------------------------------------------------------------
# Yosys 综合（ice40 面积口径）
# ---------------------------------------------------------------------------

PDK_LIB = str(Path(__file__).resolve().parent / "pdk" / "NangateOpenCellLibrary_typical.lib")


def _run_yosys_asic(workdir: str, program_path: str, timeout: int) -> Tuple[Optional[float], str]:
    """Nangate45 ASIC 口径（论文主口径，对齐 REvolution）：synth-noabc → dffunmap →
    dfflibmap → abc 映射 → stat 提取 Chip area（μm²，含时序单元）。"""
    if not Path(PDK_LIB).exists():
        return None, "Nangate45 liberty missing (pdk/NangateOpenCellLibrary_typical.lib)"
    log_path = Path(workdir) / "asic_stat.txt"
    script = (
        f"read_verilog {program_path}; "
        f"synth -top top -noabc; dffunmap; "
        f"dfflibmap -liberty {PDK_LIB}; "
        f"abc -liberty {PDK_LIB}; "
        f"tee -o {log_path} stat -liberty {PDK_LIB}"
    )
    try:
        p = subprocess.run(
            ["yosys", "-q", "-p", script],
            cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "asic synthesis timeout"
    if not log_path.exists():
        return None, (p.stderr or p.stdout)[-2000:]
    try:
        text = log_path.read_text()
        m = re.search(r"Chip area for module '\\top':\s*([0-9.]+)", text)
        if not m:
            return None, f"no chip area in stat: {text[-500:]}"
        return float(m.group(1)), ""
    except OSError as e:
        return None, str(e)


def _collect_cell_counts(node, acc: Dict[str, int]) -> None:
    """递归收集 stat -json 中的 cell 计数"""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, int) and (k.startswith("LUT") or k.startswith("SB_")):
                acc[k] = acc.get(k, 0) + v
            else:
                _collect_cell_counts(v, acc)
    elif isinstance(node, list):
        for item in node:
            _collect_cell_counts(item, acc)


def _run_yosys(workdir: str, program_path: str, timeout: int) -> Tuple[Optional[int], Dict[str, int], str]:
    """返回 (area_lut_total, cell_counts, log)"""
    stat_json = Path(workdir) / "stat.json"
    script = (
        f"read_verilog {program_path}; "
        f"synth_ice40 -top top; "
        f"tee -o {stat_json} stat -json"
    )
    try:
        p = subprocess.run(
            ["yosys", "-q", "-p", script],
            cwd=workdir, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, {}, "synthesis timeout"
    if p.returncode != 0 or not stat_json.exists():
        return None, {}, (p.stderr or p.stdout)[-2000:]

    counts: Dict[str, int] = {}
    try:
        with open(stat_json) as f:
            data = json.load(f)
        _collect_cell_counts(data, counts)
    except (json.JSONDecodeError, OSError) as e:
        return None, counts, f"stat parse error: {e}"

    lut_total = sum(v for k, v in counts.items() if "LUT" in k)
    carry = sum(v for k, v in counts.items() if "CARRY" in k)
    area = lut_total + carry  # PoC 简化口径：LUT + CARRY（DFF 仅记录在 counts）
    return area, counts, ""


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------

def _hex_to_signed(h: str, bits: int) -> int:
    v = int(h, 16)
    if v >= (1 << (bits - 1)):
        v -= (1 << bits)
    return v


_HEX_CHARS = set("0123456789abcdefABCDEF")


def _read_outputs(path: Path, widths: List[int],
                  signed_flags: Optional[List[bool]] = None) -> Optional[np.ndarray]:
    rows = []
    if signed_flags is None:
        signed_flags = [True] * len(widths)
    try:
        with open(path) as f:
            for line in f:
                parts = line.split()
                if len(parts) != len(widths):
                    return None
                # DUT 输出含 x/z（未初始化/高阻）→ 视为无效结果
                if any(set(tok) - _HEX_CHARS for tok in parts):
                    return None
                rows.append([
                    _hex_to_signed(x, w) if s else int(x, 16)
                    for x, w, s in zip(parts, widths, signed_flags)
                ])
    except OSError:
        return None
    if not rows:
        return None
    return np.array(rows, dtype=np.float64)


def _sqnr_db(ref: np.ndarray, dut: np.ndarray) -> float:
    """多字段输出：逐字段 SQNR 取最差（SPEC §5.2）"""
    worst = SQNR_CAP_DB
    for col in range(ref.shape[1]):
        r = ref[:, col].astype(np.float64)
        d = dut[:, col].astype(np.float64)
        noise = float(np.sum((r - d) ** 2))
        signal = float(np.sum(r ** 2))
        if noise == 0.0:
            continue
        if signal == 0.0:
            return 0.0
        worst = min(worst, 10.0 * math.log10(signal / noise))
    return max(worst, 0.0)


def _blackman_harris(n: int) -> np.ndarray:
    """4 项 Blackman-Harris 窗"""
    k = np.arange(n)
    a = [0.35875, 0.48829, 0.14128, 0.01168]
    w = (
        a[0]
        - a[1] * np.cos(2 * np.pi * k / (n - 1))
        + a[2] * np.cos(4 * np.pi * k / (n - 1))
        - a[3] * np.cos(6 * np.pi * k / (n - 1))
    )
    return w


def _sfdr_db(dut: np.ndarray, params: dict) -> float:
    """SFDR：逐段加窗 FFT，主音功率减最大杂散，取最差段（SPEC §5.3）

    dut: (n, 1) 正弦输出列。段结构与 FCW 集合由 task.yaml metric.params 锁定。
    """
    seg_len = int(params.get("segment_len", 16384))
    transient = int(params.get("transient", 64))
    mainlobe = int(params.get("mainlobe_bins", 8))
    col = dut[:, 0].astype(np.float64)
    n = col.shape[0]
    worst = SQNR_CAP_DB
    n_seg = max(1, n // seg_len)
    for s in range(n_seg):
        seg = col[s * seg_len : (s + 1) * seg_len][transient:]
        if len(seg) < 256:
            continue
        w = _blackman_harris(len(seg))
        spec = np.abs(np.fft.rfft(seg * w)) ** 2
        k = int(np.argmax(spec))
        # 掩蔽主瓣与直流邻域（窗函数泄漏）
        lo, hi = max(0, k - mainlobe), min(len(spec), k + mainlobe + 1)
        mask = np.ones(len(spec), dtype=bool)
        mask[lo:hi] = False
        mask[:3] = False
        spur = float(np.max(spec[mask])) if mask.any() else 0.0
        if spur <= 0.0:
            continue
        worst = min(worst, 10.0 * math.log10(float(spec[k]) / spur))
    return max(worst, 0.0)


def _combined_score(sqnr_db: float, area: Optional[int], thr: Optional[float]) -> float:
    p = min(max(sqnr_db, 0.0), PRECISION_REF_DB) / PRECISION_REF_DB
    if area is not None:
        a = AREA_REF_LUT / (AREA_REF_LUT + float(area))
    else:
        a = 0.0
    t = min(max(thr if thr is not None else 0.0, 0.0), 1.0)
    return 0.5 * p + 0.3 * a + 0.2 * t


# ---------------------------------------------------------------------------
# 核心评估流程
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 任务族 golden（v2 生成层：按 task 名前缀分发，参数从 task.yaml 读）
# ---------------------------------------------------------------------------

def _bit_of(axis_index: int, nb: int, b: int) -> int:
    """axis_index 的第 b 位（从 MSB 数，与激励生成约定一致）"""
    return (axis_index >> (nb - 1 - b)) & 1


def _axis_gray_map(val_b: int, nb: int) -> float:
    """binary→Gray→奇数幅度（与 _stimulus_qam_awgn 完全一致）"""
    g = val_b ^ (val_b >> 1)
    amp = 0
    sign = 1
    for k in range(nb):
        bit = (g >> (nb - 1 - k)) & 1
        if k == 0:
            sign = -1 if bit else 1
        else:
            amp |= bit << (nb - 1 - k)
    return sign * (2 * amp + 1)


def _golden_crc(rows: List[List[int]], params: dict) -> np.ndarray:
    """流式 CRC（3GPP 风格 MSB-first 非反射）：逐位更新，每字输出累积值"""
    width = int(params["width"])
    poly = int(params["poly"], 16)
    mask = (1 << width) - 1
    crc = 0
    out = []
    for r in rows:
        word = r[0] & 0xFFFF
        for b in range(15, -1, -1):
            bit = (word >> b) & 1
            fb = ((crc >> (width - 1)) & 1) ^ bit
            crc = (crc << 1) & mask
            if fb:
                crc ^= (poly & mask)
        out.append(float(crc))
    return np.array(out, dtype=np.float64).reshape(-1, 1)


def _golden_llr(rows: List[List[int]], params: dict) -> np.ndarray:
    """精确 LLR（log-sum-exp）：与激励同 Gray 映射分桶，Q8.8 刻度"""
    bits = int(params["bits"])
    sigma2 = float(params["sigma2"])
    nbits = 2 * bits
    axis_vals = [_axis_gray_map(v, bits) for v in range(1 << bits)]
    sc = 4096.0  # Q4.12
    llrs = np.zeros((len(rows), nbits), dtype=np.float64)
    # 预计算每个 bit 的星座分桶（按 axis_index 的位）
    buckets = []
    for b in range(nbits):
        ai = 0 if b < bits else 1  # I 轴 bit 在前
        bb = b if b < bits else b - bits
        s0 = [(si, sq) for si in range(1 << bits) for sq in range(1 << bits)
              if _bit_of(si if ai == 0 else sq, bits, bb) == 0]
        s1 = [(si, sq) for si in range(1 << bits) for sq in range(1 << bits)
              if _bit_of(si if ai == 0 else sq, bits, bb) == 1]
        buckets.append((s0, s1))
    for idx, r in enumerate(rows):
        yi = r[0] / sc
        yq = r[1] / sc
        for b in range(nbits):
            s0, s1 = buckets[b]
            d0 = np.array([-((yi - axis_vals[si])**2 - 2*(yi-axis_vals[si])*0 + (yq - axis_vals[sq])**2) / (2*sigma2) for si, sq in s0])
            d1 = np.array([-((yi - axis_vals[si])**2 + (yq - axis_vals[sq])**2) / (2*sigma2) for si, sq in s1])
            m0, m1 = d0.max(), d1.max()
            l0 = m0 + np.log(np.exp(d0 - m0).sum())
            l1 = m1 + np.log(np.exp(d1 - m1).sum())
            # 2σ² 归一化 LLR（通信标准软信息口径）：ln 域差 × 2σ² = 距离差；
            # Q8.8 定标（×256），16 位域充足（距离差 ≤ 最大格距²×2 ≈ 450×256 时饱和）
            v = (l0 - l1) * 2.0 * sigma2 * 256.0  # Q8.8
            llrs[idx, b] = max(-32768.0, min(32767.0, v))
    return llrs


def _golden_atan2(rows: List[List[int]], params: dict) -> np.ndarray:
    """atan2 金标：线性角度码（与 cordic 同编码），四舍五入 + clamp"""
    w = int(params.get("width", 16))
    half = 1 << (w - 1)
    arr = np.array(rows, dtype=np.float64)
    theta = np.arctan2(arr[:, 1], arr[:, 0]) * half / np.pi
    theta = np.round(theta)
    theta = np.clip(theta, -half, half - 1)
    return theta.reshape(-1, 1)


def _golden_mfilt(rows: List[List[int]], params: dict) -> np.ndarray:
    """匹配滤波：c[n] = sum_k S[k] * r[n-k]（S 正序，k=0 对应最新样本；
    历史初始为零）——与任务卡 spec 约定一致"""
    S = np.array(params["sequence"], dtype=np.float64)
    arr = np.array(rows, dtype=np.float64)
    c_re = np.convolve(arr[:, 0], S, mode="full")[: len(rows)]
    c_im = np.convolve(arr[:, 1], S, mode="full")[: len(rows)]
    return np.stack([c_re, c_im], axis=1)


def _golden_nco_scaled(rows: List[List[int]], params: dict) -> np.ndarray:
    """NCO 族金标：按相位位宽缩放"""
    pw = int(params.get("phase_bits", 24))
    arr = np.array(rows, dtype=np.int64)
    phase = np.cumsum(arr[:, 0]) & ((1 << pw) - 1)
    sin_q = np.sin(2.0 * np.pi * phase / (1 << pw)) * 32768.0
    return np.stack([sin_q], axis=1)


def _golden_family_dispatch(task: dict, rows: List[List[int]]) -> np.ndarray:
    """任务族 golden 分发：按 task 名前缀匹配，参数从 metric.params 读"""
    name = task["task"]
    params = task["metric"].get("params", {})
    if name.startswith("crc"):
        return _golden_crc(rows, params)
    if name.startswith("llr_"):
        return _golden_llr(rows, params)
    if name.startswith("atan2"):
        return _golden_atan2(rows, params)
    if name.startswith("mfilt"):
        return _golden_mfilt(rows, params)
    if name.startswith("fir_"):
        return _golden_fir(rows, params["coefficients"])
    if name.startswith("nco_"):
        return _golden_nco_scaled(rows, params)
    if name.startswith("cmul_"):
        return _golden_cmul(rows)
    raise ValueError(f"no golden for task '{name}'")


def _golden_for_task(task: dict, rows: List[List[int]]) -> np.ndarray:
    """金标分发：v1 精任务查注册表；fir 需系数；v2 族按前缀分发"""
    name = task["task"]
    if name == "fir":
        h = task["metric"]["params"]["coefficients"]
        return _golden_fir(rows, h)
    impl = _GOLDEN_IMPLS.get(name)
    if impl is not None:
        return impl(rows)
    # v2 生成族：前缀分发
    return _golden_family_dispatch(task, rows)


def _simulate(
    program_path: str, n_samples: int, sim_timeout: int, metric_mode: str = "task"
) -> Tuple[Optional[dict], Optional[str]]:
    """运行一次完整仿真。返回 (result_dict, error_msg)。

    metric_mode: "task" 用任务定义的精度指标；"sqnr" 强制 SQNR（stage1 冒烟用）。
    """
    task = _load_task()
    rng = random.Random(random.randrange(1 << 32))  # fresh seed per eval（SPEC §7.3）
    dist = task["golden"]["stimulus"]["distribution"]
    rows = _STIMULUS_IMPLS[dist](n_samples, rng, task)
    ref = _golden_for_task(task, rows)

    widths_in = [p["width"] for p in task["io_protocol"]["inputs"]]
    with tempfile.TemporaryDirectory(prefix="commdsp_") as workdir:
        stim = Path(workdir) / "stimulus.txt"
        with open(stim, "w") as f:
            for r in rows:
                f.write(" ".join(f"{v & ((1 << w) - 1):x}" for v, w in zip(r, widths_in)) + "\n")
        with open(Path(workdir) / "tb.v", "w") as f:
            f.write(_gen_testbench(task, n_samples, BUBBLE_PROB))

        prog = str(Path(program_path).resolve())
        ok, log = _run_sim(workdir, prog, sim_timeout)
        if not ok:
            return None, log

        out_widths = [p["width"] for p in task["io_protocol"]["outputs"]]
        out_signed = [bool(p.get("signed", True)) for p in task["io_protocol"]["outputs"]]
        dut = _read_outputs(Path(workdir) / "output.txt", out_widths, out_signed)
        if dut is None or dut.shape[0] < n_samples:
            n_got = 0 if dut is None else dut.shape[0]
            return None, f"incomplete output: got {n_got}/{n_samples} samples"
        # 多余输出（spurious valid）截断：由精度指标自然惩罚，不崩溃
        dut = dut[:n_samples]

        try:
            meta = (Path(workdir) / "meta.txt").read_text().split()
            cycles, received = int(meta[0]), int(meta[1])
        except (OSError, ValueError, IndexError):
            cycles, received = 0, 0

        mtype = task["metric"]["type"] if metric_mode == "task" else "sqnr"
        if mtype == "sfdr":
            precision = _sfdr_db(dut, task["metric"].get("params", {}))
        elif mtype == "exact_match":
            # 逐样本位精确：全部一致 → 999（满格哨兵），否则 0
            max_abs = float(np.max(np.abs(ref - dut))) if ref.shape == dut.shape else 1e9
            precision = SQNR_CAP_DB if (ref.shape == dut.shape and max_abs == 0.0) else 0.0
        else:
            precision = _sqnr_db(ref, dut)
        thr = (received / cycles) if cycles > 0 else 0.0
        return {"sqnr_db": precision, "cycles": cycles, "received": received, "throughput": thr}, None


def _synthesize(program_path: str, synth_timeout: int) -> Tuple[Optional[int], Dict[str, int], Optional[str]]:
    with tempfile.TemporaryDirectory(prefix="commdsp_synth_") as workdir:
        prog = str(Path(program_path).resolve())
        return _run_yosys(workdir, prog, synth_timeout)


def _error_result(stage: str, msg: str, suggestion: str = "") -> EvaluationResult:
    # 哨兵指标：让失败程序进入网格最差 cell（而非被框架丢弃），
    # 保留为父代材料形成修复环路（类似 REvolution 的 Fail population）。
    # area 用适度哨兵值，避免毒化自适应特征缩放。
    return EvaluationResult(
        metrics={
            "combined_score": 0.0,
            "precision": 0.0,
            "area": 10000.0,
            "throughput": 0.0,
        },
        artifacts={
            "error_type": stage,
            "error_message": msg[-1500:] if msg else "unknown error",
            "suggestion": suggestion or "Check Verilog syntax and synthesizability",
        },
    )


# ---------------------------------------------------------------------------
# Cascade stages（OpenEvolve evaluator 接口约定）
# ---------------------------------------------------------------------------

def evaluate_stage1(program_path: str) -> EvaluationResult:
    """L0+L1: 编译 + 256 样本冒烟（cascade_thresholds[0] 与 combined_score 比较）"""
    try:
        return _evaluate_stage1_impl(program_path)
    except Exception as e:  # 评估器自身异常也走哨兵路径，避免框架丢弃个体
        import traceback
        return _error_result("evaluator_exception", traceback.format_exc(),
                             "Internal evaluator error; see traceback in artifacts.")


def _evaluate_stage1_impl(program_path: str) -> EvaluationResult:
    task = _load_task()
    t = task.get("timeouts", {})
    sim_timeout = int(t.get("L1", 5)) + 5

    result, err = _simulate(program_path, SMOKE_SAMPLES, sim_timeout, metric_mode="sqnr")
    if result is None:
        return _error_result(
            "smoke_fail", err,
            "Fix compile errors or handshake protocol violations "
            "(module top, ports, valid/ready semantics).",
        )
    smoke_sqnr = result["sqnr_db"]
    # 封顶 0.49：stage2 超时/失败时 stage1 分数不得成为"幻影最优"
    # （合法 stage2 评估分 ≥ 0.5；级联网关阈值 0.2 不受影响）
    combined = min(max(smoke_sqnr / 60.0, 0.0), 1.0) * 0.49
    return EvaluationResult(
        metrics={
            "stage1_passed": 1.0,
            "combined_score": combined,
            # 哨兵特征值：若未过 cascade 阈值（约 SQNR<12dB），低分个体仍可入网格，
            # 保留为父代材料形成修复环路；过阈值时 stage2 真实值覆盖（合并逻辑后写优先）
            "precision": 0.0,
            "area": 10000.0,
            "throughput": 0.0,
        },
        artifacts={
            "smoke_sqnr_db": f"{smoke_sqnr:.2f}",
            "smoke_samples": str(SMOKE_SAMPLES),
        },
    )


def evaluate_stage2(program_path: str) -> EvaluationResult:
    """L2: 全量仿真 + ice40 综合"""
    try:
        return _evaluate_stage2_impl(program_path)
    except Exception as e:
        import traceback
        return _error_result("evaluator_exception", traceback.format_exc(),
                             "Internal evaluator error; see traceback in artifacts.")


def _evaluate_stage2_impl(program_path: str) -> EvaluationResult:
    task = _load_task()
    t = task.get("timeouts", {})
    sim_timeout = int(t.get("L2_sim", 30)) + 10
    synth_timeout = int(t.get("L2_synth", 60)) + 10
    full_samples = int(task["golden"]["stimulus"].get("samples", FULL_SAMPLES))

    result, err = _simulate(program_path, full_samples, sim_timeout)
    if result is None:
        return _error_result(
            "full_sim_fail", err,
            "Design passed smoke test but failed full simulation "
            "(possible hang, overflow or protocol violation).",
        )
    area, counts, synth_err = _synthesize(program_path, synth_timeout)
    if area is None:
        return _error_result("synth_fail", synth_err, "Check synthesizability (synth_ice40).")

    # Nangate45 ASIC 主口径（不进网格维度，避免破坏存量 checkpoint 的 LUT 坐标；
    # 正式实验时可直接切 feature_dimensions 到 area_um2）
    with tempfile.TemporaryDirectory(prefix="commdsp_asic_") as asic_dir:
        area_um2, asic_err = _run_yosys_asic(
            asic_dir, str(Path(program_path).resolve()), synth_timeout
        )

    sqnr = result["sqnr_db"]
    thr = result["throughput"]
    combined = _combined_score(sqnr, area, thr)
    metrics = {
        "precision": round(sqnr, 4),
        "area": float(area),
        "throughput": round(thr, 6),
        "combined_score": combined,
    }
    if area_um2 is not None:
        metrics["area_um2"] = round(area_um2, 2)
    return EvaluationResult(
        metrics=metrics,
        artifacts={
            "sqnr_db": f"{sqnr:.2f}",
            "area_lut": str(area),
            "cell_counts": json.dumps(counts),
            "area_um2": f"{area_um2:.2f}" if area_um2 is not None else (f"asic_fail: {asic_err[-200:]}" if asic_err else "n/a"),
            "cycles": str(result["cycles"]),
            "note": "area = ice40 LUT (grid dim); area_um2 = Nangate45 45nm ASIC (paper metric)",
        },
    )


def evaluate(program_path: str) -> EvaluationResult:
    """完整评估（非 cascade 路径 / 命令行测试用）"""
    r1 = evaluate_stage1(program_path)
    if r1.metrics.get("combined_score", 0.0) <= 0.0:
        return r1
    return evaluate_stage2(program_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: python {sys.argv[0]} <program.v>")
        sys.exit(1)
    res = evaluate(sys.argv[1])
    print("metrics:", json.dumps(res.metrics, indent=2))
    print("artifacts:", json.dumps(res.artifacts, indent=2))
