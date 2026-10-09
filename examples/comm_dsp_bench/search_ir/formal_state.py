"""正式实验状态机：沿用pilot策略，预算边界参数化；成本优先分支预先固定。"""

import copy
import math

import numpy as np

from .actions import propose
from .dev_fixtures import development_candidates
from .pilot import _plain
from .selection import family_key, lock_families, main_archive, ranked, tournament, truncate


class FormalState:
    def __init__(self, seed, arm, budget=32, q_budget=2.32929922807541e-5,
                 initial_candidates=None, semantic_profile="current"):
        if type(seed) is not int or arm not in ("joint", "staged", "cost-first"):
            raise ValueError("invalid seed or arm")
        if type(budget) is not int or budget < 8 or budget % 2:
            raise ValueError("budget must be an even integer >=8")
        if not math.isfinite(q_budget) or q_budget <= 0:
            raise ValueError("invalid q_budget")
        self.seed, self.arm, self.budget, self.q_budget = seed, arm, budget, q_budget
        self.initial_candidates = copy.deepcopy(
            development_candidates() if initial_candidates is None else initial_candidates
        )
        if len(self.initial_candidates) != 3:
            raise ValueError("exactly three initial candidates are required")
        self.semantic_profile = semantic_profile
        self.rng = np.random.Generator(np.random.PCG64(seed))
        self.population, self.history, self.families = [], {}, None
        self.last_attempt = 0

    def phase(self, attempt):
        if not 1 <= attempt <= self.budget:
            raise ValueError("attempt outside budget")
        if attempt <= 3:
            return "initial"
        if self.arm == "staged":
            return "structure" if attempt <= self.budget // 2 else "numeric"
        return "mixed"

    def quality_target(self, attempt):
        return self.q_budget * ((0.25, 0.5, 1.0)[(attempt - 4) % 3] if attempt > 3 else 1.0)

    def _cost_pool(self, attempt):
        eligible = [r for r in self.history.values() if r["Q"] <= self.quality_target(attempt)]
        return sorted(eligible, key=lambda r: (r["area_um2"], r["candidate_hash"]))[:8]

    def candidate(self, attempt, phase=None):
        expected = self.phase(attempt)
        if attempt != self.last_attempt + 1 or phase not in (None, expected):
            raise ValueError("attempt order or phase mismatch")
        if attempt <= 3:
            return {"candidate": copy.deepcopy(self.initial_candidates[attempt - 1]),
                    "actions": [], "error": None}
        family = None
        if self.arm == "cost-first":
            pool = self._cost_pool(attempt)
            if not pool:
                raise ValueError("cost-first has no eligible parent")
            index = 0 if len(pool) == 1 else min(int(i) for i in self.rng.choice(len(pool), 2, replace=False))
            parent = pool[index]
        else:
            if self.arm == "staged" and self.families is not None:
                family = self.families[(attempt - self.budget // 2 - 1) % len(self.families)]
            parent = tournament(self.population, self.rng, family=family)
        result = propose(parent["candidate"], self.rng, expected,
                         semantic_profile=self.semantic_profile)
        if family is not None and result["candidate"] is not None and family_key(result["candidate"]) != family:
            result = {**result, "candidate": None, "error": "locked structure family changed"}
        return {**result, "parent_hash": parent["candidate_hash"]}

    def update(self, record, attempt):
        self.phase(attempt)
        if attempt != self.last_attempt + 1:
            raise ValueError("attempt order mismatch")
        if record is not None:
            record = _plain(record)
            # 与共同选择器相同的合法性检查，不让成本分支绕过有限性或身份校验。
            ranked([record])
            identity = record["candidate_hash"]
            if self.families is not None and family_key(record["candidate"]) not in self.families:
                raise ValueError("record outside locked families")
            if identity in self.history and self.history[identity] != record:
                raise ValueError("conflicting deterministic candidate")
            self.history[identity] = record
            if self.arm != "cost-first":
                self.population = [_plain(r) for r in truncate(
                    [*self.population, record], capacity=8, families=self.families,
                )]
        if self.arm == "cost-first":
            self.population = [_plain(r) for r in self._cost_pool(attempt)]
        elif self.arm == "staged" and attempt == self.budget // 2:
            history = list(self.history.values())
            self.families = lock_families(history, max_families=3)
            if not self.families:
                raise ValueError("no valid family to lock")
            selected = [r for r in self.population if family_key(r["candidate"]) in self.families]
            for family in self.families:
                if not any(family_key(r["candidate"]) == family for r in selected):
                    selected.append(next(r for r in ranked(history) if family_key(r["candidate"]) == family))
            self.population = [_plain(r) for r in truncate(selected, capacity=8, families=self.families)]
        self.last_attempt = attempt

    def snapshot(self, q_budget=None):
        return {"rng_state": copy.deepcopy(self.rng.bit_generator.state),
                "population": copy.deepcopy(self.population), "history": copy.deepcopy(list(self.history.values())),
                "families": copy.deepcopy(self.families),
                "main_archive": [_plain(r) for r in main_archive(list(self.history.values()),
                                                                  self.q_budget if q_budget is None else q_budget)]}
