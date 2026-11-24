//+------------------------------------------------------------------+
//| ScalpingPatterns.mq5                                             |
//| The TradingView script "Scalping Patterns" v2 (fixed), ported to |
//| MT5 as an Expert Advisor so it can run in the Strategy Tester.   |
//|                                                                  |
//| Same 7 patterns and rules as pine/scalping_patterns.pine and the |
//| Python port app/signals/scalping.py:                             |
//|  1 ORB  2 VWAP Pullback  3 EMA 9/20 Micro Pullback  4 Flag       |
//|  5 Inside Bar  6 Liquidity Sweep  7 Double Top / Bottom          |
//| Signals are found on CLOSED candles; the order is sent at the    |
//| start of the next candle. SL and TP2 sit on the broker server,   |
//| half the position closes at TP1 and the stop moves to entry,     |
//| time stop after N minutes if TP1 is not reached.                 |
//|                                                                  |
//| Differences from the TradingView script (MT5 has no equivalent): |
//|  * Indian-session hours / square-off are not used (MT5 symbols   |
//|    here trade all day, like the Pine "Auto" setting does).       |
//|  * VWAP / volume use MT5 tick volume unless "real volume" is on. |
//|  * Results are real money from the tester (spread, commission,   |
//|    slippage included), shown in R = profit / money at risk.      |
//|                                                                  |
//| SAFETY: orders are placed ONLY in the Strategy Tester unless     |
//| "Allow live trading" is switched on. On a normal chart it only   |
//| draws the signals, so it can never disturb the live bot.         |
//+------------------------------------------------------------------+
#property copyright   "BYTEFX"
#property version     "2.00"
#property description "Scalping Patterns v2 (TradingView) for the MT5 Strategy Tester. Trades only in the tester unless live trading is allowed."
#include <Trade/Trade.mqh>

enum ENUM_SP_MODE { SP_MORE = 0, SP_BALANCED = 1, SP_STRICT = 2 };
enum ENUM_SP_DIR  { SP_BOTH = 0, SP_LONG = 1, SP_SHORT = 2 };

input group "Signal Mode"
input ENUM_SP_MODE InpMode       = SP_MORE;   // Signal mode (More trades / Balanced / Strict)
input bool         InpRevOpp     = false;     // Reverse the trade on an opposite signal

input group "Patterns (on / off)"
input bool InpORB  = true;   // 1. Opening Range Breakout (ORB)
input bool InpVWP  = true;   // 2. VWAP Pullback
input bool InpMPB  = true;   // 3. EMA 9/20 Micro Pullback
input bool InpFlag = true;   // 4. Bull Flag / Bear Flag
input bool InpIB   = true;   // 5. Inside Bar Breakout
input bool InpSwp  = true;   // 6. Liquidity Sweep Reversal
input bool InpDbl  = true;   // 7. Double Top / Double Bottom

input group "Trade Setup"
input ENUM_SP_DIR InpDir        = SP_BOTH; // Trade direction
input double      InpTp1R       = 1.0;     // TP1 (x risk)
input bool        InpTp2Pattern = true;    // TP2 = pattern target (else fixed R)
input double      InpTp2R       = 2.0;     // TP2 (x risk) fixed / fallback
input double      InpMaxTpR     = 3.0;     // Max TP2 (x risk)
input bool        InpBeAfterTp1 = true;    // Move SL to entry after TP1
input double      InpSlBufAtr   = 0.1;     // SL buffer beyond pattern (x ATR)
input double      InpMinRiskAtr = 0.6;     // Min SL distance (x ATR)
input int         InpTimeStopMin = 15;     // Time stop: exit if TP1 not hit within (minutes)

input group "Quality Filters"
input bool   InpUseTrend  = true;  // Trend filter (VWAP + EMA 20/50) for ORB, VWAP, Micro, Flag, Inside Bar
input bool   InpUseChop   = true;  // Chop filter: skip when ADX is below the minimum
input int    InpAdxMin    = 20;    // ADX minimum
input bool   InpNoCounter = true;  // No Sweep / Double against a strong trend (ADX > 30)
input int    InpPauseBars = 3;     // Pause after a losing trade (bars)
input double InpMaxLossR  = 3.0;   // Stop for the day at -R (0 = off)

input group "Pattern Settings"
input int    InpOrbMin   = 5;    // ORB: opening range minutes
input int    InpSwL      = 5;    // Swings: bars to the left
input int    InpSwR      = 2;    // Swings: confirmation bars to the right
input int    InpPoleMax  = 8;    // Flag: max pole length (bars)
input int    InpFlagMax  = 10;   // Flag: max flag length (bars)
input double InpSwpMax   = 1.0;  // Sweep: max poke beyond level (x ATR)
input int    InpVolLen   = 20;   // Volume average length
input double InpDeadK    = 0.5;  // Dead market: ATR < x its 100-bar average

input group "Orders (tester)"
input double InpRiskPct     = 1.0;    // Risk per trade (% of balance)
input double InpFixedLots   = 0.0;    // Fixed lots (0 = use risk %)
input int    InpMaxSpreadPt = 0;      // Skip entry if spread > points (0 = off)
input ulong  InpMagic       = 720001; // Magic number
input bool   InpAllowLive   = false;  // Allow live trading (outside the tester) - keep OFF
input bool   InpRealVolume  = false;  // Use real volume instead of tick volume
input int    InpWarmupBars  = 1500;   // History bars loaded before the start (indicators warm up)
input bool   InpDraw        = true;   // Draw BUY / SELL on the chart

//--- effective settings for the chosen mode
bool   eUseVol, eUseDead, eVpGreen, eMpVwap, eIbEma;
double eVolMult, eLate, eMaxRisk, ePole, eFlagRet, eDblTol, eDblMinH, eSwpWick, eVpDrive, eVpTouch, eMpSep, eMpTouch, eIbMin;
int    eMaxTr, eFlagMin, eSwpAge, eSwpLook, eVpN, tsBars;

//--- bar history and series (index 0 = oldest)
int      N = 0;
double   gO[], gH[], gL[], gC[], gV[], gATR[], gE9[], gE20[], gE50[], gADX[], gVW[], gDV[];
datetime gT[];
double   cumVol = 0;

struct Smooth { int n; int cnt; double sum; double val; bool ready; bool ema; };
Smooth rATR, rE9, rE20, rE50, rPDM, rMDM, rDX;

//--- state (mirrors the Pine script)
double dayH, dayL, pdh, pdl, orH, orL;
bool   hasPd = false, orDone = false, orbUpUsed = false, orbDnUsed = false;
datetime dayOpenT = 0;
int    dayOpenB = 0, tradesToday = 0;
double rToday = 0;
double sPV = 0, sV = 0, sP = 0; int sN = 0;

double zP[]; int zB[]; int zD[];
double hLv[]; int hLb[]; double lLv[]; int lLb[];

bool   dtOn = false, dbOn = false;
double dtNeck, dtTop, dbNeck, dbBot; int dtExp, dbExp;

//--- trade state
bool   trOpen = false;
int    trDir = 0, trBar = 0, trPat = 0;
double trSL, trTP1, trTP2, trRiskPx, trRiskMoney, trEntry;
bool   trT1 = false;
ulong  trTicket = 0;
datetime trTime = 0;
int    pauseUntil = -1;
bool   pendClose = false; string pendReason = "";

//--- statistics [pattern 1..7][0 = BUY, 1 = SELL]
int    stN[8][2], stW[8][2], stT1[8][2];
double stR[8][2], stM[8][2];
int    csvH = INVALID_HANDLE;
bool   warm = false;
datetime lastBar = 0;
bool   tradeAllowed = false;
CTrade trade;

string PatName(int id)
{
   switch(id)
   {
      case 1: return "ORB";
      case 2: return "VWAP Pullback";
      case 3: return "Micro Pullback";
      case 4: return "Flag";
      case 5: return "Inside Bar";
      case 6: return "Sweep";
      case 7: return "Double Top/Bottom";
   }
   return "?";
}

double SmoothUpd(Smooth &s, double x)
{
   if(!s.ready)
   {
      s.sum += x; s.cnt++;
      if(s.cnt >= s.n) { s.val = s.sum / s.n; s.ready = true; }
   }
   else if(s.ema) s.val = (2.0 / (s.n + 1)) * x + (1 - 2.0 / (s.n + 1)) * s.val;
   else           s.val = (x + (s.n - 1) * s.val) / s.n;
   return s.val;
}
void SmoothInit(Smooth &s, int n, bool ema) { s.n = n; s.cnt = 0; s.sum = 0; s.val = 0; s.ready = false; s.ema = ema; }

double Hi(int i, int len) { double m = gH[i]; for(int j = i - len + 1; j < i; j++) if(j >= 0 && gH[j] > m) m = gH[j]; return m; }
double Lo(int i, int len) { double m = gL[i]; for(int j = i - len + 1; j < i; j++) if(j >= 0 && gL[j] < m) m = gL[j]; return m; }

bool DirOk(int d) { return InpDir == SP_BOTH || (d == 1 && InpDir == SP_LONG) || (d == -1 && InpDir == SP_SHORT); }

void PushLv(double &lv[], int &lb[], double p, int b)
{
   int k = ArraySize(lv);
   ArrayResize(lv, k + 1); ArrayResize(lb, k + 1);
   lv[k] = p; lb[k] = b;
   if(k + 1 > 12) { ArrayRemove(lv, 0, 1); ArrayRemove(lb, 0, 1); }
}

bool ZAdd(double p, int b, int d)
{
   int k = ArraySize(zP);
   if(k > 0 && zD[k - 1] == d)
   {
      if((d == 1 && p > zP[k - 1]) || (d == -1 && p < zP[k - 1])) { zP[k - 1] = p; zB[k - 1] = b; }
      return false;
   }
   ArrayResize(zP, k + 1); ArrayResize(zB, k + 1); ArrayResize(zD, k + 1);
   zP[k] = p; zB[k] = b; zD[k] = d;
   if(k + 1 > 50) { ArrayRemove(zP, 0, 1); ArrayRemove(zB, 0, 1); ArrayRemove(zD, 0, 1); }
   return true;
}
double FP(int i) { int k = ArraySize(zP) - 1 - i; return k >= 0 ? zP[k] : 0; }
int    FB(int i) { int k = ArraySize(zB) - 1 - i; return k >= 0 ? zB[k] : 0; }
int    FD(int i) { int k = ArraySize(zD) - 1 - i; return k >= 0 ? zD[k] : 0; }

//+------------------------------------------------------------------+
int OnInit()
{
   bool more = InpMode == SP_MORE, bal = InpMode == SP_BALANCED, str = InpMode == SP_STRICT;
   eUseVol  = !more;               eVolMult = more ? 1.0 : bal ? 1.2 : 1.5;
   eLate    = more ? 1.5 : bal ? 1.2 : 1.0;
   eMaxRisk = more ? 3.0 : bal ? 2.5 : 2.0;
   eUseDead = !more;
   eMaxTr   = more ? 30 : bal ? 15 : 8;
   ePole    = more ? 1.5 : bal ? 1.75 : 2.0;
   eFlagMin = more ? 2 : 3;
   eFlagRet = more ? 0.6 : bal ? 0.55 : 0.5;
   eDblTol  = more ? 0.7 : bal ? 0.6 : 0.5;
   eDblMinH = more ? 0.8 : bal ? 0.9 : 1.0;
   eSwpAge  = more ? 5 : bal ? 8 : 10;
   eSwpLook = more ? 20 : bal ? 25 : 30;
   eSwpWick = more ? 0.4 : bal ? 0.45 : 0.5;
   eVpN     = more ? 3 : bal ? 4 : 5;
   eVpDrive = more ? 0.5 : bal ? 0.75 : 1.0;
   eVpTouch = more ? 0.3 : bal ? 0.2 : 0.15;
   eVpGreen = str;
   eMpSep   = more ? 0.1 : bal ? 0.15 : 0.2;
   eMpVwap  = !more;
   eMpTouch = more ? 0.3 : bal ? 0.2 : 0.1;
   eIbMin   = more ? 0.3 : bal ? 0.4 : 0.5;
   eIbEma   = !more;
   double tfMin = PeriodSeconds(_Period) / 60.0;
   tsBars = (int)MathMax(3, MathFloor(InpTimeStopMin / tfMin + 0.5));

   SmoothInit(rATR, 14, false); SmoothInit(rPDM, 14, false); SmoothInit(rMDM, 14, false); SmoothInit(rDX, 14, false);
   SmoothInit(rE9, 9, true); SmoothInit(rE20, 20, true); SmoothInit(rE50, 50, true);
   ArrayInitialize(stN, 0); ArrayInitialize(stW, 0); ArrayInitialize(stT1, 0);
   ArrayInitialize(stR, 0); ArrayInitialize(stM, 0);

   tradeAllowed = MQLInfoInteger(MQL_TESTER) || InpAllowLive;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(50);

   string fn = StringFormat("ScalpingPatterns_%s_%s_trades.csv", _Symbol, EnumToString(_Period));
   csvH = FileOpen(fn, FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(csvH != INVALID_HANDLE)
      FileWrite(csvH, "entry_time", "exit_time", "side", "pattern", "entry", "sl", "tp1", "tp2", "lots", "tp1_hit", "reason", "profit", "R");
   if(!tradeAllowed)
      Print("Scalping Patterns: signals only (no orders). Orders are placed only in the Strategy Tester.");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void AppendBar(const MqlRates &r)
{
   int n = N;
   if(ArraySize(gO) <= n)
   {
      int sz = n + 5000;
      ArrayResize(gO, sz); ArrayResize(gH, sz); ArrayResize(gL, sz); ArrayResize(gC, sz); ArrayResize(gV, sz);
      ArrayResize(gATR, sz); ArrayResize(gE9, sz); ArrayResize(gE20, sz); ArrayResize(gE50, sz);
      ArrayResize(gADX, sz); ArrayResize(gVW, sz); ArrayResize(gDV, sz); ArrayResize(gT, sz);
   }
   gO[n] = r.open; gH[n] = r.high; gL[n] = r.low; gC[n] = r.close; gT[n] = r.time;
   gV[n] = InpRealVolume ? (double)r.real_volume : (double)r.tick_volume;
   cumVol += gV[n];
   double tr = n == 0 ? r.high - r.low
               : MathMax(r.high - r.low, MathMax(MathAbs(r.high - gC[n - 1]), MathAbs(r.low - gC[n - 1])));
   gATR[n] = SmoothUpd(rATR, tr);
   gE9[n] = SmoothUpd(rE9, r.close); gE20[n] = SmoothUpd(rE20, r.close); gE50[n] = SmoothUpd(rE50, r.close);
   gADX[n] = 0;
   if(n > 0)
   {
      double up = gH[n] - gH[n - 1], dn = gL[n - 1] - gL[n];
      double pdm = (up > dn && up > 0) ? up : 0, mdm = (dn > up && dn > 0) ? dn : 0;
      double ap = SmoothUpd(rPDM, pdm), am = SmoothUpd(rMDM, mdm);
      if(rPDM.ready && rATR.ready && gATR[n] != 0)
      {
         double plus = 100 * ap / gATR[n], minus = 100 * am / gATR[n];
         double dx = MathAbs(plus - minus) / (plus + minus != 0 ? plus + minus : 1);
         gADX[n] = 100 * SmoothUpd(rDX, dx);
      }
   }
   bool newDay = n == 0 || (long)gT[n] / 86400 != (long)gT[n - 1] / 86400;
   if(newDay) { sPV = 0; sV = 0; sP = 0; sN = 0; }
   double hlc3 = (r.high + r.low + r.close) / 3;
   sPV += hlc3 * gV[n]; sV += gV[n]; sP += hlc3; sN++;
   gVW[n] = sV > 0 ? sPV / sV : sP / sN;
   gDV[n] = r.close - gVW[n];
   N = n + 1;
}

//+------------------------------------------------------------------+
//| Process the closed candle that was just appended (index bi).     |
//+------------------------------------------------------------------+
void ProcessBar(bool live)
{
   int bi = N - 1;
   double o = gO[bi], h = gH[bi], lo = gL[bi], c = gC[bi];
   double atrV = gATR[bi], vwapV = gVW[bi];
   bool newDay = bi == 0 || (long)gT[bi] / 86400 != (long)gT[bi - 1] / 86400;
   bool ready = bi >= 160 && rATR.ready && rE50.ready && rDX.ready;

   double volA = 0; int vc = 0;
   for(int j = bi; j > bi - InpVolLen && j >= 0; j--) { volA += gV[j]; vc++; }
   volA = vc > 0 ? volA / vc : 0;
   bool volOk = !eUseVol || cumVol <= 0 || gV[bi] >= eVolMult * volA;
   double atrA = 0; int ac = 0;
   for(int j = bi; j > bi - 100 && j >= 0; j--) { atrA += gATR[j]; ac++; }
   bool notDead = !eUseDead || ac < 100 || atrV >= InpDeadK * (atrA / ac);

   bool orJustDone = false;
   if(newDay)
   {
      if(bi > 0) { pdh = dayH; pdl = dayL; hasPd = true; }
      dayH = h; dayL = lo; dayOpenT = gT[bi]; dayOpenB = bi;
      orH = h; orL = lo; orDone = false; orbUpUsed = false; orbDnUsed = false;
      tradesToday = 0; rToday = 0;
   }
   else
   {
      dayH = MathMax(dayH, h); dayL = MathMin(dayL, lo);
      if(!orDone)
      {
         if(gT[bi] < dayOpenT + InpOrbMin * 60) { orH = MathMax(orH, h); orL = MathMin(orL, lo); }
         else { orDone = true; orJustDone = true; }
      }
   }

   //--- swings (pivot high/low confirmed swR bars later)
   bool phOk = false, plOk = false; double ph = 0, pl = 0;
   int cpiv = bi - InpSwR;
   if(cpiv - InpSwL >= 0)
   {
      double hc = gH[cpiv], lc = gL[cpiv];
      bool okH = true, okL = true;
      for(int j = cpiv - InpSwL; j < cpiv; j++) { if(!(gH[j] < hc)) okH = false; if(!(gL[j] > lc)) okL = false; }
      for(int j = cpiv + 1; j <= bi; j++)       { if(!(gH[j] <= hc)) okH = false; if(!(gL[j] >= lc)) okL = false; }
      if(okH) { phOk = true; ph = hc; }
      if(okL) { plOk = true; pl = lc; }
   }
   bool newHi = false, newLo = false;
   if(phOk) newHi = ZAdd(ph, cpiv, 1);
   if(plOk) newLo = ZAdd(pl, cpiv, -1);
   int zn = ArraySize(zP);

   //--- liquidity levels
   if(phOk && ph >= Hi(bi, eSwpLook)) PushLv(hLv, hLb, ph, cpiv);
   if(plOk && pl <= Lo(bi, eSwpLook)) PushLv(lLv, lLb, pl, cpiv);
   if(newDay && hasPd) { PushLv(hLv, hLb, pdh, bi); PushLv(lLv, lLb, pdl, bi); }
   if(orJustDone) { PushLv(hLv, hLb, orH, dayOpenB); PushLv(lLv, lLb, orL, dayOpenB); }

   int swpDir = 0; double swpLvl = 0;
   double rng = h - lo;
   double pL1 = bi > 0 ? gL[bi - 1] : lo, pH1 = bi > 0 ? gH[bi - 1] : h;
   bool rejDn = rng > 0 && ((h - MathMax(o, c)) >= eSwpWick * rng || (c < o && c <= (h + lo) / 2 && c < pL1));
   bool rejUp = rng > 0 && ((MathMin(o, c) - lo) >= eSwpWick * rng || (c > o && c >= (h + lo) / 2 && c > pH1));
   for(int i = ArraySize(hLv) - 1; i >= 0; i--)
   {
      double lv = hLv[i];
      if(c > lv) { ArrayRemove(hLv, i, 1); ArrayRemove(hLb, i, 1); }
      else if(h > lv)
      {
         if(swpDir == 0 && rejDn && h - lv <= InpSwpMax * atrV && bi - hLb[i] >= eSwpAge) { swpDir = -1; swpLvl = lv; }
         ArrayRemove(hLv, i, 1); ArrayRemove(hLb, i, 1);
      }
   }
   for(int i = ArraySize(lLv) - 1; i >= 0; i--)
   {
      double lv = lLv[i];
      if(c < lv) { ArrayRemove(lLv, i, 1); ArrayRemove(lLb, i, 1); }
      else if(lo < lv)
      {
         if(swpDir == 0 && rejUp && lv - lo <= InpSwpMax * atrV && bi - lLb[i] >= eSwpAge) { swpDir = 1; swpLvl = lv; }
         ArrayRemove(lLv, i, 1); ArrayRemove(lLb, i, 1);
      }
   }

   //--- double top / bottom
   if(newHi && zn >= 4 && FD(0) == 1)
   {
      double h2 = FP(0), h1 = FP(2), nk = FP(1), top = MathMax(h1, h2);
      int gap = FB(0) - FB(2);
      if(MathAbs(h1 - h2) <= eDblTol * atrV && top - nk >= eDblMinH * atrV && gap >= 3 && gap <= 80 && FP(3) < nk)
      { dtOn = true; dtNeck = nk; dtTop = top; dtExp = bi + 30; }
   }
   if(newLo && zn >= 4 && FD(0) == -1)
   {
      double l2 = FP(0), l1 = FP(2), nk = FP(1), bot = MathMin(l1, l2);
      int gap = FB(0) - FB(2);
      if(MathAbs(l1 - l2) <= eDblTol * atrV && nk - bot >= eDblMinH * atrV && gap >= 3 && gap <= 80 && FP(3) > nk)
      { dbOn = true; dbNeck = nk; dbBot = bot; dbExp = bi + 30; }
   }
   bool dtSig = false, dbSig = false;
   if(dtOn) { if(c > dtTop || bi > dtExp) dtOn = false; else if(c < dtNeck) { dtSig = true; dtOn = false; } }
   if(dbOn) { if(c < dbBot || bi > dbExp) dbOn = false; else if(c > dbNeck) { dbSig = true; dbOn = false; } }

   //--- ORB flags are consumed even if no trade (as in Pine)
   bool orbUp = false, orbDn = false;
   if(bi > 0)
   {
      orbUp = orDone && !orbUpUsed && c > orH && gC[bi - 1] <= orH;
      orbDn = orDone && !orbDnUsed && c < orL && gC[bi - 1] >= orL;
   }
   if(orbUp) orbUpUsed = true;
   if(orbDn) orbDnUsed = true;

   int cDir = 0, cPat = 0;
   double cTrig = 0, cSLr = 0, cSLalt = 0, cPT = 0;
   bool hasAlt = false, hasPT = false, hasTrig = false, cBrk = false;
   bool lookOk = bi >= InpFlagMax + 2 + InpPoleMax + 2;

   if(ready && lookOk)
   {
      //--- 1 ORB
      if(InpORB)
      {
         if(orbUp && c > vwapV && DirOk(1))       { cDir = 1;  cTrig = orH; cPT = orH + (orH - orL); }
         else if(orbDn && c < vwapV && DirOk(-1)) { cDir = -1; cTrig = orL; cPT = orL - (orH - orL); }
         if(cDir != 0) { cPat = 1; cSLr = (orH + orL) / 2; cBrk = true; hasPT = true; hasTrig = true; }
      }
      //--- 6 Sweep
      if(InpSwp && cDir == 0 && swpDir != 0 && DirOk(swpDir))
      {
         cDir = swpDir; cPat = 6; cTrig = swpLvl; hasTrig = true;
         cSLr = swpDir == 1 ? lo : h;
         if((swpDir == 1 && vwapV > c) || (swpDir == -1 && vwapV < c)) { cPT = vwapV; hasPT = true; }
      }
      //--- 7 Double top / bottom
      if(InpDbl && cDir == 0)
      {
         if(dtSig && DirOk(-1))
         { cDir = -1; cPat = 7; cTrig = dtNeck; cSLr = dtTop; cSLalt = (dtTop + dtNeck) / 2; cPT = dtNeck - (dtTop - dtNeck); }
         else if(dbSig && DirOk(1))
         { cDir = 1; cPat = 7; cTrig = dbNeck; cSLr = dbBot; cSLalt = (dbBot + dbNeck) / 2; cPT = dbNeck + (dbNeck - dbBot); }
         if(cDir != 0) { hasAlt = true; hasPT = true; hasTrig = true; cBrk = true; }
      }
      //--- 4 Flag
      if(InpFlag && cDir == 0)
      {
         for(int pass = 0; pass < 2 && cDir == 0; pass++)
         {
            int d = pass == 0 ? 1 : -1;
            if(!DirOk(d)) continue;
            for(int fl = eFlagMin; fl <= InpFlagMax; fl++)
            {
               double fHi = gH[bi - 1], fLo = gL[bi - 1];
               for(int k = 1; k <= fl; k++) { fHi = MathMax(fHi, gH[bi - k]); fLo = MathMin(fLo, gL[bi - k]); }
               double top = d == 1 ? gH[bi - fl - 1] : gL[bi - fl - 1];
               if(!(d == 1 ? top > fHi : top < fLo)) continue;
               double pS = d == 1 ? gL[bi - fl - 1] : gH[bi - fl - 1];
               for(int k = fl + 2; k < fl + 2 + InpPoleMax; k++)
               {
                  if(d == 1 && gL[bi - k] < pS) pS = gL[bi - k];
                  if(d == -1 && gH[bi - k] > pS) pS = gH[bi - k];
               }
               double pH = d == 1 ? top - pS : pS - top;
               double ret = d == 1 ? top - fLo : fHi - top;
               bool brk = d == 1 ? c > fHi : c < fLo;
               if(pH >= ePole * atrV && ret <= eFlagRet * pH && fHi - fLo <= 0.6 * pH && brk)
               {
                  cDir = d; cPat = 4; cTrig = d == 1 ? fHi : fLo; cSLr = d == 1 ? fLo : fHi;
                  cSLalt = (fHi + fLo) / 2; cPT = c + d * pH;
                  hasAlt = true; hasPT = true; hasTrig = true; cBrk = true;
                  break;
               }
            }
         }
      }
      //--- 2 VWAP pullback
      int b1 = bi - 1;
      double minDV = gDV[b1], maxDV = gDV[b1];
      for(int j = b1 - eVpN + 1; j < b1; j++) { minDV = MathMin(minDV, gDV[j]); maxDV = MathMax(maxDV, gDV[j]); }
      double hiAbv = gH[b1] - gVW[b1], loBlw = gL[b1] - gVW[b1];
      for(int j = b1 - 14; j < b1; j++) { hiAbv = MathMax(hiAbv, gH[j] - gVW[j]); loBlw = MathMin(loBlw, gL[j] - gVW[j]); }
      bool vpL = minDV > 0 && hiAbv >= eVpDrive * atrV && gL[b1] <= gVW[b1] + eVpTouch * atrV
                 && (gC[b1] > gO[b1] || !eVpGreen) && c > gH[b1] && c > o && gE9[bi] > gE20[bi];
      bool vpS = maxDV < 0 && loBlw <= -eVpDrive * atrV && gH[b1] >= gVW[b1] - eVpTouch * atrV
                 && (gC[b1] < gO[b1] || !eVpGreen) && c < gL[b1] && c < o && gE9[bi] < gE20[bi];
      if(InpVWP && cDir == 0)
      {
         if(vpL && DirOk(1))       { cDir = 1;  cTrig = gH[b1]; cSLr = gL[b1]; cPT = Hi(b1, 20); }
         else if(vpS && DirOk(-1)) { cDir = -1; cTrig = gL[b1]; cSLr = gH[b1]; cPT = Lo(b1, 20); }
         if(cDir != 0) { cPat = 2; hasPT = true; hasTrig = true; }
      }
      //--- 3 Micro pullback
      int nRed = 0, nGrn = 0;
      for(int i = 1; i <= 3; i++) { if(gC[bi - i] < gO[bi - i]) nRed++; else break; }
      for(int i = 1; i <= 3; i++) { if(gC[bi - i] > gO[bi - i]) nGrn++; else break; }
      bool mpTouchL = false, mpHoldL = true, mpTouchS = false, mpHoldS = true;
      double mpLowL = 0, mpHighS = 0;
      if(nRed > 0)
      {
         mpLowL = gL[bi - 1];
         for(int i = 1; i <= nRed; i++)
         {
            mpLowL = MathMin(mpLowL, gL[bi - i]);
            if(gL[bi - i] <= gE9[bi - i] + eMpTouch * atrV) mpTouchL = true;
            if(gC[bi - i] <= gE20[bi - i]) mpHoldL = false;
         }
      }
      if(nGrn > 0)
      {
         mpHighS = gH[bi - 1];
         for(int i = 1; i <= nGrn; i++)
         {
            mpHighS = MathMax(mpHighS, gH[bi - i]);
            if(gH[bi - i] >= gE9[bi - i] - eMpTouch * atrV) mpTouchS = true;
            if(gC[bi - i] >= gE20[bi - i]) mpHoldS = false;
         }
      }
      bool trendUp = gE9[bi] > gE20[bi] && gE9[bi] - gE20[bi] >= eMpSep * atrV && gE20[bi] > gE20[bi - 3] && (c > vwapV || !eMpVwap);
      bool trendDn = gE9[bi] < gE20[bi] && gE20[bi] - gE9[bi] >= eMpSep * atrV && gE20[bi] < gE20[bi - 3] && (c < vwapV || !eMpVwap);
      bool mpL = nRed >= 1 && gC[bi - nRed - 1] > gO[bi - nRed - 1] && mpTouchL && mpHoldL && trendUp && c > gH[bi - 1] && c > o;
      bool mpS = nGrn >= 1 && gC[bi - nGrn - 1] < gO[bi - nGrn - 1] && mpTouchS && mpHoldS && trendDn && c < gL[bi - 1] && c < o;
      if(InpMPB && cDir == 0)
      {
         if(mpL && DirOk(1))       { cDir = 1;  cTrig = gH[bi - 1]; cSLr = mpLowL;  cPT = Hi(bi - 1, 20); }
         else if(mpS && DirOk(-1)) { cDir = -1; cTrig = gL[bi - 1]; cSLr = mpHighS; cPT = Lo(bi - 1, 20); }
         if(cDir != 0) { cPat = 3; hasPT = true; hasTrig = true; }
      }
      //--- 5 Inside bar
      double h1_ = gH[bi - 1], h2_ = gH[bi - 2], h3_ = gH[bi - 3], l1_ = gL[bi - 1], l2_ = gL[bi - 2], l3_ = gL[bi - 3];
      bool ib2 = h1_ <= h3_ && l1_ >= l3_ && h2_ <= h3_ && l2_ >= l3_;
      bool ib1 = h1_ <= h2_ && l1_ >= l2_;
      double ibH = ib2 ? h3_ : h2_, ibL = ib2 ? l3_ : l2_;
      double ibInL = ib2 ? MathMin(l1_, l2_) : l1_, ibInH = ib2 ? MathMax(h1_, h2_) : h1_;
      bool ibOk = (ib1 || ib2) && ibH - ibL >= eIbMin * atrV;
      if(InpIB && cDir == 0 && ibOk)
      {
         if(c > ibH && (eIbEma ? gE9[bi] > gE20[bi] : c > gE20[bi]) && DirOk(1))        { cDir = 1;  cTrig = ibH; cSLr = ibL; cSLalt = ibInL; }
         else if(c < ibL && (eIbEma ? gE9[bi] < gE20[bi] : c < gE20[bi]) && DirOk(-1)) { cDir = -1; cTrig = ibL; cSLr = ibH; cSLalt = ibInH; }
         if(cDir != 0) { cPat = 5; cBrk = true; hasAlt = true; hasTrig = true; }
      }
   }

   //--- filters
   bool cCont = cPat >= 1 && cPat <= 5;
   bool trUpQ = c > vwapV && gE20[bi] > gE50[bi];
   bool trDnQ = c < vwapV && gE20[bi] < gE50[bi];
   bool chopOk = !InpUseChop || gADX[bi] >= InpAdxMin;
   string why = ""; double sl = 0, risk = 0; bool candOk = false;
   if(cDir != 0)
   {
      sl = cSLr - cDir * InpSlBufAtr * atrV;
      risk = cDir * (c - sl);
      if(risk > eMaxRisk * atrV && hasAlt) { sl = cSLalt - cDir * InpSlBufAtr * atrV; risk = cDir * (c - sl); }
      if(risk < InpMinRiskAtr * atrV) { risk = InpMinRiskAtr * atrV; sl = c - cDir * risk; }
      if(cCont && InpUseTrend && !(cDir == 1 ? trUpQ : trDnQ)) why = "against trend";
      else if(cCont && !chopOk) why = "sideways market";
      else if(!cCont && InpNoCounter && gADX[bi] > 30 && (cDir == 1 ? trDnQ : trUpQ)) why = "against strong trend";
      else if(cBrk && !volOk) why = "low volume";
      else if(hasTrig && cBrk && cDir * (c - cTrig) > eLate * atrV) why = "late breakout";
      else if(risk > eMaxRisk * atrV) why = "SL too wide";
      candOk = why == "" && tradesToday < eMaxTr && notDead && bi >= pauseUntil && (InpMaxLossR == 0 || rToday > -InpMaxLossR);
   }

   //--- manage the open trade (at the close of this candle)
   bool reversedNow = false;
   if(trOpen && bi > trBar)
   {
      if(!PosSelect())
         FinishTrade(bi, "");                        // closed on the server (SL / TP2 / breakeven)
      else
      {
         string ex = "";
         if(!trT1 && bi - trBar >= tsBars) ex = "Time exit";
         else if(bi - trBar >= 4 * tsBars) ex = "Time exit";
         else if(InpRevOpp && candOk && cDir == -trDir) { ex = "Reversed"; reversedNow = true; }
         if(ex != "")
         {
            trade.PositionClose(trTicket);
            FinishTrade(bi, ex);
         }
      }
   }

   //--- accept the new signal
   bool paused = bi < pauseUntil && !reversedNow;
   if(cDir != 0 && !trOpen && tradesToday < eMaxTr && notDead && !paused
      && (InpMaxLossR == 0 || rToday > -InpMaxLossR) && why == "")
   {
      double en = c;
      double tp1 = en + cDir * InpTp1R * risk;
      double tp2 = en + cDir * InpTp2R * risk;
      if(InpTp2Pattern && hasPT && cDir * (cPT - tp1) > 0) tp2 = cPT;
      if(cDir * (tp2 - en) > InpMaxTpR * risk) tp2 = en + cDir * InpMaxTpR * risk;
      if(cDir * (tp2 - tp1) <= 0) tp2 = en + cDir * MathMax(InpTp2R, InpTp1R + 0.5) * risk;
      if(InpDraw) DrawSignal(bi, cDir, cPat, sl, tp1, tp2);
      if(live && tradeAllowed) OpenTrade(bi, cDir, cPat, sl, tp1, tp2);
      if(trOpen) tradesToday++;
   }
}

//+------------------------------------------------------------------+
bool PosSelect()
{
   if(trTicket == 0) return false;
   return PositionSelectByTicket(trTicket);
}

double NormVol(double v)
{
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   v = MathFloor(v / step + 1e-9) * step;
   return MathMin(mx, MathMax(mn, v));
}

void OpenTrade(int bi, int d, int pat, double sl, double tp1, double tp2)
{
   if(InpMaxSpreadPt > 0 && SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPt) return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double px = d == 1 ? ask : bid;
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0) tick = _Point;
   sl  = MathRound(sl / tick) * tick;
   tp2 = MathRound(tp2 / tick) * tick;
   double stopsLvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(d * (px - sl) <= stopsLvl || d * (tp2 - px) <= stopsLvl) return;   // price already beyond SL / TP2
   ENUM_ORDER_TYPE ot = d == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double lossPerLot = 0;
   if(!OrderCalcProfit(ot, _Symbol, 1.0, px, sl, lossPerLot) || lossPerLot >= 0) return;
   double vol;
   if(InpFixedLots > 0) vol = NormVol(InpFixedLots);
   else
   {
      double want = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0;
      vol = NormVol(want / -lossPerLot);
      double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      if(vol < 2 * mn) vol = NormVol(2 * mn);     // room to close half at TP1
   }
   bool ok = d == 1 ? trade.Buy(vol, _Symbol, 0, sl, tp2, "SP " + PatName(pat))
                    : trade.Sell(vol, _Symbol, 0, sl, tp2, "SP " + PatName(pat));
   if(!ok || trade.ResultRetcode() != TRADE_RETCODE_DONE) { PrintFormat("Order failed: %d %s", trade.ResultRetcode(), trade.ResultComment()); return; }
   ulong deal = trade.ResultDeal();
   ulong pos = 0;
   if(HistoryDealSelect(deal)) pos = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   if(pos == 0 || !PositionSelectByTicket(pos)) return;
   trOpen = true; trDir = d; trBar = bi; trPat = pat; trT1 = false; trTicket = pos;
   trEntry = PositionGetDouble(POSITION_PRICE_OPEN);
   trSL = sl; trTP1 = tp1; trTP2 = tp2; trRiskPx = MathAbs(trEntry - sl);
   trTime = (datetime)PositionGetInteger(POSITION_TIME);
   double loss = 0;
   OrderCalcProfit(ot, _Symbol, PositionGetDouble(POSITION_VOLUME), trEntry, sl, loss);
   trRiskMoney = MathMax(-loss, 1e-9);
}

//--- the position is gone (or was just closed): book the result
void FinishTrade(int bi, string reason)
{
   double money = 0, lots = 0; long lastReason = -1;
   if(HistorySelectByPosition(trTicket))
   {
      for(int i = 0; i < HistoryDealsTotal(); i++)
      {
         ulong dl = HistoryDealGetTicket(i);
         money += HistoryDealGetDouble(dl, DEAL_PROFIT) + HistoryDealGetDouble(dl, DEAL_COMMISSION) + HistoryDealGetDouble(dl, DEAL_SWAP);
         if(HistoryDealGetInteger(dl, DEAL_ENTRY) == DEAL_ENTRY_IN) lots += HistoryDealGetDouble(dl, DEAL_VOLUME);
         else lastReason = HistoryDealGetInteger(dl, DEAL_REASON);
      }
   }
   if(reason == "")
   {
      if(lastReason == DEAL_REASON_SL) reason = trT1 ? "Breakeven exit" : "SL hit";
      else if(lastReason == DEAL_REASON_TP) reason = "TP2 hit";
      else reason = "Closed";
   }
   double r = money / trRiskMoney;
   int s = trDir == 1 ? 0 : 1;
   stN[trPat][s]++; stR[trPat][s] += r; stM[trPat][s] += money;
   if(money > 0) stW[trPat][s]++;
   if(trT1) stT1[trPat][s]++;
   rToday += r;
   if(r <= 0) pauseUntil = bi + InpPauseBars;
   if(csvH != INVALID_HANDLE)
      FileWrite(csvH, TimeToString(trTime, TIME_DATE | TIME_MINUTES), TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES),
                trDir == 1 ? "BUY" : "SELL", PatName(trPat), DoubleToString(trEntry, _Digits), DoubleToString(trSL, _Digits),
                DoubleToString(trTP1, _Digits), DoubleToString(trTP2, _Digits), DoubleToString(lots, 2),
                trT1 ? "yes" : "no", reason, DoubleToString(money, 2), DoubleToString(r, 3));
   trOpen = false; trTicket = 0; trDir = 0;
}

//--- TP1: close half, stop to entry (checked on every tick)
void ManageTp1()
{
   if(!trOpen || trT1 || !PosSelect()) return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double px = trDir == 1 ? bid : ask;
   if(trDir * (px - trTP1) < 0) return;
   trT1 = true;
   double vol = PositionGetDouble(POSITION_VOLUME);
   double half = NormVol(vol / 2);
   if(half < vol) trade.PositionClosePartial(trTicket, half);
   if(InpBeAfterTp1 && PosSelect())
   {
      double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE); if(tick <= 0) tick = _Point;
      double be = MathRound(trEntry / tick) * tick;
      double stopsLvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
      if(trDir * (px - be) > stopsLvl) { trade.PositionModify(trTicket, be, trTP2); trSL = be; }
   }
}

void DrawSignal(int bi, int d, int pat, double sl, double tp1, double tp2)
{
   string nm = "SP_" + IntegerToString((long)gT[bi]);
   double y = d == 1 ? gL[bi] - 0.25 * gATR[bi] : gH[bi] + 0.25 * gATR[bi];
   ObjectCreate(0, nm, d == 1 ? OBJ_ARROW_BUY : OBJ_ARROW_SELL, 0, gT[bi], y);
   ObjectCreate(0, nm + "_t", OBJ_TEXT, 0, gT[bi], d == 1 ? y - 0.3 * gATR[bi] : y + 0.6 * gATR[bi]);
   ObjectSetString(0, nm + "_t", OBJPROP_TEXT, (d == 1 ? "BUY " : "SELL ") + PatName(pat));
   ObjectSetInteger(0, nm + "_t", OBJPROP_COLOR, d == 1 ? clrSeaGreen : clrCrimson);
   ObjectSetInteger(0, nm + "_t", OBJPROP_FONTSIZE, 8);
   ObjectSetString(0, nm, OBJPROP_TOOLTIP, StringFormat("%s %s  Entry %s  SL %s  TP1 %s  TP2 %s", d == 1 ? "BUY" : "SELL", PatName(pat),
                   DoubleToString(gC[bi], _Digits), DoubleToString(sl, _Digits), DoubleToString(tp1, _Digits), DoubleToString(tp2, _Digits)));
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(!warm)
   {
      MqlRates hist[];
      ArraySetAsSeries(hist, false);
      int got = CopyRates(_Symbol, _Period, 1, InpWarmupBars, hist);
      if(got <= 0) return;
      for(int i = 0; i < got; i++) { AppendBar(hist[i]); ProcessBar(false); }
      lastBar = hist[got - 1].time;
      warm = true;
      PrintFormat("Scalping Patterns: %d history bars loaded, trading from %s", got, TimeToString(TimeCurrent()));
      return;
   }
   ManageTp1();
   datetime cur = iTime(_Symbol, _Period, 0);
   if(cur > lastBar + PeriodSeconds(_Period) - 1 && cur != lastBar)
   {
      MqlRates nb[];
      ArraySetAsSeries(nb, false);
      int got = CopyRates(_Symbol, _Period, lastBar + 1, cur - 1, nb);
      for(int i = 0; i < got; i++)
      {
         if(nb[i].time <= lastBar || nb[i].time >= cur) continue;
         AppendBar(nb[i]);
         ProcessBar(true);
         lastBar = nb[i].time;
      }
      if(MQLInfoInteger(MQL_VISUAL_MODE) || !MQLInfoInteger(MQL_TESTER)) Comment(Summary());
   }
}

string Summary()
{
   string s = StringFormat("Scalping Patterns  %s %s  (%s)\n", _Symbol, EnumToString(_Period),
                           InpMode == SP_MORE ? "More trades" : InpMode == SP_BALANCED ? "Balanced" : "Strict");
   s += "Pattern              BUY: trades  win%   R      | SELL: trades  win%   R\n";
   int tn[2] = {0, 0}, tw[2] = {0, 0}; double tr[2] = {0, 0};
   for(int k = 1; k <= 7; k++)
   {
      s += StringFormat("%-20s", PatName(k));
      for(int sd = 0; sd < 2; sd++)
      {
         int n = stN[k][sd];
         s += StringFormat(" %6d  %5s  %+6.1f %s", n, n > 0 ? DoubleToString(100.0 * stW[k][sd] / n, 0) + "%" : "-", stR[k][sd], sd == 0 ? "|" : "");
         tn[sd] += n; tw[sd] += stW[k][sd]; tr[sd] += stR[k][sd];
      }
      s += "\n";
   }
   s += StringFormat("%-20s", "ALL");
   for(int sd = 0; sd < 2; sd++)
      s += StringFormat(" %6d  %5s  %+6.1f %s", tn[sd], tn[sd] > 0 ? DoubleToString(100.0 * tw[sd] / tn[sd], 0) + "%" : "-", tr[sd], sd == 0 ? "|" : "");
   int all = tn[0] + tn[1];
   s += StringFormat("\nTotal %d trades, win %s, net %+.1fR (win = trade made money after spread/commission)",
                     all, all > 0 ? DoubleToString(100.0 * (tw[0] + tw[1]) / all, 1) + "%" : "-", tr[0] + tr[1]);
   return s;
}

double OnTester()
{
   double r = 0;
   for(int k = 1; k <= 7; k++) r += stR[k][0] + stR[k][1];
   return r;
}

void OnDeinit(const int reason)
{
   if(trOpen && MQLInfoInteger(MQL_TESTER)) { if(PosSelect()) trade.PositionClose(trTicket); FinishTrade(N - 1, "Test end"); }
   string s = Summary();
   string lines[];
   int k = StringSplit(s, '\n', lines);
   for(int i = 0; i < k; i++) Print(lines[i]);
   int fh = FileOpen(StringFormat("ScalpingPatterns_%s_%s_summary.txt", _Symbol, EnumToString(_Period)), FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, s + "\n"); FileClose(fh); }
   if(csvH != INVALID_HANDLE) FileClose(csvH);
   Comment("");
}
//+------------------------------------------------------------------+
