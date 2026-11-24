import { dateTime, money, plClass, price } from "@/lib/format";
import type { ClosedPosition, Summary } from "@/lib/types";
import { Badge, Empty, SideBadge, Table, Td } from "@/components/ui";

export function summarize(rows: ClosedPosition[]): Summary {
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

export function ClosedTradesTable({ rows, empty = "No closed trades yet." }: { rows: ClosedPosition[]; empty?: string }) {
  if (!rows.length) return <Empty>{empty}</Empty>;
  return (
    <Table head={["#", "Opened", "Closed", "Symbol", "Side", "Lots", "Entry", "Exit", "Result", "Profit / Loss", "Strategy"]}>
      {rows.map((t, i) => (
        <tr key={`${t.instance}:${t.trade_id}`}>
          <Td className="num text-slate-500">{rows.length - i}</Td>
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
  );
}
