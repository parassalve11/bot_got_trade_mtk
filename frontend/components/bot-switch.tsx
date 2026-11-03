"use client";

import { useState } from "react";
import { Play, Square } from "lucide-react";
import { post } from "@/lib/api";
import { Button } from "@/components/ui";

/** Master Start/Stop. Stopped = no new signals or entries; open trades keep broker SL/TP. */
export function BotSwitch({ running, onChanged, size = "md" }: {
  running: boolean | undefined;
  onChanged: () => void;
  size?: "md" | "lg";
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (running === undefined) return null;
  const big = size === "lg" ? "px-5 py-2.5 text-base" : "";

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      await post(running ? "bot/stop" : "bot/start", {});
      setConfirming(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative">
      {running ? (
        <Button variant="danger" className={big} onClick={() => setConfirming(true)} disabled={busy}>
          <Square size={14} fill="currentColor" /> Stop bot
        </Button>
      ) : (
        <Button className={`bg-emerald-600 hover:bg-emerald-700 ${big}`} onClick={() => setConfirming(true)} disabled={busy}>
          <Play size={14} fill="currentColor" /> Start bot
        </Button>
      )}
      {confirming && (
        <div className="absolute right-0 z-50 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-xl">
          <p className="text-sm font-semibold text-slate-900">{running ? "Stop the bot?" : "Start the bot?"}</p>
          <p className="mt-1 text-xs text-slate-600">
            {running
              ? "No new signals or trades. Open trades keep their broker stop-loss and take-profit."
              : "The bot starts reading signals. Strategies in Trade mode will place real orders."}
          </p>
          {error && <p className="mt-2 text-xs text-rose-600">{error}</p>}
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => { setConfirming(false); setError(null); }} disabled={busy}>Cancel</Button>
            <Button variant={running ? "danger" : "primary"} className={running ? "" : "bg-emerald-600 hover:bg-emerald-700"}
              onClick={toggle} disabled={busy}>
              {busy ? "Working…" : running ? "Stop" : "Start"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
