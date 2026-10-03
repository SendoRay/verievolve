"""quad有符号舍入回归；覆盖浅表截断及深表量化导致的正a2。"""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import types

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "examples/comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.ddc import rtl_gen
from design_gen import gen_lut_quarter
from search_ir.schema import lut_sincos

loader = importlib.util.spec_from_file_location("quad_verifier", ROOT / "scripts/verify_ddc_pilot.py")
verifier = importlib.util.module_from_spec(loader)
loader.loader.exec_module(verifier)


@pytest.fixture
def tools():
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp required")
    return {name: {"path": shutil.which(name)} for name in ("iverilog", "vvp")}


@pytest.mark.parametrize("depth", [64, 128, 256, 512, 1024])
@pytest.mark.parametrize("phase_bits", range(8, 17))
def test_quad_mapping_matches_model_for_every_phase(depth, phase_bits, tmp_path, tools):
    acc = (np.arange(65536, dtype=np.int64) << 16) | 0xA5A5
    result = verifier.check_nco(tmp_path / "mapping", lut_sincos(depth, "quad", phase_bits), tools, acc)
    assert result["status"] == "pass"


@pytest.mark.parametrize("depth", [64, 1024])
def test_original_generator_confirms_the_existing_model(depth, tmp_path, tools, monkeypatch):
    # 用原生成器的组合内部信号独立确认期望值，不调整模型来适配DDC错误。
    wrapper = """module nco_map(input [31:0] phase_acc, output signed [15:0] sin_o, cos_o);
wire signed [15:0] z = phase_acc[31:16];
top original(.clk(1'b0), .rst_n(1'b1), .in_valid(1'b0), .out_ready(1'b1), .z(z));
assign sin_o = original.sin_v;
assign cos_o = original.cos_v;
endmodule
"""
    source = wrapper + gen_lut_quarter(depth, "quad")
    monkeypatch.setattr(verifier, "lower_nco_map_rtl", lambda _: source)
    result = verifier.check_nco(tmp_path / "original", lut_sincos(depth, "quad", 16), tools,
                                np.arange(65536, dtype=np.int64) << 16)
    assert result["status"] == "pass"


def test_non_quad_emission_stays_byte_identical_to_pre_fix():
    p = subprocess.run(["git", "show", "834d449:examples/comm_dsp_bench/chains/ddc/rtl_gen.py"],
                       cwd=ROOT, capture_output=True, text=True)
    if p.returncode:
        pytest.skip("pre-fix checkpoint unavailable in this checkout")
    old = types.ModuleType("old_rtl_gen")
    old.__file__ = str(BENCH / "chains/ddc/rtl_gen.py")
    exec(compile(p.stdout, old.__file__, "exec"), old.__dict__)
    for order in ("nearest", "linear"):
        for depth in (64, 128, 256, 512, 1024):
            for b in (8, 12, 16):
                cfg = {"name": "parity", "algo": "lut", "order": order, "depth": depth, "phase_bits": b}
                assert rtl_gen.gen_nco_verilog(cfg) == old.gen_nco_verilog(cfg)
