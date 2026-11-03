"use client";

import { useMemo, useState } from "react";
import { usePoll } from "@/lib/api";
import { dateTime, money, plClass, price } from "@/lib/format";
import type { ClosedPosition, CloseRequest, OpenPosition, Summary } from "@/lib/types";
import { OpenPositionsTable } from "@/components/positions-table";
import { Badge, Card, Empty, ErrorBanner, SideBadge, SummaryTable, Table, Td } from "@/components/ui";

type Positions = { open: OpenPosition[]; closed: ClosedPosition[]; summary: Summary; close_requests: CloseRequest[] };

function summarize(rows: ClosedPosition[]): Summary {
  const p = rows.map((r) => r.profit).filter((v): v is number => v !== null);
  const wins = p.filter((v) => v > 0);
  const losses = p.filter((v) => v <= 0);
  return {
    trades: p.length,
    wins: wins.length,
    losses: losses.length,
    win_rate: p.length ? wins.length / p.length : null,
    gross_profit: wins.reduce((a, b) => a + b, 0),
    gross_loss: losses.reduce((a, b) => a + b, 0),
    net: p.reduce((a, b) => a + b, 0),
  };
}

export default function PositionsPage() {
  const { data, error, refresh } = usePoll<Positions>("positions", 5_000);
  const [tab, setTab] = useState<"open" | "closed">("open");
  const [strategy, setStrategy] = useState("all");
  const closed = useMemo(() => data?.closed ?? [], [data]);
  const strategies = useMemo(() => Array.from(new Set(closed.map((c) => c.instance))).sort(), [closed]);
  const shown = strategy === "all" ? closed : closed.filter((c) => c.instance === strategy);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Positions</h1>
        <p className="text-sm text-slate-500">Bot trades only (magic number), with results from MT5 deal history.</p>
      </div>
      <ErrorBanner message={error} />

      <Card title="Results by strategy">
        <SummaryTable
          rows={[
            { label: "All strategies", s: data ? summarize(closed) : null },
            ...strategies.map((name) => ({ label: name, s: summarize(closed.filter((c) => c.instance === name)) })),
          ]}
        />
      </Card>

      <div className="flex gap-1 rounded-lg bg-slate-100 p-1 text-sm font-medium w-fit">
        {(["open", "closed"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`rounded-md px-4 py-1.5 ${tab === t ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"}`}>
            {t === "open" ? `Open (${data?.open.length ?? 0})` : `Closed (${closed.length})`}
          </button>
        ))}
      </div>

      {tab === "open" ? (
        <Card title="Open positions">
          <OpenPositionsTable positions={data?.open ?? []} onChanged={refresh} />
        </Card>
      ) : (
        <Card
          title="Closed trades"
          action={
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm">
              <option value="all">All strategies</option>
              {strategies.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          }
        >
          {shown.length ? (
            <Table head={["#", "Opened", "Closed", "Symbol", "Side", "Lots", "Entry", "Exit", "Result", "Profit / Loss", "Strategy"]}>
              {shown.map((t, i) => (
                <tr key={`${t.instance}:${t.trade_id}`}>
                  <Td className="num text-slate-500">{shown.length - i}</Td>
                  <Td className="text-slate-600">{dateTime(t.opened_at)}</Td>
                  <Td className="text-slate-600">{dateTime(t.closed_at)}</Td>
                  <Td className="font-medium">{t.symbol}</Td>
                  <Td><SideBadge side={t.side} /></Td>
                  <Td className="num">{t.volume.toFixed(2)}</Td>
                  <Td className="num">{price(t.entry_price)}</Td>
                  <Td className="num">{price(t.exit_price)}</Td>
                  <Td>{t.profit === null ? <Badge>Pending</Badge> : t.profit > 0 ? <Badge tone="green">Win</Badge> : <Badge tone="red">Loss</Badge>}</Td>
                  <Td className={`num font-semibold ${plClass(t.profit)}`}>{money(t.profit, "USD", true)}</Td>
                  <Td className="text-slate-600">{t.instance}</Td>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty>No closed trades yet.</Empty>
          )}
        </Card>
      )}

      {data && data.close_requests.length > 0 && (
        <Card title="Manual close requests">
          <Table head={["Requested", "Trade", "Reason", "Status", "Finished"]}>
            {data.close_requests.map((r) => (
              <tr key={r.id}>
                <Td className="text-slate-600">{dateTime(r.requested_at)}</Td>
                <Td className="text-slate-700">{r.instance}</Td>
                <Td className="max-w-xs truncate text-slate-600">{r.note}</Td>
                <Td><Badge tone={r.status === "CLOSED" ? "green" : r.status === "PENDING" ? "amber" : "red"}>{r.status}</Badge>
                  {r.error && <span className="ml-2 text-xs text-slate-500">{r.error.replace(/_/g, " ")}</span>}</Td>
                <Td className="text-slate-600">{dateTime(r.finished_at)}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}
