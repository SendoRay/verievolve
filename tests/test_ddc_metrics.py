import math
import sys
from pathlib import Path

import numpy as np


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.ddc import candidates, fixed_chain, metrics, ref_chain, run_s1, spec
from certfit import tpl_cordic


def test_fold_power_aliases_uses_true_preimages():
    p_in = np.arange(8, dtype=np.float64)
    # N_out=4: k 的 preimage 是 k 与 k+4，而不是相邻偶/奇 bin。
    np.testing.assert_array_equal(
        metrics.fold_power_aliases(p_in, 2),
        np.array([4.0, 6.0, 8.0, 10.0]),
    )


def test_sfdr_removes_known_carrier_and_recovers_injected_spurs():
    n = 4096
    idx = np.arange(n, dtype=np.float64)
    carrier = np.exp(2j * math.pi * 0.1937123 * idx)

    assert metrics.sfdr_db(carrier, carrier) >= 140.0

    for level_db, offset_bins in ((-40.0, 17.0), (-60.0, 17.5), (-80.0, 29.5)):
        spur = 10 ** (level_db / 20.0) * np.exp(
            2j * math.pi * (0.1937123 + offset_bins / n) * idx
        )
        measured = metrics.sfdr_db(carrier + spur, carrier)
        assert abs(measured + level_db) <= 0.10

    stronger = 10 ** (-50.0 / 20.0) * np.exp(
        2j * math.pi * (0.1937123 + 21.0 / n) * idx
    )
    weaker = 10 ** (-70.0 / 20.0) * np.exp(
        2j * math.pi * (0.1937123 + 43.0 / n) * idx
    )
    assert abs(metrics.sfdr_db(carrier + stronger + weaker, carrier) - 50.0) <= 0.10


def test_reference_alignment_is_exact_for_zero_implementation_error():
    rng = np.random.default_rng(7)
    y_ref = rng.standard_normal(128) + 1j * rng.standard_normal(128)
    y_des = 0.25 * np.ones(128, dtype=np.complex128)
    result = metrics.aligned_impl_error(y_ref, y_ref.copy(), 32, y_des)
    assert result["gain_off_db"] == 0.0
    assert result["phase_off_deg"] == 0.0
    assert result["err_aligned"] == 0.0
    assert result["err_aligned_db"] == -math.inf
    assert result["gain_re"] == 1.0 and result["gain_im"] == 0.0


def test_reference_alignment_recovers_known_complex_gain():
    rng = np.random.default_rng(11)
    y_ref = rng.standard_normal(256) + 1j * rng.standard_normal(256)
    gain = 0.875 * np.exp(0.37j)
    y_fix = gain * y_ref
    result = metrics.aligned_impl_error(y_ref, y_fix, 64, y_des_ref=y_ref)
    assert math.isclose(result["gain_re"], gain.real, rel_tol=0, abs_tol=1e-14)
    assert math.isclose(result["gain_im"], gain.imag, rel_tol=0, abs_tol=1e-14)
    assert result["err_aligned"] < 1e-29


def test_reference_alignment_known_small_error_and_desired_denominator():
    n = 256
    y_ref = np.ones(n, dtype=np.complex128)
    y_des = np.full(n, 0.5 + 0.0j)
    y_fix = y_ref.copy()
    y_fix[64:] += 1e-4j
    result = metrics.aligned_impl_error(y_ref, y_fix, 64, y_des_ref=y_des)
    # 前导完全相同，g 严格为 1；分母功率为 0.25，因此 q=4e-8。
    assert result["gain_re"] == 1.0 and result["gain_im"] == 0.0
    assert math.isclose(result["p_ref"], 0.25, rel_tol=0, abs_tol=0)
    assert math.isclose(result["err_aligned"], 4e-8, rel_tol=1e-12)


def test_reference_nco_uses_same_integer_fcw_as_candidate_interface():
    f_off_mhz = 0.39
    n = 64
    cos_i, sin_i, fcw = ref_chain.ideal_nco(f_off_mhz, n)
    assert fcw == int(round(f_off_mhz * 1e6 / spec.FS_IN * (1 << spec.W_P_ACC)))
    phase = 2.0 * math.pi * fcw * np.arange(n) / (1 << spec.W_P_ACC)
    np.testing.assert_allclose(cos_i + 1j * sin_i, np.exp(1j * phase), atol=1e-15)


def test_frozen_v2_pool_has_exactly_twenty_points_and_union_has_26():
    v2 = candidates.witness_nco_candidates(include_legacy=False)
    union = candidates.witness_nco_candidates(include_legacy=True)
    assert len(v2) == 20
    assert len(union) == 26
    assert len({x["name"] for x in v2}) == 20
    assert sum(x["algo"] == "lut" and x["order"] == "nearest" for x in v2) == 4
    assert sum(x["algo"] == "lut" and x["order"] == "linear" for x in v2) == 10
    assert sum(x["algo"] == "cordic" for x in v2) == 6


def test_cordic_stage_7_is_legal_but_stage_6_is_not():
    assert tpl_cordic.validate({"algo": "cordic", "stages": 7}) == (True, "ok")
    legal, reason = tpl_cordic.validate({"algo": "cordic", "stages": 6})
    assert not legal
    assert "[7,20]" in reason


def test_accumulator_metrics_match_small_domain_bruteforce():
    cases = [
        ({"algo": "lut", "order": "nearest", "depth": 128, "phase_bits": 4}, 10),
        ({"algo": "lut", "order": "linear", "depth": 256, "phase_bits": 6}, 11),
        ({"algo": "cordic", "stages": 7, "phase_bits": 8}, 12),
        # phase_bits == acc_bits：bin_size=1，覆盖最小 bin 边界。
        ({"algo": "lut", "order": "nearest", "depth": 1024, "phase_bits": 10}, 10),
    ]
    for cfg, acc_bits in cases:
        acc = np.arange(1 << acc_bits, dtype=np.int64)
        phase_word = acc >> (acc_bits - cfg["phase_bits"])
        z = phase_word << (16 - cfg["phase_bits"])
        z_signed = np.where(z >= 2**15, z - 2**16, z)
        params = ({"algo": "lut", "order": cfg["order"], "depth": cfg["depth"]}
                  if cfg["algo"] == "lut"
                  else {"algo": "cordic", "stages": cfg["stages"]})
        sin_code, cos_code = tpl_cordic.emulate(params, z_signed)
        candidate = (cos_code + 1j * sin_code) / 2**15
        ideal = np.exp(2j * math.pi * acc / 2**acc_bits)
        gain = np.vdot(ideal, candidate) / len(acc)
        calibrated = candidate / gain
        error = calibrated - ideal
        raw_error = candidate - ideal
        mse = float(np.mean(np.abs(error) ** 2))
        raw_mse = float(np.mean(np.abs(raw_error) ** 2))
        wce_lsb = float(2**15 * max(np.max(np.abs(error.real)),
                                    np.max(np.abs(error.imag))))
        raw_wce_lsb = float(2**15 * max(np.max(np.abs(raw_error.real)),
                                        np.max(np.abs(raw_error.imag))))
        ideal_re_code = np.clip(np.rint(ideal.real * 2**15), -2**15, 2**15 - 1)
        ideal_im_code = np.clip(np.rint(ideal.imag * 2**15), -2**15, 2**15 - 1)
        hits = ((np.abs(calibrated.real * 2**15 - ideal_re_code) <= 1.0)
                & (np.abs(calibrated.imag * 2**15 - ideal_im_code) <= 1.0))
        raw_hits = ((np.abs(candidate.real * 2**15 - ideal_re_code) <= 1.0)
                    & (np.abs(candidate.imag * 2**15 - ideal_im_code) <= 1.0))

        exact = metrics.nco_accumulator_metrics(cfg, acc_bits=acc_bits)
        assert math.isclose(exact["gain_re"], gain.real, rel_tol=0, abs_tol=1e-14)
        assert math.isclose(exact["gain_im"], gain.imag, rel_tol=0, abs_tol=1e-14)
        assert math.isclose(exact["mse"], mse, rel_tol=0, abs_tol=1e-12)
        assert math.isclose(exact["wce_lsb"], wce_lsb, rel_tol=0, abs_tol=1e-8)
        assert exact["last_bit_hit_count"] == int(np.sum(hits))
        assert math.isclose(exact["raw_mse"], raw_mse, rel_tol=0, abs_tol=1e-12)
        assert math.isclose(exact["raw_wce_lsb"], raw_wce_lsb,
                            rel_tol=0, abs_tol=1e-8)
        assert exact["raw_last_bit_hit_count"] == int(np.sum(raw_hits))


def test_accumulator_phase_mapping_matches_fixed_chain_nco():
    """防止 M_core 与主链的 accumulator→signed-angle 映射日后漂移。"""
    n = 1 << 16
    f_off_mhz = 0.57
    cfgs = [
        {"algo": "lut", "order": "nearest", "depth": 512, "phase_bits": 16},
        {"algo": "lut", "order": "linear", "depth": 256, "phase_bits": 8},
        {"algo": "cordic", "stages": 7, "phase_bits": 16},
    ]
    for cfg in cfgs:
        sin_chain, cos_chain = fixed_chain.nco_sincos(cfg, n, f_off_mhz)
        phase_word = fixed_chain.nco_phase_word(n, f_off_mhz, cfg["phase_bits"])
        z = phase_word << (16 - cfg["phase_bits"])
        z_signed = np.where(z >= 2**15, z - 2**16, z)
        params = ({"algo": "lut", "order": cfg["order"], "depth": cfg["depth"]}
                  if cfg["algo"] == "lut"
                  else {"algo": "cordic", "stages": cfg["stages"]})
        sin_direct, cos_direct = tpl_cordic.emulate(params, z_signed)
        np.testing.assert_array_equal(sin_chain, sin_direct)
        np.testing.assert_array_equal(cos_chain, cos_direct)


def test_kendall_tau_b_corrects_ties():
    a = np.array([0.0, 0.0, 1.0])
    b = np.array([0.0, 1.0, 2.0])
    assert math.isclose(run_s1.kendall_tau_a(a, b), 2.0 / 3.0)
    assert math.isclose(run_s1.kendall_tau_b(a, b), 2.0 / math.sqrt(6.0))


def test_topk_preserves_boundary_ties_and_all_truth_optima():
    selected = run_s1.topk_indices_with_ties(np.array([0.0, 1.0, 1.0, 2.0]), 2)
    assert selected == {0, 1, 2}
    assert run_s1.minimum_tie_indices(np.array([0.0, 0.0, 1.0])) == {0, 1}


def test_worst_inversion_labels_kept_and_dropped_correctly():
    # predictor 认为 B 更好（更小），truth 认为 A 更好；故 B 被保留、A 被误删。
    count, worst = run_s1.worst_inversion(
        np.array([3.0, 1.0]),
        np.array([1.0, 3.0]),
        ["A", "B"],
        margin=0.5,
    )
    assert count == 1
    assert worst["kept"] == "B"
    assert worst["dropped"] == "A"
    assert worst["pred_gap_db"] == 2.0
    assert worst["truth_gap_db"] == 2.0
