#!/usr/bin/env python3
"""DDC 子链冒烟测试：小规模端到端一致性检查（run_s1 的前置）。"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent.parent
sys.path.insert(0, str(BENCH))

from chains.ddc import spec, scenarios, ref_chain, fixed_chain, candidates, metrics


def main() -> int:
    ok = True

    # 1. 场景生成
    scen_all = spec.build_scenarios()
    print(f"[1] 场景数 = {len(scen_all)}（预期 15 = 3 频移 × [clean + 2 obb + 2 alias]）")
    ok &= len(scen_all) == 15
    sd = scenarios.generate_scenario(scen_all[1])
    print(f"    场景 {sd.scen.name}: n={len(sd.x_adc)}, "
          f"|x_adc|max={np.max(np.abs(sd.x_adc)):.3f}")

    # 2. 参考链 + 原型
    h = ref_chain.prototype_taps()
    sym = bool(np.allclose(h, h[::-1]))
    print(f"[2] 原型: {len(h)} 抽头 对称={sym} Σh={float(np.sum(h)):.6f} "
          f"Σ|h|={float(np.sum(np.abs(h))):.4f}")
    ok &= sym
    ref = ref_chain.run_reference(sd, h)
    print(f"    参考输出 {len(ref['y_out'])} 样点, rms={np.sqrt(np.mean(np.abs(ref['y_out'])**2)):.4f}")

    # 3. 候选池合法性
    pool = candidates.build_all(h)
    n_leg = len(pool["fir"])
    print(f"[3] NCO {len(pool['nco'])} / FIR {n_leg}/{len(candidates.FIR_CANDIDATES)} "
          f"/ CMUL {len(pool['cmul'])}；非法: {len(pool['illegal'])}")
    for f in pool["fir"]:
        mc = f["mask_check"]
        print(f"    {f['name']:24s} pb={mc['pb_ripple_db']:+.3f} dB (≤{mc['limit_pb_db']}) "
              f"sb={mc['sb_worst_db']:.1f} dB (≤{mc['limit_sb_db']}) legal={mc['legal']}")
    for f in pool["fir"]:
        ok &= f["mask_check"]["legal"]
    for n in pool["nco"]:
        print(f"    {n['name']:24s} sqnr={n['sqnr_static_db']:.2f} dB wc={n['wc_db']:.1f} dB")

    # 4. 端到端：最优候选 vs 参考
    nco = pool["nco"][3]   # n4 lut1024 linear b16
    fir = pool["fir"][0]   # f1 c16
    cm = pool["cmul"][0]   # c1 exact
    cand = fixed_chain.run_candidate(nco, fir, cm, sd, fir["hq"])
    y_fix = (cand["y_re"] + 1j * cand["y_im"]) / float(1 << 15)
    y_ref = ref["y_out"]
    print(f"[4] 长度: fix={len(y_fix)} ref={len(y_ref)}")
    ok &= len(y_fix) == len(y_ref)
    e = y_fix - y_ref
    print(f"    最优候选 err_rel = {20*math.log10(np.sqrt(np.mean(np.abs(e**2)))/np.sqrt(np.mean(np.abs(y_ref)**2))):.2f} dB"
          if np.mean(np.abs(e**2)) > 0 else "    最优候选 err = 0")
    print(f"    饱和: mix={cand['n_sat_mix']} fir={cand['n_sat_fir']}")

    # 5. 符号对齐校验：互相关找延迟
    #    结构推导（输出域）：MF 群延迟 20 + FIR 群延迟 16(in)=8 − 裁剪 32(in)=16
    #    → 20 + 8 − 16 = 12
    from chains.ddc.scenarios import rrc_taps
    sps_out = int(spec.FS_OUT / spec.SYM_RATE)
    mf = np.convolve(y_ref, rrc_taps(sps_out, spec.RRC_BETA), mode="full")
    sym_ref = sd.symbols * math.sqrt(sps_out)  # 匹配滤波增益归一
    n_sym = len(sd.symbols)
    best_d, best_v = None, -1.0
    for d in range(0, 60):
        idx = d + np.arange(min(n_sym, (len(mf) - d) // sps_out)) * sps_out
        v = np.abs(np.sum(np.conj(sym_ref[:len(idx)]) * mf[idx]))
        if v > best_v:
            best_v, best_d = v, d
    print(f"[5] 符号域互相关最优延迟 = {best_d}（结构推导 12）")
    ok &= best_d == 12

    evm = metrics.symbol_evm(y_ref, sd.symbols, sps_out, 48, 12)
    print(f"    参考链自身 evm_total = {evm['evm_total_db']:.2f} dB"
          f"（≈−26.7：AWGN 经 MF 能量归一后的场景底，共同分量）")

    # 6. 局部指标抽查
    mix16 = (cand["mix_re"] + 1j * cand["mix_im"]) / float(1 << 15)
    l_sqnr = metrics.worst_field_sqnr_db(ref["mix"], mix16)
    print(f"[6] 混频级局部 SQNR = {l_sqnr:.2f} dB")

    # 7. 谱加权预测自检（最优候选；全部换算到 ADC 刻度，FIR 有效段口径）
    mix_fix = (cand["mix_re"] + 1j * cand["mix_im"]) / float(1 << 15)
    e_mix = (mix_fix - ref["mix"])[spec.N_TAPS - 1:]          # 混频级误差（有效段）
    hq_f = fir["hq"].astype(np.float64)
    y_ff = (cand["fir_re"][spec.N_TAPS - 1:] + 1j * cand["fir_im"][spec.N_TAPS - 1:]) / float(1 << 15)
    y_ref_of_x = ref_chain.fir_float(mix_fix, hq_f / float(np.sum(hq_f)))  # 同输入理想 FIR（自动裁剪）
    fir_err = y_ff - y_ref_of_x                                # FIR 自身误差
    p_ref = float(np.mean(np.abs(y_ref) ** 2))
    pred = metrics.spectral_prediction(e_mix, fir_err, h, p_ref)
    meas = metrics.aligned_impl_error(y_ref, y_fix, 240)
    print(f"[7] 谱加权预测 err = {pred['pred_err_db']:.2f} dB, "
          f"实测 = {meas['err_raw_db']:.2f} dB（差值 = 互相关/非线性项）")

    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
