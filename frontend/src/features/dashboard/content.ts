import {
  BarChart3,
  Calculator,
  ClipboardCheck,
  Database,
  FileText,
  Lightbulb,
  Search,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { EngagementForm } from "@/features/engagements/validation";

export interface AgentInfo {
  /** The agent's name in traces and cost reports. */
  key: string;
  name: string;
  role: string;
  uses: string;
  Icon: LucideIcon;
  /** pipeline stage, for the order shown */
  stage: "understand" | "analyse" | "decide" | "control";
}

/** Every agent in the pipeline, in the order a run meets them. */
export const AGENTS: AgentInfo[] = [
  { key: "discovery_agent", name: "Discovery", role: "Turns the question into a precise brief: the decision, success measures and the data needed.", uses: "Question, objectives, constraints", Icon: Lightbulb, stage: "understand" },
  { key: "research_agent", name: "Research", role: "Finds market evidence and quotes it with its source, so every claim can be checked.", uses: "Knowledge base search", Icon: Search, stage: "understand" },
  { key: "data_agent", name: "Data Analyst", role: "Writes read-only SQL against approved tables to get the company's own baseline.", uses: "Data warehouse (SELECT only)", Icon: Database, stage: "understand" },
  { key: "financial_agent", name: "Financial", role: "Builds the scenarios. Every figure (ROI, NPV, payback) comes from a calculation tool, never from model text.", uses: "Financial calculation tools", Icon: Calculator, stage: "analyse" },
  { key: "risk_agent", name: "Risk", role: "Scores risks by likelihood and impact, with mitigations and past precedents.", uses: "Risk taxonomy, precedents", Icon: TriangleAlert, stage: "analyse" },
  { key: "solution_agent", name: "Solution", role: "Compares the options against your constraints and recommends one, with its reasoning.", uses: "Options, constraints", Icon: BarChart3, stage: "decide" },
  { key: "evaluator", name: "Evaluator", role: "Checks the work: are claims grounded in sources, constraints met, and the numbers consistent?", uses: "Deterministic checks + an LLM judge", Icon: ClipboardCheck, stage: "control" },
  { key: "guardian", name: "Guardian", role: "Applies policy. Allows, blocks, or escalates to a partner when the stakes or risks are high.", uses: "Policy rules + an AI reviewer", Icon: ShieldCheck, stage: "control" },
  { key: "report_agent", name: "Report", role: "Writes the client-facing report, only after a partner approves.", uses: "Approved outputs only", Icon: FileText, stage: "decide" },
];

export const STAGE_LABEL: Record<AgentInfo["stage"], string> = {
  understand: "Understand",
  analyse: "Analyse",
  decide: "Decide",
  control: "Control",
};

export interface ExampleQuestion {
  category: string;
  form: EngagementForm;
}

const base = { data_classification: "confidential" as const };

/** Questions that fit the platform: a yes/no strategic decision with money, time and risk attached. */
export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  { category: "Market entry", form: { ...base, business_problem: "Should we expand into the UAE market?", industry: "Retail", objectives: "Increase revenue", constraints: "Budget under $10M\nLaunch within 18 months" } },
  { category: "Market entry", form: { ...base, business_problem: "Should we enter the Saudi market next year?", industry: "Retail", objectives: "Grow regional market share", constraints: "Budget under $8M\nLaunch within 12 months" } },
  { category: "Investment", form: { ...base, business_problem: "Should we acquire a regional competitor?", industry: "Retail", objectives: "Increase market share\nAdd store locations", constraints: "Budget under $25M\nClose within 12 months" } },
  { category: "Operations", form: { ...base, business_problem: "Should we open a second distribution centre?", industry: "Logistics", objectives: "Cut delivery times\nReduce stockouts", constraints: "Budget under $6M\nOperational within 9 months" } },
  { category: "Growth", form: { ...base, business_problem: "Should we launch an online store for our top product categories?", industry: "Retail", objectives: "Increase online revenue", constraints: "Budget under $3M\nLaunch within 6 months" } },
  { category: "Growth", form: { ...base, business_problem: "Should we move to a franchise model for new regions?", industry: "Retail", objectives: "Expand faster with less capital", constraints: "Keep brand standards\nBudget under $5M" } },
];

export const GOOD_FITS = [
  "Go / no-go strategic decisions: enter a market, expand, acquire, open a site, launch a channel",
  "Questions with a budget and a deadline, so options can be checked against them",
  "Decisions where you want the evidence, the numbers and the risks laid out side by side",
];

export const NOT_FOR = [
  "Legal or regulatory advice: the platform flags these risks for a person to judge",
  "Live prices or today's news: evidence comes from the indexed knowledge base",
  "Anything about named individuals: personal data is redacted before it reaches a model",
];
