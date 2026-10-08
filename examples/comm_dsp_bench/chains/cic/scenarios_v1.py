"""从第二次冻结 manifest 生成 CIC 输入场景。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from chains.ddc.scenarios import qpsk_symbols, rrc_taps
from chains.cic.reference import fir_coefficients


BENCH = Path(__file__).resolve().parent.parent.parent
PREFLIGHT = BENCH / "experiments_system/cic_witness_v1/preflight_manifest.json"


@dataclass
class CICScenarioData:
    spec: dict
    x: np.ndarray
    desired: np.ndarray
    blocker: np.ndarray
    noise: np.ndarray
    i_codes: np.ndarray
    q_codes: np.ndarray
    desired_i_codes: np.ndarray
    desired_q_codes: np.ndarray
    n_pre_in: int
    scale: float
    levels: dict


def load_manifest() -> dict:
    return json.loads(PREFLIGHT.read_text())


def adc_codes(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lo, hi = -2048, 2047
    i = np.clip(np.floor(np.asarray(x).real * 2048.0 + 0.5), lo, hi).astype(np.int64)
    q = np.clip(np.floor(np.asarray(x).imag * 2048.0 + 0.5), lo, hi).astype(np.int64)
    return i, q


def _ideal_float(v: np.ndarray, R: int, N: int) -> np.ndarray:
    h = fir_coefficients(R, N).astype(np.float64) / float(R ** N)
    return np.convolve(np.asarray(v, dtype=np.complex128), h)[: len(v)][::R]


def generate(spec: dict) -> CICScenarioData:
    signal = load_manifest()["scenario_manifest"]["signal"]
    fs = float(signal["fs_in_hz"])
    sps = int(round(fs / float(signal["symbol_rate_hz"])))
    n_warm = int(signal["n_warmup_symbols"])
    n_meas = int(signal["n_measure_symbols"])
    n_total = (n_warm + n_meas) * sps
    n_pre = n_warm * sps

    root = np.random.default_rng(int(spec["seed"]))
    sym_seed = int(root.integers(0, 2**31))
    noise_seed = int(root.integers(0, 2**31))
    blocker_seed = int(root.integers(0, 2**31))

    symbols = qpsk_symbols(n_warm + n_meas, sym_seed)
    up = np.zeros(n_total, dtype=np.complex128)
    up[::sps] = symbols
    taps = rrc_taps(sps, float(signal["rrc_beta"]))
    desired = np.convolve(up, taps, mode="same")
    p_desired = float(np.mean(np.abs(desired) ** 2))

    t = np.arange(n_total, dtype=np.float64) / fs
    blocker = np.zeros(n_total, dtype=np.complex128)
    if spec["blocker_hz"] is not None:
        phase = float(np.random.default_rng(blocker_seed).uniform(0.0, 2.0 * math.pi))
        amplitude = math.sqrt(p_desired) * 10.0 ** (float(spec["blocker_rel_db"]) / 20.0)
        blocker = amplitude * np.exp(
            1j * (2.0 * math.pi * float(spec["blocker_hz"]) * t + phase)
        )

    noise_unit = (np.random.default_rng(noise_seed).standard_normal(n_total)
                  + 1j * np.random.default_rng(noise_seed ^ 0x5A5A5A5A).standard_normal(n_total))
    noise_unit /= math.sqrt(2.0)
    R = int(spec["R"])
    # 同一 R 下 N=3/4 必须看到同一输入。用固定 N=4 的理想 CIC 作为场景噪声
    # 校准链，令 desired-only 输出测量段 SNR 为 manifest 的 30 dB；N=3 不重新定幅。
    calibration_N = 4
    n_pre_out = n_pre // R
    y_des = _ideal_float(desired, R, calibration_N)[n_pre_out:]
    y_noise_unit = _ideal_float(noise_unit, R, calibration_N)[n_pre_out:]
    p_des_out = float(np.mean(np.abs(y_des) ** 2))
    p_noise_unit_out = float(np.mean(np.abs(y_noise_unit) ** 2))
    noise_gain = math.sqrt(p_des_out / (p_noise_unit_out * 10.0 ** (
        float(spec["awgn_snr_db"]) / 10.0)))
    noise = noise_unit * noise_gain

    raw = desired + blocker + noise
    peak = float(np.max(np.abs(raw)))
    front_scale = 0.95 / peak if peak >= 1.0 else 1.0
    desired_s = front_scale * desired
    blocker_s = front_scale * blocker
    noise_s = front_scale * noise
    x = desired_s + blocker_s + noise_s
    i_codes, q_codes = adc_codes(x)
    desired_i, desired_q = adc_codes(desired_s)
    return CICScenarioData(
        spec=spec,
        x=x,
        desired=desired_s,
        blocker=blocker_s,
        noise=noise_s,
        i_codes=i_codes,
        q_codes=q_codes,
        desired_i_codes=desired_i,
        desired_q_codes=desired_q,
        n_pre_in=n_pre,
        scale=front_scale,
        levels={
            "p_desired_in": p_desired * front_scale * front_scale,
            "p_blocker_in": float(np.mean(np.abs(blocker_s) ** 2)),
            "p_noise_in": float(np.mean(np.abs(noise_s) ** 2)),
            "snr_in_fullband_db": 10.0 * math.log10(
                float(np.mean(np.abs(desired_s) ** 2))
                / float(np.mean(np.abs(noise_s) ** 2))
            ),
            "noise_calibration_N": calibration_N,
            "snr_calibration_output_db": 10.0 * math.log10(
                p_des_out / (p_noise_unit_out * noise_gain * noise_gain)
            ),
            "peak_raw": peak,
            "scale": front_scale,
        },
    )


def all_specs(split: str | None = None) -> list[dict]:
    rows = load_manifest()["scenario_manifest"]["rows"]
    return [row for row in rows if split is None or row["split"] == split]
