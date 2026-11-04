import { backendConfig } from "@/lib/backend";

/**
 * Connection self-test for deployment problems. Reveals no secrets: only whether settings
 * look valid, the bot host name, and what the bot answered.
 */
export async function GET() {
  const { url, secret, validUrl } = backendConfig();
  const report: Record<string, unknown> = {
    backend_url_set: Boolean(process.env.BACKEND_URL),
    backend_url_valid: validUrl,
    backend_host: validUrl ? new URL(url).host : null,
    proxy_secret_set: Boolean(secret),
    proxy_secret_length_ok: secret.length >= 32,
  };
  if (!validUrl || !secret) {
    report.result = "Fix the Vercel environment variables, then redeploy.";
    return Response.json(report, { headers: { "cache-control": "no-store" } });
  }
  const started = Date.now();
  try {
    // With the right secret and no session the bot answers 401; a wrong secret gets 404.
    const res = await fetch(`${url}/api/v1/dash/me`, {
      headers: { "x-dash-proxy-secret": secret, "ngrok-skip-browser-warning": "1" },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    report.bot_status = res.status;
    report.response_ms = Date.now() - started;
    report.result =
      res.status === 401
        ? "OK: bot reachable and DASH_PROXY_SECRET matches. Sign-in should work."
        : res.status === 404
          ? "Bot reachable, but DASH_PROXY_SECRET does not match backend/.env (or the Tailscale /api/v1/dash path is missing)."
          : "Unexpected answer from the bot.";
  } catch (error) {
    const e = error as { name?: string; message?: string; cause?: { code?: string; message?: string } };
    report.result = "Cannot connect to the bot from Vercel.";
    report.error = { name: e?.name, code: e?.cause?.code, message: e?.cause?.message ?? e?.message };
    report.response_ms = Date.now() - started;
  }
  return Response.json(report, { headers: { "cache-control": "no-store" } });
}
