"use client";

import { useState } from "react";
import { Ban, Pause, Play, ShieldCheck } from "lucide-react";
import { post, usePoll } from "@/lib/api";
import { dateTime, humanize } from "@/lib/format";
import type { Overview, RiskConfig } from "@/lib/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge, Button, Card, ErrorBanner, Table, Td } from "@/components/ui";
import { BotSwitch } from "@/components/bot-switch";

type Action = "pause" | "resume" | "acknowledge-hold" | "close-all";

const ACTIONS: Record<Action, { title: string; description: string; label: string; danger?: boolean }> = {
  pause: {
    title: "Pause new entries?",
    description: "No new trades will be opened. Open trades keep their broker stop-loss and take-profit.",
    label: "Pause entries",
  },
  resume: { title: "Resume new entries?", description: "The bot may open new trades again.", label: "Resume entries" },
  "acknowledge-hold": {
    title: "Acknowledge the safety hold?",
    description: "Only do this after you checked the cause in MT5. The bot must have a fresh, clean reconciliation.",
    label: "Acknowledge",
  },
  "close-all": {
    title: "Close ALL bot positions?",
    description: "Every open bot position is closed at market within a few seconds. Manual trades are not touched.",
    label: "Close all positions",
    danger: true,
  },
};

const RISK_LABELS: Record<string, string> = {
  max_risk_percent: "Max risk per trade (%)",
  max_total_risk_percent: "Max total open risk (%)",
  max_daily_loss_percent: "Daily loss limit (%)",
  max_daily_entries: "Max entries per day",
  max_open_positions: "Max open positions",
  max_lot: "Max lot size",
  max_deviation_points: "Max slippage (points)",
};

export default function ControlsPage() {
  const overview = usePoll<Overview>("overview", 5_000);
  const config = usePoll<RiskConfig>("config", 60_000);
  const [action, setAction] = useState<Action | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const o = overview.data;
  const hold = o?.entries.safety_hold;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Controls</h1>
        <p className="text-sm text-slate-500">Every action requires a reason and is written to the audit log.</p>
      </div>
      <ErrorBanner message={overview.error} />
      {message && <p className="rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</p>}

      <Card title="Bot">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-sm text-slate-600">
              Status:{" "}
              {o ? (o.entries.bot_running ? <Badge tone="green">RUNNING</Badge> : <Badge>STOPPED</Badge>) : "—"}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Stopped: no new signals or trades. MT5 stays connected and open trades stay protected.
            </p>
          </div>
          <BotSwitch running={o?.entries.bot_running} onChanged={overview.refresh} size="lg" />
        </div>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="New entries">
          <p className="text-sm text-slate-600">
            Status:{" "}
            {o ? (
              o.entries.paused ? <Badge tone="amber">Paused</Badge> : <Badge tone="green">Active</Badge>
            ) : "—"}
          </p>
          {o && !o.entries.trading_enabled && (
            <p className="mt-2 text-xs text-amber-700">TRADING_ENABLED is off in the bot settings, so no entries are possible.</p>
          )}
          <div className="mt-4 flex gap-2">
            <Button variant="secondary" onClick={() => setAction("pause")} disabled={!o || o.entries.paused}>
              <Pause size={16} /> Pause
            </Button>
            <Button onClick={() => setAction("resume")} disabled={!o || !o.entries.paused}>
              <Play size={16} /> Resume
            </Button>
          </div>
        </Card>

        <Card title="Safety hold">
          {hold ? (
            <>
              <p className="text-sm text-rose-700">
                <strong>{humanize(hold.reason)}</strong> since {dateTime(hold.at)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                The bot stopped new entries because something needs a human check. Review MT5 first.
              </p>
            </>
          ) : (
            <p className="text-sm text-slate-600">No safety hold. The bot is operating normally.</p>
          )}
          <div className="mt-4">
            <Button variant="secondary" onClick={() => setAction("acknowledge-hold")} disabled={!hold}>
              <ShieldCheck size={16} /> Acknowledge hold
            </Button>
          </div>
        </Card>

        <Card title="Emergency" className="md:col-span-2">
          <p className="text-sm text-slate-600">
            Close every open bot position now ({o?.positions.length ?? 0} open). To also stop new trades, pause entries.
          </p>
          <div className="mt-4">
            <Button variant="danger" onClick={() => setAction("close-all")} disabled={!o || o.positions.length === 0}>
              <Ban size={16} /> Close all positions
            </Button>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Risk limits (read-only)">
          <Table head={["Limit", "Value"]}>
            {Object.entries(config.data?.risk ?? {}).map(([key, value]) => (
              <tr key={key}>
                <Td className="text-slate-600">{RISK_LABELS[key] ?? humanize(key)}</Td>
                <Td className="num font-medium">{value}</Td>
              </tr>
            ))}
          </Table>
          <p className="mt-3 text-xs text-slate-500">Change these in the bot&apos;s .env on the trading PC, then restart the bot.</p>
        </Card>
        <Card title="Symbols (read-only)">
          <Table head={["TradingView", "MT5", "Enabled", "Max spread", "Max lot"]}>
            {(config.data?.symbols ?? []).map((s) => (
              <tr key={s.tv_symbol}>
                <Td>{s.tv_symbol}</Td>
                <Td className="font-medium">{s.broker_symbol}</Td>
                <Td>{s.enabled ? <Badge tone="green">Yes</Badge> : <Badge>No</Badge>}</Td>
                <Td className="num">{s.max_spread_points}</Td>
                <Td className="num">{s.max_lot}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>

      <ConfirmDialog
        open={action !== null}
        title={action ? ACTIONS[action].title : ""}
        description={action ? ACTIONS[action].description : ""}
        confirmLabel={action ? ACTIONS[action].label : ""}
        danger={action ? ACTIONS[action].danger : false}
        onCancel={() => setAction(null)}
        onConfirm={async (note) => {
          if (!action) return;
          if (action === "close-all") {
            const res = await post<{ requested: number }>("positions/close-all", { note });
            setMessage(`Close requested for ${res.requested} position(s).`);
          } else {
            await post(`control/${action}`, { note });
            setMessage("Saved.");
          }
          setAction(null);
          overview.refresh();
        }}
      />
    </div>
  );
}
