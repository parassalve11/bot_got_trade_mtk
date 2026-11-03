import { NextRequest, NextResponse } from "next/server";

// Pages require a session cookie; the bot validates the session itself on every API call.
export function proxy(request: NextRequest) {
  const hasSession = Boolean(request.cookies.get("bfx_session")?.value);
  const isLogin = request.nextUrl.pathname === "/login";
  if (!hasSession && !isLogin) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (hasSession && isLogin) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
