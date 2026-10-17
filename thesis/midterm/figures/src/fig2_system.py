"""图：系统架构（论文 fig:system）。左：任务契约；中：LLM 智能体；右：三个方法对应的工具链与反馈回路。"""
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from style import (AQUA, AQUA_T, BLUE, BLUE_T, GRAY, INK, INK2, ORANGE, ORANGE_T, VIOLET, VIOLET_T, WHITE,
                   arrow, box, canvas, save, use_diagram_style)

# ===== 数据（可直接修改） =====
# 示意图没有数值数据；所有文字都在下面的 PANELS 和绘图代码里。
# 字号按“画布宽 10.4 英寸缩放到约 6.3 英寸的 \textwidth”设定：12.5 号缩放后约 7.6 pt。
FS_S, FS, FS_T = 12.5, 13, 14
# 三个方法：(标题, 描边色, 浅底色, 三个小框文字, 底部说明)
PANELS = [
    ("方法一  原语表示与编译器", BLUE, BLUE_T,
     ["原语程序", "带类型数据流图\n位宽·小数点\n速率域·时延", "逐位整数模型\n+ Verilog"],
     "构造错误诊断（接口 / 速率 / 结构）返回智能体"),
    ("方法二  系统级容差验证", AQUA, AQUA_T,
     ["逐位等价\nRTL ≡ 整数模型\n联合仿真对拍", "容差等价\n所有 s∈S：\nM(实现, F) ∈ T", "诊断\n溢出位置\n精度 or 结构"],
     "场景覆盖全部混叠带 · 留出复核 · 安全裕量"),
    ("方法三  双粒度智能体搜索", ORANGE, ORANGE_T,
     ["选父节点与区域\n可行 / 近可行\n数值诊断", "REWRITE\n结构重写\nTUNE\n参数调优", "根级重评\n容差 + 代价\n保留 / 分支 / 回退"],
     "完整程序只追加进候选档案 · 大小修改走同一条验收路径"),
]
FEEDBACK = "指标、裕量\n逐段面积\n关键路径\n功耗"
# ==============================

use_diagram_style()


def panel_bg(ax, x0, y0, w, h, ec, fc):
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.1",
                                ec=ec, fc=fc, lw=1.3, zorder=0))


def vline(ax, p, q, rad=0.0):
    """智能体框内的箭头（画在框底色之上）。"""
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=11, color=VIOLET, lw=1.3,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0, zorder=4))


def fig_system():
    W, H = 10.4, 6.6
    fig, ax = canvas(W, H)

    # 左：任务契约
    cx, cy, cw, ch = 0.92, 3.35, 1.66, 4.6
    box(ax, cx, cy, cw, ch, "", GRAY, WHITE)
    ax.text(cx, cy + 1.95, "任务契约", ha="center", va="center", fontsize=FS_T, color=INK, fontweight="bold")
    ax.text(cx, cy + 0.6, "公式 F\n（理想程序）\n指标 M\n允许空间 T\n接口与\n设计边界", ha="center", va="center",
            fontsize=FS, color=INK, linespacing=1.45)
    ax.plot([cx - 0.65, cx + 0.65], [cy - 0.95, cy - 0.95], color=GRAY, lw=0.8, ls="--")
    ax.text(cx, cy - 1.6, "一份规格文件\n自动生成参考、\n门槛、场景\n与直写起点", ha="center", va="center",
            fontsize=FS_S, color=INK2, linespacing=1.35)

    # 中：LLM 智能体
    ax_, ay, aw, ah = 2.82, 3.35, 1.5, 5.75
    box(ax, ax_, ay, aw, ah, "", VIOLET, VIOLET_T)
    ax.text(ax_, ay + 2.48, "LLM 智能体", ha="center", va="center", fontsize=FS_T, color=INK, fontweight="bold")
    ax.text(ax_, ay + 1.95, "编码智能体 /\n反馈驱动设计", ha="center", va="center", fontsize=FS_S, color=INK2,
            linespacing=1.3)
    steps = ["读取档案\n选择父节点", "选择粒度\n重写 / 调优", "编辑程序\n调用工具", "依据反馈\n继续或回退"]
    ys = [ay + 1.05, ay + 0.0, ay - 1.05, ay - 2.1]
    sx = ax_ + 0.13
    for s, y in zip(steps, ys):
        box(ax, sx, y, 1.08, 0.72, s, VIOLET, WHITE, fs=FS_S)
    for y0, y1 in zip(ys[:-1], ys[1:]):
        vline(ax, (sx, y0 - 0.36), (sx, y1 + 0.36))
    # 循环：依据反馈修改 → 小步修改（在智能体框内左侧）
    vline(ax, (sx - 0.54, ys[3]), (sx - 0.54, ys[1]), rad=-0.12)

    arrow(ax, (cx + cw / 2, cy), (ax_ - aw / 2, cy))

    # 右：三个方法的工具链
    px0, pw, ph, gap = 3.98, 5.02, 1.86, 0.08
    top = ay + ah / 2
    for k, (title, ec, fc, items, note) in enumerate(PANELS):
        y1 = top - k * (ph + gap)
        y0 = y1 - ph
        yc = (y0 + y1) / 2
        panel_bg(ax, px0, y0, pw, ph, ec, "#ffffff")
        ax.add_patch(FancyBboxPatch((px0, y0), pw, ph, boxstyle="round,pad=0,rounding_size=0.1",
                                    ec="none", fc=fc, alpha=0.35, zorder=0))
        ax.text(px0 + 0.14, y1 - 0.2, title, ha="left", va="center", fontsize=FS_T, color=ec, fontweight="bold")
        bw, bh = 1.5, 0.98
        bxs = [px0 + 0.86, px0 + pw / 2, px0 + pw - 0.86]
        by = yc - 0.02
        for t, bx in zip(items, bxs):
            box(ax, bx, by, bw, bh, t, ec, WHITE, fs=FS_S)
        for a, b in zip(bxs[:-1], bxs[1:]):
            arrow(ax, (a + bw / 2, by), (b - bw / 2, by), color=ec)
        ax.text(px0 + pw / 2, y0 + 0.16, note, ha="center", va="center", fontsize=FS_S, color=INK2)
        # 智能体 ⇄ 工具：上面实线调用，下面虚线反馈
        arrow(ax, (ax_ + aw / 2, yc + 0.32), (px0, yc + 0.32), color=INK2)
        arrow(ax, (px0, yc - 0.32), (ax_ + aw / 2, yc - 0.32), color=ec, dashed=True)

    # 右下：最终设计（由方法三的接受规则产出）
    y3c = top - 2 * (ph + gap) - ph / 2
    ox = 9.72
    box(ax, ox, y3c, 1.1, 1.62, "最终设计\nVerilog\n+ PPA\n+ 验证\n记录", AQUA, AQUA_T, fs=FS_S)
    arrow(ax, (px0 + pw, y3c), (ox - 0.55, y3c), color=ORANGE)

    # 右上：图例与反馈内容
    lx = 9.2
    ax.add_line(Line2D([lx, lx + 0.4], [5.9, 5.9], color=INK2, lw=1.3))
    ax.text(lx + 0.48, 5.9, "调用", va="center", fontsize=FS_S, color=INK2)
    ax.add_line(Line2D([lx, lx + 0.4], [5.45, 5.45], color=INK2, lw=1.3, ls="--"))
    ax.text(lx + 0.48, 5.45, "反馈", va="center", fontsize=FS_S, color=INK2)
    ax.text(lx, 4.95, "数值反馈：", va="center", fontsize=FS_S, color=INK, fontweight="bold")
    ax.text(lx, 3.85, FEEDBACK, va="center", fontsize=FS_S, color=INK2, linespacing=1.4)

    save(fig, "fig2_system")


fig_system()
