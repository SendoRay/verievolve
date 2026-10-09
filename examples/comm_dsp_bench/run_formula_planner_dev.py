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
from search_ir import (
    DevelopmentSynthesisEvaluator,
    PlanningRunArchive,
    ddc_formula_request,
    evaluate_with_optional_synthesis,
    run_llm_planning_loop,
)
from search_ir import synthesize as synth
from search_ir.dev_fixtures import (
    development_candidate_evaluator,
    development_evaluation_contract,
)


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
    parser.add_argument(
        "--synthesize", action="store_true",
        help="map a quality-accepted candidate with the frozen Nangate45 flow",
    )
    parser.add_argument("--synthesis-timeout", type=int, default=600)
    parser.add_argument("--max-syntheses", type=int, default=1)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--resume", action="store_true",
        help="continue a nonterminal run from its last fully committed attempt",
    )
    parser.add_argument(
        "--plan-only", action="store_true",
        help="stop after schema/lowering checks instead of using measured development feedback",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.resume and not args.run_id:
        raise SystemExit("--resume requires --run-id")
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
    synthesis_contract = None
    if args.synthesize:
        if args.plan_only:
            raise SystemExit("--synthesize cannot be combined with --plan-only")
        if args.synthesis_timeout < 1 or args.max_syntheses < 1:
            raise SystemExit("synthesis timeout and budget must be positive")
        synthesis_contract = synth.build_contract()
        synthesis_contract.update({
            "scope": "development formula-planner candidate; full-DDC mapped cell area",
            "cache_enabled": True,
            "resume_enabled": True,
            "timeout_seconds": args.synthesis_timeout,
        })
    run_id = args.run_id or datetime.now(timezone.utc).strftime("dev-%Y%m%dT%H%M%SZ")
    output_root = BENCH / "experiments_system" / "formula_to_rtl_dev"
    metadata = {
        "provider": args.provider,
        "model": args.model,
        "planning_mode": "plan_only" if args.plan_only else "measured_quality_feedback",
        "timeout_seconds": args.timeout,
        "max_budget_usd": args.max_budget_usd,
        "synthesis_enabled": args.synthesize,
    }
    archive = PlanningRunArchive(
        output_root,
        run_id,
        formula,
        max_attempts=args.attempts,
        evaluation_contract=(
            None if args.plan_only else development_evaluation_contract()
        ),
        synthesis_contract=synthesis_contract,
        max_synthesis_evaluations=args.max_syntheses if args.synthesize else 0,
        run_metadata=metadata,
        resume=args.resume,
    )
    synthesis_evaluator = None
    if synthesis_contract is not None:
        synthesis_evaluator = (
            DevelopmentSynthesisEvaluator.resume(archive.path, synthesis_contract)
            if args.resume
            else DevelopmentSynthesisEvaluator(archive.path, synthesis_contract)
        )
    evaluator = None
    if not args.plan_only:
        evaluator = lambda candidate, request: evaluate_with_optional_synthesis(
            candidate,
            request,
            archive=archive,
            quality_evaluator=development_candidate_evaluator,
            synthesis_evaluator=synthesis_evaluator,
        )
    result = asyncio.run(
        run_llm_planning_loop(
            formula,
            llm,
            max_attempts=args.attempts,
            candidate_evaluator=evaluator,
            resume_transcript=archive.transcript(),
            attempt_recorder=archive.record_attempt,
        )
    )
    archive.finalize(result)
    if result["status"] == "success":
        archive.export_selected()
    print(json.dumps({
        "status": result["status"],
        "attempt_count": result["attempt_count"],
        "output": str(archive.path.relative_to(ROOT)),
    }, ensure_ascii=False))
    return {"success": 0, "inconclusive": 3}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
