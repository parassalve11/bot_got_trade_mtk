"use client";

import { money } from "@/lib/format";

type Point = { at: number; balance: number; equity: number };

/** Lightweight SVG equity curve (no chart library needed). */
export function EquityChart({ points }: { points: Point[] }) {
  if (points.length < 2) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-slate-500">
        The equity curve fills in as the bot runs (one point every 5 minutes).
      </div>
    );
  }
  const W = 640;
  const H = 180;
  const pad = 4;
  const values = points.flatMap((p) => [p.equity, p.balance]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const t0 = points[0].at;
  const t1 = points[points.length - 1].at;
  const x = (t: number) => pad + ((t - t0) / (t1 - t0 || 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - min) / span) * (H - 2 * pad);
  const line = (key: "equity" | "balance") =>
    points.map((p, i) => `${i ? "L" : "M"}${x(p.at).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");
  const area = `${line("equity")} L${x(t1)},${H} L${x(t0)},${H} Z`;
  const up = points[points.length - 1].equity >= points[0].equity;
  const stroke = up ? "#059669" : "#e11d48";

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-48 w-full" preserveAspectRatio="none" role="img" aria-label="Equity curve">
        <defs>
          <linearGradient id="eq-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#eq-fill)" />
        <path d={line("balance")} fill="none" stroke="#94a3b8" strokeWidth="1.5" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
        <path d={line("equity")} fill="none" stroke={stroke} strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
        <span className="num">Low {money(min)} · High {money(max)}</span>
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1"><span className="h-0.5 w-4" style={{ background: stroke }} />Equity</span>
          <span className="flex items-center gap-1"><span className="h-0.5 w-4 border-t border-dashed border-slate-400" />Balance</span>
        </span>
      </div>
    </div>
  );
}
