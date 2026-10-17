"""图：通用通信基带的数值处理链路（论文 fig:chain）。

发射在上、接收在下，都从左到右。模块按算子类别着色；接收端在混频处分成 I/Q 两路，抽取后汇合；
同步之后分成 OFDM 与 CDMA 两条互为替代的支路（不同标准），再汇合到软解调。
图下方的括号标出基准中各条链路（表 8 的 A–H）覆盖的范围。
"""
from matplotlib.patches import FancyBboxPatch
from style import (AQUA, AQUA_T, BLUE, BLUE_T, GRAY, GRAY_T, INK, INK2, ORANGE, ORANGE_T, VIOLET, VIOLET_T,
                   YELLOW, YELLOW_T, canvas, save, use_diagram_style)

# ===== 数据（可直接修改） =====
# 算子类别：名称 -> (描边色, 浅底色)
CATS = {
    "osc": ("数控振荡与混频", BLUE, BLUE_T),
    "filt": ("滤波与变速率", ORANGE, ORANGE_T),
    "xform": ("变换（FFT / IFFT）", YELLOW, YELLOW_T),
    "sync": ("相关与同步", VIOLET, VIOLET_T),
    "est": ("估计、均衡与合并", AQUA, AQUA_T),
    "map": ("映射与解调", "#c2417a", "#f8dfe9"),
    "io": (None, GRAY, GRAY_T),
}
# 发射行：(文字, 类别)，等间距从左到右
TX = [("比特", "io"), ("调制映射", "map"), ("IFFT", "xform"), ("加 CP\n/ 加窗", "filt"), ("成形滤波", "filt"),
      ("多级内插", "filt"), ("NCO\n上变频", "osc"), ("DAC", "io")]
# 发射行括号：(起始列, 结束列, 标签)，列号为 TX 的下标
TX_BRACKETS = [(1, 3, "C  OFDM 发射"), (4, 6, "B  发射 DUC")]
# 接收行：列 -> 模块。I/Q 两路与两条支路各占同一列的上下两个位置
RX_SINGLE = {0: ("ADC", "io"), 1: ("NCO", "osc"), 4: ("分数倍\n重采样", "filt"), 5: ("同步\n频偏估计", "sync"),
             6: ("相位旋转", "osc"), 9: ("软解调", "map"), 10: ("LLR", "io")}
RX_SPLIT = {2: (("混频 I", "osc"), ("混频 Q", "osc")), 3: (("抽取\n滤波 I", "filt"), ("抽取\n滤波 Q", "filt")),
            7: (("FFT", "xform"), ("解扰解扩", "sync")), 8: (("信道估计\n与均衡", "est"), ("Rake\n合并", "est"))}
BRANCH_NOTE = ("OFDM", "CDMA")  # 两条支路的小字标注
# 接收行括号：(起始列, 结束列, 标签, 位置 "below" 或 "above"，"above" 只用于上支路)
RX_BRACKETS = [(1, 3, "A  接收 DDC / F  多相信道化", "below"), (4, 4, "H  重采样", "below"),
               (5, 6, "E  同步前端", "below"), (7, 8, "G  Rake 支路", "below"), (7, 9, "D  OFDM 接收内环", "above")]
# ==============================

use_diagram_style()
W_IN, H_IN = 10.6, 4.6
fig, ax = canvas(W_IN, H_IN)
FS = 11            # 缩放到 \textwidth（约 6.3 英寸）后约 6.5–7 pt 以上
BW, BH = 0.80, 0.50
RW = 0.70            # 接收行方框更窄，留出箭头间距
X0, X1 = 0.55, W_IN - 0.45
Y_TX, Y_RX, DY = 3.85, 1.75, 0.37   # DY：I/Q 与两条支路相对接收行中线的上下偏移
LINE = "#9a9994"


def node(x, y, text, cat, w=BW):
    _, ec, fc = CATS[cat]
    ax.add_patch(FancyBboxPatch((x - w / 2, y - BH / 2), w, BH, boxstyle="round,pad=0,rounding_size=0.07",
                                ec=ec, fc=fc, lw=1.1, zorder=2))
    lines = text.count("\n") + 1
    ax.text(x, y, text, ha="center", va="center", fontsize=FS - (1.5 if lines > 1 else 0), color=INK,
            zorder=3, linespacing=1.05)


def link(p, q):
    ax.annotate("", xy=q, xytext=p, arrowprops=dict(arrowstyle="-|>", color=LINE, lw=0.9, mutation_scale=8,
                                                    shrinkA=0, shrinkB=0), zorder=1)


def bracket(xa, xb, y, label, up=False):
    s = 1 if up else -1
    ax.plot([xa, xa, xb, xb], [y - s * 0.07, y, y, y - s * 0.07], color=INK2, lw=0.8)
    ax.text((xa + xb) / 2, y + s * 0.17, label, ha="center", va="center", fontsize=FS - 1, color=INK2)


# ---- 发射行
xt = [X0 + BW / 2 + i * (X1 - X0 - BW) / (len(TX) - 1) for i in range(len(TX))]
for i, (t, c) in enumerate(TX):
    node(xt[i], Y_TX, t, c)
    if i:
        link((xt[i - 1] + BW / 2, Y_TX), (xt[i] - BW / 2, Y_TX))
for a, b, lab in TX_BRACKETS:
    bracket(xt[a] - BW / 2, xt[b] + BW / 2, Y_TX - BH / 2 - 0.16, lab)
ax.text(X0 - 0.12, Y_TX, "发射", ha="right", va="center", fontsize=FS, color=INK2, rotation=90)

# ---- 接收行
ncol = 11
xr = [X0 + RW / 2 + i * (X1 - X0 - RW) / (ncol - 1) for i in range(ncol)]
for i, (t, c) in RX_SINGLE.items():
    node(xr[i], Y_RX, t, c, RW)
for i, ((t1, c1), (t2, c2)) in RX_SPLIT.items():
    node(xr[i], Y_RX + DY, t1, c1, RW)
    node(xr[i], Y_RX - DY, t2, c2, RW)
ax.text(X0 - 0.12, Y_RX, "接收", ha="right", va="center", fontsize=FS, color=INK2, rotation=90)


def right(i, y):
    return (xr[i] + RW / 2, y)


def left(i, y):
    return (xr[i] - RW / 2, y)


link(right(0, Y_RX), left(1, Y_RX))
for dy in (DY, -DY):
    link(right(1, Y_RX), left(2, Y_RX + dy))      # NCO 分成 I/Q
    link(right(2, Y_RX + dy), left(3, Y_RX + dy))
    link(right(3, Y_RX + dy), left(4, Y_RX))      # 抽取后汇合
    link(right(6, Y_RX), left(7, Y_RX + dy))      # 分成 OFDM / CDMA 两支
    link(right(7, Y_RX + dy), left(8, Y_RX + dy))
    link(right(8, Y_RX + dy), left(9, Y_RX))      # 汇合到软解调
link(right(4, Y_RX), left(5, Y_RX))
link(right(5, Y_RX), left(6, Y_RX))
link(right(9, Y_RX), left(10, Y_RX))
xm = (xr[7] + xr[8]) / 2
ax.text(xm, Y_RX, "或", ha="center", va="center", fontsize=FS - 1.5, color=INK2)
ax.text(xr[7] - RW / 2, Y_RX + DY + BH / 2 + 0.1, BRANCH_NOTE[0], ha="left", va="center", fontsize=FS - 2.5,
        color=INK2, style="italic")
ax.text(xr[7] - RW / 2, Y_RX - DY - BH / 2 - 0.1, BRANCH_NOTE[1], ha="left", va="center", fontsize=FS - 2.5,
        color=INK2, style="italic")

y_low = Y_RX - DY - BH / 2 - 0.3
y_high = Y_RX + DY + BH / 2 + 0.3
for a, b, lab, pos in RX_BRACKETS:
    xa, xb = xr[a] - RW / 2, xr[b] + RW / 2
    if pos == "above":
        bracket(xa, xb, y_high, lab, up=True)
    else:
        bracket(xa, xb, y_low, lab)

# ---- 图例
items = [v for k, v in CATS.items() if v[0]]
ly = 0.22
widths = [0.36 + 0.14 * sum(0.55 if ord(ch) < 128 else 1 for ch in name) + 0.35 for name, _, _ in items]   # 按文字长度排布，整体居中
x = (X0 + X1 - sum(widths)) / 2
for (name, ec, fc), wd in zip(items, widths):
    ax.add_patch(FancyBboxPatch((x, ly - 0.09), 0.28, 0.18, boxstyle="round,pad=0,rounding_size=0.04",
                                ec=ec, fc=fc, lw=1.0))
    ax.text(x + 0.36, ly, name, ha="left", va="center", fontsize=FS - 1.5, color=INK2)
    x += wd

save(fig, "fig1_comm_chain")
