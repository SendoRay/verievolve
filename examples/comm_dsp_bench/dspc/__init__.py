"""dspc：通信 DSP 原语契约（VeriEvolve 框架 v5 的方法一）。

设计见 thesis/midterm/FRAMEWORK_v5.md。要点：
- 原语只描述“算什么”（A 层：数值语义）与“承诺怎样造”（B 层：微结构承诺），不生成 Verilog；
- 误差只能经由显式近似点（q、const、lut 等）进入，同一程序可按理想与定点两种方式执行（双重解释）；
- 通过候选级判定的程序冻结为实现契约，交给 Lowering Agent 写 RTL，RTL 必须逐位忠实。
"""

from .fixtype import ContractError, Fx
from .prog import Prog, Sig
from .interp import run

__all__ = ["ContractError", "Fx", "Prog", "Sig", "run"]
