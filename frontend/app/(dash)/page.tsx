"use client";

import Link from "next/link";
import { usePoll } from "@/lib/api";
import { ago, money, pct, plClass } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { EquityChart } from "@/components/equity-chart";
import { OpenPositionsTable } from "@/components/positions-table";
import { SignalsTable } from "@/components/signals-list";
import { Card, ErrorBanner, Stat, SummaryTable } from "@/components/ui";

type EquityPoint = { at: number; balance: number; equity: number };

export default function OverviewPage() {
  const { data: o, error, refresh } = usePoll<Overview>("overview", 5_000);
  const equity = usePoll<{ points: EquityPoint[] }>("equity?days=30", 60_000);
  const currency = o?.account.currency ?? "USD";
  const lossUsed = o ? Math.min(100, (o.daily.loss_used_percent / o.daily.loss_limit_percent) * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Overview</h1>
          <p className="text-sm text-slate-500">
            Live account data from MT5 · updated {o ? ago(o.account.snapshot_at) : "…"}
          </p>
        </div>
      </div>
      <ErrorBanner message={error} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Balance" value={money(o?.account.balance, currency)} />
        <Stat label="Equity" value={money(o?.account.equity, currency)} />
        <Stat label="Floating P/L" value={money(o?.account.floating, currency, true)} tone={plClass(o?.account.floating)} />
        <Stat label="Today P/L" value={money(o?.daily.today_pl, currency, true)} tone={plClass(o?.daily.today_pl)}
          hint={o ? `from ${money(o.daily.starting_equity, currency)} at 00:00 UTC` : undefined} />
        <Stat label="Open trades" value={o ? `${o.positions.length} / ${o.limits.max_open_positions}` : "—"}
          hint={o ? `Free margin ${money(o.account.margin_free, currency)}` : undefined} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Equity curve (30 days)" className="lg:col-span-2">
          <EquityChart points={equity.data?.points ?? []} />
        </Card>
        <Card title="Today's risk">
          <div className="space-y-5">
            <div>
              <div className="flex justify-between text-sm">
                <span className="text-slate-600">Daily loss limit</span>
                <span className="num font-medium">
                  {o ? `${o.daily.loss_used_percent.toFixed(2)}% of ${o.daily.loss_limit_percent}%` : "—"}
                </span>
              </div>
              <div className="mt-2 h-2 rounded-full bg-slate-100">
                <div
                  className={`h-2 rounded-full ${lossUsed > 75 ? "bg-rose-500" : lossUsed > 40 ? "bg-amber-500" : "bg-emerald-500"}`}
                  style={{ width: `${lossUsed}%` }}
                />
              </div>
              {o?.daily.paused_by_loss && <p className="mt-2 text-xs text-rose-600">Limit reached: entries paused until tomorrow.</p>}
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-600">Entries today</span>
              <span className="num font-medium">{o ? `${o.daily.entries} / ${o.daily.max_entries}` : "—"}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-600">Risk per trade</span>
              <span className="num font-medium">{o ? `${o.limits.max_risk_percent}% max` : "—"}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-600">Closed bot trades</span>
              <span className="num font-medium">
                {o ? `${o.summary.wins}W / ${o.summary.losses}L · ${pct(o.summary.win_rate)}` : "—"}
              </span>
            </div>
          </div>
        </Card>
      </div>

      <Card title="Open positions" action={<Link href="/positions" className="text-sm text-indigo-600 hover:underline">All positions →</Link>}>
        <OpenPositionsTable positions={o?.positions ?? []} onChanged={refresh} />
      </Card>

      <Card title="Bot trade results (closed)">
        <SummaryTable rows={[{ label: "All strategies", s: o?.summary ?? null }]} />
      </Card>

      <Card title="Latest signals" action={<Link href="/signals" className="text-sm text-indigo-600 hover:underline">All signals →</Link>}>
        <SignalsTable signals={o?.signals ?? []} />
      </Card>
    </div>
  );
}
