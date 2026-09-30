"""DDC 指标：局部指标（筛选用）与系统指标（真值），及谱加权预测模型。

口径约定（冻结）：
  - SQNR 一律逐字段（re/im）取最差（SPEC §5.2 / evaluator._sqnr_db 同式）；
  - SFDR 用 Blackman-Harris 窗、纯音长记录；
  - 系统质量主指标 = 实现 EVM：候选输出相对同输入 float 参考输出的误差
    （含 AWGN 与干扰的共同分量抵消，只反映候选数值误差）；
    前 n_pre_out 个输出样点做冻结增益/相位 LS 对齐，原始偏置另报；
  - evm_total：符号域总 EVM（匹配 RRC + 符号抽取 + 前导 LS 对齐），
    相对发送符号，含 AWGN 底（约 −SNR dB）；
  - 带内误差：误差谱在 |f| ≤ PB_EDGE 的积分相对输出信号功率（dB）。
"""

from __future__ import annotations

import math

import numpy as np

from . import spec


# ---------------------------------------------------------------------------
# 基础指标
# ---------------------------------------------------------------------------

def worst_field_sqnr_db(ref: np.ndarray, dut: np.ndarray) -> float:
    """复数场拆 re/im 两字段，逐字段 SQNR 取最差（与 evaluator 同式）。"""
    worst = 999.0
    for a, b in ((ref.real, dut.real), (ref.imag, dut.imag)):
        sig = float(np.mean(a ** 2))
        err = float(np.mean((a - b) ** 2))
        s = 999.0 if err <= 0 else (-999.0 if sig <= 0
                                    else 10 * math.log10(sig / err))
        worst = min(worst, s)
    return worst


def nco_accumulator_metrics(nco_cfg: dict, acc_bits: int = 32) -> dict:
    """均匀 accumulator 全域上的 calibrated 与 raw NCO ``M_core``。

    候选只读取 accumulator 的高 ``phase_bits`` 位，所以每个相位 bin 内
    候选输出恒定。复增益与 MSE 用 bin 内单位根几何和精确合并；WCE 由
    每个不跨象限 bin 的端点给出；last-bit accuracy 用单调量化码区间在
    整数 accumulator 上二分计数。raw 三指标按相同定义但不除全局复
    增益，供冻结协议的敏感性分析使用。理想 Q1.15 码采用 ``np.rint``
    的 ties-to-even 后饱和到 [-32768,32767]，所以 cos(0) 的理想码为
    32767。默认域大小为 2^32，但复杂度只与 2^phase_bits 和
    acc_bits 成正比。

    MSE 使用闭式功率差，约 90 dB 以上会有浮点抵消；缩位宽暴力对拍
    显示其 SQNR 误差远低于冻结的 0.10 dB 容差，但正式运行仍须记录
    全尺寸校准结果。
    """
    phase_bits = int(nco_cfg["phase_bits"])
    if not 2 <= phase_bits <= min(16, acc_bits):
        raise ValueError("phase_bits 必须在 [2,min(16,acc_bits)] 内")

    from certfit import tpl_cordic

    n_bins = 1 << phase_bits
    domain = 1 << acc_bits
    bin_size = 1 << (acc_bits - phase_bits)
    phase_word = np.arange(n_bins, dtype=np.int64)
    z = phase_word << (16 - phase_bits)
    z_signed = np.where(z >= (1 << 15), z - (1 << 16), z).astype(np.int64)
    params = ({"algo": "lut", "order": nco_cfg["order"],
               "depth": int(nco_cfg["depth"])}
              if nco_cfg["algo"] == "lut"
              else {"algo": "cordic", "stages": int(nco_cfg["stages"])})
    sin_code, cos_code = tpl_cordic.emulate(params, z_signed)
    candidate = (cos_code + 1j * sin_code) / float(1 << 15)

    starts = phase_word * bin_size
    ends = starts + bin_size - 1
    omega = 2.0 * math.pi / domain
    center = starts.astype(np.float64) + (bin_size - 1) / 2.0
    root_sum_mag = math.sin(bin_size * omega / 2.0) / math.sin(omega / 2.0)
    root_sums = root_sum_mag * np.exp(-1j * omega * center)
    gain = np.sum(candidate * root_sums) / domain
    if abs(gain) <= np.finfo(float).tiny:
        raise ValueError("NCO 全域复增益为零，无法校正")
    calibrated = candidate / gain

    candidate_power = float(np.mean(np.abs(candidate) ** 2))
    mse = float(candidate_power / (abs(gain) ** 2) - 1.0)
    mse = max(0.0, mse)
    sqnr = math.inf if mse == 0.0 else -10.0 * math.log10(mse)
    raw_mse = max(0.0, float(candidate_power - 2.0 * gain.real + 1.0))
    raw_sqnr = math.inf if raw_mse == 0.0 else -10.0 * math.log10(raw_mse)

    theta_start = omega * starts
    theta_end = omega * ends
    cos_start, cos_end = np.cos(theta_start), np.cos(theta_end)
    sin_start, sin_end = np.sin(theta_start), np.sin(theta_end)
    re = calibrated.real
    im = calibrated.imag
    wce_re = np.maximum(np.abs(re - cos_start), np.abs(re - cos_end))
    wce_im = np.maximum(np.abs(im - sin_start), np.abs(im - sin_end))
    wce_lsb = float((1 << 15) * max(np.max(wce_re), np.max(wce_im)))

    raw_re = candidate.real
    raw_im = candidate.imag
    raw_wce_re = np.maximum(np.abs(raw_re - cos_start),
                            np.abs(raw_re - cos_end))
    raw_wce_im = np.maximum(np.abs(raw_im - sin_start),
                            np.abs(raw_im - sin_end))
    raw_wce_lsb = float((1 << 15) * max(np.max(raw_wce_re),
                                        np.max(raw_wce_im)))

    hit_count = _last_bit_hit_count(
        re, im, starts, ends, acc_bits)
    raw_hit_count = _last_bit_hit_count(
        raw_re, raw_im, starts, ends, acc_bits)

    return {
        "sqnr_db": float(sqnr),
        "mse": mse,
        "wce_lsb": wce_lsb,
        "last_bit_accuracy": hit_count / domain,
        "last_bit_hit_count": hit_count,
        "raw_sqnr_db": float(raw_sqnr),
        "raw_mse": raw_mse,
        "raw_wce_lsb": raw_wce_lsb,
        "raw_last_bit_accuracy": raw_hit_count / domain,
        "raw_last_bit_hit_count": raw_hit_count,
        "domain_size": domain,
        "phase_bins": n_bins,
        "gain_re": float(gain.real),
        "gain_im": float(gain.imag),
    }


def _last_bit_hit_count(re: np.ndarray, im: np.ndarray,
                        starts: np.ndarray, ends: np.ndarray,
                        acc_bits: int) -> int:
    """计算 I/Q 同时落在正确舍入理想码 ±1 LSB 内的 accumulator 数。"""
    re_code = re * (1 << 15)
    im_code = im * (1 << 15)
    re_lo = np.ceil(re_code - 1.0).astype(np.int64)
    re_hi = np.floor(re_code + 1.0).astype(np.int64)
    im_lo = np.ceil(im_code - 1.0).astype(np.int64)
    im_hi = np.floor(im_code + 1.0).astype(np.int64)
    re_first, re_last = _ideal_code_intervals(
        starts, ends, re_lo, re_hi, acc_bits, component="cos")
    im_first, im_last = _ideal_code_intervals(
        starts, ends, im_lo, im_hi, acc_bits, component="sin")
    first = np.maximum(re_first, im_first)
    last = np.minimum(re_last, im_last)
    return int(np.sum(np.maximum(0, last - first + 1), dtype=np.int64))


def _ideal_output_code(acc: np.ndarray, acc_bits: int,
                       component: str) -> np.ndarray:
    theta = (2.0 * math.pi / (1 << acc_bits)) * acc.astype(np.float64)
    value = np.cos(theta) if component == "cos" else np.sin(theta)
    return np.clip(np.rint(value * (1 << 15)), -(1 << 15), (1 << 15) - 1).astype(np.int64)


def _ideal_code_intervals(starts: np.ndarray, ends: np.ndarray,
                          code_lo: np.ndarray, code_hi: np.ndarray,
                          acc_bits: int, component: str) -> tuple[np.ndarray, np.ndarray]:
    """每个不跨象限 bin 内，理想量化码落在 [lo,hi] 的首末 accumulator。"""
    mid_phase = (2.0 * math.pi / (1 << acc_bits)) * (
        (starts.astype(np.float64) + ends.astype(np.float64)) / 2.0)
    if component == "cos":
        increasing = mid_phase >= math.pi
    elif component == "sin":
        increasing = (mid_phase < math.pi / 2.0) | (mid_phase >= 3.0 * math.pi / 2.0)
    else:
        raise ValueError("component 必须是 cos 或 sin")

    # 把递减段乘 -1 后统一成非递减整数码，再做两个 lower_bound。
    lo_target = np.where(increasing, code_lo, -code_hi)
    hi_target = np.where(increasing, code_hi, -code_lo)

    def monotone_code(acc: np.ndarray) -> np.ndarray:
        code = _ideal_output_code(acc, acc_bits, component)
        return np.where(increasing, code, -code)

    def lower_bound(target: np.ndarray) -> np.ndarray:
        lo = starts.copy()
        hi = ends.copy() + 1
        for _ in range(acc_bits + 1):
            active = lo < hi
            if not np.any(active):
                break
            mid = (lo + hi) // 2
            go_right = monotone_code(mid) < target
            lo = np.where(active & go_right, mid + 1, lo)
            hi = np.where(active & ~go_right, mid, hi)
        return lo

    first = lower_bound(lo_target)
    after = lower_bound(hi_target + 1)
    valid = (code_lo <= code_hi) & (first < after)
    return np.where(valid, first, ends + 1), np.where(valid, after - 1, starts - 1)


def sfdr_db(x: np.ndarray, ideal_tone: np.ndarray,
            zero_pad_factor: int = 8) -> float:
    """冻结有限记录上的复 NCO SFDR（dBc）。

    先按已知理想载波做复数最小二乘消除，再对残差加四项
    Blackman-Harris 窗并搜索最大谱线。这样不会把窗的载波主瓣误当杂散，
    也不依赖任意的“峰值 ±N bin”排除宽度。

    ``ideal_tone`` 必须与候选使用相同的整数 FCW 和初相；本函数测的是
    冻结记录长度下的确定性 SFDR，不冒充无限周期解析 SFDR。
    """
    from scipy.signal.windows import blackmanharris

    x = np.asarray(x, dtype=np.complex128)
    u = np.asarray(ideal_tone, dtype=np.complex128)
    if x.ndim != 1 or u.ndim != 1 or len(x) != len(u) or len(x) < 2:
        raise ValueError("x 与 ideal_tone 必须是一维、等长且至少含 2 个样点")
    if zero_pad_factor < 1:
        raise ValueError("zero_pad_factor 必须为正整数")

    u_energy = float(np.vdot(u, u).real)
    if u_energy <= 0.0:
        raise ValueError("ideal_tone 能量必须为正")
    g = np.vdot(u, x) / u_energy
    residual = x - g * u
    w = blackmanharris(len(x), sym=True)
    coherent_gain = float(np.sum(w))
    spectrum = np.fft.fft(residual * w, n=zero_pad_factor * len(x))
    spur = float(np.max(np.abs(spectrum)) / coherent_gain)
    carrier = float(abs(g))
    if carrier <= 0.0:
        return -math.inf
    if spur <= 0.0:
        return math.inf
    return float(20.0 * math.log10(carrier / spur))


# ---------------------------------------------------------------------------
# 系统指标
# ---------------------------------------------------------------------------

def aligned_impl_error(y_ref: np.ndarray, y_fix: np.ndarray,
                       n_pre_out: int,
                       y_des_ref: np.ndarray | None = None) -> dict:
    """实现误差：前导段冻结 LS 复增益对齐 + 全段误差。

    返回 raw 误差（不对齐）、aligned 误差、以及对齐偏置（|g| dB 与相位）。
    """
    if len(y_ref) != len(y_fix):
        raise ValueError("y_ref 与 y_fix 必须等长")
    if not 0 < n_pre_out < len(y_ref):
        raise ValueError("n_pre_out 必须把非空前导段与非空测量段分开")
    if y_des_ref is None:
        y_des_ref = y_ref
    if len(y_des_ref) != len(y_ref):
        raise ValueError("y_des_ref 与 y_ref 必须等长")

    pre_energy = float(np.sum(np.abs(y_ref[:n_pre_out]) ** 2))
    if pre_energy <= 0.0:
        raise ValueError("参考前导段能量必须为正")
    if np.array_equal(y_ref[:n_pre_out], y_fix[:n_pre_out]):
        # 零实现误差校准必须在浮点实现里也精确落到 g=1，而不是留下求和
        # 舍入产生的 1e-16 级伪误差。
        g = 1.0 + 0.0j
    else:
        g = np.sum(np.conj(y_ref[:n_pre_out]) * y_fix[:n_pre_out]) / pre_energy
    if abs(g) <= np.finfo(float).tiny:
        raise ValueError("候选前导段复增益为零，无法对齐")
    y_al = y_fix / g
    seg = slice(n_pre_out, len(y_ref))  # 数据段（对齐冻结后）
    e_raw = y_fix[seg] - y_ref[seg]
    e_al = y_al[seg] - y_ref[seg]
    p_ref = float(np.mean(np.abs(y_des_ref[seg]) ** 2))
    if p_ref <= 0.0:
        raise ValueError("desired-only 参考测量段功率必须为正")
    raw_linear = float(np.mean(np.abs(e_raw) ** 2)) / p_ref
    aligned_linear = float(np.mean(np.abs(e_al) ** 2)) / p_ref
    return {
        "err_raw": raw_linear,
        "err_aligned": aligned_linear,
        "err_raw_db": -math.inf if raw_linear <= 0.0 else 10 * math.log10(raw_linear),
        "err_aligned_db": (-math.inf if aligned_linear <= 0.0
                           else 10 * math.log10(aligned_linear)),
        "gain_off_db": 20 * math.log10(abs(g)),
        "phase_off_deg": math.degrees(math.atan2(g.imag, g.real)) % 360.0,
        "gain_re": float(g.real),
        "gain_im": float(g.imag),
        "p_ref": p_ref,
    }


def symbol_evm(y_out: np.ndarray, symbols: np.ndarray, sps_out: int,
               n_pre_sym: int, delay_out: int) -> dict:
    """符号域总 EVM：匹配 RRC → 符号采样 → 前导 LS 对齐 → 对发送符号。

    delay_out: 输出域符号中心偏移（由链结构确定，冻结一次）。
    """
    from .scenarios import rrc_taps
    sps = sps_out
    h_mf = rrc_taps(sps, spec.RRC_BETA)
    mf = np.convolve(y_out, h_mf, mode="full")
    sym_idx = delay_out + np.arange(len(symbols)) * sps
    sym_idx = sym_idx[sym_idx < len(mf)]
    ns = len(sym_idx)
    rxsym = mf[sym_idx] * sps
    txsym = symbols[:ns]
    g = (np.sum(np.conj(txsym[:n_pre_sym]) * rxsym[:n_pre_sym])
         / np.sum(np.abs(txsym[:n_pre_sym]) ** 2))
    rx_al = rxsym / g
    seg = slice(n_pre_sym, ns)
    evm = float(np.mean(np.abs(rx_al[seg] - txsym[seg]) ** 2)
                / np.mean(np.abs(txsym[seg]) ** 2))
    return {"evm_total_db": -10 * math.log10(evm), "n_sym": ns - n_pre_sym}


def inband_error_db(y_ref: np.ndarray, y_fix: np.ndarray) -> float:
    """带内误差：|E(f)|² 在 |f| ≤ PB_EDGE 的积分 / 输出信号功率（dB）。"""
    e = y_fix - y_ref
    n = len(e)
    E = np.fft.fftshift(np.fft.fft(e))
    Y = np.fft.fftshift(np.fft.fft(y_ref))
    f = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / spec.FS_OUT))
    band = np.abs(f) <= spec.PB_EDGE_MHZ * 1e6
    p_err = float(np.mean(np.abs(E[band]) ** 2))
    p_sig = float(np.mean(np.abs(Y[band]) ** 2))
    return 10 * math.log10(p_err / p_sig)


# ---------------------------------------------------------------------------
# 谱加权预测模型（经典基线：逐级误差 + FIR 加权 + 抽取折叠）
# ---------------------------------------------------------------------------

def spectral_prediction(e_mix: np.ndarray, fir_err: np.ndarray,
                        h_ideal: np.ndarray, p_ref: float) -> dict:
    """预测输出误差功率（经典谱加权模型——不跑完整链路组合）。

    精确分解（FIR 线性）：
      out_fix − out_ref = fir_err(x_fix) ⊕ h_ideal ⊛ e_mix
    其中 fir_err 是 FIR 自身误差（同输入下候选 FIR − 理想 FIR，含系数
    量化失配与算术误差），e_mix 是混频级误差。经典模型把两项的**相干和**
    近似为**功率和**（忽略互相关）：
      P_out(f) ≈ |H_id(f)|²·|E_mix(f)|² + |A(f)|²    （每 bin 除以 N²）
    抽取折叠（R 倍降采样，复信号镜像副本相加）：
      P_fold[k] = Σ_{j<R} P_in[k + j·N_out]
    预测与真值的差不预先归因：至少包括被功率和近似丢弃的互相关项，以及
    CMUL/FIR 舍入、截断、饱和残差及其交叉项；须由逐级分解另行验证。

    参数（同一有效段、同一长度 N，FIR 有效段口径）：
      e_mix   : 混频级误差 = 候选混频输出 − 理想混频（Q1.15 刻度 float）
      fir_err : FIR 自身误差 = fir_fixed(x_mix_fix) − fir_float(x_mix_fix)
      h_ideal : 理想原型系数（DC 归一）
      p_ref   : 参考输出时域平均功率（与 aligned_impl_error 同分母口径）
    """
    n_in = len(e_mix)
    assert len(fir_err) == n_in, "误差序列须同长度（FIR 有效段）"
    n_out = n_in // spec.R
    assert n_out * spec.R == n_in, "有效段长度须为 R 的整数倍"
    E = np.fft.fft(e_mix)
    A = np.fft.fft(fir_err)
    H = np.fft.fft(h_ideal / float(np.sum(h_ideal)), n_in)
    p_in = ((np.abs(H) ** 2) * (np.abs(E) ** 2) + np.abs(A) ** 2) / (n_in ** 2)

    p_fold = fold_power_aliases(p_in, spec.R)
    pred_err = float(np.sum(p_fold))

    f_out = np.fft.fftfreq(n_out, 1.0 / spec.FS_OUT)
    band = np.abs(f_out) <= spec.PB_EDGE_MHZ * 1e6
    pred_inband_err = float(np.sum(p_fold[band]))
    return {
        "pred_err": pred_err / p_ref,
        "pred_err_db": 10 * math.log10(pred_err / p_ref),
        "pred_inband_err": pred_inband_err / p_ref,
        "pred_inband_err_db": 10 * math.log10(pred_inband_err / p_ref),
    }


def fold_power_aliases(p_in: np.ndarray, r: int) -> np.ndarray:
    """按抽取的 alias preimage 折叠功率谱。

    对输入长度 ``N``、输出长度 ``N_out=N/r``，输出 bin ``k`` 的
    preimage 是 ``k + j*N_out``，而不是相邻的 ``j::r``。
    """
    p_in = np.asarray(p_in)
    if p_in.ndim != 1 or r < 1 or len(p_in) % r:
        raise ValueError("p_in 必须是一维，且长度能被 r 整除")
    n_out = len(p_in) // r
    return p_in.reshape(r, n_out).sum(axis=0)
