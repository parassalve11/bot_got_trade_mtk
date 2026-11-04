import "server-only";

/**
 * Server-side only: talks to the bot's FastAPI on the Windows PC (via Tailscale Funnel).
 * BACKEND_URL and DASH_PROXY_SECRET never reach the browser.
 */
export const SESSION_COOKIE = "bfx_session";

/** Tolerates common copy/paste mistakes: spaces, quotes, trailing slashes or a pasted /api path. */
function clean(value: string | undefined): string {
  return (value ?? "").trim().replace(/^["']|["']$/g, "").trim();
}

export function backendConfig() {
  const url = clean(process.env.BACKEND_URL)
    .replace(/\/+$/, "")
    .replace(/\/api(\/v1(\/dash)?)?$/, "");
  const secret = clean(process.env.DASH_PROXY_SECRET);
  let validUrl = false;
  try {
    validUrl = ["https:", "http:"].includes(new URL(url).protocol);
  } catch {
    validUrl = false;
  }
  return { url, secret, validUrl };
}

export async function backendFetch(
  path: string,
  init: { method?: "GET" | "POST"; token?: string; body?: unknown; search?: string } = {},
): Promise<Response> {
  const { url, secret, validUrl } = backendConfig();
  if (!validUrl || !secret) {
    console.error("[backend] BACKEND_URL or DASH_PROXY_SECRET missing/invalid; open /api/diagnostics");
    return Response.json({ detail: "dashboard_not_configured" }, { status: 500 });
  }
  const headers: Record<string, string> = { "x-dash-proxy-secret": secret, "ngrok-skip-browser-warning": "1" };
  if (init.token) headers.authorization = `Bearer ${init.token}`;
  if (init.body !== undefined) headers["content-type"] = "application/json";
  try {
    return await fetch(`${url}/api/v1/dash${path}${init.search ?? ""}`, {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    // Visible in Vercel > Logs. Never includes the secret or the user's password.
    const e = error as { name?: string; message?: string; cause?: { code?: string } };
    console.error("[backend] request failed", { host: new URL(url).host, name: e?.name, code: e?.cause?.code, message: e?.message });
    return Response.json({ detail: "bot_unreachable" }, { status: 503 });
  }
}
