r"""Backtest the user's "Wolfs Radar+" TradingView indicator (auto_treading_bot/wolf_radar.pine).

Usage (from backend/):  .venv\Scripts\python.exe research\wolf_radar.py

The file holds two independent signal engines, ported with their DEFAULT inputs:
  ghost  "Ghost Scalp": liquidity sweep of a stored 5/5 swing level (>= 30 pips beyond it), the
         sweep candle closes back inside with wick >= 35%, body <= 65%, range >= 20 pips; within
         2 candles a confirming candle (bullish/bearish body, beyond EMA50, beyond the sweep
         candle's middle) -> entry at its close. Fixed TP 2000 pips / SL 500 pips (gold pip 0.01,
         other symbols = tick size), stop first when both are touched, 10-candle cooldown, no new
         signal while a trade is open (exactly the script's internal simulation).
  wolf   "Wolfs Radar" Dynamic dips: low >= 2% below EMA3(lowest(low,50) + 0.5 ATR) with score >= 70
         (BUY) and the mirror for SELL (the script's SELL score also awards its 30 trend points in an
         UP-trend). The script draws no exits, so its own inputs are used: stop 3%, target 2 x 3%.
Signals on CLOSED candles. Costs: every trade pays max(candle spread, median spread).
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from app.signals.scalping import _ema, _rma  # noqa: E402  (Pine-identical EMA / RMA)

FILES = {
    ("XAUUSD", 5): "research/data_gold2y/XAUUSD_5.npz", ("XAUUSD", 15): "research/data_gold2y/XAUUSD_15.npz",
    ("XAUUSD", 60): "research/data_h1_1124/XAUUSD_60.npz",
    ("XAGUSD", 5): "research/data_silver2y/XAGUSD_5.npz", ("XAGUSD", 15): "research/data_silver2y/XAGUSD_15.npz",
    ("XAGUSD", 60): "research/data_h1_1124/XAGUSD_60.npz",
}


def load(path):
    z = np.load(path)
    d = {k: np.asarray(z[k], float) for k in ("open", "high", "low", "close", "time")}
    d["volume"] = np.asarray(z["volume"], float) if "volume" in z.files else np.ones(len(d["close"]))
    d["spread"] = np.asarray(z["spread"], float) * float(z["point"]) if "spread" in z.files else np.zeros(len(d["close"]))
    d["point"] = float(z["point"])
    return d


def pivots(H, L, n):
    N = len(H)
    ph, pl = np.full(N, np.nan), np.full(N, np.nan)
    for i in range(2 * n, N):
        c = i - n
        if all(H[j] < H[c] for j in range(c - n, c)) and all(H[j] <= H[c] for j in range(c + 1, i + 1)):
            ph[i] = H[c]
        if all(L[j] > L[c] for j in range(c - n, c)) and all(L[j] >= L[c] for j in range(c + 1, i + 1)):
            pl[i] = L[c]
    return ph, pl


def ghost(d, sym, *, tp_pips=2000, sl_pips=500, min_sweep=30, min_range=20, win=2, cooldown=10,
          wick=0.35, body=0.65, ema_len=50, use_ema=True):
    O, H, L, C = d["open"], d["high"], d["low"], d["close"]
    pip = 0.01 if sym == "XAUUSD" else d["point"]
    tp, sl, msw, mrg = tp_pips * pip, sl_pips * pip, min_sweep * pip, min_range * pip
    E = np.array(_ema(list(C), ema_len))
    ph, pl = pivots(H, L, 5)
    med = float(np.median(d["spread"]))
    hl, hb, ll, lb = [], [], [], []
    pb = pbm = None   # pending bull sweep bar / mid
    sb = sbm = None
    last_sig = None
    pos = None
    out = []
    for i in range(len(C)):
        o, h, lo, c = O[i], H[i], L[i], C[i]
        if not np.isnan(ph[i]):
            hl.append(ph[i]); hb.append(i - 5)
            if len(hl) > 20:
                hl.pop(0); hb.pop(0)
        if not np.isnan(pl[i]):
            ll.append(pl[i]); lb.append(i - 5)
            if len(ll) > 20:
                ll.pop(0); lb.pop(0)
        rng = h - lo
        bodyp = abs(c - o) / rng if rng > 0 else 0
        upw = (h - max(o, c)) / rng if rng > 0 else 0
        dnw = (min(o, c) - lo) / rng if rng > 0 else 0
        shl = next((hl[k] for k in range(len(hl) - 1, -1, -1) if hb[k] < i and h > hl[k] and h - hl[k] >= msw), None)
        sll = next((ll[k] for k in range(len(ll) - 1, -1, -1) if lb[k] < i and lo < ll[k] and ll[k] - lo >= msw), None)
        if sll is not None and c > sll and dnw >= wick and bodyp <= body and rng >= mrg:
            pb, pbm = i, (h + lo) / 2
        if shl is not None and c < shl and upw >= wick and bodyp <= body and rng >= mrg:
            sb, sbm = i, (h + lo) / 2
        ema_ok_l = not use_ema or c > E[i]
        ema_ok_s = not use_ema or c < E[i]
        buy = pb is not None and i - pb <= win and c > o and ema_ok_l and c > pbm
        sell = sb is not None and i - sb <= win and c < o and ema_ok_s and c < sbm
        cool = last_sig is None or i - last_sig > cooldown
        buy, sell = buy and cool, sell and cool and not (buy and cool)
        active = pos is not None
        if buy or sell:
            last_sig = i
        if buy or (pb is not None and i - pb > win):
            pb = None
        if sell or (sb is not None and i - sb > win):
            sb = None
        if not active and (buy or sell):
            dd = 1 if buy else -1
            pos = dict(i=i, d=dd, e=c, tp=c + dd * tp, sl=c - dd * sl, cost=max(d["spread"][i], med))
        elif active and i > pos["i"]:
            dd = pos["d"]
            slh = lo <= pos["sl"] if dd == 1 else h >= pos["sl"]
            tph = h >= pos["tp"] if dd == 1 else lo <= pos["tp"]
            if slh or tph:
                r = (-1.0 if slh else tp / sl) - pos["cost"] / sl
                out.append((pos["i"], dd, r))
                pos = None
    return out


def wolf(d, *, dip=2.0, min_score=70, sl_pct=3.0, rr=2.0, sens=1.0, look=50):
    O, H, L, C, V = d["open"], d["high"], d["low"], d["close"], d["volume"]
    N = len(C)
    TR = np.maximum(H - L, np.maximum(abs(H - np.r_[C[0], C[:-1]]), abs(L - np.r_[C[0], C[:-1]])))
    A = np.array(_rma(list(TR), 14))
    lowest = np.array([L[max(0, i - look + 1):i + 1].min() for i in range(N)])
    highest = np.array([H[max(0, i - look + 1):i + 1].max() for i in range(N)])
    sup = np.array(_ema(list(np.nan_to_num(lowest + A * sens * 0.5, nan=lowest[0])), 3))
    res = np.array(_ema(list(np.nan_to_num(highest - A * sens * 0.5, nan=highest[0])), 3))
    e200, e50 = np.array(_ema(list(C), 200)), np.array(_ema(list(C), 50))
    dlt = np.diff(C, prepend=C[0])
    up, dn = np.array(_rma(list(np.maximum(dlt, 0)), 14)), np.array(_rma(list(np.maximum(-dlt, 0)), 14))
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(dn == 0, 100.0, 100 - 100 / (1 + up / dn))
    vma = np.convolve(V, np.ones(20) / 20, mode="full")[:N]
    mom = C - np.r_[np.full(10, np.nan), C[:-10]]
    med = float(np.median(d["spread"]))
    out, pos = [], None
    for i in range(210, N):
        if pos is not None:
            dd = pos["d"]
            slh = L[i] <= pos["sl"] if dd == 1 else H[i] >= pos["sl"]
            tph = H[i] >= pos["tp"] if dd == 1 else L[i] <= pos["tp"]
            if slh or tph:
                risk = abs(pos["e"] - pos["sl"])
                out.append((pos["i"], dd, (-1.0 if slh else rr) - pos["cost"] / risk))
                pos = None
            continue
        ts = (0.3 if C[i] > e200[i] else -0.3) + (0.2 if C[i] > e50[i] else -0.2) + \
             (0.3 if e50[i] > e200[i] else -0.3) + (0.2 if rsi[i] > 50 else -0.2)
        vol = 20 if V[i] > vma[i] * 1.5 else 10
        mrise = 15 if mom[i] > mom[i - 1] else 5
        dpb = (sup[i] - L[i]) / sup[i] * 100
        dps = (H[i] - res[i]) / res[i] * 100
        sb = (30 if ts > 0.5 else 0) + vol + (20 if rsi[i] < 30 else 10 if rsi[i] < 40 else 0) + mrise + min(dpb / 5 * 15, 15)
        ss = (30 if ts > 0.5 else 0) + vol + (20 if rsi[i] > 70 else 10 if rsi[i] > 60 else 0) + \
             (15 if mom[i] < mom[i - 1] else 5) + min(dps / 5 * 15, 15)
        buy = (L[i] < sup[i] or C[i] < sup[i]) and dpb >= dip and sb >= min_score
        sell = (H[i] > res[i] or C[i] > res[i]) and dps >= dip and ss >= min_score
        if buy or sell:
            dd = 1 if buy else -1
            e = C[i]
            pos = dict(i=i, d=dd, e=e, sl=e * (1 - dd * sl_pct / 100), tp=e * (1 + dd * rr * sl_pct / 100),
                       cost=max(d["spread"][i], med))
    return out


def st(rows):
    if not rows:
        return "no trades"
    r = np.array([x[2] for x in rows])
    eq = np.cumsum(r)
    dd = (eq - np.maximum.accumulate(eq)).min()
    return f"n {len(r):4} win {100 * (r > 0).mean():5.1f}% net {r.sum():+7.1f}R avg {r.mean():+.3f} maxDD {dd:6.1f}R"


if __name__ == "__main__":
    for (sym, tf), f in FILES.items():
        d = load(f)
        n = len(d["close"])
        half = n // 2
        from datetime import datetime, timezone
        span = f"{datetime.fromtimestamp(d['time'][0], timezone.utc).date()} .. {datetime.fromtimestamp(d['time'][-1], timezone.utc).date()}"
        print(f"\n### {sym} {tf}m  ({span}, {n} candles)")
        g = ghost(d, sym)
        print(f"  Ghost Scalp   all: {st(g)}")
        print(f"                1st half: {st([x for x in g if x[0] < half])} | 2nd half: {st([x for x in g if x[0] >= half])}")
        print(f"                BUY: {st([x for x in g if x[1] == 1])} | SELL: {st([x for x in g if x[1] == -1])}")
        w = wolf(d)
        print(f"  Wolfs Radar   all: {st(w)}")
        if w:
            print(f"                BUY: {st([x for x in w if x[1] == 1])} | SELL: {st([x for x in w if x[1] == -1])}")
