import json, os, glob
from collections import Counter
CLS = {"eval": "eval", "veval": "eval", "vsweep": "eval", "archive_add": "eval", "ppa": "ppa", "ppa_vcd": "ppa",
       "vppa": "ppa", "vppa_vcd": "ppa", "final": "final", "vfinal": "final", "archive_verify": "final"}
for d in sorted(glob.glob("/Users/chengzhy/verievolve_agent_ws/r2_*")):
    log = [json.loads(l) for l in open(f"{d}/tool_log.jsonl")] if os.path.exists(f"{d}/tool_log.jsonl") else []
    c = Counter(CLS.get(l["cmd"]) for l in log if CLS.get(l["cmd"]))
    feas = [l.get("area_est") for l in log if l.get("verdict") == "FEASIBLE" and l.get("area_est")]
    fin = [(l.get("verdict"), l.get("area_um2")) for l in log if l["cmd"] in ("final", "vfinal")]
    side = f"/Users/chengzhy/verievolve_agent_ws/.hidden/{os.path.basename(d)}.jsonl"
    ver = [(r.get("id"), r.get("verdict"), (r.get("objectives") or {}).get("area_um2")) for r in
           (json.loads(l) for l in open(side)) if r.get("kind") == "verify"] if os.path.exists(side) else []
    print(f"{os.path.basename(d):28s} {dict(c)}  最小可行代理 {min(feas) if feas else None}  final {fin}  verify {ver}")
