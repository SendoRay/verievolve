#!/usr/bin/env python
"""E1 分析：两臂前沿、HV、适应度噪声证据。

用法: python analyze_e1.py
输出: experiments_e1/analysis.json + 控制台报告
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import pareto_filter, hypervolume_3d, load_final_front
from run_e1 import TASK_NORM

BENCH = Path(__file__).resolve().parent
OUT = BENCH / "experiments_e1"


def front_of(run_dir: Path, prec_key="precision"):
    ckpts = sorted((run_dir / "checkpoints").glob("checkpoint_*"),
                   key=lambda p: int(p.name.split("_")[1]))
    if not ckpts:
        return []
    pts = []
    for pf in (ckpts[-1] / "programs").glob("*.json"):
        d = json.loads(pf.read_text())
        m = d.get("metrics", {})
        if m.get("combined_score", 0) > 0.5 and "precision" in m:
            pts.append((float(m["precision"]), float(m["area"]),
                        float(m.get("throughput", 0))))
    return pareto_filter(dedup(pts))


def dedup(pts):
    seen, out = set(), []
    for p in sorted(pts, key=lambda x: (x[1], -x[0])):
        key = (round(p[0], 1), round(p[1]), round(p[2], 3))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def hv_curve(run_dir: Path, norm):
    """每个 checkpoint 的 HV（前沿去重后）。"""
    ckpts = sorted((run_dir / "checkpoints").glob("checkpoint_*"),
                   key=lambda p: int(p.name.split("_")[1]))
    curve = []
    for ck in ckpts:
        pts = []
        for pf in (ck / "programs").glob("*.json"):
            d = json.loads(pf.read_text())
            m = d.get("metrics", {})
            if m.get("combined_score", 0) > 0.5 and "precision" in m:
                pts.append((float(m["precision"]), float(m["area"]),
                            float(m.get("throughput", 0))))
        pts = dedup(pts)
        front = pareto_filter(pts) if pts else []
        curve.append({"iter": int(ck.name.split("_")[1]),
                      "hv": round(hypervolume_3d(front, norm), 4) if front else 0.0})
    return curve


def main():
    report = {"arms": {}}
    for task in ["cmul", "cmul_w16_free", "cordic_sincos", "atan2_w16",
                 "llr_64qam_snr20"]:
        norm = TASK_NORM.get(task) or TASK_NORM.get(task.split("_")[0])
        for arm in ["S", "C"]:
            rd = OUT / f"e1_{task}_arm{arm}_seed0"
            if not rd.exists():
                continue
            front = front_of(rd)
            hv = hypervolume_3d(front, norm) if front else 0.0
            report["arms"].setdefault(task, {})[arm] = {
                "hv": round(hv, 4),
                "n_front": len(front),
                "front": [{"prec": round(p, 1), "area": int(a), "thr": round(t, 3)}
                          for p, a, t in sorted(front, key=lambda x: x[1])],
                "hv_curve": hv_curve(rd, norm),
            }
    (OUT / "analysis.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    for task, arms in report["arms"].items():
        print(f"== {task}")
        for arm, info in arms.items():
            print(f"  Arm {arm}: HV={info['hv']:.4f}  前沿 {info['n_front']} 点")
            for pt in info["front"][:8]:
                print(f"     {pt['prec']:7.1f} dB  {pt['area']:6d} LUT  thr={pt['thr']:.3f}")


if __name__ == "__main__":
    main()
