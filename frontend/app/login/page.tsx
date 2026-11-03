"use client";

import { useState, type FormEvent } from "react";
import { Lock, Zap } from "lucide-react";
import { explain } from "@/lib/api";

export default function LoginPage() {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [server, setServer] = useState(process.env.NEXT_PUBLIC_MT5_SERVER ?? "MetaQuotes-Demo");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ login: Number(login), password, server }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(explain(data.detail));
        return;
      }
      window.location.replace("/");
    } catch {
      setError("Could not reach the dashboard server.");
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  const input =
    "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100";

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
            <Zap size={22} />
          </span>
          <h1 className="mt-3 text-xl font-semibold text-slate-900">BYTEFX Trader</h1>
          <p className="text-sm text-slate-500">Sign in with your MetaTrader 5 account</p>
        </div>
        <form onSubmit={submit} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <label className="block text-xs font-medium text-slate-700" htmlFor="login">MT5 login</label>
          <input id="login" inputMode="numeric" autoComplete="username" required value={login}
            onChange={(e) => setLogin(e.target.value.replace(/\D/g, ""))} className={`num ${input}`} placeholder="115042927" />
          <label className="mt-4 block text-xs font-medium text-slate-700" htmlFor="password">Password</label>
          <input id="password" type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} className={input} />
          <label className="mt-4 block text-xs font-medium text-slate-700" htmlFor="server">Server</label>
          <input id="server" required value={server} onChange={(e) => setServer(e.target.value)} className={input} />
          {error && <p className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
          <button type="submit" disabled={busy}
            className="mt-5 w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-indigo-300">
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="mt-4 space-y-1.5 text-xs text-slate-500">
          <p className="flex items-center gap-1.5"><Lock size={13} /> Use the MT5 account&apos;s master password.</p>
          <p>Your password is checked by the bot on the trading PC and is never stored here.</p>
        </div>
      </div>
    </main>
  );
}
