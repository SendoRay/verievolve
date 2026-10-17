"""agent 工具命令行（在工作区目录内运行）：

  python -m dspc.tool verdict <prog.py> [--parent <p.py>] [--claim equiv|precision|structure] [--no-sweep]
  python -m dspc.tool freeze  <prog.py> <contract_dir>
  python -m dspc.tool conform <contract_dir> <rtl.v> [--sets search0,random]
  python -m dspc.tool ppa     <contract_dir> <rtl.v> [--vcd]
  python -m dspc.tool archive add <prog.py> [--parent dNNN] [--action REWRITE|TUNE] [--claim ...] [--note ...]
  python -m dspc.tool archive impl <dNNN> <rtl.v> [--note ...]     （G3 一致性 + G4 真实综合）
  python -m dspc.tool archive show
  python -m dspc.tool archive final <dNNN> [<实现号>]     （G5 终验，只返回通过与否）
  python -m dspc.tool api     （打印原语参考）

任务名与预算取自工作区的 .ws.json（{"task": ..., "budget": {"verdict": N, "lower": N, "ppa": N}}）。
每次调用记入 tool_log.jsonl；超出预算的调用直接拒绝（所有实验变体同一口径）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BUDGET_CLASS = {"verdict": "verdict", "conform": "lower", "ppa": "ppa", "freeze": None, "api": None, "probe": None,
                "archive_add": "verdict", "archive_impl": "lower", "archive_show": None, "archive_final": "final"}


def _ws() -> dict:
    p = Path.cwd() / ".ws.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _log(cmd: str, rec: dict) -> None:
    with open(Path.cwd() / "tool_log.jsonl", "a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "cmd": cmd, **rec}, ensure_ascii=False, default=str)
                + "\n")


def _budget_ok(cmd: str) -> bool:
    cls = BUDGET_CLASS.get(cmd)
    lim = _ws().get("budget", {}).get(cls) if cls else None
    if lim is None:
        return True
    log = Path.cwd() / "tool_log.jsonl"
    used = sum(1 for l in log.read_text().splitlines() if l.strip()
               and BUDGET_CLASS.get(json.loads(l).get("cmd")) == cls) if log.exists() else 0
    if used >= lim:
        print(json.dumps({"error": f"预算已用完：{cls} 类调用上限 {lim} 次，已用 {used} 次"}, ensure_ascii=False))
        return False
    return True


def _clock_ns(task_name: str) -> float:
    from dspgen.contract import CONTRACTS
    c = CONTRACTS.get(task_name)
    return float(c.clock_ns) if c is not None else 2.0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dspc.tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verdict")
    v.add_argument("prog", type=Path)
    v.add_argument("--parent", type=Path)
    v.add_argument("--claim")
    v.add_argument("--no-sweep", action="store_true")
    v.add_argument("--task")
    f = sub.add_parser("freeze")
    f.add_argument("prog", type=Path)
    f.add_argument("out", type=Path)
    f.add_argument("--task")
    c = sub.add_parser("conform")
    c.add_argument("contract", type=Path)
    c.add_argument("rtl", type=Path)
    c.add_argument("--sets")
    p = sub.add_parser("ppa")
    p.add_argument("contract", type=Path)
    p.add_argument("rtl", type=Path)
    p.add_argument("--vcd", action="store_true")
    p.add_argument("--clock-ns", type=float)
    sub.add_parser("api")
    pb = sub.add_parser("probe")
    pb.add_argument("contract", type=Path)
    pb.add_argument("node", type=int)
    pb.add_argument("--set", default="random")
    pb.add_argument("--n", type=int, default=64)
    ar = sub.add_parser("archive")
    ar.add_argument("sub", choices=["add", "impl", "show", "final"])
    ar.add_argument("args", nargs="*")
    ar.add_argument("--parent")
    ar.add_argument("--action", default="")
    ar.add_argument("--claim")
    ar.add_argument("--note", default="")
    ar.add_argument("--no-sweep", action="store_true")
    a = ap.parse_args(argv)
    key = f"archive_{a.sub}" if a.cmd == "archive" else a.cmd
    if not _budget_ok(key):
        return
    task = getattr(a, "task", None) or _ws().get("task")

    if a.cmd == "archive":
        from . import archive
        ws = Path.cwd()
        if a.sub == "add":
            r = archive.add_design(ws, task, Path(a.args[0]), a.parent, a.action, a.note, a.claim,
                                   sweep=not a.no_sweep)
            _log("archive_add", {"id": r["id"], "status": r["status"], "cls": r.get("cls"), "v": r.get("v")})
            if _ws().get("variant") == "score":           # 反馈消融：只给状态与一个标量分数
                sc = min(((k["slack"] - k["margin"]) / k["scale"] for k in r["report"].get("constraints", [])),
                         default=None)
                r = {"id": r["id"], "status": r["status"], "score": None if sc is None else round(sc, 4)}
        elif a.sub == "impl":
            r = archive.add_impl(ws, a.args[0], Path(a.args[1]), a.note)
            _log("archive_impl", {"id": r.get("id"), "conform": r.get("conform"),
                                  "area_um2": (r.get("ppa") or {}).get("area_um2")})
            if r.get("ppa"):
                _log("ppa", {"impl": r.get("id"), "area_um2": r["ppa"].get("area_um2")})
        elif a.sub == "final":
            r = archive.final(ws, a.args[0], a.args[1] if len(a.args) > 1 else None)
            _log("archive_final", r)
        else:
            r = archive.show(ws)
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return
    if a.cmd == "probe":
        import numpy as np
        from dspgen.task import get
        from .interp import run
        from .judge import load
        cj = json.loads((a.contract / "contract.json").read_text())
        prog = load((a.contract / "program.py").read_text(), get(cj["task"]))
        vd = a.contract / "vectors" / a.set
        bits = cj["interface"]["in_bits"]
        def codes(f):
            v = np.array([int(l, 16) for l in f.read_text().split()], dtype=np.int64)
            return np.where(v >= 1 << (bits - 1), v - (1 << bits), v)[None, :]
        xs = [codes(vd / "in.hex")] + ([codes(vd / "inq.hex")] if (vd / "inq.hex").exists() else [])
        r = run(prog, xs, "fixed", keep=[a.node])
        v = r.values[a.node]
        nd = prog.nodes[a.node]
        seq = [int(x) for x in np.atleast_2d(v)[0][:a.n]] if isinstance(v, np.ndarray) else [int(v)]
        print(json.dumps({"node": a.node, "op": nd.op, "fmt": str(nd.fmt), "rate": str(nd.rate), "scope": nd.scope,
                          "set": a.set, "codes": seq}, ensure_ascii=False))
        return
    if a.cmd == "api":
        from .docs import PRIMITIVES_MD
        print(PRIMITIVES_MD)
        return
    if a.cmd == "verdict":
        from .judge import verdict
        parent = a.parent.read_text() if a.parent else None
        pr = None
        if a.parent and (a.parent.with_suffix(".verdict.json")).exists():
            pr = json.loads(a.parent.with_suffix(".verdict.json").read_text())
        r = verdict(a.prog.read_text(), task, parent_code=parent, claim=a.claim, sweep=not a.no_sweep,
                    parent_report=pr)
        a.prog.with_suffix(".verdict.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        _log("verdict", {"prog": str(a.prog), "verdict": r.get("verdict"), "v": r.get("v"),
                         "class": (r.get("class") or {}).get("actual")})
        r.get("diagnostics", {}).pop("qstats", None)
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return
    if a.cmd == "freeze":
        from .contract import freeze
        rp = a.prog.with_suffix(".verdict.json")
        rep = json.loads(rp.read_text()) if rp.exists() else None
        if rep is None or rep.get("verdict") != "FEASIBLE":
            print(json.dumps({"error": "只有候选级判定为 FEASIBLE 的程序才能冻结为契约；先运行 verdict"},
                             ensure_ascii=False))
            return
        c = freeze(a.prog.read_text(), task, a.out, report=rep)
        _log("freeze", {"prog": str(a.prog), "out": str(a.out), "a_hash": c["a_hash"]})
        from .docs import PRIMITIVES_MD
        (a.out / "PRIMITIVES.md").write_text(PRIMITIVES_MD)
        print(json.dumps({"contract": str(a.out), "vectors": c["vectors"], "a_hash": c["a_hash"]}, ensure_ascii=False))
        return
    if a.cmd == "conform":
        from .conform import check
        r = check(a.contract, a.rtl.read_text(), sets=a.sets.split(",") if a.sets else None)
        _log("conform", {"contract": str(a.contract), "rtl": str(a.rtl), "passed": r["passed"],
                         "violations": [x.get("code") for x in r["violations"]]})
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    if a.cmd == "ppa":
        import numpy as np
        from dspgen.ppa_sta import evaluate_verilog, evaluate_verilog_vcd
        cj = json.loads((a.contract / "contract.json").read_text())
        clk = a.clock_ns or _clock_ns(cj["task"])
        rtl = a.rtl.read_text()
        if a.vcd:
            sc = next(k for k in cj["vectors"] if k.startswith("search"))
            exp = np.array([list(map(int, l.split())) for l in
                            (a.contract / "vectors" / sc / "expected.txt").read_text().splitlines() if l.strip()])
            from dspgen.task import get
            r = evaluate_verilog_vcd(rtl, cj["task"], scenario=get(cj["task"]).search_scenarios[0], period_ns=clk,
                                     expect=exp)
        else:
            r = evaluate_verilog(rtl, top="top", period_ns=clk)
        keep = {k: r.get(k) for k in ("status", "area_um2", "cells", "wns_ns", "fmax_mhz", "power_at_clock",
                                      "power_vcd", "gate_vs_model", "critical_path", "stderr") if k in r}
        _log("ppa", {"rtl": str(a.rtl), "vcd": a.vcd, **{k: keep.get(k) for k in ("area_um2", "wns_ns")}})
        print(json.dumps(keep, ensure_ascii=False, indent=1, default=str))
        return


if __name__ == "__main__":
    sys.exit(main())
