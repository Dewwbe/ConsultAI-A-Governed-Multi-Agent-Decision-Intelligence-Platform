import type { DataClassification, EngagementRequest } from "@/api/types";

/** The API's limits (backend/app/schemas/api.py). Keep these in step with EngagementRequest. */
export const LIMITS = { problemMin: 5, problemMax: 4000, industryMax: 200, maxItems: 20 } as const;

export const CLASSIFICATIONS: { value: DataClassification; label: string; hint: string }[] = [
  { value: "confidential", label: "Confidential", hint: "Client-sensitive. Only approved Azure OpenAI models may process it." },
  { value: "internal", label: "Internal", hint: "Internal use. A wider set of approved providers is allowed." },
  { value: "public", label: "Public", hint: "Already public. Any approved provider may process it; only public material is used." },
];

export interface EngagementForm {
  business_problem: string;
  industry: string;
  /** One objective per line. */
  objectives: string;
  /** One constraint per line, for example "Budget under $10M". */
  constraints: string;
  data_classification: DataClassification;
}

export type FormErrors = Partial<Record<keyof EngagementForm, string>>;

export const EMPTY_FORM: EngagementForm = {
  business_problem: "",
  industry: "",
  objectives: "",
  constraints: "",
  data_classification: "confidential",
};

export const UAE_EXAMPLE: EngagementForm = {
  business_problem: "Should we expand into the UAE market?",
  industry: "Retail",
  objectives: "Increase revenue",
  constraints: "Budget under $10M\nLaunch within 18 months",
  data_classification: "confidential",
};

/** One entry per non-empty line, trimmed. */
export function parseLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
}

function validateList(label: string, items: string[]): string | undefined {
  if (items.length > LIMITS.maxItems) return `Use at most ${LIMITS.maxItems} ${label} (you have ${items.length}).`;
  return undefined;
}

export function validateEngagement(form: EngagementForm): { errors: FormErrors; payload: EngagementRequest | null } {
  const errors: FormErrors = {};
  const problem = form.business_problem.trim();
  if (!problem) errors.business_problem = "Describe the business question.";
  else if (problem.length < LIMITS.problemMin) errors.business_problem = `Use at least ${LIMITS.problemMin} characters.`;
  else if (problem.length > LIMITS.problemMax) errors.business_problem = `Use at most ${LIMITS.problemMax} characters (you have ${problem.length}).`;

  const industry = form.industry.trim();
  if (industry.length > LIMITS.industryMax) errors.industry = `Use at most ${LIMITS.industryMax} characters.`;

  const objectives = parseLines(form.objectives);
  const constraints = parseLines(form.constraints);
  const oe = validateList("objectives", objectives);
  if (oe) errors.objectives = oe;
  const ce = validateList("constraints", constraints);
  if (ce) errors.constraints = ce;

  if (Object.keys(errors).length > 0) return { errors, payload: null };
  return {
    errors,
    payload: { business_problem: problem, industry, objectives, constraints, data_classification: form.data_classification },
  };
}

/** Map server-reported field names (from a 422) onto form fields so the message lands next to the input. */
export function fieldErrorsFromServer(fields: string[], detail: string): FormErrors {
  const known: (keyof EngagementForm)[] = ["business_problem", "industry", "objectives", "constraints", "data_classification"];
  const out: FormErrors = {};
  for (const f of fields) {
    const key = known.find((k) => f === k || f.startsWith(`${k}.`));
    if (key) out[key] = detail;
  }
  return out;
}
