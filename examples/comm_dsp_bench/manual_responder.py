#!/usr/bin/env python
"""manual 模式自动应答助手：把指定设计投给所有待答任务"""
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
QUEUE = BENCH / "output_cordic_jump" / "manual_tasks_queue"

def make_answer(desc: str, code_path: str) -> str:
    code = (BENCH / code_path).read_text()
    return desc + "\n\n```verilog\n" + code + "```\n"

desc = sys.argv[2] if len(sys.argv) > 2 else "重提交当前最优设计（填充 MAP-Elites 格）。"
answer = make_answer(desc, sys.argv[1])

n = 0
for f in sorted(QUEUE.glob("*.json")):
    if f.name.endswith(".answer.json"):
        continue
    out = f.with_suffix(".answer.json")
    if out.exists():
        continue
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"answer": answer}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)
    print(f"answered: {f.stem[:8]}")
    n += 1
print(f"total answered: {n}")
