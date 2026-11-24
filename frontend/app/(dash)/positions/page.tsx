"use client";

import { useMemo, useState } from "react";
import { usePoll } from "@/lib/api";
import Link from "next/link";
import { dateTime } from "@/lib/format";
import type { ClosedPosition, CloseRequest, OpenPosition, Summary } from "@/lib/types";
import { OpenPositionsTable } from "@/components/positions-table";
import { ClosedTradesTable, summarize } from "@/components/trades";
import { Badge, Card, ErrorBanner, SummaryTable, Table, Td } from "@/components/ui";

type Positions = { open: OpenPosition[]; closed: ClosedPosition[]; summary: Summary; close_requests: CloseRequest[] };

export default function PositionsPage() {
  const { data, error, refresh } = usePoll<Positions>("positions", 15_000);
  const [tab, setTab] = useState<"open" | "closed">("open");
  const [strategy, setStrategy] = useState("all");
  // Swing (1-hour) trades only; 15-minute trades have their own Intraday page.
  const closed = useMemo(() => (data?.closed ?? []).filter((c) => c.group !== "intraday"), [data]);
  const open = useMemo(() => (data?.open ?? []).filter((p) => p.group !== "intraday"), [data]);
  const strategies = useMemo(() => Array.from(new Set(closed.map((c) => c.instance))).sort(), [closed]);
  const shown = strategy === "all" ? closed : closed.filter((c) => c.instance === strategy);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Positions</h1>
        <p className="text-sm text-slate-500">
          Swing trades (1-hour strategies), with results from MT5 deal history. 15-minute trades are on the{" "}
          <Link href="/intraday" className="font-medium text-indigo-600 hover:underline">Intraday page</Link>.
        </p>
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
            {t === "open" ? `Open (${open.length})` : `Closed (${closed.length})`}
          </button>
        ))}
      </div>

      {tab === "open" ? (
        <Card title="Open positions">
          <OpenPositionsTable positions={open} onChanged={refresh} />
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
          <ClosedTradesTable rows={shown} />
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
