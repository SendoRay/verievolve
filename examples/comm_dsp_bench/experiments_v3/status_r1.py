import json, os, glob
WS = "/Users/chengzhy/verievolve_agent_ws"
for d in sorted(glob.glob(f"{WS}/r1_*")):
    n = os.path.basename(d)
    rows = [json.loads(l) for l in open(f"{d}/archive.jsonl")] if os.path.exists(f"{d}/archive.jsonl") else []
    log = [json.loads(l) for l in open(f"{d}/tool_log.jsonl")] if os.path.exists(f"{d}/tool_log.jsonl") else []
    feas = [r for r in rows if r["status"] in ("FEASIBLE", "VERIFIED")]
    ev_feas = [l for l in log if l.get("cmd") in ("eval", "veval") and l.get("verdict") == "FEASIBLE" and l.get("area_est")]
    best = min([r["area_est"] for r in feas] + [l["area_est"] for l in ev_feas], default=None)
    ver = [(r["id"], (r.get("verify") or {}).get("objectives", {}).get("area_um2")) for r in rows if r["status"] == "VERIFIED"]
    fin = [l for l in log if l.get("cmd") in ("final", "vfinal")]
    print(f"{n:34s} 调用 {len(log):3d} 登记 {len(rows):2d} 最小可行代理面积 {best}  VERIFIED {ver}  final {[(l['verdict'], l.get('area_um2')) for l in fin]}  notes {sorted(os.listdir(d + '/notes'))}")
