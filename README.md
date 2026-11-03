# BYTEFX Auto Trader Platform

| Folder | What | Runs on |
|---|---|---|
| [`backend/`](backend/README.md) | Python bot: FastAPI API, MT5 worker, UT Bot signal engine, risk/execution, research | The Windows PC next to MetaTrader 5 (Windows startup tasks) |
| [`frontend/`](frontend/README.md) | Next.js + Tailwind dashboard (light theme) | Vercel (Root Directory = `frontend`) |

```text
Browser ──> Vercel (Next.js dashboard, server-side API proxy)
                 │ HTTPS (Tailscale Funnel, /api/v1/dash/*)
                 ▼
        Windows PC: FastAPI ──> SQLite journal ──> Worker ──> MetaTrader 5
```

Login uses the MT5 account: master password = Admin (controls), investor password = Viewer
(read-only). Passwords are checked by the backend on the PC; Vercel never stores them.
Secrets live only in `backend/.env` and Vercel environment variables, never in Git.
