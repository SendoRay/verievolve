"""X4 反向规格：以开源 USRP DDC 在每个场景上实测达到的 SNR 作为该场景的门槛（纹波门槛取 USRP 实测纹波）。

新设计只有在每一个场景（搜索、留出、统计复核）上都不比 USRP 差才算达标，然后在同一 PPA 流程下比面积与功耗。
USRP 的逐场景结果按需仿真并缓存到 experiments_v3/usrp_ref_<任务>.json。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..task import Task, get, register

CACHE = Path(__file__).resolve().parent.parent.parent / "experiments_v3"


@dataclass
class USRPRefTask(Task):
    base: str = ""
    ref: dict = field(default_factory=dict, repr=False)

    def _ref(self, idx: int) -> dict:
        f = CACHE / f"usrp_ref_{self.base}.json"
        if not self.ref and f.exists():
            self.ref = {int(k): v for k, v in json.loads(f.read_text()).items()}
        if idx not in self.ref:
            from ..baselines import usrp
            from .. import vlog
            from types import SimpleNamespace
            b = get(self.base)
            cfg = json.loads((CACHE / f"usrp_{self.base}.json").read_text())["best"]
            sp = SimpleNamespace(input_bits=b.interface["in_bits"], r_total=int(b.params["r_total"]), fcw=int(b.params["fcw"]))
            v = usrp.design(sp, cfg["cfg"], -sp.fcw, cfg["scale"])
            y = vlog.simulate(v, self.base, [idx], lead=usrp.LEAD, reset_cycles=usrp.RESET_CYCLES)[idx]
            s = b.score(idx, y)
            self.ref[idx] = {"snr_db": float(s["snr_db"]), "ripple_db": float(s["ripple_db"])}
            CACHE.mkdir(exist_ok=True)
            f.write_text(json.dumps(self.ref, indent=1))
        return self.ref[idx]

    def scene(self, idx: int) -> dict:
        st = get(self.base).scene(idx)
        if idx not in self._cache:
            self._cache[idx] = dict(st, snr_min_db=self._ref(idx)["snr_db"])
        return self._cache[idx]

    def score(self, idx: int, y) -> dict:
        r = get(self.base).score(idx, y)
        ref = self._ref(idx)
        r.update(snr_min_db=ref["snr_db"], ripple_max_db=max(ref["ripple_db"], 1e-3))
        r["passed"] = bool(r.get("valid_output", True) and r["snr_db"] >= ref["snr_db"] and r["ripple_db"] <= r["ripple_max_db"])
        return r


for base in ("dev_r32_narrow", "real_r32_narrow"):
    b = get(base)
    register(USRPRefTask(
        name=f"usrpq_{base}", params=dict(b.params), interface=dict(b.interface), ideal=b.ideal, stimulus=b.stimulus,
        tolerance=dict(b.tolerance), search_scenarios=b.search_scenarios, holdout_scenarios=b.holdout_scenarios,
        seed_key=b.seed_key, base=base,
        description=b.description + " 质量门槛：每个场景的 SNR 不低于开源 USRP DDC 在同一场景上的实测 SNR，纹波不高于 USRP。"))
