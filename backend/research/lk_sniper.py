r"""Backtest the user's "LK Sniper" TradingView indicator (auto_treading_bot/lk-sniper.pine), default inputs.

Usage (from backend/):  .venv\Scripts\python.exe research\lk_sniper.py

Port of the trend engine: EMA34 baseline, momentum, efficiency, volatility regime, three adaptive
Supertrends (ta.supertrend with a per-bar factor), composite regime EMA3, dynamic gate, candidate /
confirmation counters, strong-move fast pass, Supertrend takeover, adaptive cooldown -> UP / DOWN
flips on closed candles. Trade: entry = signal close, SL = basis -/+ 1.15 ATR (at least 10 ticks),
TP1/2/3 = 1/2/3 R. Per candle: stop first (if touched), else targets; an opposite signal closes.
Exit models compared (R after spread):
  script  whole position until SL, TP3 or reversal (what the indicator tracks)
  tp1 / tp2  whole position at TP1 / TP2
  thirds  1/3 at TP1, 1/3 at TP2, 1/3 at TP3, SL never moves
  half_be half at TP1, stop to entry, rest to TP3 / entry / reversal
"""

import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "research")
from app.signals.scalping import _ema, _rma  # noqa: E402
from wolf_radar import FILES, load  # noqa: E402


def ema(x, n):
    return np.array(_ema(list(x), n), float)


def supertrend(H, L, C, factor, n):
    tr = np.maximum(H - L, np.maximum(abs(H - np.r_[C[0], C[:-1]]), abs(L - np.r_[C[0], C[:-1]])))
    atr = np.array(_rma(list(tr), n), float)
    hl2 = (H + L) / 2
    N = len(C)
    d = np.ones(N)
    ub, lb = np.full(N, np.nan), np.full(N, np.nan)
    st = np.full(N, np.nan)
    for i in range(N):
        if np.isnan(atr[i]):
            continue
        up, lo = hl2[i] + factor[i] * atr[i], hl2[i] - factor[i] * atr[i]
        pu, pl = ub[i - 1] if i else np.nan, lb[i - 1] if i else np.nan
        lb[i] = lo if np.isnan(pl) or lo > pl or C[i - 1] < pl else pl
        ub[i] = up if np.isnan(pu) or up < pu or C[i - 1] > pu else pu
        if i == 0 or np.isnan(atr[i - 1]):
            d[i] = 1
        elif st[i - 1] == pu:
            d[i] = -1 if C[i] > ub[i] else 1
        else:
            d[i] = 1 if C[i] < lb[i] else -1
        st[i] = lb[i] if d[i] == -1 else ub[i]
    return d


def signals(d, tick, sens=0.35, trend_len=34, mom_len=12, sl_mult=1.15):
    O, H, L, C = d["open"], d["high"], d["low"], d["close"]
    N = len(C)
    clip = lambda x, a, b: np.minimum(b, np.maximum(a, x))  # noqa: E731
    basis = ema(C, trend_len)
    tr = np.maximum(H - L, np.maximum(abs(H - np.r_[C[0], C[:-1]]), abs(L - np.r_[C[0], C[:-1]])))
    atr = np.nan_to_num(np.array(_rma(list(tr), 14), float), nan=tr[0])
    satr = np.maximum(atr, tick)
    lag = lambda x, k: np.r_[np.full(k, np.nan), x[:-k]]  # noqa: E731
    mom = ema(np.nan_to_num(C - lag(C, mom_len)), 5) / satr
    dist = (C - basis) / satr
    net = np.abs(C - lag(C, 10))
    path = np.convolve(np.abs(np.diff(C, prepend=C[0])), np.ones(10), mode="full")[:N]
    eff = np.where(path > 0, clip(np.nan_to_num(net / np.where(path > 0, path, 1)), 0, 1), 0)
    chop = 1 - eff
    edir = np.sign(np.nan_to_num(C - lag(C, 10)))
    normal = ema(satr, 50)
    vr = np.where(normal > 0, satr / normal, 1)
    vexp, vdev = clip(vr - 1, 0, 1.25), clip(np.abs(vr - 1), 0, 1.5)
    df = supertrend(H, L, C, 1.45 + chop * 0.25 + vexp * 0.10, 9)
    dm = supertrend(H, L, C, 1.95 + chop * 0.35 + vexp * 0.15, 14)
    ds = supertrend(H, L, C, 2.55 + chop * 0.45 + vexp * 0.20, 21)
    bv = (df < 0).astype(int) + (dm < 0) + (ds < 0)
    sv = (df > 0).astype(int) + (dm > 0) + (ds > 0)
    req = np.where(chop > 0.70, 3, 2)
    dlt = np.diff(C, prepend=C[0])
    up, dn = np.array(_rma(list(np.maximum(dlt, 0)), 14)), np.array(_rma(list(np.maximum(-dlt, 0)), 14))
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.nan_to_num(np.where(dn == 0, 100.0, 100 - 100 / (1 + up / dn)), nan=50)
    slow = ema((H + L) / 2, max(10, int(round(trend_len * 0.7))))
    sl_len = max(3, int(round(trend_len * 0.12)))
    rh = np.array([H[max(0, i - sl_len):i].max() if i else H[0] for i in range(N)])
    rl = np.array([L[max(0, i - sl_len):i].min() if i else L[0] for i in range(N)])
    rngb = np.maximum(H - L, tick)
    press = clip((C - O) / rngb * 0.6 + ((C - L) / rngb - 0.5) * 2 * 0.4, -1, 1)
    raw = (clip(dist / 1.2, -1, 1) * 0.22 + clip(np.nan_to_num(mom) / 0.35, -1, 1) * 0.19 +
           clip(np.nan_to_num((basis - lag(basis, 3)) / satr) / 0.25, -1, 1) * 0.14 +
           clip(np.nan_to_num((slow - lag(slow, 3)) / satr) / 0.25, -1, 1) * 0.10 +
           clip((rsi - 50) / 20, -1, 1) * 0.08 + eff * edir * 0.09 + press * 0.05 +
           np.where(C > rh, 1.0, np.where(C < rl, -1.0, 0.0)) * 0.05 + (bv - sv) / 3.0 * 0.20)
    regime = ema(np.nan_to_num(raw), 3)
    gate = 0.22 + sens * 0.12 + chop * 0.085 + clip(vdev * 0.04, 0, 0.06)
    bull_c = (regime > gate) & (C > basis + satr * sens * 0.3) & (mom > 0.025)
    bear_c = (regime < -gate) & (C < basis - satr * sens * 0.3) & (mom < -0.025)
    sig = np.zeros(N, int)
    sl = np.full(N, np.nan)
    bsb = ssb = bcf = scf = 0
    trend, last_flip = 0, None
    for i in range(60, N):
        bsb = min(bsb + 1, 5) if bv[i] >= req[i] else 0
        ssb = min(ssb + 1, 5) if sv[i] >= req[i] else 0
        pr = 2 if chop[i] > 0.72 else 1
        bc = bull_c[i] and bsb >= pr
        sc = bear_c[i] and ssb >= pr
        bcf = min(bcf + 1, 4) if bc else 0
        scf = min(scf + 1, 4) if sc else 0
        rb = 3 if chop[i] > 0.72 else 2 if chop[i] > 0.40 else 1
        sb = bc and bv[i] == 3 and regime[i] > gate[i] + 0.26 and mom[i] > 0.16 and eff[i] > 0.42
        ss = sc and sv[i] == 3 and regime[i] < -(gate[i] + 0.26) and mom[i] < -0.16 and eff[i] > 0.42
        br = (bcf >= rb or sb) and df[i] < 0 and (dm[i] < 0 or ds[i] < 0)
        sr = (scf >= rb or ss) and df[i] > 0 and (dm[i] > 0 or ds[i] > 0)
        cd = 6 + int(round(chop[i] * 4))
        done = last_flip is None or i - last_flip >= cd
        if trend != 1 and br and (done or sb):
            trend, last_flip, bcf, scf, bsb, ssb = 1, i, 0, 0, 0, 0
            sig[i] = 1
        elif trend != -1 and sr and (done or ss):
            trend, last_flip, bcf, scf, bsb, ssb = -1, i, 0, 0, 0, 0
            sig[i] = -1
        if sig[i]:
            anchor = basis[i] - sig[i] * satr[i] * sl_mult
            e = C[i]
            sl[i] = min(anchor, e - 10 * tick) if sig[i] == 1 else max(anchor, e + 10 * tick)
    return sig, sl


def trades(d, sig, sl, model):
    H, L, C = d["high"], d["low"], d["close"]
    med = float(np.median(d["spread"]))
    out, pos = [], None
    for i in range(len(C)):
        if pos is not None and i > pos["i"]:
            s, e, risk = pos["d"], pos["e"], pos["risk"]
            stop = pos["stop"]
            if (s == 1 and L[i] <= stop) or (s == -1 and H[i] >= stop):
                pos["r"] += pos["left"] * (stop - e) * s / risk
                pos["left"] = 0
            else:
                for k, part in pos["targets"]:
                    if pos["left"] > 1e-9 and not pos["hit"][k] and s * ((H[i] if s == 1 else L[i]) - (e + s * k * risk)) >= 0:
                        pos["hit"][k] = True
                        take = min(part, pos["left"])
                        pos["r"] += take * k
                        pos["left"] -= take
                        if model == "half_be" and k == 1:
                            pos["stop"] = e
            if pos["left"] > 1e-9 and sig[i] == -s:
                pos["r"] += pos["left"] * (C[i] - e) * s / risk
                pos["left"] = 0
            if pos["left"] <= 1e-9:
                out.append((pos["i"], s, pos["r"] - pos["cost"] / risk, pos["hit"][1]))
                pos = None
        if sig[i] and pos is None:
            e = C[i]
            risk = abs(e - sl[i])
            tg = {"script": [(3, 1.0)], "tp1": [(1, 1.0)], "tp2": [(2, 1.0)],
                  "thirds": [(1, 1 / 3), (2, 1 / 3), (3, 1 / 3)], "half_be": [(1, 0.5), (3, 0.5)]}[model]
            pos = dict(i=i, d=sig[i], e=e, risk=risk, stop=sl[i], left=1.0, r=0.0, targets=tg,
                       hit={1: False, 2: False, 3: False}, cost=max(d["spread"][i], med))
    return out


def st(rows):
    if not rows:
        return "no trades"
    r = np.array([x[2] for x in rows])
    eq = np.cumsum(r)
    return (f"n {len(r):4} win {100 * (r > 0).mean():5.1f}% net {r.sum():+7.1f}R avg {r.mean():+.3f} "
            f"maxDD {(eq - np.maximum.accumulate(eq)).min():6.1f}R")


if __name__ == "__main__":
    for (sym, tf), f in FILES.items():
        d = load(f)
        tick = d["point"]
        sig, sl = signals(d, tick)
        n = len(d["close"])
        span = (f"{datetime.fromtimestamp(d['time'][0], timezone.utc).date()} .. "
                f"{datetime.fromtimestamp(d['time'][-1], timezone.utc).date()}")
        print(f"\n### {sym} {tf}m ({span}) - {int((sig != 0).sum())} UP/DOWN signals")
        for model in ("script", "tp1", "tp2", "thirds", "half_be"):
            rows = trades(d, sig, sl, model)
            extra = ""
            if model == "script":
                t1 = 100 * np.mean([x[3] for x in rows]) if rows else 0
                extra = f" | TP1 touched on {t1:.0f}% of trades"
            print(f"  {model:8} {st(rows)} | 1st half {st([x for x in rows if x[0] < n // 2]).split(' avg')[0]} | "
                  f"2nd half {st([x for x in rows if x[0] >= n // 2]).split(' avg')[0]}{extra}")
