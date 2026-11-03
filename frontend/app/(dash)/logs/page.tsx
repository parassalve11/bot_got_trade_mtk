"use client";

import { usePoll } from "@/lib/api";
import { dateTime, humanize } from "@/lib/format";
import type { AuditRow } from "@/lib/types";
import { Badge, Card, Empty, ErrorBanner, Table, Td, type Tone } from "@/components/ui";

function tone(action: string): Tone {
  if (action.includes("failed") || action.includes("hold") || action.includes("safety")) return "red";
  if (action.startsWith("operator")) return "amber";
  if (action.startsWith("dashboard_login")) return "blue";
  return "gray";
}

function details(d: Record<string, unknown>): string {
  return Object.entries(d)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .map(([k, v]) => `${humanize(k)}: ${String(v)}`)
    .join(" · ");
}

export default function LogsPage() {
  const { data, error } = usePoll<{ audit: AuditRow[] }>("audit?limit=300", 15_000);
  const rows = data?.audit ?? [];
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Logs</h1>
        <p className="text-sm text-slate-500">Audit trail: sign-ins, controls, safety events and engine signals. Read-only.</p>
      </div>
      <ErrorBanner message={error} />
      <Card title={`Audit log (${rows.length})`}>
        {rows.length ? (
          <Table head={["Time", "Action", "Details"]}>
            {rows.map((r) => (
              <tr key={r.id}>
                <Td className="text-slate-600">{dateTime(r.at)}</Td>
                <Td><Badge tone={tone(r.action)}>{humanize(r.action)}</Badge></Td>
                <Td className="max-w-xl truncate text-slate-600">{details(r.details)}</Td>
              </tr>
            ))}
          </Table>
        ) : (
          <Empty>No audit entries yet.</Empty>
        )}
      </Card>
    </div>
  );
}
