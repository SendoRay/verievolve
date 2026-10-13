"""给编码 agent 用的工具（KDA 式任务契约的评价命令）。只读调用 dspgen，不改仓库。

用法（在 examples/comm_dsp_bench 下，以 python -m dspgen.agent_tool 调用）：
  python agent_tool.py eval    TASK PROG.py          # 搜索场景的 SNR 裕量、纹波、饱和、面积及逐段面积
  python agent_tool.py probe   TASK PROG.py          # 单音扫描：通带幅频、I/Q 符号、混叠抑制
  python agent_tool.py freqz   COEFS.json RATE       # 系数列表的幅频响应摘要（RATE 为该级相对输入的抽取倍率，仅用于标注）
  python agent_tool.py direct  TASK                  # 打印自动生成的直写程序（约定示例，本身达标）
  python agent_tool.py api                           # 打印原语说明
  python agent_tool.py spec    TASK                  # 打印规格、接口、门槛与干扰信息
  python agent_tool.py ppa     TASK PROG.py [时钟ns]  # 真实综合 + OpenSTA：面积、最小周期/最高频率、功耗、关键路径（约数秒到数分钟）
"""
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

import numpy as np  # noqa: E402


def main():
    cmd = sys.argv[1]
    if cmd == "api":
        from dspgen.prompt import api_doc
        from dspgraph.llm_prog import GENERAL
        print(api_doc()); print(GENERAL); return
    if cmd == "freqz":
        import scipy.signal as ss
        h = np.array(json.loads(Path(sys.argv[2]).read_text()), dtype=float)
        w, H = ss.freqz(h, worN=8192)
        f = w / (2 * np.pi)
        mag = 20 * np.log10(np.abs(H) / max(1e-30, abs(np.sum(h))) + 1e-30)
        for lo, hi in [(0, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5)]:
            sel = (f >= lo) & (f < hi)
            print(f"f∈[{lo},{hi}) 相对直流：最大 {mag[sel].max():.2f} dB，最小 {mag[sel].min():.2f} dB")
        print(f"直流增益 sum(h) = {np.sum(h):.6f}，抽头数 {len(h)}")
        return
    from dspgen.task import evaluate_program, get
    t = get(sys.argv[2])
    if cmd == "spec":
        sc = [t.scene(i) for i in t.search_scenarios]
        print(json.dumps({"name": t.name, "description": t.description, "params": t.params,
                          "interface": t.interface, "tolerance": t.tolerance,
                          "snr_min_db": [round(s["snr_min_db"], 2) for s in sc],
                          "ideal_ceiling_db": [round(s["ceiling_db"], 2) for s in sc],
                          "stimulus": t.stimulus,
                          "stimulus_note": "期望信号：通带内多音；干扰：覆盖全部会混叠进通带的频带的强阻塞（总功率相对期望信号为 params.blocker_rel_db dB）"},
                         ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "direct":
        print(t.direct_start()); return
    code = Path(sys.argv[3]).read_text()
    if cmd == "eval":
        r = evaluate_program(code, t.name)
        if r.get("valid"):
            q = r["quality"]
            print(json.dumps({"passed": q["passed"], "snr_margin_db": round(q["snr_margin_db"], 3),
                              "ripple_db": round(q["ripple_db"], 3), "ripple_max_db": q["ripple_max_db"],
                              "saturation": q["saturation"],
                              "per_scenario": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()
                                                if k in ("scenario", "snr_db", "snr_min_db", "ripple_db", "passed")}
                                               for s in q["scenarios"]],
                              "area_um2_est": round(r["area"], 1), "area_per_scope": r["area_per_scope"]},
                             ensure_ascii=False, indent=1, default=str))
        else:
            print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "ppa":
        from dspgen.ppa_sta import evaluate_program as ppa_eval
        clk = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
        r = ppa_eval(t.name, Path(sys.argv[3]), period_ns=clk, fast=True)
        keep = ("status", "area_um2", "cells", "clock_ns", "wns_ns", "min_period_ns", "fmax_mhz", "power_at_clock",
                "critical_path", "error", "stderr")
        print(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "probe":
        from dspgen.probe_tones import probe
        print(json.dumps(probe(code, t.name), ensure_ascii=False, indent=1, default=str)[:6000])
        return


if __name__ == "__main__":
    main()
