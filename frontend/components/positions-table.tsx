"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { post } from "@/lib/api";
import { dateTime, money, plClass, price } from "@/lib/format";
import type { OpenPosition } from "@/lib/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Empty, SideBadge, Table, Td } from "@/components/ui";

export function OpenPositionsTable({ positions, onChanged }: { positions: OpenPosition[]; onChanged?: () => void }) {
  const [closing, setClosing] = useState<OpenPosition | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (!positions.length) return <Empty>No open positions.</Empty>;

  return (
    <>
      {message && <p className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{message}</p>}
      <Table head={["Symbol", "Side", "Lots", "Entry", "Stop-loss", "Take-profit", "Profit / Loss", "Strategy", "Opened", ""]}>
        {positions.map((p) => (
          <tr key={`${p.instance}:${p.trade_id}`}>
            <Td className="font-medium">{p.symbol}</Td>
            <Td><SideBadge side={p.side} /></Td>
            <Td className="num">{p.volume.toFixed(2)}</Td>
            <Td className="num">{price(p.entry_price)}</Td>
            <Td className="num text-rose-600">{price(p.sl)}</Td>
            <Td className="num text-emerald-600">{price(p.tp)}</Td>
            <Td className={`num font-semibold ${plClass(p.profit)}`}>{money(p.profit, "USD", true)}</Td>
            <Td className="text-slate-600">{p.instance}</Td>
            <Td className="text-slate-600">{dateTime(p.opened_at)}</Td>
            <Td>
              <button
                  onClick={() => setClosing(p)}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50"
                >
                  <X size={14} /> Close
                </button>
            </Td>
          </tr>
        ))}
      </Table>
      <ConfirmDialog
        open={closing !== null}
        title={`Close ${closing?.symbol} ${closing?.side === "LONG" ? "BUY" : "SELL"}?`}
        description={
          <>
            The bot closes this position at market within a few seconds. Current result:{" "}
            <strong className={plClass(closing?.profit)}>{money(closing?.profit, "USD", true)}</strong>.
          </>
        }
        confirmLabel="Close position"
        danger
        onCancel={() => setClosing(null)}
        onConfirm={async (note) => {
          if (!closing) return;
          await post("positions/close", { instance: closing.instance, trade_id: closing.trade_id, note });
          setClosing(null);
          setMessage("Close requested. The worker executes it within a few seconds.");
          onChanged?.();
        }}
      />
    </>
  );
}
