import hashlib
import math
import sys
from pathlib import Path

import numpy as np


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from chains.ddc import scenarios, spec


def _gen(split, i=0, n_sym=256):
    return scenarios.generate_scenario(spec.build_witness_scenarios(split)[i], n_sym=n_sym)


def test_witness_scenario_counts_and_unique_keys():
    main = spec.build_witness_scenarios("main")
    held = spec.build_witness_scenarios("heldout")
    stress = spec.build_witness_scenarios("stress")
    assert (len(main), len(held), len(stress)) == (36, 32, 9)
    allsc = main + held + stress
    keys = {spec.scenario_key(s.klass, s.f_off_mhz, s.blocker_off_mhz,
                              s.blocker_rel_db, s.snr_db) for s in allsc}
    assert len(keys) == len(allsc)
    assert len({s.seed for s in allsc}) == len(allsc)
    assert all(s.split for s in allsc)
    # 主模板：每个频点 clean + OBB 0.30 + OBB 0.42 + alias 0.555（均 −3 dB）
    for s in main + held:
        assert s.klass == "clean" or s.blocker_rel_db == -3.0
    assert all(s.klass == "alias" and s.blocker_rel_db == 6.0 for s in stress)


def test_seed_depends_on_full_key_not_list_position():
    s = spec.build_witness_scenarios("heldout")[5]
    key = spec.scenario_key(s.klass, s.f_off_mhz, s.blocker_off_mhz,
                            s.blocker_rel_db, s.snr_db)
    assert key.startswith(spec.SCENARIO_VERSION + "|")
    expect = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") >> 1
    assert s.seed == expect
    # 重排列表不改变 seed
    rev = {x.name + x.split: x.seed for x in reversed(spec.build_witness_scenarios())}
    assert rev[s.name + s.split] == s.seed


def test_legacy_scenarios_bit_identical():
    # 旧清单保持 ddc-p0-v2 逐位行为（旧产物可复现，不被覆盖）
    old = spec.build_scenarios()
    assert [s.seed for s in old] == [spec.SEED_BASE + k for k in range(len(old))]
    sd = scenarios.generate_scenario(old[1])
    assert sd.desired is None and sd.scale == 1.0
    # 黄金值来自修改前 HEAD 版 scenarios.py 的同一场景
    assert hashlib.sha256(sd.x_adc.tobytes()).hexdigest()[:16] == "35e89cb378224428"


def test_qpsk_symbol_power_matches_declaration():
    syms = scenarios.qpsk_symbols(4096, 7)
    np.testing.assert_allclose(np.abs(syms) ** 2, 0.5, rtol=0, atol=1e-15)


def test_components_sum_to_input_with_common_scale():
    for split, i in (("main", 1), ("main", 3), ("stress", 0)):
        sd = _gen(split, i)
        np.testing.assert_allclose(sd.x, sd.desired + sd.blocker + sd.noise,
                                   rtol=0, atol=1e-15)
        assert 0 < sd.scale <= 1.0
        assert sd.levels["scale"] == sd.scale
        np.testing.assert_array_equal(sd.x_adc, scenarios.adc_quantize(sd.x))
    assert not np.any(_gen("main", 0).blocker)


def test_awgn_snr_is_desired_only_in_output_domain():
    for split, i in (("main", 0), ("main", 1), ("stress", 0)):
        sd = _gen(split, i)
        m0 = scenarios.measure_start_out(sd.n_pre)
        f = sd.scen.f_off_mhz
        p_d = np.mean(np.abs(scenarios.ideal_output(sd.desired, f)[m0:]) ** 2)
        p_n = np.mean(np.abs(scenarios.ideal_output(sd.noise, f)[m0:]) ** 2)
        assert abs(10 * math.log10(p_d / p_n) - sd.scen.snr_db) < 1e-9
        assert abs(sd.levels["snr_out_db"] - sd.scen.snr_db) < 1e-9
    # blocker 不进入噪声功率：同 f 的 clean 与 +6 dB stress 噪声相对 desired 相同
    clean, stress = _gen("main", 0), _gen("stress", 0)
    assert clean.scen.f_off_mhz == stress.scen.f_off_mhz
    assert abs(clean.levels["snr_out_db"] - stress.levels["snr_out_db"]) < 1e-9


def test_blocker_level_relative_to_desired():
    sd = _gen("main", 1)
    rel = 10 * math.log10(np.mean(np.abs(sd.blocker) ** 2) / np.mean(np.abs(sd.desired) ** 2))
    assert abs(rel - sd.scen.blocker_rel_db) < 1e-9


def test_front_end_scale_triggers_and_is_common():
    # 构造必触发峰值保护的场景：+20 dB blocker
    s = spec.build_witness_scenarios("stress")[0]
    big = spec.Scenario(name="t", klass="alias", f_off_mhz=s.f_off_mhz,
                        blocker_off_mhz=s.blocker_off_mhz, blocker_rel_db=20.0,
                        snr_db=s.snr_db, seed=s.seed, split="test")
    sd = scenarios.generate_scenario(big, n_sym=128)
    assert sd.scale < 1.0
    assert abs(np.max(np.abs(sd.x)) - 0.95) < 1e-12
    np.testing.assert_allclose(sd.x, sd.desired + sd.blocker + sd.noise, rtol=0, atol=1e-15)
    assert abs(sd.levels["snr_out_db"] - 30.0) < 1e-9


def test_manifest_fcw_fields():
    m = spec.export_witness_manifest()
    assert m["scenario_version"] == spec.SCENARIO_VERSION
    assert len(m["scenarios"]) == 77
    for f, info in m["fcw"].items():
        fcw = round(float(f) * 1e6 / spec.FS_IN * 2**32)
        assert info["fcw"] == fcw
        assert info["gcd"] == math.gcd(fcw, 2**32)
        assert info["period"] * info["gcd"] == 2**32
    assert m["decim_phase"] == 0 and m["nco_init_phase"] == 0
