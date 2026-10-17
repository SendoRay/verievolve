"""候选档案：LLM 驱动树搜索的状态（讨论归纳 §12.5）。

每个节点是一个完整的原语程序，记录：父节点、动作（REWRITE 改结构 / TUNE 调参数）、变换类别声明与核实结果、
状态、约束表、相对父节点的变化量。
状态：BROKEN（构造失败）、OPEN（合法但有缺口 v > 0）、FEASIBLE（搜索数据集上满足全部约束的裕量）、
VERIFIED（隐藏数据集与实现级检查全部通过）。
框架自动调度：新的最小可行点自动做 L2（隐藏数据集）判定；verify 做 L3（RTL、门级、PPA），并用真实面积校准代理面积。
调度提示：开发（前沿上继续 TUNE）、修复（缺口最小的 OPEN 节点）、探索（连续 TUNE 停滞时做 REWRITE）。
档案文件为工作区下的 archive.jsonl。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

ARCHIVE = "archive.jsonl"
STALL = 4


def load(ws: Path) -> list:
    p = Path(ws) / ARCHIVE
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def _save(ws: Path, rows):
    (Path(ws) / ARCHIVE).write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows))


def _front(points, key):
    pts = sorted(points, key=key)
    out, best = [], float("inf")
    for p in pts:
        if key(p)[1] < best:
            out.append(p)
            best = key(p)[1]
    return out


def _delta(rec, par):
    if not par or par.get("status") == "BROKEN" or rec.get("status") == "BROKEN":
        return None
    d = {"area_est": round(rec["area_est"] - par["area_est"], 1)}
    for k, v in rec.get("constraints", {}).items():
        if k in par.get("constraints", {}):
            d[f"slack_{k}"] = round(v["slack"] - par["constraints"][k]["slack"], 4)
    return d


def add(ws: Path, task: str, prog: Path, parent: str | None, action: str, note: str, claim: str = "approx") -> dict:
    from .verdict import search, hidden
    from .claims import check_equiv, check_math
    ws = Path(ws)
    rows = load(ws)
    by = {r["id"]: r for r in rows}
    par = by.get(parent) if parent else None
    cid = f"c{len(rows):03d}"
    (ws / "archive").mkdir(exist_ok=True)
    dst = ws / "archive" / f"{cid}.py"
    shutil.copy(prog, dst)
    code = Path(prog).read_text()
    rec = {"id": cid, "parent": parent, "action": action.upper(), "claim": claim, "note": note, "file": str(dst),
           "time": time.strftime("%H:%M:%S")}
    claim_res = None
    if claim == "equiv" and par and par.get("status") != "BROKEN":
        claim_res = check_equiv(code, Path(par["file"]).read_text(), task)
        if claim_res["verified"]:            # 质量继承父节点，只更新面积
            rec.update(status=par["status"] if par["status"] != "VERIFIED" else "FEASIBLE", v=par.get("v", 0.0),
                       margin_db=par.get("margin_db"), constraints=par.get("constraints", {}),
                       area_est=round(float(claim_res["area"]), 1), inherited_from=parent)
    elif claim == "math" and par and par.get("status") != "BROKEN":
        claim_res = check_math(code, Path(par["file"]).read_text(), task)
    if "status" not in rec:
        r = search(code, task)
        rec["status"] = r["verdict"]
        if r["verdict"] == "BROKEN":
            rec["error"] = r.get("error")
        else:
            snr = next(k for k in r["constraints"] if k["name"] == "snr")
            rec.update(v=r["v"], margin_db=snr["slack"], area_est=r["objectives"]["area_est"],
                       constraints={k["name"]: {"slack": k["slack"], "margin": k["margin"], "ok": k["ok"],
                                                "value": k["value"], "threshold": k["threshold"], "source": k["source"]}
                                    for k in r["constraints"]})
            rec["report"] = r
    if claim_res is not None:
        rec["claim_check"] = claim_res
        if claim == "equiv" and not claim_res["verified"]:
            rec["claim_note"] = "声明为逐位等价但比对不一致，已按近似变换判定"
    rec["delta_vs_parent"] = _delta(rec, par)
    # L2 自动调度：新的最小可行点
    feas = [r for r in rows if r["status"] in ("FEASIBLE", "VERIFIED")]
    if rec["status"] == "FEASIBLE" and all(rec["area_est"] < r["area_est"] for r in feas):
        has_sweep = any(v.get("source") == "sweep" for v in rec.get("constraints", {}).values())
        from .verdict import sidecar
        h = hidden(code, task, has_sweep)
        sidecar(ws, "L2", {"id": cid, **h})
        rec["hidden_ok"] = h["ok"]                 # agent 只看到通过与否（F2）
    rows.append(rec)
    _save(ws, rows)
    if (ws / ".contract.json").exists():
        with (ws / "tool_log.jsonl").open("a") as f:
            f.write(json.dumps({"t": rec["time"], "cmd": "archive_add", "file": str(dst), "id": cid,
                                "verdict": rec["status"], "v": rec.get("v"), "area_est": rec.get("area_est")},
                               ensure_ascii=False) + "\n")
    out = {k: v for k, v in rec.items() if k != "report"}
    if "report" in rec:
        out["diagnostics"] = rec["report"]["diagnostics"]
    return out


def show(ws: Path) -> dict:
    rows = load(Path(ws))
    feas = [r for r in rows if r["status"] in ("FEASIBLE", "VERIFIED")]
    opn = [r for r in rows if r["status"] == "OPEN"]
    f_front = _front(feas, key=lambda r: (r["area_est"], -(r.get("margin_db") or 0)))
    o_front = _front(opn, key=lambda r: (r["v"], r["area_est"]))
    stall, cur = 0, float("inf")
    for r in rows:
        if r["status"] in ("FEASIBLE", "VERIFIED") and r["area_est"] < cur:
            cur, stall = r["area_est"], 0
        elif r.get("action") == "TUNE":
            stall += 1
    cal = [r["verify"]["objectives"]["area_um2"] / r["area_est"] for r in rows
           if r.get("verify") and (r["verify"].get("objectives") or {}).get("area_um2") and r.get("area_est")]
    brief = lambda r: {k: r.get(k) for k in ("id", "parent", "action", "claim", "status", "margin_db", "v", "area_est",
                                             "note")} | ({"hidden_ok": r["hidden_ok"]} if "hidden_ok" in r else {})
    hints = []
    if f_front:
        hints.append(f"开发：可行前沿上面积最小的是 {f_front[0]['id']}，可继续 TUNE")
    if o_front:
        hints.append(f"修复：缺口最小的 OPEN 节点是 {o_front[0]['id']}（v={o_front[0]['v']}），微调后可能变为可行")
    if stall >= STALL:
        hints.append(f"探索：最近 {stall} 次 TUNE 没有降低最小可行面积，建议做一次 REWRITE（改结构、分解或融合）")
    return {"candidates": len(rows), "broken": sum(r["status"] == "BROKEN" for r in rows),
            "best_feasible_area_est": f_front[0]["area_est"] if f_front else None,
            "feasible_front": [brief(r) for r in f_front], "near_feasible_front": [brief(r) for r in o_front[:6]],
            "verified": [{"id": r["id"], **(r["verify"].get("objectives") or {})} for r in rows
                         if r["status"] == "VERIFIED"],
            "proxy_to_real_area": round(sum(cal) / len(cal), 3) if cal else None, "hints": hints}


def verify(ws: Path, task: str, cid: str) -> dict:
    from .verdict import final
    ws = Path(ws)
    rows = load(ws)
    rec = next(r for r in rows if r["id"] == cid)
    res = final(Path(rec["file"]).read_text(), task, Path(rec["file"]))
    from .verdict import public, sidecar
    sidecar(ws, "verify", {"id": cid, **res})
    rec["verify"] = public(res)
    if res.get("verdict") == "VERIFIED":
        rec["status"] = "VERIFIED"
    _save(ws, rows)
    return {k: v for k, v in rec.items() if k != "report"}
