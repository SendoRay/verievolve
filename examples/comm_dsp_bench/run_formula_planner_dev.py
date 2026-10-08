#!/usr/bin/env python3
"""Run one development-only Formula Request → LLM → typed IR pass.

The output is diagnostic and must not be cited as a formal comparison. No
held-out task is read, and every LLM response is retained in the transcript.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BENCH))

from openevolve.config import LLMModelConfig
from openevolve.llm.ensemble import LLMEnsemble
from search_ir import ddc_formula_request, lower_ddc_rtl, run_llm_planning_loop


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["claude_code", "openai"],
                        default="claude_code")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-budget-usd", type=float, default=0.25)
    parser.add_argument("--run-id", default=None)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    api_key = None
    if args.provider == "openai":
        api_key = os.environ.get(args.api_key_env)
        key_file = BENCH / ".api_key_deepseek"
        if not api_key and args.api_key_env == "DEEPSEEK_API_KEY" and key_file.exists():
            api_key = key_file.read_text(encoding="utf-8").strip()
        if not api_key:
            raise SystemExit(
                f"missing {args.api_key_env} and local {key_file.relative_to(ROOT)}"
            )
        if not args.api_base:
            raise SystemExit("--api-base is required for provider=openai")

    model = LLMModelConfig(
        name=args.model,
        provider=args.provider,
        api_base=args.api_base,
        api_key=api_key,
        temperature=0.2,
        max_tokens=4096,
        timeout=args.timeout,
        retries=0,
        max_budget_usd=args.max_budget_usd,
    )
    llm = LLMEnsemble([model])
    formula = ddc_formula_request()
    result = asyncio.run(
        run_llm_planning_loop(formula, llm, max_attempts=args.attempts)
    )

    run_id = args.run_id or datetime.now(timezone.utc).strftime("dev-%Y%m%dT%H%M%SZ")
    output = BENCH / "experiments_system" / "formula_to_rtl_dev" / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "development_only",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "max_attempts": args.attempts,
        "formula_request": formula,
        "result": result,
    }
    (output / "result.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if result["status"] == "success":
        candidate = result["compile_result"]["candidate"]
        (output / "candidate.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output / "design.v").write_text(lower_ddc_rtl(candidate), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "attempt_count": result["attempt_count"],
        "output": str(output.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
