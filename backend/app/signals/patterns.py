"""Classic Chart Patterns, ported line-by-line from pine/classic_chart_patterns.pine.

Pure maths: no MT5, database or clock access. `pattern_signals(bars, cfg)` replays the Pine
script bar by bar over CLOSED candles and returns, for every bar, the BUY/SELL signal the
indicator draws on that candle (or None). Drawing-only code (labels, colors, polylines) is left
out; every value that decides a signal is kept, including the indicator's own simulated trade
(it suppresses a second BUY while its simulated long is still open, exactly like the chart).

Pine `na` is NaN or None here. Pine comparisons with na are false; so are Python's with NaN.

ta.pivothigh / ta.pivotlow tie rule (equal highs/lows): the pivot must be strictly beyond the
bars on its left and at least equal to those on its right, so on a flat top the first bar counts.
"""

import math
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

NA = float("nan")


class PatternSettings(BaseModel):
    """Pine input defaults. Changing one here must match the chart's settings to compare."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    piv_len: int = Field(default=5, ge=2, le=50)
    piv_r: int = Field(default=2, ge=1, le=50)
    tol_pct: float = Field(default=25, ge=1, le=60)
    flat_atr: float = Field(default=0.02, ge=0.001)
    touch_atr: float = Field(default=0.6, ge=0.1)
    min_h_atr: float = Field(default=1.5, ge=0.1)
    no_overlap: bool = True
    brk_bars: int = Field(default=60, ge=5)
    show_hs: bool = True
    show_ihs: bool = True
    show_sym: bool = True
    show_bt: bool = True
    show_at: bool = True
    show_desc: bool = True
    show_rw: bool = True
    show_fw: bool = True
    show_cup: bool = True
    show_rb: bool = True
    show_dia_t: bool = True
    show_dia_b: bool = True
    cup_min: int = Field(default=20, ge=10)
    cup_max: int = Field(default=300, ge=30, le=900)
    round_k: float = Field(default=0.6, ge=0.3, le=0.9)
    hdl_max: float = Field(default=0.5, ge=0.1, le=0.9)
    trade_dir: str = Field(default="Long & Short", pattern=r"^(Long & Short|Long only|Short only)$")
    sig_set: str = Field(default="All patterns",
                         pattern=r"^(All patterns|Reversal patterns only|Continuation patterns only)$")
    with_bias: bool = True
    rev_on_opp: bool = True
    tp_mult: float = Field(default=1.0, ge=0.25)
    sl_buf: float = Field(default=0.2, ge=0.0)
    max_hold: int = Field(default=150, ge=5)
    max_late: float = Field(default=1.0, ge=0.1)


@dataclass(frozen=True)
class PatternSignal:
    side: str          # LONG or SHORT
    close: float       # entry reference (signal candle close)
    stop: float        # stop-loss price
    target: float      # target price
    pattern: str
    reversal: bool


def _na(v) -> bool:
    return v is None or v != v


def atr14(highs, lows, closes, length=14):
    """ta.atr(14) = ta.rma(ta.tr(true), 14), seeded with the SMA."""
    out, prev = [], NA
    trs = []
    for i in range(len(highs)):
        tr = highs[i] - lows[i] if i == 0 else max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                                                   abs(lows[i] - closes[i - 1]))
        trs.append(tr)
        if _na(prev):
            cur = sum(trs[-length:]) / length if len(trs) >= length else NA
        else:
            cur = (tr + (length - 1) * prev) / length
        out.append(cur)
        prev = cur
    return out


@dataclass
class _Line:
    x1: int
    y1: float
    x2: int
    y2: float

    def price(self, x):  # line.get_price
        return self.y1 if self.x2 == self.x1 else self.y1 + (self.y2 - self.y1) * (x - self.x1) / (self.x2 - self.x1)


def _y(x1, y1, x2, y2, x):
    return y1 if x2 == x1 else y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def _ix(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    m1 = (ay2 - ay1) / (ax2 - ax1)
    m2 = (by2 - by1) / (bx2 - bx1)
    return NA if m1 == m2 else (by1 - ay1 + m1 * ax1 - m2 * bx1) / (m1 - m2)


@dataclass
class _State:
    zP: list = field(default_factory=list)
    zB: list = field(default_factory=list)
    zD: list = field(default_factory=list)
    lastEnd: int = -1
    lpPrevEnd: int = -1
    lpName: str = ""
    lpStart: object = None
    lpEnd: object = None
    actUp: object = None
    actLo: object = None
    actEnd: object = None
    actName: str = ""
    actBias: int = 0
    actRev: bool = False
    actH: float = NA
    actSLl: float = NA
    actSLs: float = NA
    trDir: int = 0
    trSL: float = NA
    trTP: float = NA
    trBar: object = None


def pattern_signals(bars: list[dict], cfg: PatternSettings | None = None) -> list[PatternSignal | None]:
    """Signal for every CLOSED bar in `bars` (oldest first). Never pass a forming bar."""
    cfg = cfg or PatternSettings()
    H = [b["high"] for b in bars]
    L = [b["low"] for b in bars]
    C = [b["close"] for b in bars]
    HL2 = [(h + l) / 2 for h, l in zip(H, L)]
    ATR = atr14(H, L, C)
    tolPct = cfg.tol_pct / 100
    s = _State()
    out: list[PatternSignal | None] = []

    for bi in range(len(bars)):
        atrV = ATR[bi]
        close = C[bi]

        def f_p(i):
            idx = len(s.zP) - 1 - i
            return s.zP[idx] if idx >= 0 and i >= 0 else NA

        def f_b(i):
            idx = len(s.zB) - 1 - i
            return s.zB[idx] if idx >= 0 and i >= 0 else None

        def f_d(i):
            idx = len(s.zD) - 1 - i
            return s.zD[idx] if idx >= 0 and i >= 0 else 0

        def f_add(p, b, d):
            cnt = len(s.zP)
            last_dir = s.zD[cnt - 1] if cnt > 0 else 0
            if last_dir == d:
                last = s.zP[cnt - 1]
                if (d == 1 and p > last) or (d == -1 and p < last):
                    s.zP[cnt - 1] = p
                    s.zB[cnt - 1] = b
                return False
            s.zP.append(p)
            s.zB.append(b)
            s.zD.append(d)
            if len(s.zP) > 80:
                s.zP.pop(0)
                s.zB.pop(0)
                s.zD.pop(0)
            return True

        def f_avgMid(q):
            tot, c = 0.0, 0
            for j in range(-2, 3):
                off = bi - (q + j)
                if 0 <= off < 999:
                    tot += HL2[bi - off]
                    c += 1
            return tot / c if c > 0 else NA

        def f_viol(ux1, uy1, ux2, uy2, lx1, ly1, lx2, ly2, xs, xe, tol):
            bad = tot = 0
            for x in range(xs, xe + 1):
                off = bi - x
                if 0 <= off < 999:
                    tot += 1
                    c = C[x]
                    if c > _y(ux1, uy1, ux2, uy2, x) + tol or c < _y(lx1, ly1, lx2, ly2, x) - tol:
                        bad += 1
            return bad / tot if tot > 0 else 1.0

        def f_round(bk, span, lvl, d):
            lv1 = f_avgMid(bk + int(_pround(span * 0.25)))
            lv3 = f_avgMid(bk + int(_pround(span * 0.75)))
            return (lvl - lv1) / d >= cfg.round_k and (lvl - lv3) / d >= cfg.round_k

        def f_cup(r):
            cnt = len(s.zP)
            rim, rimBar = f_p(r), f_b(r)
            runMin, runMinBar, runMax = 1e30, 0, -1e30
            lim = min(cnt - 1, r + 40)
            if lim >= r + 2:
                for k in range(r + 1, lim + 1):
                    pk, bk = f_p(k), f_b(k)
                    if f_d(k) == -1:
                        if pk < runMin:
                            runMin, runMinBar = pk, bk
                    else:
                        span = rimBar - bk
                        if span > cfg.cup_max:
                            break
                        lvl = min(pk, rim)
                        d = lvl - runMin
                        shapeOk = False
                        if (span >= cfg.cup_min and d >= cfg.min_h_atr * atrV and abs(pk - rim) <= tolPct * d
                                and runMax <= lvl + 0.1 * d):
                            pos = float(runMinBar - bk) / span
                            if 0.25 <= pos <= 0.75:
                                shapeOk = f_round(bk, span, lvl, d)
                        if shapeOk:
                            return True, k, runMin, runMinBar, d
                        runMax = max(runMax, pk)
            return False, -1, NA, None, NA

        def f_rbNow():
            cnt = len(s.zP)
            runMin, runMinBar, runMax = 1e30, 0, -1e30
            lim = min(cnt - 1, 40)
            if cnt >= 2:
                for k in range(0, lim + 1):
                    pk, bk = f_p(k), f_b(k)
                    if f_d(k) == -1:
                        if pk < runMin:
                            runMin, runMinBar = pk, bk
                    else:
                        span = bi - bk
                        if span > cfg.cup_max:
                            break
                        hit = False
                        if bi >= 1 and close > pk and C[bi - 1] <= pk and runMin < 1e29:
                            d = pk - runMin
                            if span >= cfg.cup_min and d >= cfg.min_h_atr * atrV and runMax <= pk:
                                pos = float(runMinBar - bk) / span
                                if 0.25 <= pos <= 0.75:
                                    hit = f_round(bk, span, pk, d)
                        if hit:
                            return True, k, runMin, runMinBar
                        runMax = max(runMax, pk)
            return False, -1, NA, None

        def f_can(startBar):
            return not cfg.no_overlap or startBar > s.lastEnd

        # ─── Update swings ───
        newPt = False
        c = bi - cfg.piv_r
        if c - cfg.piv_len >= 0:
            hc, lc = H[c], L[c]
            if all(H[j] < hc for j in range(c - cfg.piv_len, c)) and all(H[j] <= hc for j in range(c + 1, bi + 1)):
                newPt = f_add(hc, c, 1) or newPt
            if all(L[j] > lc for j in range(c - cfg.piv_len, c)) and all(L[j] >= lc for j in range(c + 1, bi + 1)):
                newPt = f_add(lc, c, -1) or newPt

        zn = len(s.zP)
        found = ""
        pStart = pEnd = None
        pBias, pRev = 0, False
        pHeight = pSLl = pSLs = NA
        actUp, actLo = s.actUp, s.actLo

        # ─── Head and Shoulders ───
        if newPt and cfg.show_hs and zn >= 5 and f_d(0) == 1:
            h1, l1, h2, l2, h3 = f_p(4), f_p(3), f_p(2), f_p(1), f_p(0)
            neck = max(l1, l2)
            ht = h2 - neck
            ok = (h2 > h1 and h2 > h3 and ht >= cfg.min_h_atr * atrV and min(h1, h3) - neck >= 0.3 * ht
                  and h2 - max(h1, h3) >= 0.15 * ht and abs(h1 - h3) <= tolPct * ht
                  and abs(l1 - l2) <= tolPct * ht * 1.5)
            if ok and f_can(f_b(4)):
                actUp, actLo = None, _Line(f_b(3), l1, f_b(1), l2)
                pStart, pEnd, pBias, pRev, pHeight, pSLs = f_b(4), f_b(0), -1, True, ht, h3
                found = "Head and Shoulders"

        # ─── Inverted Head and Shoulders ───
        if newPt and found == "" and cfg.show_ihs and zn >= 5 and f_d(0) == -1:
            l1, h1, l2, h2, l3 = f_p(4), f_p(3), f_p(2), f_p(1), f_p(0)
            neck = min(h1, h2)
            ht = neck - l2
            ok = (l2 < l1 and l2 < l3 and ht >= cfg.min_h_atr * atrV and neck - max(l1, l3) >= 0.3 * ht
                  and min(l1, l3) - l2 >= 0.15 * ht and abs(l1 - l3) <= tolPct * ht
                  and abs(h1 - h2) <= tolPct * ht * 1.5)
            if ok and f_can(f_b(4)):
                actUp, actLo = _Line(f_b(3), h1, f_b(1), h2), None
                pStart, pEnd, pBias, pRev, pHeight, pSLl = f_b(4), f_b(0), 1, True, ht, l3
                found = "Inverted Head and Shoulders"

        # ─── Diamond Top / Bottom ───
        if newPt and found == "" and (cfg.show_dia_t or cfg.show_dia_b) and zn >= 8:
            hiO = 0 if f_d(0) == 1 else 1
            loO = 1 - hiO
            hLp, hMp, hRp = f_p(hiO + 4), f_p(hiO + 2), f_p(hiO)
            lLp, lMp, lRp = f_p(loO + 4), f_p(loO + 2), f_p(loO)
            ht = hMp - lMp
            mg = 0.1 * ht
            shape = ht >= cfg.min_h_atr * atrV and hMp - max(hLp, hRp) >= mg and min(lLp, lRp) - lMp >= mg
            isTop = (f_p(6) + f_p(7)) / 2 < (hMp + lMp) / 2
            xs = f_b(5)
            repl = s.lpName == "Broadening Triangle" and s.lpEnd is not None and s.lpEnd > xs and s.lpEnd <= f_b(0)
            endRef = s.lpPrevEnd if repl else s.lastEnd
            if shape and ((isTop and cfg.show_dia_t) or (not isTop and cfg.show_dia_b)) and (
                    not cfg.no_overlap or xs > endRef):
                if repl:
                    s.lastEnd = s.lpPrevEnd
                    s.lpName = ""
                actUp = _Line(f_b(hiO + 2), hMp, f_b(hiO), hRp)
                actLo = _Line(f_b(loO + 2), lMp, f_b(loO), lRp)
                pStart, pEnd, pBias, pRev, pHeight = xs, f_b(0), (-1 if isTop else 1), True, ht
                pSLs, pSLl = hRp, lRp
                found = "Diamond Top" if isTop else "Diamond Bottom"

        # ─── Cup and Handle ───
        if newPt and found == "" and cfg.show_cup and zn >= 4 and f_d(0) == -1:
            cOk, cK, cLow, cBar, cDep = f_cup(1)
            if cOk:
                rimR, rimL, hLow = f_p(1), f_p(cK), f_p(0)
                retr = rimR - hLow
                cupStart, cupEnd = f_b(cK), f_b(1)
                hOk = (retr > 0 and retr <= cfg.hdl_max * cDep and hLow > cLow + 0.5 * cDep
                       and (f_b(0) - cupEnd) <= 0.5 * (cupEnd - cupStart))
                repl = s.lpName == "Rounding Bottom" and s.lpEnd == cupEnd
                endRef = s.lpPrevEnd if repl else s.lastEnd
                if hOk and (not cfg.no_overlap or cupStart > endRef):
                    if repl:
                        s.lastEnd = s.lpPrevEnd
                        s.lpName = ""
                    rimLvl = max(rimL, rimR)
                    actUp, actLo = _Line(cupStart, rimLvl, f_b(0), rimLvl), None
                    pStart, pEnd, pBias, pRev, pHeight, pSLl = cupStart, f_b(0), 1, False, cDep, hLow
                    found = "Cup and Handle"

        # ─── Rounding Bottom (right rim is a swing high) ───
        if newPt and found == "" and cfg.show_rb and zn >= 3 and f_d(0) == 1:
            rOk, rK, rLow, rBar, rDep = f_cup(0)
            if rOk and f_can(f_b(rK)):
                rimLvl = max(f_p(rK), f_p(0))
                actUp, actLo = _Line(f_b(rK), rimLvl, f_b(0), rimLvl), None
                pStart, pEnd, pBias, pRev, pHeight = f_b(rK), f_b(0), 1, True, rDep
                pSLl = (rimLvl + rLow) / 2
                found = "Rounding Bottom"

        # ─── Rounding Bottom (price breaks straight through the rim) ───
        if found == "" and cfg.show_rb and zn >= 2:
            nOk, nK, nLow, nBar = f_rbNow()
            if nOk:
                bk, rim = f_b(nK), f_p(nK)
                dup = s.lpStart == bk and s.lpName in ("Rounding Bottom", "Cup and Handle")
                if not dup and f_can(bk):
                    actUp, actLo = _Line(bk, rim, bi, rim), None
                    pStart, pEnd, pBias, pRev, pHeight = bk, bi, 1, True, rim - nLow
                    pSLl = (rim + nLow) / 2
                    found = "Rounding Bottom"

        # ─── Triangles & Wedges ───
        if newPt and found == "" and zn >= 5:
            if f_d(0) == 1:
                hA, hB, hM, lA, lB, lM = 4, 0, 2, 3, 1, -1
            else:
                hA, hB, hM, lA, lB, lM = 3, 1, -1, 4, 0, 2
            ux1, uy1, ux2, uy2 = f_b(hA), f_p(hA), f_b(hB), f_p(hB)
            lx1, ly1, lx2, ly2 = f_b(lA), f_p(lA), f_b(lB), f_p(lB)
            if ux2 > ux1 and lx2 > lx1:
                sU = (uy2 - uy1) / (ux2 - ux1) / atrV if atrV == atrV and atrV != 0 else NA
                sL = (ly2 - ly1) / (lx2 - lx1) / atrV if atrV == atrV and atrV != 0 else NA
                xs, xe = f_b(4), f_b(0)
                tol = cfg.touch_atr * atrV
                gS = _y(ux1, uy1, ux2, uy2, xs) - _y(lx1, ly1, lx2, ly2, xs)
                gE = _y(ux1, uy1, ux2, uy2, xe) - _y(lx1, ly1, lx2, ly2, xe)
                hm, lm = max(hM, 0), max(lM, 0)
                tU = hM < 0 or abs(f_p(hm) - _y(ux1, uy1, ux2, uy2, f_b(hm))) <= tol
                tL = lM < 0 or abs(f_p(lm) - _y(lx1, ly1, lx2, ly2, f_b(lm))) <= tol
                geomOk = gS > 0 and gE > 0 and max(gS, gE) >= cfg.min_h_atr * atrV and tU and tL
                conv = gE <= 0.8 * gS
                divg = gE >= 1.25 * gS
                fa = cfg.flat_atr
                upFlat, loFlat = abs(sU) <= fa, abs(sL) <= fa
                upRise, upFall, loRise, loFall = sU > fa, sU < -fa, sL > fa, sL < -fa
                nm = ""
                if geomOk:
                    if upFall and loRise and conv and cfg.show_sym:
                        nm = "Symmetrical Triangle"
                    elif upRise and loFall and divg and cfg.show_bt:
                        nm = "Broadening Triangle"
                    elif upFlat and loRise and conv and cfg.show_at:
                        nm = "Ascending Triangle"
                    elif upFall and loFlat and conv and cfg.show_desc:
                        nm = "Descending Triangle"
                    elif upRise and loRise and sL > sU and conv and cfg.show_rw:
                        nm = "Rising Wedge"
                    elif upFall and loFall and sU < sL and conv and cfg.show_fw:
                        nm = "Falling Wedge"
                if nm and f_viol(ux1, uy1, ux2, uy2, lx1, ly1, lx2, ly2, xs, xe, tol) > 0.1:
                    nm = ""
                if nm and f_can(xs):
                    actUp = _Line(ux1, uy1, xe, _y(ux1, uy1, ux2, uy2, xe))
                    actLo = _Line(lx1, ly1, xe, _y(lx1, ly1, lx2, ly2, xe))
                    pStart, pEnd = xs, xe
                    pBias = (1 if nm in ("Ascending Triangle", "Falling Wedge")
                             else -1 if nm in ("Descending Triangle", "Rising Wedge") else 0)
                    pRev = nm in ("Rising Wedge", "Falling Wedge")
                    pHeight = max(gS, gE)
                    pSLl = f_p(0) if f_d(0) == -1 else f_p(1)
                    pSLs = f_p(0) if f_d(0) == 1 else f_p(1)
                    found = nm

        # ─── Register pattern ───
        if found:
            s.lpPrevEnd, s.lastEnd = s.lastEnd, pEnd
            s.lpName, s.lpStart, s.lpEnd = found, pStart, pEnd
            s.actUp, s.actLo = actUp, actLo
            s.actEnd = bi + cfg.brk_bars
            s.actName, s.actBias, s.actRev = found, pBias, pRev
            s.actH, s.actSLl, s.actSLs = pHeight, pSLl, pSLs

        # ─── Manage the indicator's simulated trade (stop / target / time) ───
        if s.trDir != 0 and bi > s.trBar:
            hitSL = L[bi] <= s.trSL if s.trDir == 1 else H[bi] >= s.trSL
            hitTP = H[bi] >= s.trTP if s.trDir == 1 else L[bi] <= s.trTP
            if hitSL or hitTP or bi - s.trBar >= cfg.max_hold:
                s.trDir = 0

        # ─── Breakout / breakdown ───
        sigDir = 0
        if s.actEnd is not None:
            if bi > s.actEnd:
                s.actEnd = None
            else:
                uNow = s.actUp.price(bi) if s.actUp is not None else NA
                lNow = s.actLo.price(bi) if s.actLo is not None else NA
                if not _na(uNow) and not _na(lNow) and uNow <= lNow:
                    s.actEnd = None
                else:
                    brkUp = not _na(uNow) and close > uNow
                    brkDn = not _na(lNow) and close < lNow
                    if brkUp or brkDn:
                        d = 1 if brkUp else -1
                        dirOk = cfg.trade_dir == "Long & Short" or (d == 1 and cfg.trade_dir == "Long only") or (
                            d == -1 and cfg.trade_dir == "Short only")
                        setOk = cfg.sig_set == "All patterns" or (
                            cfg.sig_set == "Reversal patterns only" and s.actRev) or (
                            cfg.sig_set == "Continuation patterns only" and not s.actRev)
                        biasOk = not cfg.with_bias or s.actBias == 0 or s.actBias == d
                        late = (close - uNow if brkUp else lNow - close) > cfg.max_late * atrV
                        if dirOk and setOk and biasOk and not late:
                            sigDir = d
                        s.actEnd = None

        # ─── Already in a trade? ───
        if sigDir != 0 and s.trDir != 0:
            if s.trDir == sigDir:
                sigDir = 0
            elif cfg.rev_on_opp:
                s.trDir = 0
            else:
                sigDir = 0

        if sigDir == 0:
            out.append(None)
            continue
        en = close
        sl = s.actSLl if sigDir == 1 else s.actSLs
        h0 = 2 * atrV if _na(s.actH) else s.actH
        if _na(sl) or (sigDir == 1 and sl >= en) or (sigDir == -1 and sl <= en):
            sl = en - sigDir * 0.5 * h0
        sl = sl - sigDir * cfg.sl_buf * atrV
        tp = en + sigDir * h0 * cfg.tp_mult
        s.trDir, s.trSL, s.trTP, s.trBar = sigDir, sl, tp, bi
        out.append(PatternSignal("LONG" if sigDir == 1 else "SHORT", en, sl, tp, s.actName, s.actRev))
    return out


def _pround(x: float) -> float:
    """Pine math.round: half away from zero (Python's round() is banker's rounding)."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)
