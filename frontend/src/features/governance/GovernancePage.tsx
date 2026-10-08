import { Tabs } from "@/components/ui/tabs";
import { BudgetsTab } from "./BudgetsTab";
import { DegradationTab } from "./DegradationTab";
import { PolicyTab } from "./PolicyTab";
import { ProvidersTab } from "./ProvidersTab";
import { ToolsTab } from "./ToolsTab";

export function GovernancePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Governance</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The rules the agents run under and whether they are holding. Everything here is read-only; changes go through the policy file.
        </p>
      </div>
      <Tabs
        label="Governance sections"
        items={[
          { id: "policy", label: "Policy", content: <PolicyTab /> },
          { id: "tools", label: "Tools", content: <ToolsTab /> },
          { id: "providers", label: "Providers", content: <ProvidersTab /> },
          { id: "budgets", label: "Budgets", content: <BudgetsTab /> },
          { id: "degradation", label: "Quality", content: <DegradationTab /> },
        ]}
      />
    </div>
  );
}
