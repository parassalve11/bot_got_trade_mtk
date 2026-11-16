"""Scalping Patterns, ported line-by-line from pine/scalping_patterns.pine.

Pure maths (no MT5, database or clock). `scalp_trades(bars, tf_minutes, cfg)` replays the Pine
script bar by bar over CLOSED candles and returns the indicator's own trades (entry candle,
Entry / SL / TP1 / TP2, exit reason and the result in R exactly as the chart's dashboard counts
it: half closed at TP1, rest at TP2 / breakeven / time exit).

Bars need: time (seconds, broker/exchange clock: a new date = a new session), open, high, low,
close, volume. Pine `na` is NaN here; comparisons with NaN are False, like Pine's.

`cfg.fixed=True` applies the corrections made in the Pine file (v2):
  * a stop-loss gapped through fills at the candle open, not at the stop price (was optimistic);
  * "Reverse on opposite signal" really reverses: the pause after a losing trade no longer
    blocks the opposite entry on the same candle.
"""

import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

NA = float("nan")


class ScalpSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: str = Field(default="More trades", pattern=r"^(More trades|Balanced|Strict)$")
    rev_opp: bool = False
    use_orb: bool = True
    use_vwp: bool = True
    use_mpb: bool = True
    use_flag: bool = True
    use_ib: bool = True
    use_swp: bool = True
    use_dbl: bool = True
    trade_dir: str = Field(default="Long & Short", pattern=r"^(Long & Short|Long only|Short only)$")
    tp1_r: float = Field(default=1.0, ge=0.25)
    tp2_pattern: bool = True
    tp2_r: float = Field(default=2.0, ge=0.5)
    max_tp_r: float = Field(default=3.0, ge=1.0)
    be_after_tp1: bool = True
    sl_buf_atr: float = Field(default=0.1, ge=0)
    min_risk_atr: float = Field(default=0.6, ge=0.05)
    time_stop_min: int = Field(default=15, ge=1)
    use_trend: bool = True
    use_chop: bool = True
    adx_min: int = Field(default=20, ge=5, le=50)
    no_counter: bool = True
    pause_bars: int = Field(default=3, ge=0)
    max_loss_r: float = Field(default=3.0, ge=0)
    vol_len: int = 20
    dead_k: float = 0.5
    orb_min: int = 5
    sw_l: int = 5
    sw_r: int = 2
    pole_max: int = 8
    flag_max: int = 10
    swp_max: float = 1.0
    fixed: bool = True


@dataclass
class ScalpTrade:
    bar: int            # entry candle index
    time: float
    side: str           # LONG / SHORT
    pattern: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    risk: float
    exit_bar: int = -1
    exit_price: float = NA
    reason: str = ""
    tp1_hit: bool = False
    r: float = NA       # result as the Pine dashboard counts it


PATTERNS = {1: "ORB", 2: "VWAP Pullback", 3: "Micro Pullback", 4: "Flag", 5: "Inside Bar",
            6: "Sweep", 7: "Double Top/Bottom"}


def _na(v) -> bool:
    return v is None or v != v


def _rma(src, n):
    out, prev, buf = [], NA, []
    for x in src:
        if _na(prev):
            if not _na(x):
                buf.append(x)
            cur = sum(buf[-n:]) / n if len(buf) >= n else NA
        else:
            cur = (x + (n - 1) * prev) / n
        out.append(cur)
        prev = cur
    return out


def _ema(src, n):
    a, out, prev, buf = 2 / (n + 1), [], NA, []
    for x in src:
        if _na(prev):
            buf.append(x)
            cur = sum(buf[-n:]) / n if len(buf) >= n else NA
        else:
            cur = a * x + (1 - a) * prev
        out.append(cur)
        prev = cur
    return out


def _sma(src, n):
    out, s, q = [], 0.0, []
    for x in src:
        q.append(x)
        s += x if not _na(x) else 0
        if len(q) > n:
            old = q.pop(0)
            s -= old if not _na(old) else 0
        out.append(s / n if len(q) == n and not any(_na(v) for v in q) else NA)
    return out


def _roll(src, n, fn):
    return [fn(src[i - n + 1:i + 1]) if i >= n - 1 else NA for i in range(len(src))]


def scalp_trades(bars: list[dict], tf_minutes: float, cfg: ScalpSettings | None = None) -> list[ScalpTrade]:
    cfg = cfg or ScalpSettings()
    OPN = [b["open"] for b in bars]
    H = [b["high"] for b in bars]
    L = [b["low"] for b in bars]
    C = [b["close"] for b in bars]
    V = [b.get("volume", 0.0) or 0.0 for b in bars]
    T = [b["time"] for b in bars]
    n = len(bars)

    more, bal, strict = cfg.mode == "More trades", cfg.mode == "Balanced", cfg.mode == "Strict"

    def fm(m, b, s):
        return m if more else b if bal else s

    eUseVol = not more
    eVolMult = fm(1.0, 1.2, 1.5)
    eLate = fm(1.5, 1.2, 1.0)
    eMaxRisk = fm(3.0, 2.5, 2.0)
    eUseDead = not more
    eMaxTr = fm(30, 15, 8)
    ePole = fm(1.5, 1.75, 2.0)
    eFlagMin = fm(2, 3, 3)
    eFlagRet = fm(0.6, 0.55, 0.5)
    eDblTol = fm(0.7, 0.6, 0.5)
    eDblMinH = fm(0.8, 0.9, 1.0)
    eSwpAge = fm(5, 8, 10)
    eSwpLook = fm(20, 25, 30)
    eSwpWick = fm(0.4, 0.45, 0.5)
    eVpN = fm(3, 4, 5)
    eVpDrive = fm(0.5, 0.75, 1.0)
    eVpTouch = fm(0.3, 0.2, 0.15)
    eVpGreen = strict
    eMpSep = fm(0.1, 0.15, 0.2)
    eMpVwap = not more
    eMpTouch = fm(0.3, 0.2, 0.1)
    eIbMin = fm(0.3, 0.4, 0.5)
    eIbEma = not more
    tsBars = max(3, int(math.floor(cfg.time_stop_min / tf_minutes + 0.5)))

    # ─── core series ───
    TR = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
    ATR = _rma(TR, 14)
    ATRA = _sma(ATR, 100)
    E9, E20, E50 = _ema(C, 9), _ema(C, 20), _ema(C, 50)
    up = [NA] + [H[i] - H[i - 1] for i in range(1, n)]
    dn = [NA] + [L[i - 1] - L[i] for i in range(1, n)]
    pdm = [NA if _na(u) else (u if u > d and u > 0 else 0.0) for u, d in zip(up, dn)]
    mdm = [NA if _na(d) else (d if d > u and d > 0 else 0.0) for u, d in zip(up, dn)]
    trur = _rma(TR, 14)
    plus = [100 * a / t if not _na(a) and t else NA for a, t in zip(_rma(pdm, 14), trur)]
    minus = [100 * a / t if not _na(a) and t else NA for a, t in zip(_rma(mdm, 14), trur)]
    dx = [NA if _na(p) or _na(m) else abs(p - m) / (p + m if p + m != 0 else 1) for p, m in zip(plus, minus)]
    ADX = [100 * x if not _na(x) else NA for x in _rma(dx, 14)]
    hasVolCum = []
    acc = 0.0
    for v in V:
        acc += v
        hasVolCum.append(acc > 0)
    VOLA = _sma(V, cfg.vol_len)
    HH20, LL20 = _roll(H, 20, max), _roll(L, 20, min)
    HHS, LLS = _roll(H, eSwpLook, max), _roll(L, eSwpLook, min)
    day = [int(t // 86400) for t in T]
    NEWDAY = [i == 0 or day[i] != day[i - 1] for i in range(n)]
    VW = []
    sPV = sV = sP = 0.0
    sN = 0
    for i in range(n):
        if NEWDAY[i]:
            sPV = sV = sP = 0.0
            sN = 0
        hlc3 = (H[i] + L[i] + C[i]) / 3
        sPV += hlc3 * V[i]
        sV += V[i]
        sP += hlc3
        sN += 1
        VW.append(sPV / sV if sV > 0 else sP / sN)
    DV = [c - w for c, w in zip(C, VW)]
    MINDV, MAXDV = _roll(DV, eVpN, min), _roll(DV, eVpN, max)
    HIABV = _roll([h - w for h, w in zip(H, VW)], 15, max)
    LOBLW = _roll([lo - w for lo, w in zip(L, VW)], 15, min)

    def g(arr, i):
        return arr[i] if i >= 0 else NA

    def dir_ok(d):
        return cfg.trade_dir == "Long & Short" or (d == 1 and cfg.trade_dir == "Long only") or \
            (d == -1 and cfg.trade_dir == "Short only")

    # ─── state ───
    dayH = dayL = pdh = pdl = NA
    dayOpenT = dayOpenB = None
    orH = orL = NA
    orDone = orbUpUsed = orbDnUsed = False
    tradesToday = 0
    rToday = 0.0
    zP, zB, zD = [], [], []
    hLv, hLb, hLt, lLv, lLb, lLt = [], [], [], [], [], []
    dt = dict(on=False, neck=NA, top=NA, exp=0)
    db = dict(on=False, neck=NA, bot=NA, exp=0)
    trade: ScalpTrade | None = None
    trT1 = False
    trSL = NA

    pauseUntil = -1
    trades: list[ScalpTrade] = []

    def f_add(p, b, d):
        if zD and zD[-1] == d:
            if (d == 1 and p > zP[-1]) or (d == -1 and p < zP[-1]):
                zP[-1], zB[-1] = p, b
            return False
        zP.append(p)
        zB.append(b)
        zD.append(d)
        if len(zP) > 50:
            zP.pop(0)
            zB.pop(0)
            zD.pop(0)
        return True

    def f_p(i):
        return zP[-1 - i] if 0 <= i < len(zP) else NA

    def f_b(i):
        return zB[-1 - i] if 0 <= i < len(zB) else None

    def f_d(i):
        return zD[-1 - i] if 0 <= i < len(zD) else 0

    def push(lv, lb, lt, p, b, t):
        lv.append(p)
        lb.append(b)
        lt.append(t)
        if len(lv) > 12:
            lv.pop(0)
            lb.pop(0)
            lt.pop(0)

    for bi in range(n):
        o, h, lo, c = OPN[bi], H[bi], L[bi], C[bi]
        atrV, vwapV = ATR[bi], VW[bi]
        newDay = NEWDAY[bi]
        hasVol = hasVolCum[bi]
        volOk = not eUseVol or not hasVol or V[bi] >= eVolMult * VOLA[bi]
        notDead = not eUseDead or _na(ATRA[bi]) or atrV >= cfg.dead_k * ATRA[bi]
        orJustDone = False

        if newDay:
            pdh, pdl = dayH, dayL
            dayH, dayL = h, lo
            dayOpenT, dayOpenB = T[bi], bi
            orH, orL = h, lo
            orDone = orbUpUsed = orbDnUsed = False
            tradesToday = 0
            rToday = 0.0
        else:
            dayH, dayL = max(dayH, h), min(dayL, lo)
            if not orDone:
                if T[bi] < dayOpenT + cfg.orb_min * 60:
                    orH, orL = max(orH, h), min(orL, lo)
                else:
                    orDone = orJustDone = True

        # swings
        ph = pl = NA
        cpiv = bi - cfg.sw_r
        if cpiv - cfg.sw_l >= 0:
            hc, lc = H[cpiv], L[cpiv]
            if all(H[j] < hc for j in range(cpiv - cfg.sw_l, cpiv)) and all(H[j] <= hc for j in range(cpiv + 1, bi + 1)):
                ph = hc
            if all(L[j] > lc for j in range(cpiv - cfg.sw_l, cpiv)) and all(L[j] >= lc for j in range(cpiv + 1, bi + 1)):
                pl = lc
        newHi = newLo = False
        if not _na(ph):
            newHi = f_add(ph, cpiv, 1)
        if not _na(pl):
            newLo = f_add(pl, cpiv, -1)
        zn = len(zP)

        # liquidity levels
        if not _na(ph) and ph >= HHS[bi]:
            push(hLv, hLb, hLt, ph, cpiv, "Swing High")
        if not _na(pl) and pl <= LLS[bi]:
            push(lLv, lLb, lLt, pl, cpiv, "Swing Low")
        if newDay and not _na(pdh):
            push(hLv, hLb, hLt, pdh, bi, "Prev Day High")
            push(lLv, lLb, lLt, pdl, bi, "Prev Day Low")
        if orJustDone:
            push(hLv, hLb, hLt, orH, dayOpenB, "ORB High")
            push(lLv, lLb, lLt, orL, dayOpenB, "ORB Low")

        swpDir, swpLvl = 0, NA
        rng = h - lo
        rejDn = rng > 0 and ((h - max(o, c)) >= eSwpWick * rng or (c < o and c <= (h + lo) / 2 and c < g(L, bi - 1)))
        rejUp = rng > 0 and ((min(o, c) - lo) >= eSwpWick * rng or (c > o and c >= (h + lo) / 2 and c > g(H, bi - 1)))
        for i in range(len(hLv) - 1, -1, -1):
            lv = hLv[i]
            if c > lv:
                del hLv[i], hLb[i], hLt[i]
            elif h > lv:
                if swpDir == 0 and rejDn and h - lv <= cfg.swp_max * atrV and bi - hLb[i] >= eSwpAge:
                    swpDir, swpLvl = -1, lv
                del hLv[i], hLb[i], hLt[i]
        for i in range(len(lLv) - 1, -1, -1):
            lv = lLv[i]
            if c < lv:
                del lLv[i], lLb[i], lLt[i]
            elif lo < lv:
                if swpDir == 0 and rejUp and lv - lo <= cfg.swp_max * atrV and bi - lLb[i] >= eSwpAge:
                    swpDir, swpLvl = 1, lv
                del lLv[i], lLb[i], lLt[i]

        # double top / bottom
        if newHi and zn >= 4 and f_d(0) == 1:
            h2, h1, nk = f_p(0), f_p(2), f_p(1)
            top = max(h1, h2)
            gap = f_b(0) - f_b(2)
            if abs(h1 - h2) <= eDblTol * atrV and top - nk >= eDblMinH * atrV and 3 <= gap <= 80 and f_p(3) < nk:
                dt.update(on=True, neck=nk, top=top, exp=bi + 30)
        if newLo and zn >= 4 and f_d(0) == -1:
            l2, l1, nk = f_p(0), f_p(2), f_p(1)
            bot = min(l1, l2)
            gap = f_b(0) - f_b(2)
            if abs(l1 - l2) <= eDblTol * atrV and nk - bot >= eDblMinH * atrV and 3 <= gap <= 80 and f_p(3) > nk:
                db.update(on=True, neck=nk, bot=bot, exp=bi + 30)
        dtSig = dbSig = False
        if dt["on"]:
            if c > dt["top"] or bi > dt["exp"]:
                dt["on"] = False
            elif c < dt["neck"]:
                dtSig, dt["on"] = True, False
        if db["on"]:
            if c < db["bot"] or bi > db["exp"]:
                db["on"] = False
            elif c > db["neck"]:
                dbSig, db["on"] = True, False

        # flags
        def f_flag(d):
            for fl in range(eFlagMin, cfg.flag_max + 1):
                fHi, fLo = g(H, bi - 1), g(L, bi - 1)
                for k in range(1, fl + 1):
                    fHi, fLo = max(fHi, g(H, bi - k)), min(fLo, g(L, bi - k))
                top = g(H, bi - fl - 1) if d == 1 else g(L, bi - fl - 1)
                if _na(top) or _na(fHi) or _na(fLo):
                    continue
                if not (top > fHi if d == 1 else top < fLo):
                    continue
                pS = g(L, bi - fl - 1) if d == 1 else g(H, bi - fl - 1)
                for k in range(fl + 2, fl + 2 + cfg.pole_max):
                    if d == 1 and g(L, bi - k) < pS:
                        pS = g(L, bi - k)
                    if d == -1 and g(H, bi - k) > pS:
                        pS = g(H, bi - k)
                pH = top - pS if d == 1 else pS - top
                ret = top - fLo if d == 1 else fHi - top
                brk = c > fHi if d == 1 else c < fLo
                if pH >= ePole * atrV and ret <= eFlagRet * pH and fHi - fLo <= 0.6 * pH and brk:
                    return True, (fHi if d == 1 else fLo), (fLo if d == 1 else fHi), pH, fHi, fLo
            return False, NA, NA, NA, NA, NA

        bf = f_flag(1)
        sf = f_flag(-1)

        # micro pullback
        nRed = nGrn = 0
        for i in range(1, 4):
            if g(C, bi - i) < g(OPN, bi - i):
                nRed += 1
            else:
                break
        for i in range(1, 4):
            if g(C, bi - i) > g(OPN, bi - i):
                nGrn += 1
            else:
                break
        mpTouchL, mpHoldL, mpLowL = False, True, NA
        if nRed > 0:
            mpLowL = L[bi - 1]
            for i in range(1, nRed + 1):
                mpLowL = min(mpLowL, L[bi - i])
                if L[bi - i] <= E9[bi - i] + eMpTouch * atrV:
                    mpTouchL = True
                if C[bi - i] <= E20[bi - i]:
                    mpHoldL = False
        mpTouchS, mpHoldS, mpHighS = False, True, NA
        if nGrn > 0:
            mpHighS = H[bi - 1]
            for i in range(1, nGrn + 1):
                mpHighS = max(mpHighS, H[bi - i])
                if H[bi - i] >= E9[bi - i] - eMpTouch * atrV:
                    mpTouchS = True
                if C[bi - i] >= E20[bi - i]:
                    mpHoldS = False

        # ═══ pick the signal (first match wins) ═══
        cDir, cPat = 0, 0
        cTrig = cSLr = cSLalt = cPT = NA
        cBrk = False

        orbUp = orDone and not orbUpUsed and c > orH and g(C, bi - 1) <= orH
        orbDn = orDone and not orbDnUsed and c < orL and g(C, bi - 1) >= orL
        if orbUp:
            orbUpUsed = True
        if orbDn:
            orbDnUsed = True
        if cfg.use_orb:
            if orbUp and c > vwapV and dir_ok(1):
                cDir, cTrig, cPT = 1, orH, orH + (orH - orL)
            elif orbDn and c < vwapV and dir_ok(-1):
                cDir, cTrig, cPT = -1, orL, orL - (orH - orL)
            if cDir:
                cPat, cSLr, cBrk = 1, (orH + orL) / 2, True
        if cfg.use_swp and cDir == 0 and swpDir != 0 and dir_ok(swpDir):
            cDir, cPat, cTrig = swpDir, 6, swpLvl
            cSLr = lo if swpDir == 1 else h
            cPT = vwapV if (swpDir == 1 and vwapV > c) or (swpDir == -1 and vwapV < c) else NA
        if cfg.use_dbl and cDir == 0:
            if dtSig and dir_ok(-1):
                cDir, cPat, cTrig, cSLr = -1, 7, dt["neck"], dt["top"]
                cSLalt = (dt["top"] + dt["neck"]) / 2
                cPT = dt["neck"] - (dt["top"] - dt["neck"])
                cBrk = True
            elif dbSig and dir_ok(1):
                cDir, cPat, cTrig, cSLr = 1, 7, db["neck"], db["bot"]
                cSLalt = (db["bot"] + db["neck"]) / 2
                cPT = db["neck"] + (db["neck"] - db["bot"])
                cBrk = True
        if cfg.use_flag and cDir == 0:
            if bf[0] and dir_ok(1):
                cDir, cPat, cTrig, cSLr = 1, 4, bf[1], bf[2]
                cSLalt, cPT, cBrk = (bf[4] + bf[5]) / 2, c + bf[3], True
            elif sf[0] and dir_ok(-1):
                cDir, cPat, cTrig, cSLr = -1, 4, sf[1], sf[2]
                cSLalt, cPT, cBrk = (sf[4] + sf[5]) / 2, c - sf[3], True
        vpL = (g(MINDV, bi - 1) > 0 and g(HIABV, bi - 1) >= eVpDrive * atrV and g(L, bi - 1) <= g(VW, bi - 1) + eVpTouch * atrV
               and (g(C, bi - 1) > g(OPN, bi - 1) or not eVpGreen) and c > g(H, bi - 1) and c > o and E9[bi] > E20[bi])
        vpS = (g(MAXDV, bi - 1) < 0 and g(LOBLW, bi - 1) <= -eVpDrive * atrV and g(H, bi - 1) >= g(VW, bi - 1) - eVpTouch * atrV
               and (g(C, bi - 1) < g(OPN, bi - 1) or not eVpGreen) and c < g(L, bi - 1) and c < o and E9[bi] < E20[bi])
        if cfg.use_vwp and cDir == 0:
            if vpL and dir_ok(1):
                cDir, cTrig, cSLr, cPT = 1, H[bi - 1], L[bi - 1], HH20[bi - 1]
            elif vpS and dir_ok(-1):
                cDir, cTrig, cSLr, cPT = -1, L[bi - 1], H[bi - 1], LL20[bi - 1]
            if cDir:
                cPat = 2
        e20_3 = g(E20, bi - 3)
        trendUp = (E9[bi] > E20[bi] and E9[bi] - E20[bi] >= eMpSep * atrV and E20[bi] > e20_3 and (c > vwapV or not eMpVwap))
        trendDn = (E9[bi] < E20[bi] and E20[bi] - E9[bi] >= eMpSep * atrV and E20[bi] < e20_3 and (c < vwapV or not eMpVwap))
        mpL = nRed >= 1 and g(C, bi - nRed - 1) > g(OPN, bi - nRed - 1) and mpTouchL and mpHoldL and trendUp and c > H[bi - 1] and c > o
        mpS = nGrn >= 1 and g(C, bi - nGrn - 1) < g(OPN, bi - nGrn - 1) and mpTouchS and mpHoldS and trendDn and c < L[bi - 1] and c < o
        if cfg.use_mpb and cDir == 0:
            if mpL and dir_ok(1):
                cDir, cTrig, cSLr, cPT = 1, H[bi - 1], mpLowL, HH20[bi - 1]
            elif mpS and dir_ok(-1):
                cDir, cTrig, cSLr, cPT = -1, L[bi - 1], mpHighS, LL20[bi - 1]
            if cDir:
                cPat = 3
        h1_, h2_, h3_ = g(H, bi - 1), g(H, bi - 2), g(H, bi - 3)
        l1_, l2_, l3_ = g(L, bi - 1), g(L, bi - 2), g(L, bi - 3)
        ib2 = h1_ <= h3_ and l1_ >= l3_ and h2_ <= h3_ and l2_ >= l3_
        ib1 = h1_ <= h2_ and l1_ >= l2_
        ibH, ibL = (h3_, l3_) if ib2 else (h2_, l2_)
        ibInL = min(l1_, l2_) if ib2 else l1_
        ibInH = max(h1_, h2_) if ib2 else h1_
        ibOk = (ib1 or ib2) and ibH - ibL >= eIbMin * atrV
        if cfg.use_ib and cDir == 0 and ibOk:
            if c > ibH and (E9[bi] > E20[bi] if eIbEma else c > E20[bi]) and dir_ok(1):
                cDir, cTrig, cSLr, cSLalt = 1, ibH, ibL, ibInL
            elif c < ibL and (E9[bi] < E20[bi] if eIbEma else c < E20[bi]) and dir_ok(-1):
                cDir, cTrig, cSLr, cSLalt = -1, ibL, ibH, ibInH
            if cDir:
                cPat, cBrk = 5, True

        cCont = 1 <= cPat <= 5
        trUpQ = c > vwapV and E20[bi] > E50[bi]
        trDnQ = c < vwapV and E20[bi] < E50[bi]
        chopOk = not cfg.use_chop or ADX[bi] >= cfg.adx_min

        why, sl, risk, candOk = "", NA, NA, False
        if cDir:
            sl = cSLr - cDir * cfg.sl_buf_atr * atrV
            risk = cDir * (c - sl)
            if risk > eMaxRisk * atrV and not _na(cSLalt):
                sl = cSLalt - cDir * cfg.sl_buf_atr * atrV
                risk = cDir * (c - sl)
            if risk < cfg.min_risk_atr * atrV:
                risk = cfg.min_risk_atr * atrV
                sl = c - cDir * risk
            if cCont and cfg.use_trend and not (trUpQ if cDir == 1 else trDnQ):
                why = "against trend"
            elif cCont and not chopOk:
                why = "sideways market"
            elif not cCont and cfg.no_counter and ADX[bi] > 30 and (trDnQ if cDir == 1 else trUpQ):
                why = "against strong trend"
            elif cBrk and not volOk:
                why = "low volume"
            elif not _na(cTrig) and cBrk and cDir * (c - cTrig) > eLate * atrV:
                why = "late breakout"
            elif risk > eMaxRisk * atrV or _na(risk):
                why = "SL too wide"
            candOk = (why == "" and tradesToday < eMaxTr and notDead and bi >= pauseUntil
                      and (cfg.max_loss_r == 0 or rToday > -cfg.max_loss_r))

        # manage the open trade
        reversed_now = False
        if trade is not None and bi > trade.bar:
            d = 1 if trade.side == "LONG" else -1
            slHit = lo <= trSL if d == 1 else h >= trSL
            t2Hit = h >= trade.tp2 if d == 1 else lo <= trade.tp2
            ex, exP = "", NA
            if slHit:
                ex = "Breakeven exit" if trT1 else "SL hit"
                exP = trSL
                if cfg.fixed and (o < trSL if d == 1 else o > trSL):
                    exP = o  # gapped through the stop: filled at the open
            else:
                if not trT1 and (h >= trade.tp1 if d == 1 else lo <= trade.tp1):
                    trT1 = True
                    if cfg.be_after_tp1:
                        trSL = trade.entry
                if t2Hit:
                    ex, exP = "TP2 hit", trade.tp2
                elif not trT1 and bi - trade.bar >= tsBars:
                    ex, exP = "Time exit", c
                elif bi - trade.bar >= 4 * tsBars:
                    ex, exP = "Time exit", c
                elif cfg.rev_opp and candOk and cDir == -d:
                    ex, exP = "Reversed", c
                    reversed_now = True
            if ex:
                exR = d * (exP - trade.entry) / trade.risk
                rRes = 0.5 * cfg.tp1_r + 0.5 * exR if trT1 else exR
                trade.exit_bar, trade.exit_price, trade.reason, trade.tp1_hit, trade.r = bi, exP, ex, trT1, rRes
                trades.append(trade)
                rToday += rRes
                if rRes <= 0:
                    pauseUntil = bi + cfg.pause_bars
                trade = None

        paused = bi < pauseUntil and not (cfg.fixed and reversed_now)
        if (cDir and trade is None and tradesToday < eMaxTr and notDead and not paused
                and (cfg.max_loss_r == 0 or rToday > -cfg.max_loss_r) and why == ""):
            en = c
            tp1 = en + cDir * cfg.tp1_r * risk
            tp2 = en + cDir * cfg.tp2_r * risk
            if cfg.tp2_pattern and not _na(cPT) and cDir * (cPT - tp1) > 0:
                tp2 = cPT
            if cDir * (tp2 - en) > cfg.max_tp_r * risk:
                tp2 = en + cDir * cfg.max_tp_r * risk
            if cDir * (tp2 - tp1) <= 0:
                tp2 = en + cDir * max(cfg.tp2_r, cfg.tp1_r + 0.5) * risk
            trade = ScalpTrade(bar=bi, time=T[bi], side="LONG" if cDir == 1 else "SHORT", pattern=PATTERNS[cPat],
                               entry=en, sl=sl, tp1=tp1, tp2=tp2, risk=risk)
            trSL, trT1 = sl, False
            tradesToday += 1
    return trades
