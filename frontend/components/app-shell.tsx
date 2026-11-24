"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Activity, BarChart3, Gauge, LogOut, Radio, ScrollText, Settings2, Timer, Zap } from "lucide-react";
import { usePoll } from "@/lib/api";
import type { Overview } from "@/lib/types";
import { Badge, Dot } from "@/components/ui";
import { BotSwitch } from "@/components/bot-switch";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/positions", label: "Positions", icon: BarChart3 },
  { href: "/intraday", label: "Intraday 15m", icon: Timer },
  { href: "/signals", label: "Signals", icon: Radio },
  { href: "/strategies", label: "Strategies", icon: Activity },
  { href: "/controls", label: "Controls", icon: Settings2 },
  { href: "/logs", label: "Logs", icon: ScrollText },
];

async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.replace("/login");
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const overview = usePoll<Overview>("overview", 15_000);
  const o = overview.data;
  const hold = o?.entries.safety_hold;
  const entriesState = !o
    ? null
    : !o.entries.bot_running
      ? { tone: "gray" as const, text: "BOT STOPPED" }
      : hold
      ? { tone: "red" as const, text: "SAFETY HOLD" }
      : o.entries.paused || o.daily.paused_by_loss || !o.entries.trading_enabled
        ? { tone: "amber" as const, text: "ENTRIES PAUSED" }
        : { tone: "green" as const, text: "ENTRIES ACTIVE" };

  return (
    <>
      <div className="min-h-screen">
        <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
            <Link href="/" className="flex items-center gap-2 font-semibold text-slate-900">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
                <Zap size={18} />
              </span>
              <span className="hidden sm:inline">BYTEFX Trader</span>
            </Link>
            <nav className="flex flex-1 gap-1 overflow-x-auto">
              {NAV.map(({ href, label, icon: Icon }) => {
                const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium ${
                      active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    <Icon size={16} />
                    <span className="hidden md:inline">{label}</span>
                  </Link>
                );
              })}
            </nav>
            <BotSwitch running={o?.entries.bot_running} onChanged={overview.refresh} />
            <button onClick={logout} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" title="Sign out">
              <LogOut size={18} />
            </button>
          </div>
          <div className="border-t border-slate-100 bg-slate-50/80">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2">
              {o ? (
                <>
                  <Dot ok={o.health.api} label="API" />
                  <Dot ok={o.health.worker} label="Worker" />
                  <Dot ok={o.health.mt5} label="MT5" />
                  <Badge tone={o.health.trading_mode === "LIVE" ? "red" : "blue"}>{o.health.trading_mode}</Badge>
                  {entriesState && <Badge tone={entriesState.tone}>{entriesState.text}</Badge>}
                  <span className="text-xs text-slate-500">
                    {o.account.server} · {o.account.login} · engine {o.health.engine_mode}
                  </span>
                </>
              ) : (
                <span className="text-xs text-slate-500">{overview.error ?? "Connecting to the bot…"}</span>
              )}
            </div>
          </div>
          {hold && (
            <div className="border-t border-rose-200 bg-rose-50 px-4 py-2 text-center text-sm text-rose-700">
              Safety hold: <strong>{hold.reason.replace(/_/g, " ")}</strong>. New entries are blocked until it is reviewed on
              the Controls page.
            </div>
          )}
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </div>
    </>
  );
}
