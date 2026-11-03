import { dateTime, humanize, price, tfLabel } from "@/lib/format";
import type { Signal } from "@/lib/types";
import { Badge, Empty, SideBadge, Table, Td, type Tone } from "@/components/ui";

const STATUS: Record<string, { tone: Tone; label: string }> = {
  EXECUTED: { tone: "green", label: "Executed" },
  WATCH_ONLY: { tone: "blue", label: "Watch only" },
  QUEUED: { tone: "gray", label: "Queued" },
  PROCESSING: { tone: "gray", label: "Processing" },
  RETRY: { tone: "amber", label: "Retrying" },
  REJECTED: { tone: "red", label: "Rejected" },
  FAILED: { tone: "red", label: "Failed" },
  REVIEW: { tone: "red", label: "Needs review" },
  IGNORED: { tone: "gray", label: "Ignored" },
  LOGGED: { tone: "gray", label: "Logged" },
};

export function SignalsTable({ signals }: { signals: Signal[] }) {
  if (!signals.length) return <Empty>No signals yet. The engine checks every closed candle.</Empty>;
  return (
    <Table head={["Time", "Symbol", "Timeframe", "Signal", "Side", "Price", "Strategy", "Source", "Result"]}>
      {signals.map((s, i) => {
        const status = STATUS[s.status] ?? { tone: "gray" as Tone, label: s.status };
        return (
          <tr key={i}>
            <Td className="text-slate-600">{dateTime(s.at)}</Td>
            <Td className="font-medium">{s.symbol?.replace(/^[A-Z]+:/, "") ?? "—"}</Td>
            <Td>{tfLabel(s.timeframe)}</Td>
            <Td className="capitalize">{humanize(s.event)}</Td>
            <Td><SideBadge side={s.side} /></Td>
            <Td className="num">{price(s.price)}</Td>
            <Td className="text-slate-600">{s.instance ?? "—"}</Td>
            <Td className="text-slate-600">{s.source === "mt5_engine" ? "Engine" : "TradingView"}</Td>
            <Td>
              <span className="flex items-center gap-2">
                <Badge tone={status.tone}>{status.label}</Badge>
                {s.reason && s.status !== "WATCH_ONLY" && s.status !== "EXECUTED" && (
                  <span className="text-xs text-slate-500">{humanize(s.reason)}</span>
                )}
              </span>
            </Td>
          </tr>
        );
      })}
    </Table>
  );
}
