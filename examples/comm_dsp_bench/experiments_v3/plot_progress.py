"""搜索进度图：一个 agent 工作区的候选档案（archive.jsonl）→ 多分面进度图。

共享横轴为候选序号；分面 1 为代理面积（目标，越低越好），标出刷新最优的“保留”点、其改动说明与当前最优阶梯线；
其余分面为各质量约束的松弛量（指标 − 门槛，越高越好），虚线为安全裕量，实线为 0（门槛）。
每个分面只有一根纵轴。VERIFIED 的真实 PPA 写在图例下方。
用法：python plot_progress.py 工作区目录 输出.png [标题]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/chengzhy/verievolve/thesis/midterm/figures/src")
from style import C_EXTRA, C_OURS, GRID, INK, INK2, use_data_style  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402

C_KEPT, C_FEAS, C_OPEN = C_OURS, "#86b6ef", C_EXTRA[0]
NAMES = {"snr": "SNR/EVM 松弛 (dB)", "alias_rejection": "混叠抑制松弛 (dB)", "ripple": "通带纹波松弛 (dB)"}


def load(ws):
    return [json.loads(l) for l in (Path(ws) / "archive.jsonl").read_text().splitlines() if l.strip()]


def plot(ws, out, title=None):
    rows = load(ws)
    ok = [r for r in rows if r["status"] != "BROKEN"]
    cons = [k for k in ("snr", "alias_rejection", "ripple") if any(k in (r.get("constraints") or {}) for r in ok)]
    use_data_style()
    fig, axes = plt.subplots(1 + len(cons), 1, figsize=(11, 3.2 + 1.6 * len(cons)), sharex=True,
                             gridspec_kw={"height_ratios": [2.4] + [1] * len(cons)})
    ax = axes[0]
    best, xs, ys, kept = float("inf"), [], [], []
    for i, r in enumerate(rows):
        if r["status"] in ("FEASIBLE", "VERIFIED") and r["area_est"] < best:
            best = r["area_est"]
            kept.append(i)
        xs.append(i)
        ys.append(best if best < float("inf") else None)
    # 当前最优阶梯线
    sx = [x for x, y in zip(xs, ys) if y is not None]
    sy = [y for y in ys if y is not None]
    if sx:
        ax.step(sx + [len(rows) - 0.5], sy + [sy[-1]], where="post", color=C_KEPT, lw=2, label="当前最优（可行）", zorder=2)
    for i, r in enumerate(rows):
        if r["status"] == "BROKEN":
            continue
        if i in kept:
            c, s, lab = C_KEPT, 64, "保留（刷新最优）"
        elif r["status"] in ("FEASIBLE", "VERIFIED"):
            c, s, lab = C_FEAS, 30, "可行，未刷新最优"
        else:
            c, s, lab = C_OPEN, 30, "不达标（近可行）"
        ax.scatter([i], [r["area_est"]], s=s, color=c, edgecolor="#fcfcfb", linewidth=1.5, zorder=3, label=lab)
        if r["status"] == "VERIFIED":
            ax.scatter([i], [r["area_est"]], s=150, facecolor="none", edgecolor=INK, linewidth=1.2, zorder=4,
                       label="终验通过")
        if i in kept:
            note = (r.get("note") or "")[:26]
            ax.annotate(f"{r['id']} {r.get('action', '')}: {note}", (i, r["area_est"]), xytext=(6, 6),
                        textcoords="offset points", fontsize=7.5, color=INK2, rotation=22, ha="left", va="bottom")
    h, l = ax.get_legend_handles_labels()
    uniq = dict(zip(l, h))
    ax.legend(uniq.values(), uniq.keys(), loc="upper right", fontsize=8)
    ax.set_ylabel("代理面积 (um^2，越低越好)")
    nb = sum(r["status"] == "BROKEN" for r in rows)
    nv = [r for r in rows if r["status"] == "VERIFIED"]
    sub = f"{len(rows)} 个登记候选，{len(kept)} 次刷新最优，{nb} 个构造失败"
    if nv:
        v = nv[-1]["verify"]["objectives"]
        sub += f"；终验 {nv[-1]['id']}：真实面积 {v.get('area_um2', 0):,.0f} um^2，功耗 {v.get('power_mw')} mW，{v.get('fmax_mhz', 0):.0f} MHz"
    lo, hi = min(r["area_est"] for r in ok), max(r["area_est"] for r in ok)
    ax.set_ylim(lo - 0.08 * (hi - lo), hi + 0.55 * (hi - lo))       # 为标注留出上方空间
    fig.suptitle((title or Path(ws).name) + "\n" + sub, fontsize=10.5, color=INK, x=0.06, ha="left")
    # 约束分面
    for ax2, k in zip(axes[1:], cons):
        for i, r in enumerate(rows):
            cc = (r.get("constraints") or {}).get(k)
            if not cc and k == "snr" and r.get("margin_db") is not None:   # 旧格式记录只有 SNR 裕量
                cc = {"slack": r["margin_db"]}
            if not cc:
                continue
            c = C_KEPT if i in kept else (C_FEAS if r["status"] in ("FEASIBLE", "VERIFIED") else C_OPEN)
            ax2.scatter([i], [cc["slack"]], s=40 if i in kept else 24, color=c, edgecolor="#fcfcfb", linewidth=1.2, zorder=3)
        m = next((r["constraints"][k]["margin"] for r in ok if k in (r.get("constraints") or {})), None)
        ax2.axhline(0, color=INK2, lw=1, zorder=1)
        if m:
            ax2.axhline(m, color=INK2, lw=1, ls="--", zorder=1)
            ax2.text(0.995, m, "裕量 ", transform=ax2.get_yaxis_transform(), va="bottom", ha="right", fontsize=7.5,
                     color=INK2)
        ax2.set_ylabel(NAMES[k], fontsize=9)
    axes[-1].set_xlabel("候选序号")
    for a in axes:
        a.grid(True, color=GRID)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out, dpi=200)
    return out


if __name__ == "__main__":
    print(plot(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
