import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from certfit import tpl_cordic
from chains.ddc import rtl_gen
from search_ir import (
    cordic_sincos,
    emulate_nco_accumulators,
    leaf_nco_config,
    lower_nco_map_rtl,
    lut_sincos,
    phasor_compose,
    split_phase_accumulators,
)


@pytest.mark.parametrize(
    "node",
    [
        lut_sincos(depth=256, interpolation="linear", phase_bits=12),
        cordic_sincos(stages=9, phase_bits=16),
    ],
)
def test_leaf_bittrue_lowering_matches_existing_model(node):
    rng = np.random.default_rng(20260930)
    acc = rng.integers(0, 1 << 32, size=4096, dtype=np.uint64).astype(np.int64)
    got_sin, got_cos = emulate_nco_accumulators(node, acc)

    cfg = leaf_nco_config(node)
    phase_word = acc >> (32 - cfg["phase_bits"])
    z = phase_word << (16 - cfg["phase_bits"])
    z_signed = np.where(z >= 1 << 15, z - (1 << 16), z).astype(np.int64)
    params = (
        {"algo": "lut", "order": cfg["order"], "depth": cfg["depth"]}
        if cfg["algo"] == "lut"
        else {"algo": "cordic", "stages": cfg["stages"]}
    )
    expected_sin, expected_cos = tpl_cordic.emulate(params, z_signed)
    np.testing.assert_array_equal(got_sin, expected_sin)
    np.testing.assert_array_equal(got_cos, expected_cos)


@pytest.mark.parametrize(
    "node",
    [
        lut_sincos(depth=512, interpolation="nearest", phase_bits=16),
        cordic_sincos(stages=7, phase_bits=14),
    ],
)
def test_leaf_rtl_lowering_reuses_verified_generator_without_name_dispatch(node):
    cfg = leaf_nco_config(node)
    assert cfg["name"].startswith("ir_")
    assert lower_nco_map_rtl(node) == rtl_gen.gen_nco_verilog(cfg)
    assert "module nco_map" in lower_nco_map_rtl(node)


def test_phase_split_is_exact_modulo_and_uses_centered_residual():
    rng = np.random.default_rng(17)
    acc = rng.integers(0, 1 << 32, size=4096, dtype=np.uint64).astype(np.int64)
    coarse, residual, residual_signed = split_phase_accumulators(acc, 8)
    assert np.all(((coarse + residual) & 0xFFFFFFFF) == acc)
    step = 1 << 24
    assert np.all(residual_signed >= -(step // 2))
    assert np.all(residual_signed < step // 2)


def _hybrid_node(rounding="rne"):
    return phasor_compose(
        lut_sincos(128, "nearest", 10),
        cordic_sincos(7, 16),
        split_bits=8,
        product_rounding=rounding,
    )


def _signed_literal(value):
    value = int(value)
    return f"-32'sd{-value}" if value < 0 else f"32'sd{value}"


def test_composition_bittrue_lowering_matches_explicit_child_product():
    hybrid = _hybrid_node()
    rng = np.random.default_rng(23)
    acc = rng.integers(0, 1 << 32, size=1024, dtype=np.uint64).astype(np.int64)
    coarse_acc, residual_acc, _ = split_phase_accumulators(acc, 8)
    coarse_sin, coarse_cos = emulate_nco_accumulators(hybrid["coarse"], coarse_acc)
    residual_sin, residual_cos = emulate_nco_accumulators(
        hybrid["residual"], residual_acc
    )
    expected_cos = np.clip(
        (coarse_cos * residual_cos - coarse_sin * residual_sin + (1 << 14)) >> 15,
        -(1 << 15),
        (1 << 15) - 1,
    )
    expected_sin = np.clip(
        (coarse_sin * residual_cos + coarse_cos * residual_sin + (1 << 14)) >> 15,
        -(1 << 15),
        (1 << 15) - 1,
    )
    got_sin, got_cos = emulate_nco_accumulators(hybrid, acc)
    np.testing.assert_array_equal(got_sin, expected_sin)
    np.testing.assert_array_equal(got_cos, expected_cos)


@pytest.mark.parametrize("rounding", ["rne", "trunc"])
def test_composition_rtl_matches_bittrue_model(tmp_path, rounding):
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not installed")
    hybrid = _hybrid_node(rounding)
    rng = np.random.default_rng(29)
    random_acc = rng.integers(0, 1 << 32, size=64, dtype=np.uint64).astype(np.int64)
    edge_acc = np.array(
        [0, 1, (1 << 23) - 1, 1 << 23, (1 << 24) - 1, 0xFFFFFFFF],
        dtype=np.int64,
    )
    acc = np.concatenate([edge_acc, random_acc])
    expected_sin, expected_cos = emulate_nco_accumulators(hybrid, acc)
    checks = []
    for index, (state, sin_code, cos_code) in enumerate(
        zip(acc, expected_sin, expected_cos)
    ):
        checks.extend(
            [
                f"phase_acc = 32'h{int(state):08x}; #1;",
                f"if ($signed(sin_o) !== {_signed_literal(sin_code)}) "
                f'$fatal(1, "sin mismatch {index}");',
                f"if ($signed(cos_o) !== {_signed_literal(cos_code)}) "
                f'$fatal(1, "cos mismatch {index}");',
            ]
        )
    tb = """module tb;
reg [31:0] phase_acc;
wire signed [15:0] sin_o, cos_o;
nco_map dut(.phase_acc(phase_acc), .sin_o(sin_o), .cos_o(cos_o));
initial begin
""" + "\n".join(checks) + "\n$display(\"PASS\"); $finish;\nend\nendmodule\n"
    rtl_path = tmp_path / "hybrid.v"
    tb_path = tmp_path / "tb.v"
    sim_path = tmp_path / "sim.out"
    rtl_path.write_text(lower_nco_map_rtl(hybrid), encoding="utf-8")
    tb_path.write_text(tb, encoding="utf-8")
    compile_result = subprocess.run(
        ["iverilog", "-g2012", "-o", str(sim_path), str(rtl_path), str(tb_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(
        ["vvp", str(sim_path)], capture_output=True, text=True, check=False
    )
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert "PASS" in run_result.stdout


def test_composition_rtl_is_synthesizable(tmp_path):
    if shutil.which("yosys") is None:
        pytest.skip("yosys not installed")
    rtl_path = tmp_path / "hybrid.v"
    rtl_path.write_text(lower_nco_map_rtl(_hybrid_node()), encoding="utf-8")
    result = subprocess.run(
        [
            "yosys",
            "-q",
            "-p",
            f"read_verilog -sv {rtl_path}; synth -top nco_map; check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
