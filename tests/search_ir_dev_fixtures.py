"""只用于软件边界测试的固定合成输入，不生成 witness 场景。"""

import sys
from pathlib import Path

import numpy as np

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.dev_fixtures import make_candidate
from search_ir.evaluate import prepare_case


def make_case(case_id="synthetic-tone"):
    n = np.arange(128)
    fcw = 0x31415927
    theta = 2 * np.pi * fcw * n / (1 << 32)
    # desired-only tone + 小幅输入扰动，reference 始终使用相同量化 ADC。
    desired = 0.2 * np.exp(1j * theta)
    x = desired + 0.001 * np.exp(0.13j * n)
    i = np.rint(x.real * 2048).astype(np.int64)
    q = np.rint(x.imag * 2048).astype(np.int64)
    return prepare_case(case_id, i, q, fcw, desired, n_pre_out=16)
