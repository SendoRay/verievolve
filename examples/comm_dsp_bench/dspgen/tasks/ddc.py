"""链 A：接收 DDC。公式 y[m] = (h * (x · e^{-j2π f_if n}))[m·R]。

12 个规格的参数取自 dspgraph.rx_spec（保持与已有实验完全一致，用于回归）。"""
from dspgraph.rx_spec import DEV_SPECS, HELDOUT_SPECS

from ..task import Task, register


def ideal(g, p):
    fs_out = 1.0 / p["r_total"]
    x = g.mix(g.input(), p["fcw"], 32)
    y = g.lowpass(x, p["passband"], fs_out - p["passband"],
                  cutoff=0.5 * (p["passband"] + fs_out - p["passband"]))
    return g.decimate(y, p["r_total"])


for s in DEV_SPECS + HELDOUT_SPECS:
    register(Task(
        name=s.name,
        params=dict(r_total=s.r_total, passband=s.passband, fs_out=s.fs_out, fcw=s.fcw, f_if=s.f_if,
                    blocker_rel_db=s.blocker_rel_db, ripple_max_db=s.ripple_max_db, impl_loss_db=s.impl_loss_db),
        interface=dict(in_bits=s.input_bits, out_bits=s.output_bits, rate=s.r_total),
        ideal=ideal,
        stimulus="tones_with_dense_blockers",
        tolerance=dict(snr_loss_db=s.impl_loss_db, ripple_max_db=s.ripple_max_db),
        seed_key=int(s.sha256()[:8], 16),
        description="实数 ADC 输入中频 f_if 处 ±passband 的信号搬到零频、低通并抽取 R 倍，输出复基带 I/Q。",
    ))
