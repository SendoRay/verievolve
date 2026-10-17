"""定点类型与错误类型。"""
from __future__ import annotations

from dataclasses import dataclass

MAX_WIDTH = 128


class ContractError(ValueError):
    """构造或检查失败。code 是机器可读的类别，where 指向候选程序中的行。"""

    def __init__(self, code: str, message: str, where: str | None = None):
        super().__init__(f"{code}: {message}" + (f" (at {where})" if where else ""))
        self.code, self.message, self.where = code, message, where

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "where": self.where}


@dataclass(frozen=True)
class Fx:
    """定点格式：数值 = 整数码 × 2^-F；W 为总位宽（含符号位）。"""
    W: int
    F: int
    signed: bool = True

    def __post_init__(self):
        if not 1 <= self.W <= MAX_WIDTH:
            raise ContractError("width", f"width {self.W} outside [1, {MAX_WIDTH}]; insert q() to narrow it")

    @property
    def IB(self) -> int:
        """整数位数（含符号位）。"""
        return self.W - self.F

    @property
    def lo(self) -> int:
        return -(1 << (self.W - 1)) if self.signed else 0

    @property
    def hi(self) -> int:
        return (1 << (self.W - 1)) - 1 if self.signed else (1 << self.W) - 1

    def range(self) -> tuple[float, float]:
        s = 2.0 ** -self.F
        return self.lo * s, self.hi * s

    def as_signed(self) -> "Fx":
        """无符号转有符号需要多一位。"""
        return self if self.signed else Fx(self.W + 1, self.F, True)

    def __str__(self):
        return f"{'s' if self.signed else 'u'}{self.W}.{self.F}"


BOOL = Fx(1, 0, False)
