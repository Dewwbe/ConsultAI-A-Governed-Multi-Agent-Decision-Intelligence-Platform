from __future__ import annotations

from typing import Any

from .base import BaseAgent


class ReportAgent(BaseAgent):
    """Assembles the client-facing report only from validated, approved outputs."""
    name = "report_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        rec = view["recommendation"]
        lines = [
            f"# Engagement Report: {view['engagement_spec']['decision_question']}",
            f"**Recommendation:** Option {rec['id']} — {rec['name']}",
            f"- Cost: ${rec['cost_usd']:,.0f} | ROI: {rec['roi']:.0%} | Risk: {rec['risk']}",
            f"- Rationale: {rec['rationale']}",
            f"- Approval: {view.get('approval_status', 'n/a')}",
            "", "## Options considered",
        ]
        for o in view.get("options", []):
            lines.append(f"- {o['id']} {o['name']}: ${o['cost_usd']:,.0f}, ROI {o['roi']:.0%}, "
                         f"risk {o['risk']}, within budget: {o['within_budget']}")
        lines += ["", "## Quality scores"] + [f"- {k}: {v:.2f}" for k, v in
                                               view.get("evaluation_scores", {}).items()]
        return {"report": {"markdown": "\n".join(lines)}}
