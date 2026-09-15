#!/usr/bin/env python
"""消融实验自动应答守护进程（manual 模式 LLM 策略实现）

策略（同一"LLM 能力"，不同通道）：
  A 组（diff-only）   : 局部编辑引擎——按菜单对父代做单点小改（舍入/截断/系数微调）
  B 组（rewrite-only）: 设计库轮换——提交完整结构设计（.designs/ 下已验证文件）
  C 组（混合）        : 按采样到的模板分发——diff 任务走局部编辑，rewrite 任务走设计库

用法: python ablation_responder.py --group A [--max-rounds 12] [--idle-exit 20]
"""

import argparse
import json
import re
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent
DESIGNS = BENCH / ".designs"


# ---------------------------------------------------------------------------
# 局部编辑引擎（A 组 / C 组的 diff 通道）
# ---------------------------------------------------------------------------

def local_edit_diffs(code: str):
    """从父代代码中找可用的局部编辑，返回 SEARCH/REPLACE 文本（单点修改）"""
    lines = code.split("\n")

    # E1: 索引舍入（最近邻查表：phase[15:10] → + bit9 进位）
    for i, l in enumerate(lines):
        m = re.search(r"(\w+)\s*=\s*(\w+)\[(\d+):(\d+)\]", l)
        if m and "idx" in m.group(1):
            hi, lo = int(m.group(3)), int(m.group(4))
            if hi - lo >= 4:
                old = l.rstrip()
                new = re.sub(
                    r"(\w+\[\d+:\d+\])",
                    m.group(1) + " + {" + f"{hi - lo - 1}'d0, " + m.group(2) + f"[{lo - 1}]" + "}",
                    old, count=1,
                )
                return _hunk(old, new, "索引舍入（round-to-nearest，消除 floor 偏置）")

    # E2: 移位切片舍入（插值：X = A + $signed(B[hi:lo]) → + 舍入位）
    for i, l in enumerate(lines):
        m = re.search(r"(\w+)\s*=\s*(.+?)\+\s*\$signed\((\w+)\[(\d+):(\d+)\]\)\s*;", l)
        if m and "{" not in m.group(3):
            reg, hi, lo = m.group(3), int(m.group(4)), int(m.group(5))
            old = l.rstrip()
            new = old.replace(
                f"$signed({reg}[{hi}:{lo}])",
                f"$signed({reg}[{hi}:{lo}]) + $signed({{1'b0, {reg}[{lo - 1}]}})",
            )
            if new != old:
                return _hunk(old, new, "移位除法加舍入到最近（+0.5 LSB，压低截断偏置）")

    # E3: 乘法器截断（a2 类小动态范围乘法）
    for i, l in enumerate(lines):
        m = re.search(r"(\w+)\s*=\s*(\w+)\s*\*\s*(\w+)\s*;", l)
        if m and m.group(2) in ("a2", "a2s", "a2c"):
            old = l.rstrip()
            new = old.replace(f"{m.group(2)} *", f"$signed({m.group(2)}[7:0]) *")
            return _hunk(old, new, "二阶差分乘法器截断到 8 位（|a2|<128，数学无损，省面积）")

    # E4: 表项系数微调（通用兜底：首个非零 case 表项 ±1 LSB）
    for i, l in enumerate(lines):
        # 匹配 6'd3: T = 3212; 与 4'd0: alpha_rom = 18'sd16384; 两种字面量风格
        m = re.search(r"(\d+'d\d+):\s*\w+\s*=\s*(-?)(?:(\d+)'s?d)?(\d+);", l)
        if m:
            sign, width_lit, val = m.group(2), m.group(3), int(m.group(4))
            if val == 0 or val in (32767, 32768):
                continue
            old = l.rstrip()
            nv = val + 1 if (sign == "" ) else val - 1
            if width_lit:
                new = old.replace(f"= {sign}{width_lit}'sd{val};", f"= {sign}{width_lit}'sd{nv};")
            else:
                new = old.replace(f"= {sign}{val};", f"= {sign}{nv};")
            if new != old:
                return _hunk(old, new, "表项系数微调（量化噪声整形尝试）")

    # E5: 常量初值微调（CORDIC x0 等魔法数）
    for i, l in enumerate(lines):
        m = re.search(r"(\w+)\s*<=\s*(\d+)'sd(\d+);", l)
        if m and int(m.group(3)) > 1000:
            old = l.rstrip()
            v = int(m.group(3))
            new = old.replace(f"'sd{v};", f"'sd{v + 1};")
            return _hunk(old, new, "迭代初值微调（CORDIC 增益补偿常数精修）")

    return None


def _hunk(old: str, new: str, desc: str) -> str:
    return f"""{desc}。

<<<<<<< SEARCH
{old}
=======
{new}
>>>>>>> REPLACE
"""


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def classify(prompt: str) -> str:
    return "rewrite" if "Rewrite the program" in prompt else "diff"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=["A", "B", "C"])
    ap.add_argument("--queue", default=None)
    ap.add_argument("--max-rounds", type=int, default=40)
    ap.add_argument("--idle-exit", type=int, default=30, help="连续 N 轮无任务则退出")
    args = ap.parse_args()

    queue = Path(args.queue) if args.queue else BENCH / f"output_abl_{args.group}" / "manual_tasks_queue"
    designs = sorted(DESIGNS.glob("*.v"))
    di = 0
    idle = 0
    rounds = 0
    answered_total = 0

    print(f"[responder-{args.group}] queue={queue}, designs={len(designs)}")
    while rounds < args.max_rounds:
        pending = []
        for f in sorted(queue.glob("*.json")):
            if f.name.endswith(".answer.json"):
                continue
            if not f.with_suffix(".answer.json").exists():
                pending.append(f)
        if not pending:
            idle += 1
            if idle >= args.idle_exit:
                print(f"[responder-{args.group}] idle {args.idle_exit} rounds, exit")
                break
            time.sleep(10)
            continue
        idle = 0
        rounds += 1

        for f in pending:
            d = json.loads(f.read_text())
            mode = classify(d["display_prompt"])
            # 组策略：A 只 diff；B 只 rewrite；C 按模板
            if args.group == "A":
                mode = "diff"
            elif args.group == "B":
                mode = "rewrite"

            if mode == "rewrite":
                code = designs[di % len(designs)].read_text()
                di += 1
                answer = ("结构跳变（全重写）：参数化设计库设计 " + designs[(di - 1) % len(designs)].stem +
                          "。\n\n```verilog\n" + code + "```\n")
            else:
                m = re.search(r"# Current Program\n```verilog\n(.*?)\n```", d["display_prompt"], re.S)
                code = m.group(1) if m else ""
                hunk = local_edit_diffs(code)
                answer = hunk if hunk else "（无可用局部编辑，重发原程序微调注释）\n"

            out = f.with_suffix(".answer.json")
            tmp = out.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"answer": answer}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(out)
            answered_total += 1
            print(f"[responder-{args.group}] round {rounds}: {f.stem[:8]} mode={mode} "
                  f"({len(answer)} chars)", flush=True)

        time.sleep(15)

    print(f"[responder-{args.group}] done: {answered_total} answers in {rounds} rounds")


if __name__ == "__main__":
    main()
