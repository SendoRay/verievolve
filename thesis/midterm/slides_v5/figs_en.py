"""English versions of the motivation and agent-trace figures for the midterm slides."""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = sys.argv[1]
C_OURS, C_BASE, C_REF, C_NAIVE = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
plt.rcParams.update({"font.family": "Arial", "font.size": 12, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "axes.axisbelow": True, "figure.facecolor": SURFACE,
                     "axes.facecolor": SURFACE, "legend.frameon": False})

# Motivation: same DDC formula, two implementations (real synthesis area, Nangate45).
SPECS = ["R16\nnarrow", "R16\nwide", "R32\nnarrow", "R32\nwide", "R64\nnarrow", "R64\nwide"]
NAIVE = np.array([425644, 946859, 709042, 1889223, 1622343, 2559706]) / 1e3
TEXTBOOK = np.array([32210, 112852, 29155, 109802, 35428, 56303]) / 1e3
x = np.arange(len(SPECS)); w = 0.36
fig, ax = plt.subplots(figsize=(6.6, 4.0))
ax.bar(x - w / 2, NAIVE, w, color=C_NAIVE, edgecolor=SURFACE, linewidth=1.5, label="Direct mapping of the formula")
ax.bar(x + w / 2, TEXTBOOK, w, color=C_REF, edgecolor=SURFACE, linewidth=1.5, label="Textbook multirate structure")
for i, (a, b) in enumerate(zip(NAIVE, TEXTBOOK)):
    ax.text(i + w / 2, b * 1.15, f"{a / b:.0f}×", ha="center", va="bottom", fontsize=12, color=INK, fontweight="bold")
ax.set_yscale("log"); ax.set_ylim(10, 12000)
ax.set_ylabel("Synthesized area (10³ µm²)")
ax.set_xticks(x, SPECS); ax.grid(axis="x", visible=False)
ax.legend(loc="upper left", ncol=1, fontsize=11)
fig.savefig(f"{OUT}/motivation_en.png", dpi=220, bbox_inches="tight"); plt.close(fig)

# Agent trace on link A, R32 narrowband (proxy area; submission order).
CAND = [(25757.3, False), (25757.3, False), (18838.8, False), (18838.8, False), (22580.3, False), (19341.3, False),
        (23853.4, False), (27327.7, True), (24198.0, True), (18895.9, True), (17519.1, True), (16609.2, True),
        (14779.7, False), (15879.7, True), (15547.0, True), (15270.4, True), (14641.4, True), (14225.8, True),
        (13766.6, True), (13466.2, False), (13490.2, True), (13160.4, True), (12996.0, True), (12773.4, True),
        (12896.4, True), (12725.1, True), (12760.6, True), (12720.0, True), (12633.0, False), (12644.5, True)]
xs = list(range(1, len(CAND) + 1))
fig, ax = plt.subplots(figsize=(7.4, 3.9))
best, bx, by = None, [], []
for xi, (a, ok) in zip(xs, CAND):
    ax.scatter([xi], [a / 1e3], s=46, color=C_OURS if ok else C_NAIVE, edgecolor=SURFACE, linewidth=1.3, zorder=3)
    if ok and (best is None or a < best):
        best = a
    if best is not None:
        bx.append(xi); by.append(best / 1e3)
ax.step(bx, by, where="post", color=C_OURS, linewidth=2, zorder=2, label="Best feasible so far")
for y, lab, col in [(92.3, "Evolutionary search (real area)", C_BASE), (29.2, "Template parameter search (real area)", C_REF)]:
    ax.axhline(y, color=col, linestyle="--", linewidth=1.3, zorder=1)
    ax.text(len(CAND) + 0.5, y * 1.06, lab, ha="right", va="bottom", fontsize=10.5, color=col)
ax.set_yscale("log"); ax.set_ylim(10, 130)
ax.set_yticks([10, 20, 30, 50, 100], ["10", "20", "30", "50", "100"]); ax.minorticks_off()
ax.set_xlim(0.3, len(CAND) + 0.7)
ax.set_xlabel("Candidate index (submission order)")
ax.set_ylabel("Area (10³ µm², proxy model)")
ax.set_xticks(xs[::3]); ax.grid(axis="x", visible=False)
ax.scatter([], [], s=46, color=C_OURS, label="Feasible"); ax.scatter([], [], s=46, color=C_NAIVE, label="Infeasible")
ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.84), fontsize=10.5, ncol=3)
fig.savefig(f"{OUT}/agent_trace_en.png", dpi=220, bbox_inches="tight"); plt.close(fig)
print("ok")
