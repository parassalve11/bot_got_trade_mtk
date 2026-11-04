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
  bot_unreachable: "The trading bot is not reachable. Check that the PC is on and the bot and tunnel are running.",
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

/**
 * Shared GET cache: components polling the same path share one request per refresh window.
 * Keeps traffic low (the public tunnel's free plan has a monthly request quota).
 */
const cache = new Map<string, { at: number; data: unknown; inflight?: Promise<unknown> }>();

function cachedGet<T>(path: string, maxAgeMs: number, force: boolean): Promise<T> {
  const entry = cache.get(path);
  if (entry?.inflight) return entry.inflight as Promise<T>;
  if (!force && entry && Date.now() - entry.at < maxAgeMs) return Promise.resolve(entry.data as T);
  const inflight = request<T>(path).then(
    (data) => {
      cache.set(path, { at: Date.now(), data });
      return data;
    },
    (err) => {
      cache.delete(path);
      throw err;
    },
  );
  cache.set(path, { at: entry?.at ?? 0, data: entry?.data, inflight });
  return inflight;
}

/** Fetches `path` and refreshes it every `intervalMs` while the tab is visible. */
export function usePoll<T>(path: string, intervalMs = 15_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const load = useCallback(
    async (force: boolean) => {
      try {
        const next = await cachedGet<T>(path, intervalMs * 0.8, force);
        if (alive.current) {
          setData(next);
          setError(null);
        }
      } catch (err) {
        if (alive.current) setError(err instanceof Error ? err.message : "Request failed");
      } finally {
        if (alive.current) setLoading(false);
      }
    },
    [path, intervalMs],
  );

  /** Manual refresh (e.g. after an action) always fetches fresh data. */
  const refresh = useCallback(() => load(true), [load]);

  useEffect(() => {
    alive.current = true;
    const first = setTimeout(() => load(false), 0);
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load(false);
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") load(false);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive.current = false;
      clearTimeout(first);
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load, intervalMs]);

  return { data, error, loading, refresh };
}
