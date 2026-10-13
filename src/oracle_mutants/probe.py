"""Tolerance probe: when a nudged number is accepted, move it further until the verifier says no.

The answer turns "worth a look" into a measured fact. "+1 accepted, +2 rejected" is a documented
±1 tolerance and can be closed in seconds; "accepted up to +1000" means nobody checks that value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .oracle import OracleRun
from .runner import Outcome
from .task import Task
from .verifier import run_verifier

# Steps tried after the first nudge (integers +1, decimals +50%) was accepted.
INT_STEPS = (2, 5, 10, 100, 1000)
REL_STEPS = (1.0, 10.0, 100.0)  # +100%, +1,000%, +10,000% of the value (absolute when the value is 0)


@dataclass
class Probe:
    steps: list[tuple[str, float | None]] = field(default_factory=list)  # (label, reward)
    first: str = "the first nudge"  # the step the main run already showed was accepted

    @property
    def accepted(self) -> list[str]:
        return [label for label, reward in self.steps if reward is not None and reward >= 1.0]

    @property
    def rejected_at(self) -> str | None:
        return next((label for label, reward in self.steps if reward is None or reward < 1.0), None)

    def summary(self) -> str:
        if self.rejected_at is None:
            return f"accepted every step up to {self.steps[-1][0]}: this value looks unchecked"
        widest = self.accepted[-1] if self.accepted else self.first
        return f"accepted {widest}, rejected {self.rejected_at}: the verifier has a tolerance between those two"


def _ladder(token: str) -> list[tuple[str, float]]:
    if re.fullmatch(r"-?\d+", token):
        return [(f"+{s}", s) for s in INT_STEPS]
    if float(token) == 0:
        return [(f"0 -> {s:g}", s) for s in REL_STEPS]
    return [(f"+{int(s * 100):,}%", s) for s in REL_STEPS]


def probe(task: Task, oracle: OracleRun, image: str, outcome: Outcome) -> Probe | None:
    v = outcome.mutant.variant
    if not outcome.survived or v.rebuild is None or v.value is None:
        return None
    token = v.value
    first = "+1" if re.fullmatch(r"-?\d+", token) else ("0 -> 1" if float(token) == 0 else "+50%")
    result = Probe(first=first)
    for label, step in _ladder(v.value):
        reward = run_verifier(image, task, oracle.artifacts, {outcome.mutant.container_path: v.rebuild(step)}).reward
        result.steps.append((label, reward))
        if reward is None or reward < 1.0:
            break
    return result
