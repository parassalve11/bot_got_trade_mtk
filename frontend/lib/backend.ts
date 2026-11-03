import "server-only";

/**
 * Server-side only: talks to the bot's FastAPI on the Windows PC (via Tailscale Funnel).
 * BACKEND_URL and DASH_PROXY_SECRET never reach the browser.
 */
export const SESSION_COOKIE = "bfx_session";

function config() {
  const url = process.env.BACKEND_URL;
  const secret = process.env.DASH_PROXY_SECRET;
  if (!url || !secret) {
    throw new Error("BACKEND_URL and DASH_PROXY_SECRET must be set (see frontend/.env.example)");
  }
  return { url: url.replace(/\/+$/, ""), secret };
}

export async function backendFetch(
  path: string,
  init: { method?: "GET" | "POST"; token?: string; body?: unknown; search?: string } = {},
): Promise<Response> {
  const { url, secret } = config();
  const headers: Record<string, string> = { "x-dash-proxy-secret": secret };
  if (init.token) headers.authorization = `Bearer ${init.token}`;
  if (init.body !== undefined) headers["content-type"] = "application/json";
  try {
    return await fetch(`${url}/api/v1/dash${path}${init.search ?? ""}`, {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    return Response.json({ detail: "bot_unreachable" }, { status: 503 });
  }
}
