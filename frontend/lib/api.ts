"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const MESSAGES: Record<string, string> = {
  bot_unreachable: "The trading bot is not reachable. Check that the PC, the bot and Tailscale are running.",
  session_expired: "Your session expired. Please sign in again.",
  invalid_mt5_credentials: "Wrong MT5 login, password or server.",
  too_many_attempts_try_again_later: "Too many failed attempts. Try again in 15 minutes.",
  not_found: "Not found. Check the dashboard configuration.",
  dashboard_not_configured: "The dashboard is not configured. Open /api/diagnostics for details.",
};

export function explain(detail: unknown): string {
  if (typeof detail === "string") return MESSAGES[detail] ?? detail.replace(/_/g, " ");
  if (Array.isArray(detail)) return "Please check the form: a note of at least 10 characters is required.";
  return "Something went wrong.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/backend/${path}`, { cache: "no-store", ...init });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    window.location.replace("/login");
  }
  if (!res.ok) throw new ApiError(res.status, explain(data.detail));
  return data as T;
}

export function post<T = { ok: boolean }>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Fetches `path` and refreshes it every `intervalMs` while the tab is visible. */
export function usePoll<T>(path: string, intervalMs = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const next = await request<T>(path);
      if (alive.current) {
        setData(next);
        setError(null);
      }
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    const first = setTimeout(refresh, 0);
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, intervalMs);
    return () => {
      alive.current = false;
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}
