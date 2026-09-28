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


def sfdr_db(x: np.ndarray) -> float:
    """实信号 SFDR（Blackman-Harris 窗，dBc）。"""
    from scipy.signal.windows import blackmanharris
    w = blackmanharris(len(x))
    xw = x * w
    spec_db = 20 * np.log10(np.abs(np.fft.rfft(xw)) + 1e-12)
    peak_bin = int(np.argmax(spec_db))
    floor = spec_db.copy()
    # 主峰邻域（±2 bin）不参与杂散
    lo, hi = max(0, peak_bin - 2), min(len(spec_db), peak_bin + 3)
    rest = np.concatenate([floor[:lo], floor[hi:]])
    return float(spec_db[peak_bin] - np.max(rest))


# ---------------------------------------------------------------------------
# 系统指标
# ---------------------------------------------------------------------------

def aligned_impl_error(y_ref: np.ndarray, y_fix: np.ndarray,
                       n_pre_out: int) -> dict:
    """实现误差：前导段冻结 LS 复增益对齐 + 全段误差。

    返回 raw 误差（不对齐）、aligned 误差、以及对齐偏置（|g| dB 与相位）。
    """
    g = (np.sum(np.conj(y_ref[:n_pre_out]) * y_fix[:n_pre_out])
         / np.sum(np.abs(y_ref[:n_pre_out]) ** 2))
    y_al = y_fix / g
    seg = slice(n_pre_out, len(y_ref))  # 数据段（对齐冻结后）
    e_raw = y_fix[seg] - y_ref[seg]
    e_al = y_al[seg] - y_ref[seg]
    p_ref = float(np.mean(np.abs(y_ref[seg]) ** 2))
    return {
        "err_raw_db": 10 * math.log10(float(np.mean(np.abs(e_raw) ** 2)) / p_ref),
        "err_aligned_db": 10 * math.log10(float(np.mean(np.abs(e_al) ** 2)) / p_ref),
        "gain_off_db": 20 * math.log10(abs(g)),
        "phase_off_deg": math.degrees(math.atan2(g.imag, g.real)) % 360.0,
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
    预测与真值的差 = 互相关项 + FIR 非线性（饱和）——这是要检验的模型假设。

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

    f_out = np.fft.fftfreq(n_out, 1.0 / spec.FS_OUT)
    band = np.abs(f_out) <= spec.PB_EDGE_MHZ * 1e6
    p_fold = np.zeros(n_out)
    for j in range(spec.R):
        p_fold += p_in[j::spec.R]
    pred_err = float(np.sum(p_fold[band]))
    return {"pred_err_db": 10 * math.log10(pred_err / p_ref)}
