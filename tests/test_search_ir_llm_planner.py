import asyncio
import copy
import json
import sys
from pathlib import Path


BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.architecture_plan import architecture_plan
from search_ir.formula_contract import ddc_formula_request
from search_ir.llm_planner import extract_json_payload, run_llm_planning_loop


def _plan(formula, depth):
    return architecture_plan(
        formula,
        nco={
            "strategy": "lut",
            "depth": depth,
            "interpolation": "linear",
            "phase_bits": 12,
        },
        filter_decimator={
            "strategy": "polyphase",
            "coefficient_bits": 14,
            "product_drop": 1,
            "accumulator_bits": 28,
            "rounding": "nearest_ties_to_pos_inf",
        },
    )


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_with_context(self, system_message, messages, **kwargs):
        self.calls.append(copy.deepcopy({
            "system_message": system_message,
            "messages": messages,
        }))
        return self.responses.pop(0)


def test_real_adapter_counts_rejection_and_supplies_feedback_on_next_call():
    formula = ddc_formula_request()
    llm = ScriptedLLM([
        json.dumps(_plan(formula, 63)),
        "```json\n" + json.dumps(_plan(formula, 256)) + "\n```",
    ])
    result = asyncio.run(run_llm_planning_loop(formula, llm, max_attempts=3))
    assert result["status"] == "success"
    assert result["attempt_count"] == 2
    assert result["failed_attempts"] == 1
    second_prompt = llm.calls[1]["messages"][0]["content"]
    assert "$plan.nco.depth" in second_prompt
    assert '"attempt": 2' in second_prompt


def test_surrounding_prose_is_rejected_and_retained():
    formula = ddc_formula_request()
    llm = ScriptedLLM(["Here is the plan: " + json.dumps(_plan(formula, 256))])
    result = asyncio.run(run_llm_planning_loop(formula, llm, max_attempts=1))
    assert result["status"] == "exhausted"
    row = result["transcript"][0]
    assert row["raw_response"].startswith("Here is")
    assert row["result"]["error"]["code"] == "llm_response_error"


def test_json_extractor_allows_only_exact_object_or_one_fence():
    assert extract_json_payload('{"x": 1}') == '{"x": 1}'
    assert extract_json_payload('```json\n{"x": 1}\n```') == '{"x": 1}'


def test_real_adapter_continues_after_measured_candidate_rejection():
    formula = ddc_formula_request()
    llm = ScriptedLLM([
        json.dumps(_plan(formula, 256)),
        json.dumps(_plan(formula, 512)),
    ])

    async def evaluator(candidate, request):
        del request
        if candidate["nco"]["depth"] == 256:
            return {
                "status": "rejected",
                "measurements": {"Q_dev": 3e-4},
                "feedback": {"reason": "quality_limit"},
            }
        return {"status": "accepted", "measurements": {"Q_dev": 4e-6}}

    result = asyncio.run(
        run_llm_planning_loop(
            formula, llm, max_attempts=3, candidate_evaluator=evaluator
        )
    )
    assert result["status"] == "success"
    assert result["attempt_count"] == 2
    assert result["evaluation_result"]["status"] == "accepted"
    second_prompt = llm.calls[1]["messages"][0]["content"]
    assert "candidate_not_accepted" in second_prompt
    assert "quality_limit" in second_prompt


def test_real_adapter_resumes_after_committed_rejection_without_recalling_it():
    formula = ddc_formula_request()
    recorded = []
    first_llm = ScriptedLLM([json.dumps(_plan(formula, 256))])
    first = asyncio.run(
        run_llm_planning_loop(
            formula,
            first_llm,
            max_attempts=1,
            candidate_evaluator=lambda *_: {
                "status": "rejected",
                "measurements": {"Q_dev": 3e-4},
                "feedback": {"reason": "quality_limit"},
            },
            attempt_recorder=recorded.append,
        )
    )
    assert first["status"] == "exhausted" and len(recorded) == 1

    second_llm = ScriptedLLM([json.dumps(_plan(formula, 512))])
    resumed = asyncio.run(
        run_llm_planning_loop(
            formula,
            second_llm,
            max_attempts=3,
            candidate_evaluator=lambda *_: {
                "status": "accepted", "measurements": {"Q_dev": 1e-6}
            },
            resume_transcript=recorded,
        )
    )
    assert resumed["status"] == "success" and resumed["attempt_count"] == 2
    assert len(first_llm.calls) == len(second_llm.calls) == 1
    prompt = second_llm.calls[0]["messages"][0]["content"]
    assert '"attempt": 2' in prompt and "quality_limit" in prompt
