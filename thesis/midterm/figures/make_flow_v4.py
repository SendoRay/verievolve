"""中期报告 v4 的架构流线图：输入 → 语义直写 → 原语程序 → 编译 → 判定 → PPA → 反馈 → agent → 终验。

用法：python make_flow_v4.py <输出目录>
"""

from matplotlib.patches import FancyBboxPatch, Polygon

from make_diagrams import (
    AQUA,
    BLUE,
    BLUE_T,
    GRAY,
    GRAY_T,
    INK,
    INK2,
    ORANGE,
    ORANGE_T,
    OUT,
    VIOLET,
    VIOLET_T,
    arrow,
    canvas,
    save,
)

RED = "#c8372d"


def group(ax, x0, y0, x1, y1, title, ec, fc, bottom=False):
    """虚线分组框，标题写在左上角（bottom=True 时写在左下角）。"""
    ax.add_patch(
        FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=0.15",
                       ec=ec, fc=fc, lw=1.4, ls="--", zorder=0)
    )
    ax.text(x0 + 0.15, y0 + 0.22 if bottom else y1 - 0.22, title, fontsize=10, color=ec, fontweight="bold", va="center")


def card(ax, x, y, w, h, title, lines, ec, fc, fs=9.5):
    """标题 + 若干行说明的方框，以 (x, y) 为中心。"""
    ax.add_patch(
        FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0,rounding_size=0.08",
                       ec=ec, fc=fc, lw=1.4, zorder=2)
    )
    if not lines:
        ax.text(x, y, title, ha="center", va="center", fontsize=fs, color=INK, fontweight="bold", zorder=3)
        return
    ax.text(x, y + h / 2 - 0.26, title, ha="center", va="center", fontsize=fs, color=INK, fontweight="bold", zorder=3)
    ax.text(x, y - 0.14, "\n".join(lines), ha="center", va="center", fontsize=fs - 1.8, color=INK2,
            linespacing=1.45, zorder=3)


def diamond(ax, x, y, w, h, text, ec, fc, fs=9):
    ax.add_patch(Polygon([(x - w / 2, y), (x, y + h / 2), (x + w / 2, y), (x, y - h / 2)], closed=True,
                         ec=ec, fc=fc, lw=1.4, zorder=2))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK, linespacing=1.3, zorder=3)


def label(ax, x, y, text, color=INK2, fs=8, ha="left"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=fs, color=color, linespacing=1.35, zorder=4,
            bbox=dict(fc="white", ec="none", pad=0.6, alpha=0.9))


def fig_flow():
    fig, ax = canvas(17.0, 7.2)
    yt, yb = 5.0, 1.75

    # ── 输入：用户只写三项 ──
    group(ax, 0.15, 3.55, 2.55, 6.75, "输入（三项）", GRAY, "#fafaf8")
    card(ax, 1.35, 5.75, 2.1, 0.62, "公式 F", ["理想计算，浮点语义"], GRAY, "#ffffff", fs=9.5)
    card(ax, 1.35, 4.95, 2.1, 0.78, "质量指标 Q", ["SNR / EVM + 信号环境", "容差 p（损失上限）"], GRAY, "#ffffff", fs=9.5)
    card(ax, 1.35, 4.05, 2.1, 0.62, "接口 I", ["位宽 · 速率 · 目标时钟"], GRAY, "#ffffff", fs=9.5)

    # ── 方法一：原语表示与编译 ──
    group(ax, 3.35, 3.55, 7.55, 6.75, "方法一：原语表示与编译", BLUE, "#f3f8fe")
    card(ax, 4.45, yt, 1.85, 1.75, "原语程序",
         ["类型化数据流图", "(位宽·小数位·速率·时延)", "", "根：直写起点", "正确但面积大", "子：agent 的候选"],
         BLUE, BLUE_T)
    card(ax, 6.5, yt, 1.65, 1.75, "编译器", ["执行即编译", "", "逐位整数模型", "Verilog", "（二者逐位一致）"],
         BLUE, BLUE_T)
    arrow(ax, (5.38, yt), (5.67, yt))

    arrow(ax, (2.4, yt), (3.52, yt))
    label(ax, 2.97, yt + 0.25, "语义直写", INK, fs=9, ha="center")

    # ── 方法二：系统级判定（质量门 + PPA） ──
    group(ax, 7.75, 3.55, 13.85, 6.75, "方法二：系统级判定", ORANGE, "#fff8f4")
    card(ax, 8.85, yt, 1.75, 1.75, "容差判定",
         ["L0 类型检查", "L1 场景仿真 · 扫频", "RTL ≡ 整数模型", "（实现忠实性）"], ORANGE, ORANGE_T)
    diamond(ax, 10.55, yt, 1.35, 1.35, "质量门\n松弛 ≥ 裕量", ORANGE, "#ffffff", fs=8.8)
    card(ax, 12.65, yt, 1.95, 1.75, "PPA 评估",
         ["Yosys + ABC 综合", "OpenSTA 时序", "门级仿真功耗", "面积 · fmax · 功耗"], ORANGE, ORANGE_T)
    arrow(ax, (7.33, yt), (7.97, yt))
    arrow(ax, (9.73, yt), (9.87, yt))
    arrow(ax, (11.23, yt), (11.67, yt), color=AQUA, lw=1.6)
    label(ax, 11.45, yt + 0.25, "通过", AQUA, fs=8.5, ha="center")
    ax.text(10.55, yt + 0.85, "（系统可接受性）", ha="center", fontsize=8, color=INK2)

    # ── 终验与输出 ──
    card(ax, 14.95, yt, 1.75, 1.75, "终验",
         ["留出场景", "+ 30 个统计复核", "门级对拍 · STA", "全部通过 → VERIFIED"], AQUA, "#e9f7f1")
    card(ax, 16.45, yt, 0.9, 0.95, "最终\nVerilog", [], AQUA, "#d5f0e5", fs=9)
    arrow(ax, (15.83, yt), (15.99, yt), color=AQUA, lw=1.6)

    # ── 方法三：反馈驱动的 agent 搜索 ──
    group(ax, 3.35, 0.35, 13.85, 3.2, "方法三：反馈驱动的 agent 搜索", VIOLET, "#f8f7fd", bottom=True)
    card(ax, 5.1, yb, 3.1, 1.75, "LLM 智能体",
         ["选父节点与区域", "REWRITE：改结构（CIC+补偿、交织、融合）", "TUNE：调位宽 / 截位 / 系数 / 复用",
          "声明变换类别 equiv / math / approx"], VIOLET, VIOLET_T)
    card(ax, 10.3, yb, 4.6, 1.75, "候选档案",
         ["节点状态：BROKEN / OPEN / FEASIBLE", "可行前沿：（面积，质量松弛）",
          "近可行前沿：（缺口，面积）", "调度提示 · 预算强制"], VIOLET, VIOLET_T)
    arrow(ax, (8.0, yb), (6.65, yb), color=VIOLET, lw=1.5)
    label(ax, 7.32, yb + 0.25, "报告 + 提示", VIOLET, fs=8.5, ha="center")

    # agent → 新候选
    arrow(ax, (4.45, yb + 0.875), (4.45, yt - 0.875), color=VIOLET, lw=1.6)
    label(ax, 4.55, 3.38, "新候选", VIOLET, fs=9)

    # 三条反馈
    arrow(ax, (8.85, yt - 0.875), (8.85, yb + 0.875), color=RED, lw=1.4)
    label(ax, 8.95, 3.38, "BROKEN：错误位置", RED, fs=8)
    arrow(ax, (10.55, yt - 0.675), (10.55, yb + 0.875), color=RED, lw=1.4)
    label(ax, 10.65, 3.38, "未达标：约束表 + 缺口，保留为 OPEN", RED, fs=8)
    arrow(ax, (12.65, yt - 0.875), (12.3, yb + 0.875), color=INK2, lw=1.4)
    label(ax, 12.62, 2.85, "面积·时序·功耗·Δ", INK2, fs=8)

    # 档案 → 终验
    ax.plot([12.6, 14.95], [yb, yb], color=AQUA, lw=1.6, zorder=1)
    arrow(ax, (14.95, yb), (14.95, yt - 0.875), color=AQUA, lw=1.6)
    label(ax, 14.25, yb + 0.25, "申请终验", AQUA, fs=8.5, ha="center")
    label(ax, 15.05, 2.75, "隐藏集只回\n通过 / 未通过", INK2, fs=7.5)

    save(fig, "fig_flow_v4")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_flow()
