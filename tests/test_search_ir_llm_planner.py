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
            "rounding": "rne",
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
