"""LangGraph state machine. Human approval is a first-class node using interrupt()."""
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.base import BaseAgent, RuntimeContext
from app.agents.data_analyst import DataAnalystAgent
from app.agents.discovery import DiscoveryAgent
from app.agents.financial import FinancialAgent
from app.agents.report import ReportAgent
from app.agents.research import ResearchAgent
from app.agents.risk import RiskAgent
from app.agents.solution import SolutionAgent
from app.control_plane.budget import BudgetExceeded
from app.control_plane.evaluator import evaluate
from app.control_plane.llm import LLMUnavailable, SchemaEscalation
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
            return agent_cls(ctx).run(state)
        except BudgetExceeded as exc:
            # Stop, explain, route to human review (never silently continue past a budget)
            ctx.log["failures"].append({"type": "budget_exceeded", "error": str(exc)})
            return _halt(f"{agent_cls.name}: {exc}")
        except (SchemaEscalation, LLMUnavailable) as exc:
            # malformed output after repair+fallback, or provider down: escalate to a human
            return _halt(f"{agent_cls.name}: {exc}")
    node.__name__ = agent_cls.name
    return node


def evaluate_node(state: EngagementState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    with ctx.trace.span("evaluator", "evaluator"):
        report = evaluate({**state, "guardian_decisions": ctx.log["guardian_decisions"],
                           "tool_calls": ctx.budget.tool_calls})
    return {"evaluation_scores": {**report.scores, "quality": report.quality},
            "failures": ctx.log["failures"] + [{"type": "eval_issue", "issue": i} for i in report.issues]}


def guardian_node(state: EngagementState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    from app.control_plane.evaluator import EvaluationReport
    scores = state["evaluation_scores"]
    report = EvaluationReport(scores={k: v for k, v in scores.items() if k != "quality"})
    with ctx.trace.span("guardian", "guardian"):
        decision = ctx.guardian.review_recommendation(state, report)
    ctx.log["guardian_decisions"].append(decision.to_dict())
    needs = decision.action == "ESCALATE" or state.get("approval_required", False)
    return {"risk_level": decision.risk_level, "approval_required": needs,
            "approval_status": ApprovalStatus.PENDING.value if needs else ApprovalStatus.NOT_REQUIRED.value,
            "guardian_decisions": ctx.log["guardian_decisions"]}


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
    return "approval" if state.get("approval_required") else "report"


def _after_approval(state: EngagementState) -> str:
    return END if state["approval_status"] == ApprovalStatus.REJECTED.value else "report"


def build_graph():
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
    g.add_conditional_edges("guardian", _after_guardian, {"approval": "approval", "report": "report"})
    g.add_conditional_edges("approval", _after_approval, {"report": "report", END: END})
    g.add_edge("report", END)
    return g.compile(checkpointer=MemorySaver())
