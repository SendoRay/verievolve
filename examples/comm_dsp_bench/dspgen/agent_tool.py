"""给编码 agent 用的工具（KDA 式任务契约的评价命令）。只读调用 dspgen，不改仓库。

用法（在 examples/comm_dsp_bench 下，以 python -m dspgen.agent_tool 调用）：
  python agent_tool.py eval    TASK PROG.py          # 搜索场景的 SNR 裕量、纹波、饱和、面积及逐段面积
  python agent_tool.py probe   TASK PROG.py          # 单音扫描：通带幅频、I/Q 符号、混叠抑制
  python agent_tool.py freqz   COEFS.json RATE       # 系数列表的幅频响应摘要（RATE 为该级相对输入的抽取倍率，仅用于标注）
  python agent_tool.py direct  TASK                  # 打印自动生成的直写程序（约定示例，本身达标）
  python agent_tool.py api                           # 打印原语说明
  python agent_tool.py spec    TASK                  # 打印规格、接口、门槛与干扰信息
  python agent_tool.py ppa     TASK PROG.py [时钟ns] [--vcd]  # 真实综合 + OpenSTA：面积、最高频率、关键路径、功耗
                                                       # （--vcd：功耗用门级仿真翻转率，约 1–3 分钟；否则用全局翻转率 0.1）
  python agent_tool.py rtl     TASK PROG.py          # 生成 Verilog 并与逐位整数模型对拍（iverilog）
  python agent_tool.py check   TASK PROG.py          # 可证明性质：区间范围（饱和/回绕能否排除）；链路 A 另做全频带扫频
  python agent_tool.py observe TASK PROG.py OUT.json # 导出 g.probe 观测点的逐样点值（搜索场景 0，浮点）
  python agent_tool.py archive add TASK PROG.py --action REWRITE|TUNE --claim equiv|math|approx [--parent cNNN] [--note 说明]
                                                     # 评价并登记候选（在工作区目录下执行；档案为 archive.jsonl）
  python agent_tool.py archive show                  # 可行前沿、近可行前沿、调度提示
  python agent_tool.py archive verify TASK cNNN      # 终验：留出场景 + RTL 对拍 + 目标时钟下的 PPA
  python agent_tool.py veval   TASK DESIGN.v         # 直写 Verilog 的质量评价（顶层 top，端口与任务接口一致）
  python agent_tool.py vppa    TASK DESIGN.v [时钟ns] [--vcd]  # 直写 Verilog 的真实综合 + OpenSTA
"""
import os
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

import numpy as np  # noqa: E402


def _archive():
    import argparse
    from dspgen import archive
    ws = Path.cwd()
    sub = sys.argv[2]
    if sub == "show":
        r = archive.show(ws)
        if _variant() == "score":          # 只给分数：去掉约束层面的数值
            for k in ("feasible_front", "near_feasible_front"):
                for x in r.get(k, []):
                    x.pop("margin_db", None)
    elif sub == "verify":
        r = archive.verify(ws, sys.argv[3], sys.argv[4])
    else:
        ap = argparse.ArgumentParser()
        ap.add_argument("task"); ap.add_argument("prog", type=Path)
        ap.add_argument("--action", required=True, choices=["REWRITE", "TUNE", "rewrite", "tune"])
        ap.add_argument("--parent"); ap.add_argument("--note", default="")
        ap.add_argument("--claim", default="approx", choices=["equiv", "math", "approx"])
        a = ap.parse_args(sys.argv[3:])
        r = archive.add(ws, a.task, a.prog, a.parent, a.action, a.note, a.claim)
        if _variant() == "score":
            r = {k: r.get(k) for k in ("id", "parent", "status", "area_est")} | {
                "score": round(min(((x["slack"] - x["margin"]) / max(abs(x["threshold"]), 1e-9) if x.get("source") == "sweep"
                                    and x.get("threshold") and False else (x["slack"] - x["margin"]))
                                   for x in (r.get("constraints") or {}).values()), 4) if r.get("constraints") else None}
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))


def _variant():
    p = Path.cwd() / ".contract.json"
    return json.loads(p.read_text()).get("variant", "full") if p.exists() else "full"


def _log(cmd, target, summary):
    """每次调用记入工作区的 tool_log.jsonl（用于事后核对各变体的评价次数与预算）。"""
    if not (Path.cwd() / ".contract.json").exists():
        return
    import hashlib, time
    h = hashlib.sha256(Path(target).read_bytes()).hexdigest()[:12] if target and Path(target).exists() else None
    with (Path.cwd() / "tool_log.jsonl").open("a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "cmd": cmd, "file": str(target), "sha": h,
                            **summary}, ensure_ascii=False, default=str) + "\n")


BUDGET_CLASS = {"eval": "eval", "veval": "eval", "vsweep": "eval", "archive_add": "eval",
                "ppa": "ppa", "ppa_vcd": "ppa", "vppa": "ppa", "vppa_vcd": "ppa",
                "final": "final", "vfinal": "final", "archive_verify": "final"}


def _budget_check(cmd):
    """按 .contract.json 的预算强制执行（所有实验变体同一口径）。超额时拒绝并说明。"""
    p = Path.cwd() / ".contract.json"
    cls = BUDGET_CLASS.get(cmd)
    if not p.exists() or cls is None:
        return True
    bud = json.loads(p.read_text()).get("budget", {})
    lim = bud.get(cls)
    if lim is None:
        return True
    log = Path.cwd() / "tool_log.jsonl"
    used = sum(1 for l in log.read_text().splitlines() if l.strip()
               and BUDGET_CLASS.get(json.loads(l).get("cmd")) == cls) if log.exists() else 0
    if used >= lim:
        print(json.dumps({"error": f"预算已用完：{cls} 类调用上限 {lim} 次，已用 {used} 次"}, ensure_ascii=False))
        return False
    return True


def _score_only(r):
    """方法二消融：只给判定与一个标量分数（最小归一化松弛），外加代理面积。"""
    if r.get("verdict") == "BROKEN":
        return {"verdict": "BROKEN", "error": r.get("error")}
    cons = r.get("constraints", [])
    sc = min(((k["slack"] - k["margin"]) / k["scale"] for k in cons), default=0.0)
    return {"verdict": r["verdict"], "score": round(sc, 4), **({"objectives": r["objectives"]} if "objectives" in r else {})}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__); return
    cmd = sys.argv[1]
    v = _variant()
    if cmd == "archive":
        if v in ("flat", "verilog"):
            print(json.dumps({"error": "本工作区不提供候选档案；请直接用 eval 与 final"}, ensure_ascii=False)); return
        sub = sys.argv[2] if len(sys.argv) > 2 else ""
        key = {"add": "archive_add", "verify": "archive_verify"}.get(sub)
        if key and not _budget_check(key):
            return
        if sub == "verify":
            _log("archive_verify", None, {"id": sys.argv[4] if len(sys.argv) > 4 else None})
        return _archive()
    key = cmd + ("_vcd" if "--vcd" in sys.argv and cmd in ("ppa", "vppa") else "")
    if not _budget_check(key):
        return
    if cmd == "api":
        from dspgen.contract import primitives_doc
        print(primitives_doc()); return
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
    if cmd in ("veval", "vsweep"):
        from dspgen import verdict
        r = verdict.vsearch(code, t.name, sweep=(cmd == "vsweep"))
        _log(cmd, sys.argv[3], {"verdict": r["verdict"], "v": r.get("v")})
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "vppa":
        os.environ.setdefault("VERIEVOLVE_STA", "/Users/chengzhy/verievolve_thirdparty/OpenSTA/build/sta")
        from dspgen import ppa_sta
        args = [a for a in sys.argv[4:] if not a.startswith("--")]
        clk = float(args[0]) if args else 2.0
        r = (ppa_sta.evaluate_verilog_vcd(code, t.name, period_ns=clk, fast=True) if "--vcd" in sys.argv
             else ppa_sta.evaluate_verilog(code, period_ns=clk, fast=True))
        keep = ("status", "area_um2", "cells", "wns_ns", "fmax_mhz", "power_at_clock", "power_vcd", "stderr")
        _log("vppa" + ("_vcd" if "--vcd" in sys.argv else ""), sys.argv[3], {"area_um2": r.get("area_um2"), "wns_ns": r.get("wns_ns")})
        print(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "eval":
        from dspgen import verdict
        r = verdict.search(code, t.name)
        _log("eval", sys.argv[3], {"verdict": r["verdict"], "v": r.get("v"),
                                    "area_est": (r.get("objectives") or {}).get("area_est")})
        print(json.dumps(_score_only(r) if v == "score" else r, ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "final":
        from dspgen import verdict
        r = verdict.final(code, t.name, Path(sys.argv[3]))
        verdict.sidecar(Path.cwd(), "final", {"file": sys.argv[3], **r})
        _log("final", sys.argv[3], {"verdict": r["verdict"], **(r.get("objectives") or {})})
        print(json.dumps(verdict.public(r), ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "vfinal":
        from dspgen import verdict
        r = verdict.vfinal(code, t.name)
        verdict.sidecar(Path.cwd(), "vfinal", {"file": sys.argv[3], **r})
        _log("vfinal", sys.argv[3], {"verdict": r["verdict"], **(r.get("objectives") or {})})
        print(json.dumps(verdict.public(r), ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "ppa":
        os.environ.setdefault("VERIEVOLVE_STA", "/Users/chengzhy/verievolve_thirdparty/OpenSTA/build/sta")
        from dspgen import ppa_sta
        args = [a for a in sys.argv[4:] if not a.startswith("--")]
        clk = float(args[0]) if args else 2.0
        if "--vcd" in sys.argv:
            r = ppa_sta.evaluate_program_vcd(t.name, Path(sys.argv[3]), period_ns=clk, fast=True)
        else:
            r = ppa_sta.evaluate_program(t.name, Path(sys.argv[3]), period_ns=clk, fast=True)
        keep = ("status", "area_um2", "cells", "clock_ns", "wns_ns", "min_period_ns", "fmax_mhz", "power_at_clock",
                "power_vcd", "critical_path", "error", "stderr")
        _log("ppa" + ("_vcd" if "--vcd" in sys.argv else ""), sys.argv[3], {"area_um2": r.get("area_um2"), "wns_ns": r.get("wns_ns")})
        print(json.dumps({k: r[k] for k in keep if k in r}, ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "check":
        from dspgen import symbolic
        r = symbolic.ranges(code, t.name)
        out = {"ranges_summary": r["summary"], "ranges_note": r["note"],
               "flags": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()
                          if k in ("scope", "op", "ovf", "status", "bound", "format_max", "observed_max", "headroom_bits")}
                         for f in r["flags"] if f["status"] != "control_modular"][:40]}
        if "fcw" in t.params and "r_total" in t.params:
            from dspgen.contract import CONTRACTS
            env = CONTRACTS[t.name].envelope if t.name in CONTRACTS else {}
            sw = symbolic.sweep(code, t.name, amp_pass=env.get("desired_peak", 0.05), amp_stop=env.get("peak", 0.9))
            out["sweep"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in sw.items()}
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return
    if cmd == "observe":
        from dspgen import symbolic
        r = symbolic.observe(code, t.name)
        Path(sys.argv[4]).write_text(json.dumps(r, ensure_ascii=False))
        print(json.dumps({k: (len(v["re"]) if isinstance(v, dict) else len(v)) for k, v in r.items()}, ensure_ascii=False))
        return
    if cmd == "rtl":
        from dspgen.rtl import crosscheck
        n = t.n_in() if hasattr(t, "frame_outputs") else 4000
        print(json.dumps(crosscheck(code, t.name, scenario=t.search_scenarios[0], n_in=n), ensure_ascii=False,
                         indent=1, default=str))
        return
    if cmd == "probe":
        from dspgen.probe_tones import probe
        print(json.dumps(probe(code, t.name), ensure_ascii=False, indent=1, default=str)[:6000])
        return


if __name__ == "__main__":
    main()
