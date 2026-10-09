import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BENCH = Path(__file__).resolve().parents[1] / "examples" / "comm_dsp_bench"
sys.path.insert(0, str(BENCH))

from search_ir.actions import ActionError, propose, replay
from search_ir.dev_fixtures import development_candidates, make_candidate
from search_ir.validate import validate_candidate


class ScriptedRNG:
    """精确检查无重采样及每个边界分支，不使用概率性断言。"""

    def __init__(self, integers, randoms=()):
        self.ints = list(integers)
        self.floats = list(randoms)
        self.calls = []
        self.bit_generator = SimpleNamespace(state={"calls": 0})

    def integers(self, low, high):
        value = self.ints.pop(0)
        assert low <= value < high
        self.calls.append((low, high))
        self.bit_generator.state["calls"] += 1
        return np.int64(value)

    def random(self):
        value = self.floats.pop(0)
        self.bit_generator.state["calls"] += 1
        return value


def structure_key(tree):
    def nco(node):
        if node["kind"] == "phasor_compose":
            return node["kind"], nco(node["coarse"]), nco(node["residual"])
        return node["kind"], node.get("interpolation")
    return nco(tree["nco"]), tree["filter_decimator"]["kind"]


@pytest.mark.parametrize("phase", ["mixed", "structure", "numeric"])
@pytest.mark.parametrize("candidate", development_candidates())
def test_seed_reproducibility_json_types_replay_and_input_immutability(phase, candidate):
    original = copy.deepcopy(candidate)
    for seed in range(100):
        first = propose(candidate, np.random.default_rng(seed), phase)
        second = propose(candidate, np.random.default_rng(seed), phase)
        assert first == second
        json.dumps(first, allow_nan=False)
        assert candidate == original
        assert 1 <= len(first["actions"]) <= 2
        if phase != "mixed":
            assert all(step["family"] == phase for step in first["actions"])
        if first["error"] is None:
            validate_candidate(first["candidate"])
            assert replay(candidate, first["actions"]) == first["candidate"]
            if phase == "numeric":
                assert structure_key(first["candidate"]) == structure_key(candidate)
        else:
            assert first["candidate"] is None
            assert first["actions"][-1]["status"] == "error"
            with pytest.raises(ActionError):
                replay(candidate, first["actions"])


def test_wrap_and_second_step_use_intermediate_tree():
    candidate = make_candidate()
    rng = ScriptedRNG([2, 2, 0, 1, 0, 0])
    result = propose(candidate, rng, "structure")
    assert result["error"] is None
    wrapped = result["actions"][0]["after"]
    assert wrapped["coarse"] == candidate["nco"]
    assert wrapped["residual"]["stages"] == 12
    assert wrapped["residual"]["phase_bits"] == 16
    assert wrapped["split_bits"] == 8
    assert wrapped["product_rounding"] == "nearest_ties_to_pos_inf"
    assert wrapped["product_saturation"] == "sat"
    assert result["actions"][1]["path"] == "/nco/coarse/interpolation"
    assert result["candidate"]["nco"]["coarse"]["interpolation"] == "nearest"
    assert replay(candidate, result["actions"]) == result["candidate"]


def test_second_invalid_step_discards_whole_candidate_without_retry():
    rng = ScriptedRNG([2, 2, 0, 2])
    candidate = make_candidate()
    result = propose(candidate, rng, "structure")
    assert result["candidate"] is None and result["error"]
    assert [step["status"] for step in result["actions"]] == ["ok", "error"]
    assert result["actions"][1]["kind"] == "wrap_compose"
    assert len(rng.calls) == 4 and not rng.ints
    assert candidate["nco"]["kind"] == "lut_sincos"


def test_unwrap_leaf_is_invalid_without_resampling():
    rng = ScriptedRNG([1, 3])
    result = propose(make_candidate(), rng, "structure")
    assert result["candidate"] is None
    assert result["actions"][0]["path"] is None
    assert result["actions"][0]["kind"] == "unwrap_compose"
    assert len(rng.calls) == 2


def test_unwrap_keeps_coarse_as_full_phase_leaf():
    candidate = make_candidate("compose")
    result = propose(candidate, ScriptedRNG([1, 3, 0]), "structure")
    assert result["candidate"]["nco"] == candidate["nco"]["coarse"]
    assert replay(candidate, result["actions"]) == result["candidate"]


@pytest.mark.parametrize("kind", ["lut", "cordic"])
def test_swap_leaf_preserves_phase_bits_and_uses_fixed_defaults(kind):
    candidate = make_candidate(kind)
    candidate["nco"]["phase_bits"] = 11
    result = propose(candidate, ScriptedRNG([1, 0, 0]), "structure")
    node = result["candidate"]["nco"]
    assert node["phase_bits"] == 11
    if kind == "lut":
        assert node["kind"] == "cordic_sincos" and node["stages"] == 12
        assert "depth" not in node and "interpolation" not in node
    else:
        assert node["kind"] == "lut_sincos" and node["depth"] == 256
        assert node["interpolation"] == "linear" and "stages" not in node


def test_fir_swap_preserves_numeric_fields_and_inverse_cancels():
    candidate = make_candidate(coefficient_bits=14)
    candidate["filter_decimator"].update(
        product_drop=3,
        accumulator_bits=28,
        rounding="floor",
    )
    result = propose(candidate, ScriptedRNG([2, 4, 0, 4, 0]), "structure")
    assert result["error"] is None and result["candidate"] == candidate
    first_fir = result["actions"][0]["after"]
    assert first_fir["phases"] == 2 and first_fir["kind"] == "polyphase_fir_decimator"
    for key in ("coefficient_bits", "product_drop", "accumulator_bits", "rounding"):
        assert first_fir[key] == candidate["filter_decimator"][key]
    assert replay(candidate, result["actions"]) == candidate


@pytest.mark.parametrize("field,path_index,before,after", [
    ("depth", 4, 64, 32), ("phase_bits", 5, 8, 7),
])
def test_neighbor_boundary_failure_records_attempt_and_never_resamples(field, path_index, before, after):
    candidate = make_candidate()
    candidate["nco"][field] = before
    rng = ScriptedRNG([1, path_index, 0], [0.79])
    result = propose(candidate, rng, "numeric")
    step = result["actions"][0]
    assert result["candidate"] is None and step["status"] == "error"
    assert step["mode"] == "neighbor" and step["after"] == after
    assert len(rng.calls) == 3 and not rng.floats


def test_uniform_jump_reaches_non_neighbor_and_sentinel_domain():
    # sorted数值路径的4是depth；当前256的其他四档最后一项是1024。
    result = propose(make_candidate(), ScriptedRNG([1, 4, 3], [0.8]), "numeric")
    assert result["candidate"]["nco"]["depth"] == 1024
    assert result["actions"][0]["mode"] == "jump"
    # accumulator_bits为路径0；从0直接到48，不经过可能无效的饱和带。
    result = propose(make_candidate(), ScriptedRNG([1, 0, 28]), "numeric")
    assert result["candidate"]["filter_decimator"]["accumulator_bits"] == 48
    assert result["actions"][0]["mode"] == "uniform"
    candidate = make_candidate()
    candidate["filter_decimator"]["accumulator_bits"] = 48
    result = propose(candidate, ScriptedRNG([1, 0, 0]), "numeric")
    assert result["candidate"]["filter_decimator"]["accumulator_bits"] == 0


def test_rounding_toggle_has_no_neighbor_draw():
    rng = ScriptedRNG([1, 3])
    result = propose(make_candidate(), rng, "numeric")
    assert (
        result["candidate"]["filter_decimator"]["rounding"]
        == "floor"
    )
    assert len(rng.calls) == 2


@pytest.mark.parametrize("change", ["before", "family", "defaults", "path"])
def test_replay_rejects_drift_or_disallowed_transition(change):
    candidate = make_candidate()
    result = propose(candidate, ScriptedRNG([1, 0, 0]), "structure")
    steps = copy.deepcopy(result["actions"])
    step = steps[0]
    if change == "before":
        step["before"]["phase_bits"] = 12.0
    elif change == "family":
        step["family"] = "numeric"
    elif change == "defaults":
        step["after"]["stages"] = 7
    else:
        step["path"] = "/mixer"
        step["before"] = candidate["mixer"]
    with pytest.raises(ActionError):
        replay(candidate, steps)


def test_invalid_phase_is_rejected_before_rng_use():
    with pytest.raises(ValueError, match="phase"):
        propose(make_candidate(), ScriptedRNG([]), "initial")


def test_invalid_parent_is_reported_without_any_action():
    candidate = make_candidate()
    candidate["mixer"]["product_drop"] = False
    result = propose(candidate, ScriptedRNG([]), "numeric")
    assert result["candidate"] is None and result["error"]
    assert result["actions"] == []
