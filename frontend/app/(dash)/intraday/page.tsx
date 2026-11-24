"use client";

import Link from "next/link";
import { useMemo } from "react";
import { usePoll } from "@/lib/api";
import { money, pct, plClass, tfLabel } from "@/lib/format";
import type { ClosedPosition, OpenPosition, Signal, Strategy, Summary } from "@/lib/types";
import { OpenPositionsTable } from "@/components/positions-table";
import { SignalsTable } from "@/components/signals-list";
import { ClosedTradesTable, summarize } from "@/components/trades";
import { Badge, Card, Empty, ErrorBanner, Stat } from "@/components/ui";

type Positions = { open: OpenPosition[]; closed: ClosedPosition[]; summary: Summary };

function Row({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-slate-500">{label}</span>
      <span className={`num font-medium ${tone}`}>{value}</span>
    </div>
  );
}

function startOfToday(): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

export default function IntradayPage() {
  const positions = usePoll<Positions>("positions", 15_000);
  const strategies = usePoll<{ strategies: Strategy[] }>("strategies", 30_000);
  const signals = usePoll<{ signals: Signal[] }>("signals?limit=200", 30_000);

  const open = useMemo(() => (positions.data?.open ?? []).filter((p) => p.group === "intraday"), [positions.data]);
  const closed = useMemo(() => (positions.data?.closed ?? []).filter((c) => c.group === "intraday"), [positions.data]);
  const streams = useMemo(
    () => (strategies.data?.strategies ?? []).filter((s) => s.group === "intraday"),
    [strategies.data],
  );
  const sigs = useMemo(() => (signals.data?.signals ?? []).filter((s) => s.group === "intraday"), [signals.data]);

  const all = summarize(closed);
  const today = summarize(closed.filter((c) => (c.closed_at ?? 0) >= startOfToday()));
  const floating = open.reduce((a, p) => a + (p.profit ?? 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Intraday · 15-minute</h1>
        <p className="text-sm text-slate-500">
          Short-term trades on 15-minute charts, kept separate from the 1-hour swing trades on the{" "}
          <Link href="/positions" className="font-medium text-indigo-600 hover:underline">Positions page</Link>.
          A trade usually lasts 15 minutes to 2 hours.
        </p>
      </div>
      <ErrorBanner message={positions.error ?? strategies.error ?? signals.error} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Open now" value={String(open.length)}
          hint={open.length ? <span className={plClass(floating)}>{money(floating, "USD", true)} floating</span> : "No open trade"} />
        <Stat label="Today" value={money(today.net, "USD", true)} tone={plClass(today.net)}
          hint={`${today.trades} trades · ${today.wins}W / ${today.losses}L`} />
        <Stat label="Win rate (all)" value={pct(all.win_rate)} hint={`${all.trades} closed trades`} />
        <Stat label="Net result (all)" value={money(all.net, "USD", true)} tone={plClass(all.net)}
          hint={`won ${money(all.gross_profit)} · lost ${money(all.gross_loss)}`} />
      </div>

      <Card title="15-minute strategies">
        {streams.length ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {streams.map((s) => {
              const live = s.live;
              const b = s.backtest;
              return (
                <div key={`${s.instance}:${s.tv_symbol}`} className="rounded-lg border border-slate-200 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold text-slate-900">
                      {s.tv_symbol.replace(/^[A-Z]+:/, "")} · {tfLabel(s.timeframe)}
                      <span className="ml-2 text-sm font-normal text-slate-500">({s.instance})</span>
                    </p>
                    <Badge tone={s.mode === "trade" ? "green" : s.mode === "watch" ? "blue" : "gray"}>{s.mode.toUpperCase()}</Badge>
                  </div>
                  {s.settings.description && <p className="mt-1 text-xs text-slate-500">{s.settings.description}</p>}
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">MT5 test</p>
                      {b ? (
                        <div className="space-y-1.5">
                          <Row label="Trades" value={`${b.trades} (${b.wins}W / ${b.losses}L)`} />
                          <Row label="Win rate" value={pct(b.win_rate)} />
                          <Row label="Net result" value={money(b.net, "USD", true)} tone={plClass(b.net)} />
                        </div>
                      ) : (
                        <p className="text-sm text-slate-500">No test recorded.</p>
                      )}
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Live</p>
                      <div className="space-y-1.5">
                        <Row label="Signals" value={String(live.signals)} />
                        <Row label="Trades" value={`${live.trades} (${live.wins}W / ${live.losses}L)`} />
                        <Row label="Win rate" value={pct(live.win_rate)} />
                        <Row label="Net result" value={money(live.net, "USD", true)} tone={plClass(live.net)} />
                      </div>
                    </div>
                  </div>
                  {b?.note && <p className="mt-2 text-xs text-slate-500">{b.note}</p>}
                </div>
              );
            })}
          </div>
        ) : (
          <Empty>No 15-minute strategy is configured.</Empty>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Switch a strategy between Off / Watch / Trade on the{" "}
          <Link href="/strategies" className="font-medium text-indigo-600 hover:underline">Strategies page</Link>.
        </p>
      </Card>

      <Card title={`Open intraday trades (${open.length})`}>
        <OpenPositionsTable positions={open} onChanged={positions.refresh} />
      </Card>

      <Card title={`Closed intraday trades (${closed.length})`}>
        <ClosedTradesTable rows={closed} empty="No 15-minute trades closed yet." />
      </Card>

      <Card title="15-minute signals">
        <SignalsTable signals={sigs.slice(0, 50)} />
      </Card>
    </div>
  );
}
