import { Activity, Gauge, Inbox, Moon, ShieldCheck, Sun, SunMoon, UserRound } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useHealth, useMe } from "@/api/hooks";
import { useAuth, DEV_ROLES } from "@/auth/AuthProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTheme, type ThemePreference } from "@/lib/theme";
import { cn } from "@/lib/utils";

export interface NavItem {
  to: string;
  label: string;
  icon: typeof Gauge;
  /** Shown only to users holding one of these roles (a convenience: the server enforces access). */
  roles?: string[];
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/engagements", label: "Engagements", icon: Inbox },
  { to: "/control-center", label: "Control Center", icon: Activity },
  { to: "/governance", label: "Governance", icon: ShieldCheck, roles: ["Admin"] },
];

export function visibleNav(items: NavItem[], roles: string[] | undefined): NavItem[] {
  return items.filter((i) => !i.roles || i.roles.some((r) => roles?.includes(r)));
}

function ApiStatus() {
  const { data, isPending, isError } = useHealth();
  if (isPending) return <Badge aria-live="polite">Checking API…</Badge>;
  if (isError) return <Badge variant="destructive" aria-live="polite">API unreachable</Badge>;
  return (
    <Badge variant="success" aria-live="polite">
      API ok · {data.llm_provider}
    </Badge>
  );
}

const THEME_ORDER: ThemePreference[] = ["system", "light", "dark"];
const THEME_ICON = { system: SunMoon, light: Sun, dark: Moon } as const;

function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  const next = THEME_ORDER[(THEME_ORDER.indexOf(preference) + 1) % THEME_ORDER.length] ?? "system";
  const Icon = THEME_ICON[preference];
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setPreference(next)}
      aria-label={`Theme: ${preference}. Switch to ${next}`}
      title={`Theme: ${preference}`}
    >
      <Icon />
    </Button>
  );
}

/** Dev-only identity picker. Replaced by Microsoft sign-in in F2; hidden when AUTH_MODE is entra. */
function DevIdentityPicker() {
  const { mode, identity, setIdentity } = useAuth();
  if (mode !== "dev" || !identity) return null;
  const toggle = (role: string) =>
    setIdentity({
      ...identity,
      roles: identity.roles.includes(role) ? identity.roles.filter((r) => r !== role) : [...identity.roles, role],
    });
  return (
    <details className="relative">
      <summary className="flex h-9 cursor-pointer list-none items-center gap-2 rounded-md border bg-card px-3 text-sm hover:bg-muted">
        <UserRound className="size-4" aria-hidden="true" />
        <span>{identity.user}</span>
      </summary>
      <div className="absolute right-0 z-10 mt-2 w-64 space-y-3 rounded-lg border bg-card p-4 shadow-lg">
        <p className="text-xs text-muted-foreground">Development sign-in. The API only honours this in dev mode.</p>
        <label className="block text-sm">
          <span className="mb-1 block font-medium">User</span>
          <input
            className="h-9 w-full rounded-md border bg-background px-2"
            value={identity.user}
            onChange={(e) => setIdentity({ ...identity, user: e.target.value || "dev-user" })}
          />
        </label>
        <fieldset>
          <legend className="mb-1 text-sm font-medium">Roles</legend>
          {DEV_ROLES.map((role) => (
            <label key={role} className="flex items-center gap-2 py-0.5 text-sm">
              <input type="checkbox" checked={identity.roles.includes(role)} onChange={() => toggle(role)} />
              {role}
            </label>
          ))}
        </fieldset>
      </div>
    </details>
  );
}

export function AppShell() {
  const { data: me } = useMe();
  const items = visibleNav(NAV_ITEMS, me?.roles);
  return (
    <div className="min-h-screen md:grid md:grid-cols-[14rem_1fr]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <aside className="border-b bg-card md:border-b-0 md:border-r">
        <div className="flex items-center gap-2 px-4 py-3 md:py-5">
          <span aria-hidden="true" className="grid size-8 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
            C
          </span>
          <span className="text-base font-semibold">ConsultAI</span>
        </div>
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-4">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium hover:bg-muted",
                  isActive && "bg-secondary text-secondary-foreground",
                )
              }
            >
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-col">
        <header className="flex flex-wrap items-center justify-end gap-3 border-b bg-card px-4 py-3">
          <ApiStatus />
          <DevIdentityPicker />
          <ThemeToggle />
        </header>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
