"""LangGraph state machine. Human approval is a first-class node using interrupt()."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.base import BaseAgent, InsufficientData, RuntimeContext
from app.agents.data_analyst import DataAnalystAgent
from app.agents.discovery import DiscoveryAgent
from app.agents.financial import FinancialAgent
from app.agents.report import ReportAgent
from app.agents.research import ResearchAgent
from app.agents.risk import RiskAgent
from app.agents.solution import SolutionAgent
from app.control_plane.budget import BudgetExceeded
from app.control_plane.evaluator import EvaluationReport, evaluate
from app.control_plane.executor import ToolArgsInvalid, ToolBlocked
from app.control_plane.guardian import GuardianDecision
from app.control_plane.guardian_llm import llm_review, merge
from app.control_plane.judge import judge_evaluate
from app.control_plane.llm import LLMUnavailable, SchemaEscalation
from app.control_plane.timeouts import ToolTimeoutError
from app.schemas.state import ApprovalStatus, EngagementState

# workflow_id -> RuntimeContext (non-serialisable objects stay out of graph state)
RUNTIMES: dict[str, RuntimeContext] = {}


def _ctx(config: RunnableConfig) -> RuntimeContext:
    return RUNTIMES[config["configurable"]["thread_id"]]


def _halt(reason: str) -> dict[str, Any]:
    return {"halted": reason, "approval_required": True, "approval_status": ApprovalStatus.PENDING.value}


def _agent_node(agent_cls: type[BaseAgent]):
    def node(state: EngagementState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        if state.get("halted"):  # an earlier agent escalated: do no further work
            return {}
        try:
            ctx.budget.check()  # the workflow deadline applies between agents too, not only inside tool calls
            return agent_cls(ctx).run(state)
        except BudgetExceeded as exc:
            # Stop, explain, route to human review (never silently continue past a budget)
            ctx.log["failures"].append({"type": "budget_exceeded", "error": str(exc)})
            return _halt(f"{agent_cls.name}: {exc}")
        except (SchemaEscalation, LLMUnavailable, InsufficientData) as exc:
            # malformed output after repair+fallback, or provider down: escalate to a human
            return _halt(f"{agent_cls.name}: {exc}")
        except (ToolTimeoutError, ToolBlocked, ToolArgsInvalid) as exc:
            # a tool that keeps timing out, or that the policy refused, is a reason to stop and ask a human, not to crash
            ctx.log["failures"].append({"type": "tool_escalation", "agent": agent_cls.name, "error": str(exc)})
            return _halt(f"{agent_cls.name}: tool failed ({type(exc).__name__}): {exc}")
    node.__name__ = agent_cls.name
    return node


def evaluate_node(state: EngagementState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    with ctx.trace.span("evaluator", "evaluator"):
        base = evaluate({**state, "guardian_decisions": ctx.log["guardian_decisions"],
                         "tool_calls": ctx.budget.tool_calls})
        report = judge_evaluate(ctx.llm, dict(state), base, [s.__dict__ for s in ctx.trace.spans],
                                ctx.log["failures"])
    return {"evaluation_scores": {**report.scores, "quality": report.quality},
            "failures": ctx.log["failures"] + [{"type": "eval_issue", "issue": i} for i in report.issues]}


def guardian_node(state: EngagementState, config: RunnableConfig) -> dict[str, Any]:
    """Layer 1 (deterministic) then layer 2 (LLM reviewer, stricter-only). A fixable defect sends
    the recommendation back to the Solution Agent once before any human sees it."""
    ctx = _ctx(config)
    scores = state["evaluation_scores"]
    issues = [f["issue"] for f in state.get("failures", []) if f.get("type") == "eval_issue"]
    report = EvaluationReport(scores={k: v for k, v in scores.items() if k != "quality"}, issues=issues)
    retries = state.get("retry_count", 0)
    retries_left = ctx.guardian.max_retries() - retries
    with ctx.trace.span("guardian", "guardian"):
        defects = ctx.guardian.fixable_defects(state, report) if retries_left > 0 else []
        if defects:
            decision = GuardianDecision("RETRY", "medium", 0.5, defects, feedback="; ".join(defects)[:1000],
                                        policy_version=ctx.policy.version)
        else:
            base = ctx.guardian.review_recommendation(state, report)
            review = llm_review(ctx.llm, dict(state), report, base)
            decision = merge(base, review, retries_left) if review else base
    if ctx.degradation.actions.require_review and decision.action in {"ALLOW", "MODIFY"}:
        # autonomy is reduced while quality is degraded: nothing completes without a human
        decision = replace(decision, action="ESCALATE", risk_level="high", source="combined",
                           risk_score=max(decision.risk_score, 0.8),
                           reasons=[*decision.reasons, f"quality degradation ({ctx.degradation.level}): every run requires review"])
    ctx.log["guardian_decisions"].append(decision.to_dict())
    if decision.action == "RETRY":
        return {"retry_count": retries + 1, "guardian_feedback": decision.feedback,
                "guardian_route": "retry", "guardian_decisions": ctx.log["guardian_decisions"]}
    update: dict[str, Any] = {"risk_level": decision.risk_level, "guardian_feedback": "",
                              "guardian_decisions": ctx.log["guardian_decisions"]}
    if decision.action == "BLOCK":
        update.update(halted="guardian blocked the recommendation: " + "; ".join(decision.reasons)[:400],
                      approval_required=True, approval_status=ApprovalStatus.PENDING.value,
                      guardian_route="halt")
        return update
    if decision.action == "MODIFY" and decision.modifications.get("caveats"):
        rec = state["recommendation"]
        update["recommendation"] = {**rec, "assumptions": [
            *rec.get("assumptions", []), *(f"Reviewer caveat: {c}" for c in decision.modifications["caveats"])]}
    needs = decision.action == "ESCALATE" or state.get("approval_required", False)
    update.update(approval_required=needs, guardian_route="approval" if needs else "report",
                  approval_status=(ApprovalStatus.PENDING.value if needs
                                   else ApprovalStatus.NOT_REQUIRED.value))
    return update


def approval_node(state: EngagementState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    with ctx.trace.span("human_approval", "approval"):
        answer = interrupt({
            "recommendation": state.get("recommendation"),
            "scores": state.get("evaluation_scores"),
            "risk_level": state.get("risk_level"),
            "guardian": state.get("guardian_decisions", [])[-1:],
            "cost_usd": round(ctx.budget.cost_usd, 4),
        })
    decision = answer.get("decision")
    update: dict[str, Any] = {"approval_feedback": answer}
    if decision == "approve":
        update["approval_status"] = ApprovalStatus.APPROVED.value
    elif decision == "modify":
        update["approval_status"] = ApprovalStatus.MODIFIED.value
        update["recommendation"] = {**state["recommendation"], **answer.get("changes", {})}
    else:
        update["approval_status"] = ApprovalStatus.REJECTED.value
    # Every human decision becomes evaluation data (and later, fine-tuning data)
    ctx.memory.remember("human_feedback", __import__("app.memory.store", fromlist=["MemoryItem"]).MemoryItem(
        type="decision", scope="global", source="human",
        value={"recommendation": state.get("recommendation"), "scores": state.get("evaluation_scores"),
               "guardian": state.get("guardian_decisions", [])[-1:], "human": answer}))
    return update


def _after_solution(state: EngagementState) -> str:
    return END if state.get("halted") else "evaluate"  # escalated: stop, a human investigates


def _after_guardian(state: EngagementState) -> str:
    if state.get("halted"):
        return END
    return state.get("guardian_route") or ("approval" if state.get("approval_required") else "report")


def _after_approval(state: EngagementState) -> str:
    return END if state["approval_status"] == ApprovalStatus.REJECTED.value else "report"


def build_graph(checkpointer: Any = None):
    g = StateGraph(EngagementState)
    g.add_node("discovery", _agent_node(DiscoveryAgent))
    g.add_node("research", _agent_node(ResearchAgent))
    g.add_node("data", _agent_node(DataAnalystAgent))
    g.add_node("financial", _agent_node(FinancialAgent))
    g.add_node("risk", _agent_node(RiskAgent))
    g.add_node("solution", _agent_node(SolutionAgent))
    g.add_node("evaluate", evaluate_node)
    g.add_node("guardian", guardian_node)
    g.add_node("approval", approval_node)
    g.add_node("report", _agent_node(ReportAgent))

    g.add_edge(START, "discovery")
    g.add_edge("discovery", "research")   # research and data run in parallel
    g.add_edge("discovery", "data")
    g.add_edge(["research", "data"], "financial")  # join
    g.add_edge("financial", "risk")       # risk consumes financial output (see views.py)
    g.add_edge("risk", "solution")
    g.add_conditional_edges("solution", _after_solution, {END: END, "evaluate": "evaluate"})
    g.add_edge("evaluate", "guardian")
    g.add_conditional_edges("guardian", _after_guardian, {"approval": "approval", "report": "report",
                                                          "retry": "solution", END: END})
    g.add_conditional_edges("approval", _after_approval, {"report": "report", END: END})
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
