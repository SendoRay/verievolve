"""Verilog 生成小工具：与 fixed.py 的整数语义逐位一致。

所有积木模块使用统一端口：
  clk, rst, in_valid, in_i[, in_q], out_valid, out_i, out_q
有效样点以 in_valid 脉冲到达；时钟频率等于链输入采样率。
"""

from __future__ import annotations


def sv(width: int) -> str:
    return f"signed [{width - 1}:0]"


def header(module: str, w_in: int, w_out: int, complex_in: bool) -> list[str]:
    ports = ["input wire clk", "input wire rst", "input wire in_valid",
             f"input wire {sv(w_in)} in_i"]
    if complex_in:
        ports.append(f"input wire {sv(w_in)} in_q")
    ports += ["output reg out_valid", f"output reg {sv(w_out)} out_i",
              f"output reg {sv(w_out)} out_q"]
    return [f"module {module} ("] + ["    " + p + ("," if k < len(ports) - 1 else "")
                                      for k, p in enumerate(ports)] + [");"]


def maxpat(w: int) -> str:
    return f"{w}'b0{'1' * (w - 1)}"


def minpat(w: int) -> str:
    return f"{w}'b1{'0' * (w - 1)}"


def sconst(value: int, w: int) -> str:
    """w 位有符号常数（以二进制补码字面量给出，避免符号/位宽歧义）。"""
    return f"$signed({w}'b{value & ((1 << w) - 1):0{w}b})"


def rnd_sat(src: str, w_src: int, s: int, mode: str, w_out: int, dst: str, tag: str) -> list[str]:
    """dst（wire, w_out 位）= sat(rnd(src >>> s))。src 为 w_src 位有符号。"""
    lines = []
    if s > 0:
        if mode == "round":
            lines.append(f"wire {sv(w_src + 1)} {tag}_rb = $signed({{{src}[{w_src - 1}], {src}}}) + "
                         f"{sconst(1 << (s - 1), w_src + 1)};")
            w_sh = w_src + 1 - s
            lines.append(f"wire {sv(w_sh)} {tag}_sh = {tag}_rb[{w_src}:{s}];")
        else:
            w_sh = w_src - s
            lines.append(f"wire {sv(w_sh)} {tag}_sh = {src}[{w_src - 1}:{s}];")
    elif s == 0:
        w_sh = w_src
        lines.append(f"wire {sv(w_sh)} {tag}_sh = {src};")
    else:
        w_sh = w_src - s
        lines.append(f"wire {sv(w_sh)} {tag}_sh = {{{src}, {-s}'b0}};")
    if w_sh <= w_out:
        if w_out > w_sh:
            lines.append(f"wire {sv(w_out)} {dst} = {{{{{w_out - w_sh}{{{tag}_sh[{w_sh - 1}]}}}}, {tag}_sh}};")
        else:
            lines.append(f"wire {sv(w_out)} {dst} = {tag}_sh;")
    else:
        mx = (1 << (w_out - 1)) - 1
        lines.append(
            f"wire {sv(w_out)} {dst} = ({tag}_sh > {sconst(mx, w_sh)}) ? {maxpat(w_out)} : "
            f"({tag}_sh < {sconst(-mx - 1, w_sh)}) ? {minpat(w_out)} : {tag}_sh[{w_out - 1}:0];")
    return lines


def neg_sat(src: str, w: int, dst: str) -> list[str]:
    """dst = sat(-src, w)。"""
    return [f"wire {sv(w)} {dst} = ({src} == {minpat(w)}) ? {maxpat(w)} : -{src};"]


def csd_digits(v: int) -> list[tuple[int, int]]:
    """整数 v 的规范符号数字表示：[(位移, ±1), ...]。"""
    out, k = [], 0
    while v:
        if v & 1:
            d = 2 - (v & 3)          # v mod 4 == 1 → +1；== 3 → -1
            out.append((k, d))
            v -= d
        v >>= 1
        k += 1
    return out


def const_mult(src: str, w_src: int, v: int, w_dst: int, dst: str) -> list[str]:
    """dst = src * v，用 CSD 移位加实现（结果截到 w_dst 位，调用方保证不溢出）。"""
    digits = csd_digits(v)
    if not digits:
        return [f"wire {sv(w_dst)} {dst} = {w_dst}'sd0;"]
    ext = f"$signed({{{{{w_dst - w_src}{{{src}[{w_src - 1}]}}}}, {src}}})" if w_dst > w_src else src
    terms = []
    for k, d in digits:
        t = f"({ext} <<< {k})" if k else ext
        terms.append(("+ " if d > 0 else "- ") + t)
    expr = " ".join(terms)
    if expr.startswith("+ "):
        expr = expr[2:]
    else:
        expr = f"{w_dst}'sd0 " + expr
    return [f"wire {sv(w_dst)} {dst} = {expr};"]
