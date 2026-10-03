"""公开提案层（proposal_contract）的合同测试。

覆盖：严格解析（重复键/NaN/未知字段/类型别名/越界/非法 path）、执行语义
（确定性结构默认值、动态中间树 path、结构化失败且不重采样）、GP adapter
的日志→程序→重放与 actions.propose 逐位一致（多 seed、全动作 kind），
以及程序 JSON 的规范往返稳定。不使用随机性断言：GP 对照全部用脚本化 RNG
精确到每个抽样调用。
"""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.actions import propose
from search_ir.canonicalize import candidate_hash
from search_ir.dev_fixtures import development_candidates, make_candidate
from search_ir.proposal_contract import (
    ProposalContractError,
    apply_program,
    parse_program,
    program_from_action_log,
    program_to_json,
)
from search_ir.validate import validate_candidate


class ScriptedRNG:
    """与 test_search_ir_actions 同款：逐调用核对，证明无重采样。"""

    def __init__(self, integers, randoms=()):
        self.ints = list(integers)
        self.floats = list(randoms)
        self.bit_generator = SimpleNamespace(state={"calls": 0})

    def integers(self, low, high):
        value = self.ints.pop(0)
        assert low <= value < high
        self.bit_generator.state["calls"] += 1
        return np.int64(value)

    def random(self):
        value = self.floats.pop(0)
        self.bit_generator.state["calls"] += 1
        return value


def intent(kind, path, value=None):
    step = {"kind": kind, "path": path}
    if value is not None:
        step["value"] = value
    return step


def gp_candidate(candidate, integers, randoms=(), phase="structure"):
    result = propose(candidate, ScriptedRNG(integers, randoms), phase)
    assert result["error"] is None, result["error"]
    return result["candidate"], result["actions"]


PROVENANCE_KEYS = ("before", "after", "mode", "direction",
                   "rng_before", "rng_after", "status", "family")


# ---------------------------------------------------------------------------
# 严格解析
# ---------------------------------------------------------------------------

def test_duplicate_key_is_rejected():
    text = '{"kind":"numeric","kind":"numeric","path":"/nco/depth","value":512}'
    with pytest.raises(ProposalContractError) as err:
        parse_program(text)
    assert err.value.code == "duplicate_key"
    nested = ('[{"kind":"swap_fir","path":"/filter_decimator"},'
              '{"kind":"numeric","path":"/nco/depth","value":128,'
              '"value":256}]')
    with pytest.raises(ProposalContractError) as err:
        parse_program(nested)
    assert err.value.code == "duplicate_key"


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_literals_are_rejected(literal):
    text = ('{"kind":"numeric","path":"/nco/depth","value":%s}' % literal)
    with pytest.raises(ProposalContractError) as err:
        parse_program(text)
    assert err.value.code == "non_finite_number"


def test_malformed_json_is_rejected():
    with pytest.raises(ProposalContractError) as err:
        parse_program("{kind: }")
    assert err.value.code == "not_json"
    with pytest.raises(ProposalContractError) as err:
        parse_program(b"\xff\xfe")
    assert err.value.code == "not_json"


@pytest.mark.parametrize("payload", [
    "[]",
    json.dumps([intent("numeric", "/nco/depth", 512),
                intent("numeric", "/nco/phase_bits", 12),
                intent("numeric", "/nco/stages", 12)]),
    '"swap_leaf"',
    42,
    {"kind": "swap_leaf", "path": "/nco"},
])
def test_program_shape_is_enforced(payload):
    with pytest.raises(ProposalContractError) as err:
        parse_program(payload)
    assert err.value.code == "schema"


@pytest.mark.parametrize("extra", [*PROVENANCE_KEYS, "value_hint"])
def test_unknown_fields_including_provenance_are_rejected(extra):
    step = intent("numeric", "/nco/depth", 512)
    step[extra] = {"deep": "subtree"}
    with pytest.raises(ProposalContractError) as err:
        parse_program([step])
    assert err.value.code == "schema"
    assert err.value.detail["unknown_fields"] == [extra]


def test_missing_required_fields_are_rejected():
    with pytest.raises(ProposalContractError):
        parse_program([{"kind": "swap_leaf"}])
    with pytest.raises(ProposalContractError):
        parse_program([{"path": "/nco"}])


def test_unknown_kind_is_rejected():
    with pytest.raises(ProposalContractError):
        parse_program([intent("swap_nco", "/nco")])


@pytest.mark.parametrize("path", ["nco", "/nco/", "", "/"])
def test_malformed_path_is_rejected(path):
    with pytest.raises(ProposalContractError):
        parse_program([intent("swap_leaf", path)])


def test_value_rules_by_kind():
    with pytest.raises(ProposalContractError):
        parse_program([intent("swap_leaf", "/nco", {"stages": 12})])
    with pytest.raises(ProposalContractError):
        parse_program([intent("numeric", "/nco/depth")])
    with pytest.raises(ProposalContractError):
        parse_program([intent("change_interpolation", "/nco/interpolation")])


@pytest.mark.parametrize("value", [True, 512.0, "512", None])
def test_numeric_type_aliases_are_rejected(value):
    with pytest.raises(ProposalContractError) as err:
        parse_program([intent("numeric", "/nco/depth", value)])
    assert err.value.code == "schema"


@pytest.mark.parametrize("field,value", [
    ("depth", 32), ("stages", 6), ("stages", 21), ("phase_bits", 7),
    ("phase_bits", 17), ("split_bits", 1), ("split_bits", 15),
    ("coefficient_bits", 7), ("product_drop", 9), ("accumulator_bits", 19),
    ("rounding", "half"), ("product_rounding", "half"),
])
def test_out_of_domain_values_are_rejected(field, value):
    path = (f"/nco/{field}" if field in ("depth", "stages", "phase_bits",
                                         "split_bits", "product_rounding")
            else f"/filter_decimator/{field}")
    with pytest.raises(ProposalContractError) as err:
        parse_program([intent("numeric", path, value)])
    assert err.value.code == "schema"


def test_change_interpolation_value_and_path_rules():
    with pytest.raises(ProposalContractError):
        parse_program([intent("change_interpolation", "/nco/interpolation", "cubic")])
    with pytest.raises(ProposalContractError):
        parse_program([intent("change_interpolation", "/nco/depth", "nearest")])


# ---------------------------------------------------------------------------
# 执行语义：确定性结构默认值、动态中间树、结构化失败
# ---------------------------------------------------------------------------

def test_swap_leaf_matches_gp_deterministic_default():
    candidate = make_candidate()
    candidate["nco"]["phase_bits"] = 11
    gp_tree, _ = gp_candidate(candidate, [1, 0, 0])
    tree = apply_program(candidate, [intent("swap_leaf", "/nco")])
    assert tree == gp_tree
    assert tree["nco"]["kind"] == "cordic_sincos" and tree["nco"]["stages"] == 12
    assert tree["nco"]["phase_bits"] == 11
    validate_candidate(tree)


def test_change_interpolation_program_matches_gp_value_draw():
    candidate = make_candidate()
    gp_tree, _ = gp_candidate(candidate, [1, 1, 0, 1])
    tree = apply_program(candidate, [intent("change_interpolation",
                                            "/nco/interpolation", "quad")])
    assert tree == gp_tree


def test_two_step_program_uses_intermediate_tree_paths():
    candidate = make_candidate()
    gp_tree, _ = gp_candidate(candidate, [2, 2, 0, 1, 0, 1])
    tree = apply_program(candidate, [
        intent("wrap_compose", "/nco"),
        intent("change_interpolation", "/nco/coarse/interpolation", "quad"),
    ])
    assert tree == gp_tree
    assert tree["nco"]["coarse"]["interpolation"] == "quad"
    validate_candidate(tree)


def test_unwrap_compose_program():
    candidate = make_candidate("compose")
    gp_tree, _ = gp_candidate(candidate, [1, 3, 0])
    tree = apply_program(candidate, [intent("unwrap_compose", "/nco")])
    assert tree == gp_tree
    assert tree["nco"] == candidate["nco"]["coarse"]


def test_swap_fir_twice_cancels_and_preserves_numeric_fields():
    candidate = make_candidate(coefficient_bits=14)
    candidate["filter_decimator"].update(product_drop=3, accumulator_bits=28,
                                         rounding="trunc")
    gp_tree, _ = gp_candidate(candidate, [2, 4, 0, 4, 0])
    tree = apply_program(candidate, [intent("swap_fir", "/filter_decimator"),
                                     intent("swap_fir", "/filter_decimator")])
    assert tree == gp_tree == candidate
    validate_candidate(tree)


def test_numeric_programs_match_gp_sampling_modes():
    candidate = make_candidate()
    # depth 经 jump 直达 1024。
    gp_tree, _ = gp_candidate(candidate, [1, 4, 3], [0.8], phase="numeric")
    tree = apply_program(candidate, [intent("numeric", "/nco/depth", 1024)])
    assert tree == gp_tree
    # accumulator_bits 经 uniform 从 0 到 48。
    gp_tree, _ = gp_candidate(candidate, [1, 0, 28], phase="numeric")
    tree = apply_program(candidate, [intent("numeric",
                                            "/filter_decimator/accumulator_bits", 48)])
    assert tree == gp_tree
    # rounding toggle 不消耗额外抽样。
    gp_tree, _ = gp_candidate(candidate, [1, 3], phase="numeric")
    tree = apply_program(candidate, [intent("numeric",
                                            "/filter_decimator/rounding", "trunc")])
    assert tree == gp_tree


def test_numeric_programs_on_compose_candidate():
    candidate = make_candidate("compose")
    gp_tree, _ = gp_candidate(candidate, [1, 9, 2], [0.8], phase="numeric")
    tree = apply_program(candidate, [intent("numeric", "/nco/split_bits", 4)])
    assert tree == gp_tree
    gp_tree, _ = gp_candidate(candidate, [1, 6], phase="numeric")
    tree = apply_program(candidate, [intent("numeric",
                                            "/nco/product_rounding", "trunc")])
    assert tree == gp_tree


@pytest.mark.parametrize("step", [
    intent("numeric", "/nco/depth", 256),
    intent("change_interpolation", "/nco/interpolation", "linear"),
])
def test_value_equal_to_before_fails_without_resample(step):
    candidate = make_candidate()
    snapshot = copy.deepcopy(candidate)
    with pytest.raises(ProposalContractError) as err:
        apply_program(candidate, [step])
    assert err.value.code == "apply" and err.value.index == 0
    assert candidate == snapshot


@pytest.mark.parametrize("kind,step", [
    ("lut", intent("unwrap_compose", "/nco")),
    ("lut", intent("swap_fir", "/mixer")),
    ("cordic", intent("change_interpolation", "/nco/interpolation", "nearest")),
    ("lut", intent("numeric", "/mixer/product_drop", 1)),
    ("lut", intent("swap_leaf", "/mixer")),
])
def test_paths_outside_kind_targets_fail_at_apply(kind, step):
    candidate = make_candidate(kind)
    with pytest.raises(ProposalContractError) as err:
        apply_program(candidate, [step])
    assert err.value.code == "apply"
    assert err.value.index == 0
    assert "allowed" in err.value.detail


def test_contract_fields_are_unreachable():
    with pytest.raises(ProposalContractError) as err:
        parse_program([intent("numeric", "/formula_version", "x")])
    assert err.value.code == "schema"
    with pytest.raises(ProposalContractError) as err:
        parse_program([intent("numeric", "/metadata/label", 1)])
    assert err.value.code == "schema"
    with pytest.raises(ProposalContractError) as err:
        apply_program(make_candidate(), [intent("swap_leaf", "/phase_accumulator")])
    assert err.value.code == "apply"


def test_base_candidate_failure_is_structured():
    candidate = make_candidate()
    candidate["mixer"]["product_drop"] = False
    with pytest.raises(ProposalContractError) as err:
        apply_program(candidate, [intent("swap_leaf", "/nco")])
    assert err.value.code == "base_candidate"


def test_apply_does_not_mutate_inputs():
    candidate = make_candidate()
    snapshot = copy.deepcopy(candidate)
    program = [intent("numeric", "/nco/depth", 512)]
    tree = apply_program(candidate, program)
    assert candidate == snapshot and program == [{"kind": "numeric",
                                                  "path": "/nco/depth",
                                                  "value": 512}]
    assert tree["nco"]["depth"] == 512


# ---------------------------------------------------------------------------
# GP adapter：日志 → 程序 → 重放与 propose 逐位一致
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("candidate", development_candidates())
@pytest.mark.parametrize("phase", ["mixed", "structure", "numeric"])
@pytest.mark.parametrize("seed", range(50))
def test_gp_log_roundtrip_produces_identical_candidate(candidate, phase, seed):
    result = propose(candidate, np.random.default_rng(seed), phase)
    if result["error"] is not None:
        with pytest.raises(ProposalContractError) as err:
            program_from_action_log(result["actions"])
        assert err.value.code == "action_log"
        return
    program = program_from_action_log(result["actions"])
    assert len(program) == len(result["actions"])
    for step in program:
        assert set(step) <= {"kind", "path", "value"}
        assert not set(PROVENANCE_KEYS) & set(step)
    tree = apply_program(candidate, program)
    assert tree == result["candidate"]
    assert candidate_hash(tree) == candidate_hash(result["candidate"])
    validate_candidate(tree)


def test_gp_program_accepts_json_text_form():
    candidate = make_candidate()
    result = propose(candidate, ScriptedRNG([2, 2, 0, 1, 0, 1]), "structure")
    program = program_from_action_log(result["actions"])
    text = program_to_json(program)
    assert parse_program(text) == program
    assert program_to_json(text) == text
    assert apply_program(candidate, text) == result["candidate"]


def test_adapter_rejects_failed_or_malformed_logs():
    with pytest.raises(ProposalContractError) as err:
        program_from_action_log([{"kind": "numeric", "path": "/nco/depth",
                                  "status": "error", "error": "越界"}])
    assert err.value.code == "action_log"
    with pytest.raises(ProposalContractError):
        program_from_action_log([])
    with pytest.raises(ProposalContractError):
        program_from_action_log("not-a-list")
