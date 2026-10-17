"""所有图共用的配色、字体与保存函数。

配色按角色固定：本方法 / 对照基线 / 参考 / 直写起点。改这里会同时改所有图。
"""

import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

try:
    from .font_config import SIMPLIFIED_CHINESE_FONTS, register_simplified_chinese_fonts
except ImportError:
    from font_config import SIMPLIFIED_CHINESE_FONTS, register_simplified_chinese_fonts

FIG_DIR = Path(__file__).resolve().parent.parent  # thesis/midterm/figures
THESIS_IMG = Path("/Users/chengzhy/ucasproposal-master/Img")  # LaTeX 引用的目录，文件名加 mid_ 前缀

# 数据图角色色
C_OURS, C_BASE, C_REF, C_NAIVE = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
C_EXTRA = ["#eda100", "#e87ba4"]
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

# 示意图：描边色与浅底色
BLUE, BLUE_T = "#2a78d6", "#dbe8f8"
ORANGE, ORANGE_T = "#eb6834", "#fbe1d6"
AQUA, AQUA_T = "#1baf7a", "#d5f0e5"
YELLOW, YELLOW_T = "#c98500", "#fbeccb"
VIOLET, VIOLET_T = "#4a3aa7", "#e3e0f4"
GRAY, GRAY_T = "#8a8984", "#efeeeb"
WHITE = "#ffffff"

register_simplified_chinese_fonts()
FONTS = SIMPLIFIED_CHINESE_FONTS

SPECS = ["R16 窄带", "R16 宽带", "R32 窄带", "R32 宽带", "R64 窄带", "R64 宽带"]


def use_data_style():
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": FONTS,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "mathtext.fontset": "dejavusans",
            "font.size": 10,
            "axes.edgecolor": INK2,
            "axes.labelcolor": INK,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "axes.axisbelow": True,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "legend.frameon": False,
        }
    )


def use_diagram_style():
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": FONTS,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "mathtext.fontset": "dejavusans",
            "figure.facecolor": WHITE,
            "savefig.facecolor": WHITE,
        }
    )


def save(fig, name, pad=0.08):
    """写 figures/<name>.png/.pdf，并复制 pdf 到论文 Img/mid_<name>.pdf。"""
    png, pdf = FIG_DIR / f"{name}.png", FIG_DIR / f"{name}.pdf"
    fig.savefig(png, dpi=220, bbox_inches="tight", pad_inches=pad)
    fig.savefig(pdf, bbox_inches="tight", pad_inches=pad)
    plt.close(fig)
    if THESIS_IMG.is_dir():
        shutil.copy(pdf, THESIS_IMG / f"mid_{name}.pdf")
    print("wrote", name)


# ---------- 示意图用的小工具 ----------


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    fig.subplots_adjust(0, 0, 1, 1)
    return fig, ax


def box(ax, x, y, w, h, text, ec=GRAY, fc=GRAY_T, fs=9.5, sub=None, dashed=False, lw=1.4, bold=False, color=INK):
    """以 (x, y) 为中心的圆角方框。"""
    ax.add_patch(
        FancyBboxPatch(
            (x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0,rounding_size=0.08",
            ec=ec, fc=fc, lw=lw, ls="--" if dashed else "-", zorder=2,
        )
    )
    weight = "bold" if bold else None
    if sub:
        ax.text(x, y + 0.11, text, ha="center", va="center", fontsize=fs, color=color, zorder=3, fontweight=weight)
        ax.text(x, y - 0.14, sub, ha="center", va="center", fontsize=fs - 2, color=INK2, zorder=3)
    else:
        ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=color, zorder=3, fontweight=weight, linespacing=1.3)


def arrow(ax, p, q, color=INK2, lw=1.3, dashed=False, rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            p, q, arrowstyle="-|>", mutation_scale=11, color=color, lw=lw, ls="--" if dashed else "-",
            connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0, zorder=1,
        )
    )
