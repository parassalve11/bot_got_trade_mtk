"use client";

import { useState } from "react";
import { post, usePoll } from "@/lib/api";
import { money, pct, plClass, tfLabel } from "@/lib/format";
import type { Strategy, StrategyMode } from "@/lib/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge, Card, ErrorBanner } from "@/components/ui";

const MODES: { key: StrategyMode; label: string; help: string }[] = [
  { key: "off", label: "Off", help: "Ignores signals" },
  { key: "watch", label: "Watch", help: "Records signals, no trades" },
  { key: "trade", label: "Trade", help: "Places real orders" },
];

const SECTIONS: [string, string][] = [
  ["swing", "Swing · 1-hour"],
  ["intraday", "Intraday · 15-minute"],
];

function Row({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-slate-500">{label}</span>
      <span className={`num font-medium ${tone}`}>{value}</span>
    </div>
  );
}

export default function StrategiesPage() {
  const { data, error, refresh } = usePoll<{ engine_mode: string; strategies: Strategy[] }>("strategies", 30_000);
  const [change, setChange] = useState<{ s: Strategy; mode: StrategyMode } | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Strategies</h1>
        <p className="text-sm text-slate-500">
          Backtest results next to live results. Switch a strategy to Trade only after its live signals match the backtest.
        </p>
      </div>
      <ErrorBanner message={error} />

      {SECTIONS.map(([group, heading]) => {
        const items = (data?.strategies ?? []).filter((s) => (s.group ?? "swing") === group);
        if (!items.length) return null;
        return (
      <section key={group} className="space-y-3">
      <h2 className="text-lg font-semibold text-slate-800">{heading}</h2>
      <div className="grid gap-6 lg:grid-cols-2">
        {items.map((s) => {
          const b = s.backtest;
          return (
            <Card
              key={`${s.instance}:${s.tv_symbol}`}
              title={
                <span className="flex items-center gap-2">
                  {s.tv_symbol.replace(/^[A-Z]+:/, "")} · {tfLabel(s.timeframe)}
                  <span className="font-normal text-slate-500">({s.instance})</span>
                </span>
              }
              action={
                <Badge tone={s.mode === "trade" ? "green" : s.mode === "watch" ? "blue" : "gray"}>
                  {s.mode.toUpperCase()}
                </Badge>
              }
            >
              <p className="text-xs text-slate-500">
                {s.settings.description ?? (
                  <>
                    Sensitivity {s.settings.sensitivity} · ATR {s.settings.atr_length} · Stop {s.settings.stop_atr}× ATR ·
                    Target {s.settings.reward_ratio}× · {s.settings.opposite_mode}
                    {s.settings.htf_filter !== "none" && " · 4H trend filter"} · Risk {s.settings.risk_percent}%
                  </>
                )}
              </p>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Backtest</p>
                  {b ? (
                    <div className="space-y-1.5">
                      <Row label="Trades" value={`${b.trades} (${b.wins}W / ${b.losses}L)`} />
                      <Row label="Win rate" value={pct(b.win_rate)} />
                      <Row label="Net result" value={money(b.net, "USD", true)} tone={plClass(b.net)} />
                      {b.max_drawdown !== null && <Row label="Worst drawdown" value={money(b.max_drawdown)} tone="text-rose-600" />}
                      <p className="pt-1 text-xs text-slate-500">{b.period}</p>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500">No backtest recorded.</p>
                  )}
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Live (this bot)</p>
                  <div className="space-y-1.5">
                    <Row label="Signals seen" value={String(s.live.signals)} />
                    <Row label="Trades" value={`${s.live.trades} (${s.live.wins}W / ${s.live.losses}L)`} />
                    <Row label="Win rate" value={pct(s.live.win_rate)} />
                    <Row label="Net result" value={money(s.live.net, "USD", true)} tone={plClass(s.live.net)} />
                  </div>
                </div>
              </div>

              <div className="mt-4">
                <div className="grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1">
                  {MODES.map((m) => (
                    <button key={m.key} onClick={() => m.key !== s.mode && setChange({ s, mode: m.key })}
                      className={`rounded-md px-2 py-1.5 text-sm font-medium ${
                        s.mode === m.key
                          ? m.key === "trade" ? "bg-emerald-600 text-white" : "bg-white text-slate-900 shadow-sm"
                          : "text-slate-600 hover:text-slate-900"
                      }`}>
                      {m.label}
                    </button>
                  ))}
                </div>
                {!s.symbol_enabled && (
                  <p className="mt-2 text-xs text-amber-700">
                    {s.tv_symbol} is disabled in the bot&apos;s symbol settings, so Trade mode is not available yet.
                  </p>
                )}
              </div>
            </Card>
          );
        })}
      </div>
      </section>
        );
      })}

      <ConfirmDialog
        open={change !== null}
        title={`Switch ${change?.s.instance} to ${change?.mode.toUpperCase()}?`}
        description={
          change?.mode === "trade" ? (
            <span className="text-rose-700">
              The bot will place <strong>real orders</strong> on the MT5 account for this strategy (
              {change?.s.settings.risk_percent}% risk per trade).
            </span>
          ) : (
            MODES.find((m) => m.key === change?.mode)?.help
          )
        }
        confirmLabel={`Switch to ${change?.mode ?? ""}`}
        danger={change?.mode === "trade"}
        onCancel={() => setChange(null)}
        onConfirm={async (note) => {
          if (!change) return;
          await post("strategies/mode", { instance: change.s.instance, tv_symbol: change.s.tv_symbol, mode: change.mode, note });
          setChange(null);
          refresh();
        }}
      />
    </div>
  );
}
