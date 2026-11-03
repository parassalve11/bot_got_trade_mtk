import { NextRequest, NextResponse } from "next/server";
import { backendFetch, SESSION_COOKIE } from "@/lib/backend";

export async function POST(request: NextRequest) {
  let body: { login?: unknown; password?: unknown; server?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "invalid_request" }, { status: 400 });
  }
  const login = Number(body.login);
  if (!Number.isInteger(login) || login <= 0 || typeof body.password !== "string" || typeof body.server !== "string") {
    return NextResponse.json({ detail: "invalid_request" }, { status: 400 });
  }
  // The MT5 password is forwarded to the bot once and never stored by the dashboard.
  const res = await backendFetch("/login", {
    method: "POST",
    // Copy/paste often adds spaces around the password; MT5 passwords never start or end with one.
    body: { login, password: body.password.trim(), server: body.server.trim() },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json({ detail: data.detail ?? "login_failed" }, { status: res.status });
  }
  const response = NextResponse.json({ role: data.role });
  response.cookies.set(SESSION_COOKIE, data.token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: Math.max(60, Math.floor(data.expires_at - Date.now() / 1000)),
  });
  return response;
}
