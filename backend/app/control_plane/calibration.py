"""Calibrate the evaluation scores against what partners actually decided.

The decision dataset pairs each run's scores with a human verdict. A score is only useful as a gate if it separates
the runs a partner approved from the ones they sent back. For every score this reports:

* **AUC**: the chance that a randomly chosen approved run scores higher than a randomly chosen not-approved one
  (0.5 = no signal, 1.0 = perfect, below 0.5 = the score points the wrong way);
* the mean for each group and the **best threshold** (maximising balanced accuracy);
* what the **policy's current threshold** does: how many not-approved runs it would let through (false accepts) and
  how many approved runs it would block (false blocks).

It cannot say a threshold is right with few decisions, so it says how much data it has and flags a thin sample.
`modify` counts as not-approved by default: a partner who had to edit the recommendation did not accept it as written.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MIN_PER_CLASS = 30  # below this a threshold or AUC is anecdote, not calibration
POLICY_KEYS = {"groundedness": "min_groundedness", "constraint_satisfaction": "min_constraint_satisfaction",
               "task_adherence": "min_task_adherence", "tool_call_accuracy": "min_tool_call_accuracy",
               "contradiction_free": "min_contradiction_free"}


@dataclass
class MetricCalibration:
    metric: str
    n_approved: int
    n_not_approved: int
    mean_approved: float | None
    mean_not_approved: float | None
    auc: float | None
    best_threshold: float | None
    best_balanced_accuracy: float | None
    policy_threshold: float | None
    false_accept_rate: float | None  # not-approved runs the policy threshold would pass
    false_block_rate: float | None  # approved runs the policy threshold would block
    verdict: str


@dataclass
class CalibrationReport:
    decisions: int
    approved: int
    not_approved: int
    metrics: list[MetricCalibration] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def auc(pos: list[float], neg: list[float]) -> float | None:
    """Mann-Whitney AUC with ties counted half; None when either group is empty."""
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def best_threshold(pos: list[float], neg: list[float]) -> tuple[float, float] | None:
    """The cut-off (score >= t is accepted) with the highest balanced accuracy, and that accuracy."""
    if not pos or not neg:
        return None
    best: tuple[float, float] | None = None
    for t in sorted(set(pos) | set(neg)):
        tpr = sum(p >= t for p in pos) / len(pos)
        tnr = sum(n < t for n in neg) / len(neg)
        bal = (tpr + tnr) / 2
        if best is None or bal > best[1] + 1e-12:
            best = (t, bal)
    return (round(best[0], 4), round(best[1], 4)) if best else None


def _verdict(m: MetricCalibration) -> str:
    if m.auc is None:
        return "not enough data: need both approved and not-approved decisions"
    if min(m.n_approved, m.n_not_approved) < MIN_PER_CLASS:
        return f"thin sample (fewer than {MIN_PER_CLASS} in a group): treat as indicative only"
    if m.auc < 0.5:
        return "inverted: higher scores go with rejections"
    if m.auc < 0.55:
        return "weak: this score barely separates what partners accept from what they reject"
    flags = []
    if m.false_accept_rate is not None and m.false_accept_rate > 0.2:
        flags.append("the policy threshold lets through many runs partners did not accept; consider raising it")
    if m.false_block_rate is not None and m.false_block_rate > 0.3:
        flags.append("the policy threshold blocks many runs partners accepted; consider lowering it")
    return "; ".join(flags) or "separates well and the policy threshold is reasonable"


def calibrate(records: list[dict[str, Any]], thresholds: dict[str, float] | None = None,
              modify_as_approved: bool = False) -> CalibrationReport:
    thresholds = thresholds or {}
    groups: dict[str, list[dict[str, float]]] = {"approved": [], "not_approved": []}
    for r in records:
        scores = r.get("evaluation_scores")
        decision = r.get("decision")
        if not scores or decision not in {"approve", "modify", "reject"}:
            continue
        accepted = decision == "approve" or (decision == "modify" and modify_as_approved)
        groups["approved" if accepted else "not_approved"].append(
            {k: float(v) for k, v in scores.items() if isinstance(v, (int, float))})
    report = CalibrationReport(len(groups["approved"]) + len(groups["not_approved"]),
                               len(groups["approved"]), len(groups["not_approved"]))
    if report.decisions == 0:
        report.notes.append("no decisions with scores yet: partners must approve, modify or reject real runs first")
    metrics = sorted({k for g in groups.values() for s in g for k in s})
    for metric in metrics:
        pos = [s[metric] for s in groups["approved"] if metric in s]
        neg = [s[metric] for s in groups["not_approved"] if metric in s]
        best = best_threshold(pos, neg)
        limit = thresholds.get(POLICY_KEYS.get(metric, ""))
        m = MetricCalibration(
            metric, len(pos), len(neg), _mean(pos), _mean(neg), auc(pos, neg), best[0] if best else None,
            best[1] if best else None, limit,
            round(sum(n >= limit for n in neg) / len(neg), 4) if limit is not None and neg else None,
            round(sum(p < limit for p in pos) / len(pos), 4) if limit is not None and pos else None, "")
        m.verdict = _verdict(m)
        report.metrics.append(m)
    if report.decisions and min(report.approved, report.not_approved) < MIN_PER_CLASS:
        report.notes.append(f"{report.approved} approved and {report.not_approved} not-approved decisions: collect at least "
                            f"{MIN_PER_CLASS} of each before changing any threshold")
    return report
