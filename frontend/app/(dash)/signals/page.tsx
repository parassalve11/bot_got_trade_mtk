"use client";

import { useState } from "react";
import { usePoll } from "@/lib/api";
import type { Signal } from "@/lib/types";
import { SignalsTable } from "@/components/signals-list";
import { Card, ErrorBanner } from "@/components/ui";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "EXECUTED", label: "Executed" },
  { key: "WATCH_ONLY", label: "Watch only" },
  { key: "REJECTED", label: "Rejected" },
] as const;

export default function SignalsPage() {
  const { data, error } = usePoll<{ signals: Signal[] }>("signals?limit=300", 10_000);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const signals = (data?.signals ?? []).filter((s) => filter === "all" || s.status === filter);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Signals</h1>
        <p className="text-sm text-slate-500">
          Every UT Bot signal from the built-in engine (and TradingView, if used), with what the bot did with it.
        </p>
      </div>
      <ErrorBanner message={error} />
      <Card
        title={`Signals (${signals.length})`}
        action={
          <div className="flex gap-1 rounded-lg bg-slate-100 p-1 text-xs font-medium">
            {FILTERS.map((f) => (
              <button key={f.key} onClick={() => setFilter(f.key)}
                className={`rounded-md px-3 py-1 ${filter === f.key ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"}`}>
                {f.label}
              </button>
            ))}
          </div>
        }
      >
        <SignalsTable signals={signals} />
      </Card>
    </div>
  );
}
