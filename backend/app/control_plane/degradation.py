"""Quality-degradation controller.

Watches the recent runs. If groundedness or tool correctness average below their policy minimums, the
system becomes more cautious by itself, in proportion to how bad it is:

    normal     : everything as configured.
    cautious   : one metric below its minimum. Use a stronger model tier, retrieve more evidence, and
                 require a human to review EVERY run (autonomy is reduced: nothing auto-completes).
    restricted : two or more metrics below minimum, or one far below. As cautious, with more retrieval again.

It recovers one level at a time and only once the metrics are clearly back above the minimum (hysteresis),
so it cannot flap between levels on noise. Every change is recorded as an event with the numbers that caused it.
Pure functions over plain rows: the decision is easy to test, and easy to explain to an auditor.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any

LEVELS = ("normal", "cautious", "restricted")
# metric (as stored in a run's scores) -> policy threshold that governs it
MONITORED = {"groundedness": "min_groundedness", "tool_call_accuracy": "min_tool_call_accuracy"}


@dataclass(frozen=True)
class Actions:
    tier_boost: int = 0               # how many model tiers to move up (small -> medium -> reasoning)
    retrieval_k_multiplier: int = 1   # retrieve this many times more passages
    require_review: bool = False      # force every run to a human, whatever the Guardian would have decided


ACTIONS = {
    "normal": Actions(),
    "cautious": Actions(tier_boost=1, retrieval_k_multiplier=2, require_review=True),
    "restricted": Actions(tier_boost=1, retrieval_k_multiplier=3, require_review=True),
}


@dataclass(frozen=True)
class DegradationState:
    level: str = "normal"
    since: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())
    reasons: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    runs_considered: int = 0

    @property
    def actions(self) -> Actions:
        return ACTIONS[self.level]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        d["actions"] = asdict(self.actions)
        return d


class DegradationController:
    def __init__(self, thresholds: dict[str, float], window: int = 10, min_runs: int = 3,
                 recovery_margin: float = 0.03, severe_gap: float = 0.15):
        self.thresholds, self.window, self.min_runs = thresholds, window, min_runs
        self.recovery_margin, self.severe_gap = recovery_margin, severe_gap

    def _averages(self, rows: list[dict[str, Any]]) -> tuple[dict[str, float], int]:
        recent = [r for r in rows if r.get("scores")][-self.window:]
        out: dict[str, float] = {}
        for metric in MONITORED:
            values = [r["scores"][metric] for r in recent if isinstance(r["scores"].get(metric), (int, float))]
            if values:
                out[metric] = round(sum(values) / len(values), 4)
        return out, len(recent)

    def _target(self, avgs: dict[str, float]) -> tuple[str, list[str]]:
        breached, severe, reasons = 0, False, []
        for metric, key in MONITORED.items():
            floor, avg = self.thresholds.get(key), avgs.get(metric)
            if floor is None or avg is None or avg >= floor:
                continue
            breached += 1
            severe = severe or avg < floor - self.severe_gap
            reasons.append(f"average {metric.replace('_', ' ')} {avg:.2f} is below the policy minimum {floor:.2f}")
        return ("restricted" if severe or breached >= 2 else "cautious" if breached == 1 else "normal"), reasons

    def _clearly_healthy(self, avgs: dict[str, float]) -> bool:
        return all(avgs.get(m, 1.0) >= self.thresholds.get(k, 0.0) + self.recovery_margin for m, k in MONITORED.items())

    def evaluate(self, rows: list[dict[str, Any]], current: DegradationState) -> DegradationState:
        """The state after seeing `rows` (oldest first). Returns `current` itself if nothing changes."""
        avgs, n = self._averages(rows)
        if n < self.min_runs:
            return current  # too little evidence to act on, in either direction
        target, reasons = self._target(avgs)
        now = LEVELS.index(current.level)
        want = LEVELS.index(target)
        if want > now:
            new_level = target  # getting worse: react at once
        elif want < now:
            # improving: step down one level, and only when clearly back above the minimums
            new_level = LEVELS[now - 1] if self._clearly_healthy(avgs) else current.level
        else:
            new_level = current.level
        if new_level == current.level:
            # same level: keep the clock, but keep the numbers fresh so the API shows what it is based on
            return DegradationState(current.level, current.since, tuple(reasons) or current.reasons, avgs, n) \
                if (avgs, n) != (current.metrics, current.runs_considered) else current
        why = reasons or ["metrics have recovered above the policy minimums"]
        return DegradationState(new_level, dt.datetime.now(dt.UTC).isoformat(), tuple(why), avgs, n)
