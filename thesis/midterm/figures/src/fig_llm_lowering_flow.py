"""框架图：类型化原语 + LLM RTL lowering + 分层判定 + PPA 反馈闭环。"""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from style import (
    AQUA,
    AQUA_T,
    BLUE,
    BLUE_T,
    GRAY,
    GRAY_T,
    INK,
    INK2,
    ORANGE,
    ORANGE_T,
    VIOLET,
    VIOLET_T,
    WHITE,
    arrow,
    box,
    canvas,
    save,
    use_diagram_style,
)


FS = 11.5
FS_S = 9.5
FS_T = 13.0


def panel(ax, x, y, w, h, title, ec, fc):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=0.10",
            ec=ec,
            fc=fc,
            lw=1.4,
            alpha=0.30,
            zorder=0,
        )
    )
    ax.text(x + 0.16, y + h - 0.20, title, ha="left", va="center", fontsize=FS_T, color=ec,
            fontweight="bold")


def labeled_arrow(ax, p, q, label="", color=INK2, dashed=False, rad=0.0, offset=(0, 0)):
    ax.add_patch(
        FancyArrowPatch(
            p,
            q,
            arrowstyle="-|>",
            mutation_scale=11,
            color=color,
            lw=1.3,
            ls="--" if dashed else "-",
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=0,
            shrinkB=0,
            zorder=1,
        )
    )
    if label:
        ax.text(
            (p[0] + q[0]) / 2 + offset[0],
            (p[1] + q[1]) / 2 + offset[1],
            label,
            ha="center",
            va="center",
            fontsize=FS_S,
            color=color,
            bbox=dict(boxstyle="round,pad=0.16", fc=WHITE, ec="none"),
            zorder=5,
        )


def fig_llm_lowering_flow():
    use_diagram_style()
    fig, ax = canvas(15.8, 8.8)

    # 背景分区
    panel(ax, 0.20, 0.82, 4.15, 7.58, "输入与设计搜索", VIOLET, VIOLET_T)
    panel(ax, 4.55, 0.82, 6.15, 7.58, "方法二  分层判定", ORANGE, ORANGE_T)
    panel(ax, 10.90, 0.82, 4.70, 7.58, "RTL 实现与成本反馈", BLUE, BLUE_T)

    # 输入与设计搜索
    box(ax, 1.20, 7.15, 1.75, 1.18,
        "任务契约\n理想公式 F\n接口 · 系统容差 · PPA 目标", GRAY, WHITE, fs=FS_S, bold=True)
    box(ax, 3.30, 7.15, 1.62, 1.18,
        "设计 Agent\nREWRITE / TUNE\n选择父节点", VIOLET, WHITE, fs=FS_S, bold=True)
    labeled_arrow(ax, (2.08, 7.15), (2.49, 7.15), color=VIOLET)

    box(ax, 2.28, 5.22, 3.35, 1.38,
        "方法一  可执行类型化原语表示\n算法结构 · signed/W/F · 量化\n速率/状态 · latency/II · 资源承诺",
        VIOLET, VIOLET_T, fs=FS, bold=True)
    labeled_arrow(ax, (3.30, 6.56), (2.72, 5.91), color=VIOLET)
    box(ax, 2.28, 2.23, 2.78, 1.10,
        "候选档案\n父子谱系 · OPEN / FEASIBLE\n实现子节点", GRAY, WHITE, fs=FS_S)
    labeled_arrow(ax, (2.28, 4.53), (2.28, 2.78), label="登记候选", color=GRAY,
                  offset=(0.42, 0))
    labeled_arrow(ax, (1.00, 2.23), (2.90, 6.56), label="选父节点", color=VIOLET,
                  dashed=True, rad=-0.32, offset=(-0.48, 0.05))

    # 方法二：分类与两级判定
    box(ax, 7.30, 7.15, 2.16, 1.12,
        "变换关系分类\nbit-exact / math-equivalent\n/ approximate", ORANGE, WHITE, fs=FS_S, bold=True)
    labeled_arrow(ax, (3.96, 5.43), (6.22, 7.15), label="子候选", color=ORANGE,
                  offset=(-0.10, 0.16))

    box(ax, 6.05, 5.35, 2.08, 1.12,
        "逐位等价检查\n子候选 ≡ 父候选", BLUE, WHITE, fs=FS, bold=True)
    labeled_arrow(ax, (6.70, 6.59), (6.05, 5.91), label="bit-exact", color=BLUE,
                  offset=(-0.30, 0.02))

    box(ax, 9.20, 5.35, 2.32, 1.12,
        "系统质量判定\nSQNR / EVM / BER …\n是否满足容差契约", ORANGE, WHITE, fs=FS_S, bold=True)
    labeled_arrow(ax, (7.90, 6.59), (9.20, 5.91), label="math-equivalent / approximate",
                  color=ORANGE, offset=(0.22, 0.19))
    labeled_arrow(ax, (7.09, 5.35), (8.04, 5.35), label="检查失败", color=ORANGE,
                  offset=(0, 0.22))

    box(ax, 6.05, 3.65, 2.08, 1.00,
        "继承父节点质量结论\n只重新评价硬件实现", AQUA, AQUA_T, fs=FS_S, bold=True)
    labeled_arrow(ax, (6.05, 4.79), (6.05, 4.15), label="通过", color=AQUA, offset=(0.28, 0))

    box(ax, 9.20, 3.65, 1.82, 1.00,
        "质量可行\nFEASIBLE", AQUA, AQUA_T, fs=FS, bold=True)
    labeled_arrow(ax, (9.20, 4.79), (9.20, 4.15), label="满足", color=AQUA, offset=(0.28, 0))

    box(ax, 9.20, 2.03, 1.82, 0.82,
        "近可行 OPEN\n返回精度缺口", ORANGE, ORANGE_T, fs=FS_S)
    labeled_arrow(ax, (9.78, 4.79), (9.78, 2.44), color=ORANGE, rad=-0.08)
    box(ax, 6.05, 2.03, 1.55, 0.82, "舍弃\n非法或无潜力", "#b85450", "#f8cecc", fs=FS_S)
    labeled_arrow(ax, (8.04, 5.02), (6.70, 2.44), color="#b85450", rad=0.12)

    # 可行结果汇合到 LLM lowering
    box(ax, 13.20, 7.05, 2.18, 1.22,
        "LLM as Compiler\n受冻结原语契约约束\n生成 RTL + manifest", VIOLET, WHITE, fs=FS_S, bold=True)
    labeled_arrow(ax, (7.09, 3.65), (8.29, 3.65), label="继承", color=AQUA,
                  offset=(0.00, 0.20))
    labeled_arrow(ax, (10.11, 3.65), (12.11, 6.78), color=AQUA, rad=-0.12)

    box(ax, 13.20, 4.95, 2.55, 1.14,
        "实现忠实性检查\nRTL ≡ 原语 bit-true/事务语义\n接口 · reset · latency/II", BLUE, WHITE, fs=FS_S, bold=True)
    labeled_arrow(ax, (13.20, 6.44), (13.20, 5.52), color=BLUE)
    labeled_arrow(ax, (14.48, 4.95), (14.29, 7.05), label="失败：局部修复", color="#b85450",
                  dashed=True, rad=-0.25, offset=(0.42, 0.00))

    box(ax, 13.20, 3.12, 1.92, 0.98,
        "真实 PPA\n面积 · 时序 · 功耗", BLUE, BLUE_T, fs=FS, bold=True)
    labeled_arrow(ax, (13.20, 4.38), (13.20, 3.61), label="通过", color=AQUA, offset=(0.28, 0))

    box(ax, 13.20, 1.67, 2.00, 0.88,
        "Pareto 档案\n主 Verilog\n+ 备选 + 报告", AQUA, AQUA_T, fs=FS_S, bold=True)
    labeled_arrow(ax, (13.20, 2.63), (13.20, 2.11), color=AQUA)

    # 两类结果都回写候选档案，再由设计 Agent 选择父节点继续搜索。
    labeled_arrow(ax, (8.29, 2.03), (3.67, 2.23), label="质量缺口", color=ORANGE,
                  dashed=True, rad=-0.35, offset=(-1.30, -0.30))
    labeled_arrow(ax, (12.20, 1.67), (3.67, 1.92), label="PPA / Pareto 反馈", color=BLUE,
                  dashed=True, rad=-0.10, offset=(0.20, -0.19))

    # 底部语义说明
    ax.text(
        7.90,
        0.35,
        "两条可信性关系：RTL 对原语候选要求逐位/事务忠实；原语候选对理想公式只要求满足部署系统容差。",
        ha="center",
        va="center",
        fontsize=FS_S,
        color=INK,
        fontweight="bold",
    )

    save(fig, "fig_llm_lowering_flow", pad=0.05)


if __name__ == "__main__":
    fig_llm_lowering_flow()
