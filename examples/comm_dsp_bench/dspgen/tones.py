"""多音信号的解析表示：x(t) = Σ amps_k · exp(j2π (shift_k + freqs_k) t)，t 以链输入样点为单位，可取非整数。

频谱搬移只改 shift；搬移恰好抵消（shift == 0）时直接使用原始 freqs，避免引入浮点舍入。"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class ToneSet:
    freqs: np.ndarray
    amps: np.ndarray
    shift: np.ndarray = None

    def eff(self):
        if self.shift is None:
            return self.freqs
        return np.where(self.shift == 0, self.freqs, self.shift + self.freqs)

    def at(self, t):
        return np.exp(2j * np.pi * np.outer(t, self.eff())) @ self.amps

    def shifted(self, df):
        s = np.zeros(len(self.freqs)) if self.shift is None else self.shift
        return ToneSet(self.freqs, self.amps, s + df)

    def select(self, keep):
        s = None if self.shift is None else self.shift[keep]
        if s is not None and np.all(s == 0):
            s = None
        return ToneSet(self.freqs[keep], self.amps[keep], s)
