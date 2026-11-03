import { NextRequest, NextResponse } from "next/server";
import { backendFetch, SESSION_COOKIE } from "@/lib/backend";

// Only these bot endpoints are reachable through the dashboard.
const GET_PATHS = new Set(["me", "overview", "positions", "signals", "strategies", "equity", "audit", "config"]);
const POST_PATHS = new Set([
  "control/pause",
  "control/resume",
  "control/acknowledge-hold",
  "positions/close",
  "positions/close-all",
  "strategies/mode",
  "bot/start",
  "bot/stop",
]);

async function forward(request: NextRequest, path: string[], method: "GET" | "POST") {
  const joined = path.join("/");
  if (!(method === "GET" ? GET_PATHS : POST_PATHS).has(joined)) {
    return NextResponse.json({ detail: "not_found" }, { status: 404 });
  }
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "session_expired" }, { status: 401 });
  let body: unknown;
  if (method === "POST") {
    body = await request.json().catch(() => ({}));
  }
  const res = await backendFetch(`/${joined}`, { method, token, body, search: request.nextUrl.search });
  const data = await res.json().catch(() => ({ detail: "bad_gateway" }));
  const response = NextResponse.json(data, { status: res.status });
  if (res.status === 401) response.cookies.delete(SESSION_COOKIE);
  response.headers.set("cache-control", "no-store");
  return response;
}

export async function GET(request: NextRequest, ctx: RouteContext<"/api/backend/[...path]">) {
  return forward(request, (await ctx.params).path, "GET");
}

export async function POST(request: NextRequest, ctx: RouteContext<"/api/backend/[...path]">) {
  return forward(request, (await ctx.params).path, "POST");
}
