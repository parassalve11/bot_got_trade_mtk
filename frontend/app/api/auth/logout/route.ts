import { NextRequest, NextResponse } from "next/server";
import { backendFetch, SESSION_COOKIE } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (token) await backendFetch("/logout", { method: "POST", token });
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
