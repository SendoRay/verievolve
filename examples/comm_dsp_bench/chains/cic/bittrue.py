"""CIC decimator 的逐位整数模型。

模型只实现 ``CONTRACT_CIC_WITNESS_v1`` 已冻结的数值语义：输入锁存、
N 级积分器、phase-0 抽取、N 级梳状器和固定 Q1.15 输出。内部状态使用
Python 整数完成扩展精度运算，随后在每个锁存边界执行候选声明的低位裁剪
和 wrap/sat，因此不会被 NumPy 固定位宽的意外溢出污染。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from numeric_semantics import (
    normalize_rounding_mode,
    round_shift as semantic_round_shift,
    saturate_signed,
    wrap_signed as semantic_wrap_signed,
)


def round_shift(value: int, bits: int, mode: str) -> int:
    """按公共显式语义缩放；历史别名保持逐位兼容。"""
    return int(semantic_round_shift(value, bits, mode))


def wrap_signed(value: int, width: int) -> int:
    return semantic_wrap_signed(value, width)


def sat_signed(value: int, width: int) -> int:
    return saturate_signed(value, width)


@dataclass
class EventCounts:
    internal_wrap_event: list[int]
    internal_sat_event: list[int]
    first_internal_event: dict | None = None
    output_sat: int = 0

    def as_dict(self) -> dict:
        return {
            "internal_wrap_event": list(self.internal_wrap_event),
            "internal_sat_event": list(self.internal_sat_event),
            "first_internal_event": self.first_internal_event,
            "output_sat": self.output_sat,
        }


@dataclass
class CICState:
    integrators: list[int]
    comb_delays: list[int]
    input_index: int = 0
    output_index: int = 0
    events: EventCounts = field(default_factory=lambda: EventCounts([], []))


class CICBitTrue:
    """单个实数分量的有状态 CIC 模型；I/Q 分量分别运行同一模型。"""

    def __init__(self, candidate: dict):
        self.name = str(candidate["name"])
        self.R = int(candidate["R"])
        self.N = int(candidate["N"])
        self.B = tuple(int(x) for x in candidate["B"])
        self.B_fmt = int(candidate["B_fmt"])
        self.overflow = str(candidate["overflow"])
        self.rounding = str(candidate["rounding"])
        self.W_full = 12 + self.N * (self.R.bit_length() - 1)
        if self.R not in (2, 4) or len(self.B) != 2 * self.N:
            raise ValueError(f"invalid CIC candidate shape: {candidate}")
        if any(b < 0 for b in self.B) or any(
            self.B[i] > self.B[i + 1] for i in range(len(self.B) - 1)
        ):
            raise ValueError(f"B must be nonnegative and monotone: {self.B}")
        if self.overflow not in ("wrap", "sat"):
            raise ValueError(f"invalid overflow mode: {self.overflow}")
        self.rounding = normalize_rounding_mode(self.rounding)
        self.reset()

    def reset(self) -> None:
        # integrator k writes lock j=k+2; comb k reads lock j=N+1+k.
        n_internal = 2 * self.N - 1
        self.state = CICState(
            integrators=[0] * self.N,
            comb_delays=[0] * self.N,
            events=EventCounts([0] * n_internal, [0] * n_internal),
        )

    def _internal_write(self, value: int, prev_b: int, next_b: int,
                        lock_j: int) -> int:
        delta = next_b - prev_b
        quantized = round_shift(value, delta, self.rounding)
        width = self.W_full - next_b
        lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
        # 冻结契约对 wrap 的事件计数显式采用 abs(state) >= 2^(w-1)；
        # sat 则按真正超出有符号可表示范围计数。两者只影响诊断计数，数值处理不变。
        overflowed = (abs(quantized) >= (1 << (width - 1))
                      if self.overflow == "wrap"
                      else quantized < lo or quantized > hi)
        slot = lock_j - 2  # internal locks j=2..2N
        if overflowed:
            key = "internal_wrap_event" if self.overflow == "wrap" else "internal_sat_event"
            counts = getattr(self.state.events, key)
            counts[slot] += 1
            if self.state.events.first_internal_event is None:
                self.state.events.first_internal_event = {
                    "input_index": self.state.input_index,
                    "output_index": self.state.output_index,
                    "lock_j": lock_j,
                    "mode": self.overflow,
                    "pre_overflow_value": quantized,
                    "width": width,
                }
        return (wrap_signed(quantized, width) if self.overflow == "wrap"
                else sat_signed(quantized, width))

    def _input_lock(self, sample: int) -> int:
        # 外部 ADC 已固定为 signed 12-bit；输入锁存只裁低位，随后符号扩展。
        if sample < -2048 or sample > 2047:
            raise ValueError(f"input sample outside signed Q1.11 code range: {sample}")
        return round_shift(sample, self.B[0], self.rounding)

    def push(self, sample: int) -> int | None:
        current = self._input_lock(int(sample))
        current_b = self.B[0]

        # N 级积分器。旧状态先对齐到当前输入的细网格，再精确相加。
        for k in range(self.N):
            next_b = self.B[k + 1]
            aligned_state = self.state.integrators[k] << (next_b - current_b)
            exact = aligned_state + current
            lock_j = k + 2
            current = self._internal_write(exact, current_b, next_b, lock_j)
            self.state.integrators[k] = current
            current_b = next_b

        take = self.state.input_index % self.R == 0
        self.state.input_index += 1
        if not take:
            return None

        # N 级梳状器。前 N-1 级写候选内部锁存；最后一级写固定输出。
        for k in range(self.N):
            delayed = self.state.comb_delays[k]
            self.state.comb_delays[k] = current
            exact = current - delayed
            if k < self.N - 1:
                next_index = self.N + 1 + k  # B_{N+2+k}, zero-based
                next_b = self.B[next_index]
                lock_j = self.N + 2 + k
                current = self._internal_write(exact, current_b, next_b, lock_j)
                current_b = next_b
            else:
                current = exact

        # wrap 型 CIC 的积分器状态是在同一个物理模数 2^(B_max+1) 下传播的。
        # 最后一级梳状器的扩展精度差值仍可能带着一个整模数偏移；在解释为
        # [B_{2N}, B_max] 位窗口前必须先取回该窗口的有符号代表，否则固定
        # sat16 会把本应由最后一次差分消去的模数偏移误当成真实溢出。
        # sat 型没有模自愈性质，保留扩展差值并交给固定输出饱和。
        if self.overflow == "wrap":
            current = wrap_signed(current, self.W_full - current_b)

        d = self.B_fmt - current_b
        output = round_shift(current, d, self.rounding)
        if output < -32768 or output > 32767:
            self.state.events.output_sat += 1
        output = sat_signed(output, 16)
        self.state.output_index += 1
        return output

    def run(self, samples: Iterable[int]) -> tuple[list[int], dict]:
        out: list[int] = []
        for sample in samples:
            value = self.push(int(sample))
            if value is not None:
                out.append(value)
        return out, self.state.events.as_dict()


def run_iq(candidate: dict, i_codes: Sequence[int], q_codes: Sequence[int]) -> dict:
    if len(i_codes) != len(q_codes):
        raise ValueError("I/Q input lengths differ")
    i_model, q_model = CICBitTrue(candidate), CICBitTrue(candidate)
    i_out, i_events = i_model.run(i_codes)
    q_out, q_events = q_model.run(q_codes)
    if len(i_out) != len(q_out):
        raise AssertionError("I/Q CIC output lengths differ")
    return {
        "i": i_out,
        "q": q_out,
        "events": {"i": i_events, "q": q_events},
    }
