"""VeriEvolve canonical overview with a stage-column layout.

The overview intentionally hides search-tree and gate-level details. Those
belong to separate method figures.

Usage: python make_flow_v5.py <output-directory>
"""

from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

from make_diagrams import OUT, canvas, save


INK = "#202020"
INK2 = "#5b5b5b"
HEADER = "#595959"
CREAM = "#fff3cf"
SAGE = "#eef4e4"
PEACH = "#fff0e7"
SKY = "#edf5fc"
WHITE = "#ffffff"
BLUE = "#2a78d6"
PURPLE = "#4a3aa7"
ORANGE = "#eb6834"
GREEN = "#1baf7a"
RED = "#c74e45"
GRAY = "#7b7a76"


def stage(ax, x, w, title, subtitle, fill):
    ax.add_patch(Rectangle((x, 0.78), w, 7.48, ec=INK, fc=fill, lw=1.15, zorder=0))
    ax.add_patch(Rectangle((x, 7.30), w, 0.96, ec=INK, fc=HEADER, lw=1.15, zorder=1))
    ax.text(x + w / 2, 7.94, title, ha="center", va="center", color=WHITE,
            fontsize=12.2, fontweight="bold", zorder=2)
    ax.text(x + w / 2, 7.62, subtitle, ha="center", va="center", color=WHITE,
            fontsize=10.2, fontweight="bold", zorder=2)


def card(ax, x, y, w, h, title, lines, edge=GRAY, fill=WHITE, fs=8.8):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.08",
        ec=edge, fc=fill, lw=1.4, zorder=3,
    ))
    ax.text(x + w / 2, y + h - 0.30, title, ha="center", va="center", color=INK,
            fontsize=10.0, fontweight="bold", zorder=4)
    ax.text(x + w / 2, y + h / 2 - 0.14, "\n".join(lines), ha="center", va="center",
            color=INK2, fontsize=fs, linespacing=1.35, zorder=4)


def flow(ax, p, q, color=INK2, dashed=False, rad=0.0, label=None, label_pos=None, lw=1.5):
    ax.add_patch(FancyArrowPatch(
        p, q, arrowstyle="-|>", mutation_scale=12, color=color, lw=lw,
        ls="--" if dashed else "-", connectionstyle=f"arc3,rad={rad}",
        shrinkA=0, shrinkB=0, zorder=2,
    ))
    if label:
        lx, ly = label_pos if label_pos else ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        ax.text(lx, ly, label, ha="center", va="center", fontsize=8.2, color=color,
                bbox=dict(boxstyle="round,pad=0.12", fc=WHITE, ec="none"), zorder=5)


def route_flow(ax, points, color=INK2, dashed=False, label=None, label_pos=None, lw=1.4):
    """Orthogonal feedback path with an arrow only on the final segment."""
    ls = "--" if dashed else "-"
    for p, q in zip(points[:-2], points[1:-1]):
        ax.plot([p[0], q[0]], [p[1], q[1]], color=color, lw=lw, ls=ls, zorder=2)
    flow(ax, points[-2], points[-1], color=color, dashed=dashed, lw=lw)
    if label:
        ax.text(label_pos[0], label_pos[1], label, ha="center", va="center",
                fontsize=8.2, color=color,
                bbox=dict(boxstyle="round,pad=0.12", fc=WHITE, ec="none"), zorder=5)


def fig_framework():
    fig, ax = canvas(19.2, 8.72)

    # One organizing axis only: the chronological system stages.
    stage(ax, 0.18, 3.05, "Stage 0", "Task Preparation", CREAM)
    stage(ax, 3.36, 3.70, "Stage 1", "Primitive-Level Design", SAGE)
    stage(ax, 7.19, 3.55, "Stage 2", "Candidate Qualification", PEACH)
    stage(ax, 10.87, 3.46, "Stage 3", "RTL Realization", SKY)
    stage(ax, 14.46, 4.55, "Stage 4", "Synthesis, Selection & Output", CREAM)

    # Stage 0: the single task specification supplied to the system.
    card(ax, 0.52, 4.18, 2.38, 2.05, "Task Contract",
         ["ideal function F", "quality/environment contract Q", "interface + PPA target I"],
         GRAY, WHITE)
    card(ax, 0.52, 2.30, 2.38, 1.12, "Initial Primitive Program",
         ["direct translation of F", "tree root + baseline"],
         GRAY, WHITE, fs=8.0)

    # Stage 1: Method 1 is the representation; the agent iterates over it.
    card(ax, 3.68, 5.48, 1.38, 1.18, "Design Agent", ["REWRITE", "TUNE"], PURPLE, WHITE)
    card(ax, 5.32, 5.12, 1.42, 1.60, "Primitive Candidate",
         ["typed executable program", "numeric / rate / state", "micro-architecture intent"],
         BLUE, "#dbe8f8", fs=7.9)
    card(ax, 3.88, 2.22, 2.66, 1.72, "AND/OR Search Tree",
         ["OR node: alternative REWRITE / TUNE", "AND node: sub-regions solved jointly",
          "BROKEN / OPEN / FEASIBLE / VERIFIED"],
         PURPLE, "#eeeafa", fs=7.8)
    ax.text(3.55, 1.12, "M1: primitive representation   ·   M3: AND/OR tree search",
            ha="left", va="center", fontsize=7.8, color=PURPLE, fontweight="bold")

    # Stage 2: high-level candidate acceptance only; detailed gates live elsewhere.
    card(ax, 7.55, 5.03, 2.83, 1.72, "Transformation Validity",
         ["type / legality check", "declared: bit-exact / math-eq / approx", "exact → inherit parent quality"],
         ORANGE, WHITE, fs=8.2)
    card(ax, 7.55, 2.95, 2.83, 1.42, "System-Quality Check",
         ["SQNR / EVM / BER …", "acceptable within deployment tolerance"],
         ORANGE, WHITE, fs=8.2)
    card(ax, 7.84, 1.62, 2.25, 0.76, "Frozen Implementation Contract",
         ["accepted primitive semantics"], GREEN, "#d5f0e5", fs=7.7)
    ax.text(7.38, 1.12, "Method 2a: candidate is acceptable for deployment",
            ha="left", va="center", fontsize=8.0, color=ORANGE, fontweight="bold")

    # Stage 3: lowering is an implementation mechanism, not a separate contribution.
    card(ax, 11.23, 5.46, 2.74, 1.22, "Lowering Agent",
         ["frozen primitive contract → RTL", "+ implementation manifest"],
         PURPLE, WHITE, fs=8.2)
    card(ax, 11.48, 3.78, 2.24, 0.92, "Generated RTL", ["Verilog + scope annotations"], BLUE, WHITE, fs=8.1)
    card(ax, 11.18, 1.82, 2.84, 1.28, "Implementation Fidelity",
         ["RTL ≡ primitive bit-true result", "transaction / reset / latency / II"],
         BLUE, "#eaf3fc", fs=8.0)
    ax.text(11.06, 1.12, "Method 2b: implementation is faithful to the candidate",
            ha="left", va="center", fontsize=7.8, color=BLUE, fontweight="bold")

    # Stage 4: cost is measured independently; final output follows held-out checking.
    card(ax, 14.86, 5.48, 1.55, 1.16, "Faithful RTL", ["fidelity passed"], GREEN, WHITE)
    card(ax, 16.72, 5.14, 1.86, 1.55, "Real PPA", ["synthesis + STA", "gate-level power", "area · timing · power"],
         BLUE, "#dbe8f8", fs=8.0)
    card(ax, 14.86, 3.35, 3.72, 1.18, "Quality–Cost Pareto Front",
         ["non-dominated verified designs", "measured bottlenecks fed back to design"],
         GREEN, "#d5f0e5", fs=8.2)
    card(ax, 14.86, 1.50, 1.78, 1.20, "Independent Final Check",
         ["held-out + gate-level replay", "pass → VERIFIED", "no feedback to search"], ORANGE, WHITE, fs=7.7)
    card(ax, 16.82, 1.50, 1.76, 1.20, "Output",
         ["selected Verilog + alternatives", "quality / fidelity / PPA report"], GREEN, "#e6f5ed", fs=7.7)

    # Main forward flow.
    flow(ax, (2.90, 5.20), (3.68, 6.04), color=INK2)
    flow(ax, (1.71, 4.18), (1.71, 3.42), color=INK2)
    flow(ax, (2.90, 2.86), (3.88, 2.86), color=INK2)
    flow(ax, (4.37, 3.94), (4.37, 5.48), color=PURPLE,
         label="select parent", label_pos=(4.37, 4.71))
    flow(ax, (5.06, 6.04), (5.32, 5.92), color=PURPLE)
    flow(ax, (6.03, 5.12), (5.22, 3.94), color=PURPLE)
    flow(ax, (6.74, 5.92), (7.55, 5.92), color=ORANGE)
    flow(ax, (8.97, 5.03), (8.97, 4.37), color=ORANGE)
    flow(ax, (8.97, 2.95), (8.97, 2.38), color=GREEN, label="accepted", label_pos=(9.42, 2.69))
    route_flow(ax, [(10.09, 1.86), (10.80, 1.86), (10.80, 6.07), (11.23, 6.07)], color=GREEN, lw=1.5)
    flow(ax, (12.60, 5.46), (12.60, 4.70), color=BLUE)
    flow(ax, (12.60, 3.78), (12.60, 3.10), color=BLUE)
    flow(ax, (14.02, 2.46), (14.86, 6.06), color=GREEN, rad=-0.13)
    flow(ax, (16.41, 6.06), (16.72, 5.92), color=BLUE)
    flow(ax, (17.65, 5.14), (17.00, 4.53), color=GREEN)
    flow(ax, (15.76, 3.35), (15.76, 2.70), color=GREEN)
    flow(ax, (16.64, 2.10), (16.82, 2.10), color=GREEN)

    route_flow(ax, [(10.38, 5.40), (10.56, 5.40), (10.56, 2.16), (10.09, 2.16)], color=GREEN, lw=1.4)
    ax.text(10.56, 3.80, "bit-exact → inherit", rotation=90, ha="center", va="center",
            fontsize=8.0, color=GREEN,
            bbox=dict(boxstyle="round,pad=0.12", fc=PEACH, ec="none"), zorder=5)

    # Only two feedback concepts in the overview; their detailed policies live in method figures.
    ax.plot([7.55, 7.36, 7.36], [5.35, 5.35, 3.66], color=ORANGE, lw=1.25, ls="--", zorder=2)
    ax.text(7.36, 4.55, "invalid → BROKEN", rotation=90, ha="center", va="center", fontsize=8.0,
            color=ORANGE, bbox=dict(boxstyle="round,pad=0.12", fc=PEACH, ec="none"), zorder=5)
    flow(ax, (7.55, 3.66), (6.54, 3.66), color=ORANGE, dashed=True,
         label="quality gap → OPEN", label_pos=(7.00, 3.91), lw=1.25)
    route_flow(ax, [(16.72, 3.35), (16.72, 0.62), (5.22, 0.62), (5.22, 2.22)],
               color=BLUE, dashed=True, label="measured PPA / Pareto feedback → tree nodes",
               label_pos=(10.95, 0.62), lw=1.35)

    # Local RTL repair remains local to Stage 3.
    route_flow(ax, [(14.02, 2.46), (14.20, 2.46), (14.20, 6.08), (13.97, 6.08)],
               color=RED, dashed=True, lw=1.2)
    ax.text(14.20, 4.20, "fidelity failure → bounded repair", rotation=90, ha="center", va="center",
            fontsize=8.0, color=RED, bbox=dict(boxstyle="round,pad=0.12", fc=SKY, ec="none"), zorder=5)

    ax.text(9.60, 0.27,
            "Candidate ≈ ideal function within the deployment contract; RTL ≡ the frozen primitive candidate.",
            ha="center", va="center", fontsize=8.9, color=INK, fontweight="bold")

    save(fig, "fig_framework_v5")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_framework()
