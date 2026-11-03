export function money(value: number | null | undefined, currency = "USD", signed = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const text = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  if (value < 0) return `−${text}`;
  return signed && value > 0 ? `+${text}` : text;
}

export function price(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "—";
  const digits = value >= 100 ? 2 : value >= 10 ? 3 : 5;
  return value.toFixed(digits);
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function dateTime(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ago(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function plClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-slate-700";
  return value > 0 ? "text-emerald-600" : "text-rose-600";
}

export function tfLabel(tf: string | null | undefined): string {
  if (!tf) return "—";
  const n = Number(tf);
  return n >= 60 ? `${n / 60}H` : `${n}m`;
}

export function humanize(text: string | null | undefined): string {
  if (!text) return "—";
  return text.replace(/_/g, " ");
}
