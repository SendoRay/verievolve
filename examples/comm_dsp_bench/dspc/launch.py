"""实现环的编排：为 FEASIBLE 设计节点启动 Lowering Agent（无头模式），结束后把 top.v 登记为实现子节点。

python -m dspc.launch <设计工作区> <dNNN> [--k 0] [--agent claude|codex] [--timeout 3600]

注意：会调用本机的 claude / codex CLI，消耗对应账户的额度。实验运行前应冻结模型版本与提示词（FRAMEWORK_v5 §7.6）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from .archive import add_impl
from .workspace import make_lower_ws

CLAUDE_TOOLS = "Read,Write,Edit,Glob,Grep,Bash(./ve:*),Bash(python3:*),Bash(iverilog:*),Bash(vvp:*),Bash(ls:*)"


def launch(design_ws: Path, cid: str, k: int = 0, agent: str = "claude", timeout: int = 3600,
           model: str | None = None) -> dict:
    ws = make_lower_ws(design_ws, cid, k)
    prompt = (ws / "PROMPT.md").read_text()
    if agent == "claude":
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits",
               "--allowedTools", CLAUDE_TOOLS] + (["--model", model] if model else [])
    elif agent == "codex":
        cmd = ["codex", "exec", "-s", "workspace-write", "-C", str(ws), prompt] + (["-m", model] if model else [])
    else:
        raise ValueError("agent in {claude, codex}")
    t0 = time.time()
    try:
        pr = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout)
        status = "exit" if pr.returncode == 0 else f"error {pr.returncode}"
        (ws / "agent_stdout.txt").write_text(pr.stdout[-200000:])
        (ws / "agent_stderr.txt").write_text(pr.stderr[-20000:])
    except subprocess.TimeoutExpired:
        status = "timeout"
    rec = {"design": cid, "k": k, "agent": agent, "model": model, "status": status,
           "seconds": round(time.time() - t0, 1), "workspace": str(ws)}
    if (ws / "top.v").exists():
        r = add_impl(design_ws, cid, ws / "top.v", note=f"{agent} lowering #{k}")
        rec.update(impl=r.get("id"), conform=r.get("conform"), ppa=r.get("ppa"))
    with open(Path(design_ws) / "launch_log.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("design_ws", type=Path)
    ap.add_argument("cid")
    ap.add_argument("--k", type=int, default=0)
    ap.add_argument("--agent", default="claude")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--model")
    a = ap.parse_args(argv)
    print(json.dumps(launch(a.design_ws, a.cid, a.k, a.agent, a.timeout, a.model), ensure_ascii=False, indent=1,
                     default=str))


if __name__ == "__main__":
    main()
