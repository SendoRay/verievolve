"""从 OpenEvolve 运行目录导出：逐迭代记录 CSV、当前最优曲线、最优程序的祖先链（尽量还原）。

python -m dspgraph.export_oe RUN_DIR [RUN_DIR ...]
输出写在各运行目录下：iterations.csv、ancestry.json。
"""
import csv, glob, json, re, sys
from pathlib import Path

IT = re.compile(r"Iteration (\d+): Program ([0-9a-f-]+) \(parent: ([0-9a-f-]+)\) completed")
MT = re.compile(r"Metrics: combined_score=([-0-9.]+), passed=([-0-9.]+), area_log=([-0-9.]+), snr_margin=([-0-9.]+)")


def export(d: Path):
    rows, cur = [], None
    for line in (d / "run.log").read_text().splitlines():
        m = IT.search(line)
        if m:
            cur = {"iteration": int(m.group(1)), "id": m.group(2), "parent": m.group(3)}
            continue
        m = MT.search(line)
        if m and cur:
            cur.update(score=float(m.group(1)), passed=int(float(m.group(2))),
                       area=10 ** float(m.group(3)), snr_margin=float(m.group(4)))
            rows.append(cur)
            cur = None
    rows.sort(key=lambda r: r["iteration"])
    best, npass = None, 0
    for r in rows:
        if r["passed"]:
            npass += 1
            best = r["area"] if best is None else min(best, r["area"])
        r["best_area_so_far"], r["passed_so_far"] = best, npass
    with open(d / "iterations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["iteration", "id", "parent", "score", "passed", "area", "snr_margin",
                                          "best_area_so_far", "passed_so_far"])
        w.writeheader()
        w.writerows(rows)
    # 祖先链：用 checkpoint 中各程序的 parent_id 回溯（含迁移副本），附带每一步的 diff 说明
    progs = {}
    for f in glob.glob(str(d / "checkpoints/*/programs/*.json")):
        p = json.load(open(f))
        progs.setdefault(p["id"], p)
    ok = [p for p in progs.values() if p["metrics"].get("passed")]
    chain = []
    if ok:
        cur = min(ok, key=lambda p: p["metrics"]["area_log"])
        while cur:
            m = cur["metrics"]
            chain.append({"generation": cur.get("generation"), "iteration": cur.get("iteration_found"),
                          "id": cur["id"], "area": 10 ** m["area_log"], "passed": bool(m.get("passed")),
                          "snr_margin": m.get("snr_margin"),
                          "changes": (cur.get("metadata") or {}).get("changes", ""), "code": cur["code"]})
            cur = progs.get(cur.get("parent_id"))
        chain.reverse()
        # 去掉迁移产生的相同代码副本
        dedup = []
        for c in chain:
            if dedup and dedup[-1]["code"] == c["code"]:
                continue
            dedup.append(c)
        chain = dedup
    (d / "ancestry.json").write_text(json.dumps({"chain": chain}, indent=1, ensure_ascii=False))
    return {"run": d.name, "iterations": len(rows), "passed": npass, "best_area": best,
            "chain_len": len(chain)}


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(export(Path(a)))
