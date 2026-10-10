from __future__ import annotations

from typing import Any

from .base import BaseAgent

# The scores a reader needs, in plain words, in the order they matter.
SCORE_LABELS = {
    "groundedness": "Claims supported by evidence",
    "citation_validity": "Quotes verified in their sources",
    "constraint_satisfaction": "Options meeting your constraints",
    "contradiction_free": "Free of contradictions",
    "completeness": "Completeness",
    "policy_compliance": "Policy compliance",
}
DECISION_WORDS = {"approve": "Approved", "modify": "Approved with changes", "reject": "Rejected"}


def _money(v: float) -> str:
    return f"${v:,.0f}"


class ReportAgent(BaseAgent):
    """Assembles the client-facing report only from validated, approved outputs. Each part is its own numbered
    section, separated by a rule, so it reads as a document rather than a list of fields."""
    name = "report_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        rec = view["recommendation"]
        numbers = iter(range(1, 20))
        heading = lambda title: f"## {next(numbers)}. {title}"  # sections are numbered in the order they appear
        feedback = view.get("approval_feedback") or {}
        decision = DECISION_WORDS.get(feedback.get("decision", ""), str(view.get("approval_status", "n/a")).title())
        lines = [
            f"# Engagement Report: {view['engagement_spec']['decision_question']}",
            f"*Partner decision: {decision}*",
            "", "---", "", heading("Recommendation"),
            f"**Option {rec['id']}: {rec['name']}**", "", rec["rationale"], "",
            f"- **Investment:** {_money(rec['cost_usd'])}",
            f"- **Return on investment:** {rec['roi']:.0%}",
        ]
        if rec.get("npv") is not None:
            lines.append(f"- **Net present value:** {_money(rec['npv'])}")
        if rec.get("payback_years") is not None:
            lines.append(f"- **Payback:** {rec['payback_years']:.1f} years")
        if rec.get("launch_months") is not None:
            lines.append(f"- **Time to launch:** {rec['launch_months']:.0f} months")
        lines.append(f"- **Risk:** {rec['risk']}")

        if feedback:
            lines += ["", "---", "", heading("Partner decision"), f"- **Decision:** {decision}"]
            if feedback.get("reason"):
                lines.append(f"- **Reason:** {feedback['reason']}")
            for field, value in (feedback.get("changes") or {}).items():
                shown = "; ".join(value) if isinstance(value, list) else value
                lines.append(f"- **Edited {field}:** {shown}")

        lines += ["", "---", "", heading("Options considered")]
        for o in view.get("options", []):
            chosen = " (recommended)" if o["id"] == rec["id"] else ""
            fits = "Yes" if o.get("within_constraints", o.get("within_budget")) else \
                "No: " + "; ".join(o.get("constraint_violations") or ["outside budget"])
            lines += [f"### Option {o['id']}: {o['name']}{chosen}",
                      f"- Investment {_money(o['cost_usd'])} · ROI {o['roi']:.0%} · Risk {o['risk']}",
                      f"- Meets your constraints: {fits}", ""]

        risks = sorted(view.get("risks") or [], key=lambda r: -r.get("risk_score", 0))[:5]
        if risks:
            lines += ["---", "", heading("Key risks")]
            for r in risks:
                review = " Needs a partner's judgement." if r.get("requires_human_review") else ""
                lines.append(f"- **{r['risk']}** ({r.get('category', 'General')}, score {r.get('risk_score', 0):.2f}): "
                             f"{r.get('mitigation', 'no mitigation recorded')}.{review}")
            lines.append("")

        if rec.get("assumptions"):
            lines += ["---", "", heading("Assumptions")] + [f"- {a}" for a in rec["assumptions"]] + [""]

        scores = view.get("evaluation_scores", {})
        shown = [(label, scores[k]) for k, label in SCORE_LABELS.items() if isinstance(scores.get(k), (int, float))]
        if shown:
            lines += ["---", "", heading("Quality checks"),
                      "Scored 0 to 1 by automatic checks and an independent reviewer model."]
            lines += [f"- {label}: {v:.2f}" for label, v in shown]
        return {"report": {"markdown": "\n".join(lines)}}
