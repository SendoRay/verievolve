"""链 B：发射 DUC。公式 y[n] = Re{ (h * (x↑L))[n] · e^{j2π f_c n} }：复基带内插 L 倍、理想低通、上变频取实部。"""
from ..task import Task, register


def ideal(g, p):
    u = g.upsample(g.input(), p["L"])
    y = g.lowpass(u, p["passband"], 1.0 - p["passband"])
    return g.upconvert(y, p["fcw"], 32)


for name, L, fp, fc, ib, ob, loss, rip in (
        ("duc_l8_wide", 8, 0.40, 0.1813, 14, 16, 2.0, 0.3),
        ("duc_l16_mid", 16, 0.35, 0.2271, 12, 14, 1.5, 0.5),
        ("duc_l4_narrow", 4, 0.25, 0.1307, 14, 16, 2.0, 0.3)):
    register(Task(
        name=name,
        params=dict(L=L, passband=fp, fcw=int(round(fc * 2**32)) | 1, f_c=fc),
        interface=dict(in_bits=ib, out_bits=ob, in_kind="complex", out_kind="real", in_period=L, out_period=1),
        ideal=ideal,
        stimulus="baseband_tones",
        tolerance=dict(snr_loss_db=loss, ripple_max_db=rip),
        measure=dict(n_out=4096, warm=1024, max_delay_out=2048),
        seed_key=L * 1000 + int(fp * 100),
        description="复基带 I/Q（每 L 个时钟一个样点）内插 L 倍、低通去镜像、上变频到 f_c，输出实数中频（每个时钟一个样点）。",
    ))
