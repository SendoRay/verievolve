import json, os
WS = "/Users/chengzhy/verievolve_agent_ws"
for n in ("ofdm_tx64_q1024", "real_r32_narrow", "usrpq_real_r32_narrow", "usrpq_dev_r32_narrow"):
    p = f"{WS}/v3_{n}/archive.jsonl"
    rows = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    feas = [r for r in rows if r["status"] in ("FEASIBLE", "VERIFIED")]
    best = min(feas, key=lambda r: r["area_est"]) if feas else None
    ver = [r for r in rows if r["status"] == "VERIFIED"]
    print(f"{n:24s} 候选 {len(rows):2d}  可行 {len(feas):2d}  最小可行代理面积 {best['area_est'] if best else '-':>9}  "
          f"裕量 {best['margin_db'] if best else '-'}  VERIFIED {[ (r['id'], r['verify'].get('area_um2')) for r in ver]}"
          f"  notes {sorted(os.listdir(f'{WS}/v3_{n}/notes')) if os.path.exists(f'{WS}/v3_{n}/notes') else []}")
