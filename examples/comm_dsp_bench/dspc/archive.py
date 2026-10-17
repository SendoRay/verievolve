"""候选档案：设计—实现双环搜索的状态（FRAMEWORK_v5 §5）。

设计节点（外环）：一个完整的原语程序 + 候选级判定报告。状态 BROKEN / OPEN / FEASIBLE；终验后为 VERIFIED。
实现子节点（内环）：同一冻结契约下的一份 RTL，记录 G3 一致性结果与 G4 真实 PPA。
设计节点的 PPA 取其通过一致性、且目标时钟下时序收敛的实现子节点中面积最小者；成本按全部实现次数计。

档案只追加、不覆盖：工作区下 archive.jsonl（设计节点）与 impls.jsonl（实现子节点）。
说明：AND 分解（一次分解产生多个必须共同成立的子区域）由设计 Agent 在完整程序中物化后统一评价；
本档案记录的是 OR 关系（同一父节点下的不同完整候选、同一契约下的不同实现）。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

ARCH, IMPLS = "archive.jsonl", "impls.jsonl"
STALL = 4


def _load(ws: Path, name: str) -> list:
    p = Path(ws) / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def _append(ws: Path, name: str, rec: dict) -> None:
    with open(Path(ws) / name, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _rewrite(ws: Path, name: str, rows: list) -> None:
    (Path(ws) / name).write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows))


def add_design(ws: Path, task: str, prog: Path, parent: str | None, action: str, note: str,
               claim: str | None = None, sweep: bool = True) -> dict:
    """登记一个设计节点：执行候选级判定（G0–G2），复制程序到档案。"""
    from .judge import verdict
    ws = Path(ws)
    rows = _load(ws, ARCH)
    by = {r["id"]: r for r in rows}
    par = by.get(parent) if parent else None
    cid = f"d{len(rows):03d}"
    (ws / "archive").mkdir(exist_ok=True)
    dst = ws / "archive" / f"{cid}.py"
    shutil.copy(prog, dst)
    code = dst.read_text()
    pcode = Path(par["file"]).read_text() if par else None
    prep = json.loads((ws / "archive" / f"{parent}.verdict.json").read_text()) \
        if par and (ws / "archive" / f"{parent}.verdict.json").exists() else None
    variant = json.loads((ws / ".ws.json").read_text()).get("variant", "full") if (ws / ".ws.json").exists() \
        else "full"
    if variant == "exact" and pcode is None and (ws / "start.py").exists():
        pcode = (ws / "start.py").read_text()          # 零误差变体：根节点也必须与直写起点逐位等价
    r = verdict(code, task, parent_code=pcode, claim=claim, sweep=sweep, parent_report=prep)
    if variant == "exact" and r["verdict"] != "BROKEN" and (r.get("class") or {}).get("actual") not in ("T1", None):
        r = {"verdict": "BROKEN", "error": {"code": "exact_variant", "message":
             f"零误差对照变体只接受逐位等价（T1）的修改；该候选实际为 {r['class']['actual']}"}, "class": r["class"]}
    (ws / "archive" / f"{cid}.verdict.json").write_text(json.dumps(r, ensure_ascii=False, default=str))
    rec = {"id": cid, "parent": parent, "action": (action or "").upper(), "claim": claim, "note": note,
           "file": str(dst), "time": time.strftime("%H:%M:%S"), "status": r["verdict"]}
    if r["verdict"] == "BROKEN":
        rec["error"] = r.get("error")
    else:
        rec.update(v=r["v"], cls=(r.get("class") or {}).get("actual"),
                   a_hash=r["g0"]["summary"]["a_hash"], b_hash=r["g0"]["summary"]["b_hash"],
                   slack={k["name"]: k["slack"] for k in r["constraints"]},
                   suggestion=r.get("suggestion"))
        if par and par.get("slack"):
            rec["delta_slack"] = {k: round(v - par["slack"][k], 4) for k, v in rec["slack"].items()
                                  if k in par["slack"]}
    _append(ws, ARCH, rec)
    out = dict(rec)
    out["report"] = {k: r[k] for k in ("constraints", "class", "suggestion", "diagnostics", "g0") if k in r}
    out["report"].get("diagnostics", {}).pop("qstats", None)
    return out


def add_impl(ws: Path, cid: str, rtl: Path, note: str = "", ppa: bool = True, vcd: bool = False) -> dict:
    """登记一个实现子节点：G3 一致性；通过后做 G4 真实综合。契约在 contracts/<cid>/（首次自动冻结）。"""
    from .conform import check
    from .contract import freeze
    ws = Path(ws)
    rows = _load(ws, ARCH)
    rec = next((r for r in rows if r["id"] == cid), None)
    if rec is None or rec["status"] != "FEASIBLE":
        return {"error": f"{cid} 不是 FEASIBLE 的设计节点，不能实现（先通过候选级判定）"}
    cdir = ws / "contracts" / cid
    if not (cdir / "contract.json").exists():
        rep = json.loads((ws / "archive" / f"{cid}.verdict.json").read_text())
        freeze(Path(rec["file"]).read_text(), json.loads((ws / ".ws.json").read_text())["task"], cdir, report=rep)
        from .docs import PRIMITIVES_MD
        (cdir / "PRIMITIVES.md").write_text(PRIMITIVES_MD)
    impls = _load(ws, IMPLS)
    iid = f"{cid}.r{sum(1 for i in impls if i['design'] == cid):02d}"
    (ws / "rtl").mkdir(exist_ok=True)
    dst = ws / "rtl" / f"{iid}.v"
    shutil.copy(rtl, dst)
    g3 = check(cdir, dst.read_text())
    irec = {"id": iid, "design": cid, "file": str(dst), "note": note, "time": time.strftime("%H:%M:%S"),
            "conform": g3["passed"], "violations": [v.get("code") for v in g3["violations"]]}
    if g3["passed"] and ppa:
        from dspgen.ppa_sta import evaluate_verilog
        from .tool import _clock_ns
        cj = json.loads((cdir / "contract.json").read_text())
        p = evaluate_verilog(dst.read_text(), top="top", period_ns=_clock_ns(cj["task"]))
        irec["ppa"] = {k: p.get(k) for k in ("status", "area_um2", "cells", "wns_ns", "fmax_mhz")}
        irec["ppa"]["power_mw_est"] = (p.get("power_at_clock") or {}).get("total_mw")
    _append(ws, IMPLS, irec)
    return {**irec, "g3": g3}


def best_impl(ws: Path, cid: str) -> dict | None:
    ok = [i for i in _load(ws, IMPLS) if i["design"] == cid and i.get("conform") and i.get("ppa")
          and i["ppa"].get("status") == "ok" and (i["ppa"].get("wns_ns") or -1) >= 0]
    return min(ok, key=lambda i: i["ppa"]["area_um2"]) if ok else None


def _front(points, key):
    out, best = [], float("inf")
    for p in sorted(points, key=key):
        if key(p)[1] < best:
            out.append(p)
            best = key(p)[1]
    return out


def show(ws: Path) -> dict:
    """档案概况、双前沿与调度提示。"""
    ws = Path(ws)
    rows, impls = _load(ws, ARCH), _load(ws, IMPLS)
    for r in rows:
        b = best_impl(ws, r["id"])
        r["area_um2"] = b["ppa"]["area_um2"] if b else None
        r["n_impl"] = sum(1 for i in impls if i["design"] == r["id"])
    snr = lambda r: (r.get("slack") or {}).get("snr", 0.0)
    implemented = [r for r in rows if r["status"] in ("FEASIBLE", "VERIFIED") and r["area_um2"] is not None]
    pending = [r["id"] for r in rows if r["status"] == "FEASIBLE" and r["area_um2"] is None]
    f_front = _front(implemented, key=lambda r: (r["area_um2"], -snr(r)))
    o_front = _front([r for r in rows if r["status"] == "OPEN"], key=lambda r: (r["v"], -snr(r)))
    brief = lambda r: {k: r.get(k) for k in ("id", "parent", "action", "cls", "status", "v", "area_um2",
                                             "n_impl", "note")} | {"snr_slack": snr(r)}
    hints = []
    if f_front:
        hints.append(f"开发：已实现的可行前沿上面积最小的是 {f_front[0]['id']}（{f_front[0]['area_um2']:.0f} μm²）")
    if pending:
        hints.append(f"实现：{len(pending)} 个 FEASIBLE 节点尚未实现（{', '.join(pending[:5])}）")
    if o_front:
        s = o_front[0].get("suggestion") or {}
        hints.append(f"修复：缺口最小的 OPEN 节点是 {o_front[0]['id']}（v={o_front[0]['v']}），"
                     f"判定建议 {s.get('granularity')}：{s.get('why')}")
    stall, cur = 0, float("inf")
    for r in rows:
        if r.get("area_um2") is not None and r["area_um2"] < cur:
            cur, stall = r["area_um2"], 0
        elif r.get("action") == "TUNE":
            stall += 1
    if stall >= STALL:
        hints.append(f"探索：最近 {stall} 次 TUNE 没有降低最小实现面积，建议做一次 REWRITE")
    return {"designs": len(rows), "implementations": len(impls),
            "broken": sum(r["status"] == "BROKEN" for r in rows),
            "feasible_front": [brief(r) for r in f_front], "near_feasible_front": [brief(r) for r in o_front[:6]],
            "pending_implementation": pending, "hints": hints}


def final(ws: Path, cid: str, iid: str | None = None, seed: int = 777) -> dict:
    """G5 终验：隐藏场景质量 + 新种子的独立一致性向量 + 门级网表对拍与功耗 + 目标时钟时序。只回通过与否给 agent。

    返回完整结果（写入 final/<iid>.json 供实验统计），并给出 agent 可见的摘要。"""
    import numpy as np
    from dspgen.task import get
    from dspgen.ppa_sta import evaluate_verilog_vcd
    from .conform import check
    from .contract import freeze
    from .judge import hidden, load
    from .tool import _clock_ns
    ws = Path(ws)
    rec = next(r for r in _load(ws, ARCH) if r["id"] == cid)
    imp = best_impl(ws, cid) if iid is None else next(i for i in _load(ws, IMPLS) if i["id"] == iid)
    if imp is None:
        return {"error": f"{cid} 没有通过一致性且时序收敛的实现"}
    task_name = json.loads((ws / ".ws.json").read_text())["task"]
    task = get(task_name)
    code = Path(rec["file"]).read_text()
    rtl = Path(imp["file"]).read_text()
    out = {"design": cid, "impl": imp["id"]}
    out["hidden"] = hidden(load(code, task), task)
    # 新种子的一致性向量（不在契约中，agent 从未见过）
    fdir = ws / "final" / f"{imp['id']}_vectors"
    if not (fdir / "contract.json").exists():
        freeze(code, task_name, fdir, seed=seed, only=("random", "extreme"))
    g3 = check(fdir, rtl)
    out["fresh_conformance"] = {"passed": g3["passed"], "violations": g3["violations"][:3]}
    cj = json.loads((ws / "contracts" / cid / "contract.json").read_text())
    sc = next(k for k in cj["vectors"] if k.startswith("search"))
    exp = np.array([list(map(int, l.split())) for l in
                    (ws / "contracts" / cid / "vectors" / sc / "expected.txt").read_text().splitlines() if l.strip()])
    p = evaluate_verilog_vcd(rtl, task_name, scenario=task.search_scenarios[0], period_ns=_clock_ns(task_name),
                             expect=exp)
    out["ppa"] = {k: p.get(k) for k in ("status", "area_um2", "cells", "wns_ns", "fmax_mhz", "power_vcd",
                                        "gate_vs_model")}
    gate = p.get("gate_vs_model") or {}
    out["verified"] = bool(out["hidden"]["ok"] and g3["passed"] and p.get("status") == "ok"
                           and (p.get("wns_ns") or -1) >= 0 and gate.get("mismatches", 1) == 0)
    (ws / "final").mkdir(exist_ok=True)
    (ws / "final" / f"{imp['id']}.json").write_text(json.dumps(out, ensure_ascii=False, default=str, indent=1))
    if out["verified"]:
        rows = _load(ws, ARCH)
        for r in rows:
            if r["id"] == cid:
                r["status"] = "VERIFIED"
        _rewrite(ws, ARCH, rows)
    return {"design": cid, "impl": imp["id"], "verified": out["verified"]}
