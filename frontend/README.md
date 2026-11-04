# BYTEFX Trader dashboard (frontend)

Next.js 16 (App Router) + Tailwind CSS 4, light theme. Deployed on Vercel with **Root Directory = `frontend`**.

## How it works

- Pages are client components that poll `/api/backend/*` (Next.js route handlers) every few seconds.
- Route handlers add the server-only `DASH_PROXY_SECRET` and the user's session token, then call the bot
  (`BACKEND_URL` + `/api/v1/dash/*`) through Tailscale Funnel. Only an allowlist of paths is forwarded.
- Sign-in uses the MT5 login, server and master password. The bot checks them on the trading PC and returns a
  session token, stored here only as an HttpOnly, SameSite=Strict cookie. Passwords are never stored.
- `proxy.ts` redirects visitors without a session cookie to `/login`.

## Pages

Overview · Positions (win/loss tables, closed trades, manual closes) · Signals · Strategies (backtest vs live,
Off/Watch/Trade) · Controls (pause/resume, safety hold, close all, read-only limits) · Logs (audit trail).

## Local development

```bash
cp .env.example .env.local   # fill in BACKEND_URL and DASH_PROXY_SECRET
npm install
npm run dev                  # http://localhost:3000 (the startup task serves on http://localhost:72)
```

For a bot on the same PC, `BACKEND_URL=http://127.0.0.1:8000` also works.

## Vercel

1. New Project → import the repo → Root Directory: `frontend` (framework detected as Next.js).
2. Environment variables: `BACKEND_URL`, `DASH_PROXY_SECRET` (and optionally `NEXT_PUBLIC_MT5_SERVER`).
3. Deploy. The bot PC must expose `/api/v1/dash` through Tailscale Funnel (see the root README).
