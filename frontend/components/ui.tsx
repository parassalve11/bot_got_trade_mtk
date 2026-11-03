import type { ButtonHTMLAttributes, ReactNode } from "react";
import { money, pct, plClass } from "@/lib/format";
import type { Summary } from "@/lib/types";

export function Card({ title, action, children, className = "" }: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone = "text-slate-900" }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`num mt-1 text-xl font-semibold ${tone}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

const BADGE_TONES = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  blue: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  gray: "bg-slate-100 text-slate-700 ring-slate-200",
} as const;
export type Tone = keyof typeof BADGE_TONES;

export function Badge({ tone = "gray", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  );
}

export function Dot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-700">
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-rose-500"}`} />
      {label}
    </span>
  );
}

export function SideBadge({ side }: { side: string | null }) {
  if (!side) return <span className="text-slate-400">—</span>;
  return <Badge tone={side === "LONG" ? "green" : "red"}>{side === "LONG" ? "BUY" : "SELL"}</Badge>;
}

export function Button({ variant = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  const styles = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-indigo-300",
    secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400",
    danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
    ghost: "text-slate-600 hover:bg-slate-100",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed ${styles} ${props.className ?? ""}`}
    />
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>;
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{message}</div>;
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="-mx-4 overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-4 py-2 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`whitespace-nowrap px-4 py-2.5 ${className}`}>{children}</td>;
}

/** Win/loss summary in the table format agreed with the user. */
export function SummaryTable({ rows }: { rows: { label: ReactNode; s: Summary | null; extra?: ReactNode }[] }) {
  return (
    <Table head={["", "Trades", "Wins", "Losses", "Win rate", "Profit from wins", "Loss from losses", "Net result"]}>
      {rows.map((row, i) => (
        <tr key={i}>
          <Td className="font-medium text-slate-800">{row.label}</Td>
          <Td className="num">{row.s?.trades ?? "—"}</Td>
          <Td className="num text-emerald-600">{row.s?.wins ?? "—"}</Td>
          <Td className="num text-rose-600">{row.s?.losses ?? "—"}</Td>
          <Td className="num">{pct(row.s?.win_rate)}</Td>
          <Td className="num text-emerald-600">{row.s?.gross_profit != null ? money(row.s.gross_profit, "USD", true) : "—"}</Td>
          <Td className="num text-rose-600">{row.s?.gross_loss != null ? money(row.s.gross_loss) : "—"}</Td>
          <Td className={`num font-semibold ${plClass(row.s?.net)}`}>{row.s ? money(row.s.net, "USD", true) : "—"}</Td>
        </tr>
      ))}
    </Table>
  );
}
