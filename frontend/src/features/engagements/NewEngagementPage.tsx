import { LoaderCircle, Play, Wand2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useCreateEngagement } from "@/api/hooks";
import { ValidationError } from "@/api/errors";
import { ErrorState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  CLASSIFICATIONS,
  EMPTY_FORM,
  LIMITS,
  UAE_EXAMPLE,
  fieldErrorsFromServer,
  validateEngagement,
  type EngagementForm,
  type FormErrors,
} from "./validation";

const inputClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm aria-[invalid=true]:border-destructive placeholder:text-muted-foreground";

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string | undefined;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

export function NewEngagementPage() {
  const navigate = useNavigate();
  const create = useCreateEngagement();
  const location = useLocation();
  // a question picked on the dashboard arrives pre-filled; the user can still edit everything
  const prefill = (location.state as { prefill?: EngagementForm } | null)?.prefill;
  const [form, setForm] = useState<EngagementForm>(() => prefill ?? EMPTY_FORM);
  const [errors, setErrors] = useState<FormErrors>({});
  const summaryRef = useRef<HTMLDivElement>(null);
  const [submitted, setSubmitted] = useState(false);

  const set = <K extends keyof EngagementForm>(key: K, value: EngagementForm[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }));
  };

  // After a failed submit, move focus to the error summary so keyboard and screen-reader users land on it.
  useEffect(() => {
    if (submitted && Object.values(errors).some(Boolean)) summaryRef.current?.focus();
  }, [submitted, errors]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    const { errors: found, payload } = validateEngagement(form);
    setErrors(found);
    if (!payload) return;
    create.mutate(payload, {
      onSuccess: (created) => void navigate(`/engagements/${created.workflow_id}`),
      onError: (err) => {
        if (err instanceof ValidationError) setErrors(fieldErrorsFromServer(err.fields, err.detail));
      },
    });
  };

  const messages = Object.entries(errors).filter((entry): entry is [string, string] => Boolean(entry[1]));
  const describedBy = (id: keyof EngagementForm, hint = false) =>
    errors[id] ? `${id}-error` : hint ? `${id}-hint` : undefined;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link to="/engagements" className="text-sm text-muted-foreground hover:underline">
          &larr; Engagements
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">New engagement</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Describe the decision. Agents research it, analyse the data, model the options and assess the risks; a partner approves
          the recommendation before anything is reported.
        </p>
      </div>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Engagement details</CardTitle>
            <CardDescription>Constraints are checked by code against every option.</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => { setForm(UAE_EXAMPLE); setErrors({}); }}>
            <Wand2 /> Use the UAE example
          </Button>
        </CardHeader>
        <CardContent>
          <form noValidate onSubmit={onSubmit} className="space-y-5" aria-label="New engagement">
            {messages.length > 0 && (
              <div
                ref={summaryRef}
                tabIndex={-1}
                role="alert"
                className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm"
              >
                <p className="font-semibold">Please fix {messages.length === 1 ? "this" : "these"} before starting:</p>
                <ul className="mt-1 list-disc pl-5">
                  {messages.map(([field, message]) => (
                    <li key={field}>
                      <a href={`#${field}`} className="underline">
                        {message}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <Field id="business_problem" label="Business question" error={errors.business_problem}
              hint={`${form.business_problem.trim().length}/${LIMITS.problemMax} characters`}>
              <textarea
                id="business_problem"
                rows={3}
                className={inputClass}
                value={form.business_problem}
                onChange={(e) => set("business_problem", e.target.value)}
                aria-invalid={Boolean(errors.business_problem)}
                aria-describedby={describedBy("business_problem", true)}
                aria-required="true"
                placeholder="Should we expand into the UAE market?"
              />
            </Field>

            <Field id="industry" label="Industry (optional)" error={errors.industry}>
              <input
                id="industry"
                className={cn(inputClass, "h-9")}
                value={form.industry}
                onChange={(e) => set("industry", e.target.value)}
                aria-invalid={Boolean(errors.industry)}
                aria-describedby={describedBy("industry")}
                placeholder="Retail"
              />
            </Field>

            <Field id="objectives" label="Objectives (optional)" error={errors.objectives} hint="One per line.">
              <textarea
                id="objectives"
                rows={2}
                className={inputClass}
                value={form.objectives}
                onChange={(e) => set("objectives", e.target.value)}
                aria-invalid={Boolean(errors.objectives)}
                aria-describedby={describedBy("objectives", true)}
                placeholder="Increase revenue"
              />
            </Field>

            <Field id="constraints" label="Constraints (optional)" error={errors.constraints}
              hint="One per line, for example “Budget under $10M” or “Launch within 18 months”. Budget and timeline limits are checked automatically; others are listed as unchecked assumptions.">
              <textarea
                id="constraints"
                rows={3}
                className={inputClass}
                value={form.constraints}
                onChange={(e) => set("constraints", e.target.value)}
                aria-invalid={Boolean(errors.constraints)}
                aria-describedby={describedBy("constraints", true)}
                placeholder={"Budget under $10M\nLaunch within 18 months"}
              />
            </Field>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Data classification</legend>
              {CLASSIFICATIONS.map((c) => (
                <label key={c.value} className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 has-[:checked]:border-primary has-[:checked]:bg-primary/5">
                  <input
                    type="radio"
                    name="data_classification"
                    value={c.value}
                    checked={form.data_classification === c.value}
                    onChange={() => set("data_classification", c.value)}
                    className="mt-1"
                  />
                  <span>
                    <span className="block text-sm font-medium">{c.label}</span>
                    <span className="block text-xs text-muted-foreground">{c.hint}</span>
                  </span>
                </label>
              ))}
            </fieldset>

            {create.isError && !(create.error instanceof ValidationError) && (
              <ErrorState error={create.error} onRetry={() => create.reset()} />
            )}

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={create.isPending}>
                {create.isPending ? <LoaderCircle className="motion-safe:animate-spin" /> : <Play />}
                {create.isPending ? "Starting…" : "Start engagement"}
              </Button>
              <Button asChild variant="ghost">
                <Link to="/engagements">Cancel</Link>
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
