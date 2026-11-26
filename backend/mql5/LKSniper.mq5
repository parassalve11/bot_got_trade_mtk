//+------------------------------------------------------------------+
//| LKSniper.mq5 - the user's "LK Sniper" TradingView indicator (auto_treading_bot/lk-sniper.pine)
//| ported for the Strategy Tester (same port as research/lk_sniper.py, default inputs).
//| UP / DOWN flip on a closed candle -> market order; SL = EMA34 basis -/+ 1.15 ATR (>= 10 ticks),
//| TP = TP3 = 3R; an opposite flip closes the trade (and opens the new one).
//| Orders only in the Strategy Tester unless live trading is allowed.
//+------------------------------------------------------------------+
#property copyright   "BYTEFX"
#property version     "1.00"
#property description "LK Sniper (user's indicator) for the Strategy Tester."
#include <Trade/Trade.mqh>

input double InpSens      = 0.35;   // Signal selectivity
input int    InpTrendLen  = 34;     // Trend length
input int    InpMomLen    = 12;     // Momentum length
input double InpSlAtr     = 1.15;   // Stop distance from basis (ATR)
input double InpTargetR   = 3.0;    // Target (TP3 = 3R)
input double InpRiskPct   = 1.0;    // Risk per trade (% of balance)
input int    InpWarmup    = 3000;   // History candles processed before trading
input ulong  InpMagic     = 720060;
input bool   InpAllowLive = false;  // Allow live trading (keep OFF)

struct Sm { int n; int cnt; double sum; double val; bool ready; bool ema; };
double SmUpd(Sm &s, double x)
{
   if(!s.ready) { s.sum += x; s.cnt++; if(s.cnt >= s.n) { s.val = s.sum / s.n; s.ready = true; } else s.val = x; }
   else if(s.ema) s.val = (2.0 / (s.n + 1)) * x + (1 - 2.0 / (s.n + 1)) * s.val;
   else s.val = (x + (s.n - 1) * s.val) / s.n;
   return s.val;
}
void SmInit(Sm &s, int n, bool ema) { s.n = n; s.cnt = 0; s.sum = 0; s.val = 0; s.ready = false; s.ema = ema; }

struct ST { Sm atr; double ub; double lb; double st; double dir; bool init; double prevAtrReady; };

CTrade trade;
int N = 0;
double O[], H[], L[], C[], BAS[], SLW[], DL[];
Sm sBasis, sAtr, sMom, sNormal, sRsiU, sRsiD, sSlow, sReg;
ST stF, stM, stS;
int bsb = 0, ssb = 0, bcf = 0, scf = 0, trendDir = 0, lastFlip = -1000000;
datetime lastBar = 0; bool warm = false;
ulong pos = 0; int posDir = 0; double riskMoney = 0; datetime entryT = 0;
int stN[2], stW[2]; double stR[2], stM2[2];
int csvH = INVALID_HANDLE;

double Clip(double x, double a, double b) { return MathMax(a, MathMin(b, x)); }

double STUpd(ST &s, int i, double factor)
{
   double tr = i == 0 ? H[i] - L[i] : MathMax(H[i] - L[i], MathMax(MathAbs(H[i] - C[i - 1]), MathAbs(L[i] - C[i - 1])));
   bool wasReady = s.atr.ready;
   double a = SmUpd(s.atr, tr);
   if(!s.atr.ready) { s.dir = 1; return s.dir; }
   double hl2 = (H[i] + L[i]) / 2, up = hl2 + factor * a, lo = hl2 - factor * a;
   double pu = s.ub, pl = s.lb;
   bool first = !s.init;
   s.lb = (first || lo > pl || C[i - 1] < pl) ? lo : pl;
   s.ub = (first || up < pu || C[i - 1] > pu) ? up : pu;
   if(first || !wasReady) s.dir = 1;
   else if(s.st == pu) s.dir = C[i] > s.ub ? -1 : 1;
   else s.dir = C[i] < s.lb ? 1 : -1;
   s.st = s.dir == -1 ? s.lb : s.ub;
   s.init = true;
   return s.dir;
}

// returns +1 / -1 on a flip at bar i (and the stop price), 0 otherwise
int Process(const MqlRates &r, double &slOut)
{
   int i = N;
   if(ArraySize(O) <= i)
   {
      int sz = i + 5000;
      ArrayResize(O, sz); ArrayResize(H, sz); ArrayResize(L, sz); ArrayResize(C, sz);
      ArrayResize(BAS, sz); ArrayResize(SLW, sz); ArrayResize(DL, sz);
   }
   O[i] = r.open; H[i] = r.high; L[i] = r.low; C[i] = r.close;
   N = i + 1;
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE); if(tick <= 0) tick = _Point;
   double basis = SmUpd(sBasis, C[i]); BAS[i] = basis;
   double tr = i == 0 ? H[i] - L[i] : MathMax(H[i] - L[i], MathMax(MathAbs(H[i] - C[i - 1]), MathAbs(L[i] - C[i - 1])));
   double atr = SmUpd(sAtr, tr);
   double satr = MathMax(atr, tick);
   double mom = SmUpd(sMom, i >= InpMomLen ? C[i] - C[i - InpMomLen] : 0) / satr;
   double dist = (C[i] - basis) / satr;
   double net = i >= 10 ? MathAbs(C[i] - C[i - 10]) : 0, path = 0;
   for(int k = MathMax(1, i - 9); k <= i; k++) path += MathAbs(C[k] - C[k - 1]);
   double eff = path > 0 ? Clip(net / path, 0, 1) : 0, chop = 1 - eff;
   double edir = i >= 10 ? (C[i] > C[i - 10] ? 1 : C[i] < C[i - 10] ? -1 : 0) : 0;
   double normal = SmUpd(sNormal, satr);
   double vr = normal > 0 ? satr / normal : 1, vexp = Clip(vr - 1, 0, 1.25), vdev = Clip(MathAbs(vr - 1), 0, 1.5);
   double df = STUpd(stF, i, 1.45 + chop * 0.25 + vexp * 0.10);
   double dm = STUpd(stM, i, 1.95 + chop * 0.35 + vexp * 0.15);
   double ds = STUpd(stS, i, 2.55 + chop * 0.45 + vexp * 0.20);
   int bv = (df < 0 ? 1 : 0) + (dm < 0 ? 1 : 0) + (ds < 0 ? 1 : 0);
   int sv = (df > 0 ? 1 : 0) + (dm > 0 ? 1 : 0) + (ds > 0 ? 1 : 0);
   int req = chop > 0.70 ? 3 : 2;
   double dl = i == 0 ? 0 : C[i] - C[i - 1];
   double ru = SmUpd(sRsiU, MathMax(dl, 0)), rd = SmUpd(sRsiD, MathMax(-dl, 0));
   double rsi = rd == 0 ? 100 : 100 - 100 / (1 + ru / rd);
   double slow = SmUpd(sSlow, (H[i] + L[i]) / 2); SLW[i] = slow;
   int sl_len = (int)MathMax(3, MathRound(InpTrendLen * 0.12));
   double rh = H[i], rl = L[i];
   if(i > 0) { rh = -DBL_MAX; rl = DBL_MAX; for(int k = MathMax(0, i - sl_len); k < i; k++) { rh = MathMax(rh, H[k]); rl = MathMin(rl, L[k]); } }
   double rngb = MathMax(H[i] - L[i], tick);
   double press = Clip((C[i] - O[i]) / rngb * 0.6 + ((C[i] - L[i]) / rngb - 0.5) * 2 * 0.4, -1, 1);
   double bslope = i >= 3 ? (basis - BAS[i - 3]) / satr : 0, sslope = i >= 3 ? (slow - SLW[i - 3]) / satr : 0;
   double raw = Clip(dist / 1.2, -1, 1) * 0.22 + Clip(mom / 0.35, -1, 1) * 0.19 + Clip(bslope / 0.25, -1, 1) * 0.14 +
                Clip(sslope / 0.25, -1, 1) * 0.10 + Clip((rsi - 50) / 20, -1, 1) * 0.08 + eff * edir * 0.09 + press * 0.05 +
                (C[i] > rh ? 1.0 : C[i] < rl ? -1.0 : 0.0) * 0.05 + (bv - sv) / 3.0 * 0.20;
   double regime = SmUpd(sReg, raw);
   double gate = 0.22 + InpSens * 0.12 + chop * 0.085 + Clip(vdev * 0.04, 0, 0.06);
   bool bullC = regime > gate && C[i] > basis + satr * InpSens * 0.3 && mom > 0.025;
   bool bearC = regime < -gate && C[i] < basis - satr * InpSens * 0.3 && mom < -0.025;
   slOut = 0;
   if(i < 60) return 0;
   bsb = bv >= req ? MathMin(bsb + 1, 5) : 0;
   ssb = sv >= req ? MathMin(ssb + 1, 5) : 0;
   int pr = chop > 0.72 ? 2 : 1;
   bool bc = bullC && bsb >= pr, sc = bearC && ssb >= pr;
   bcf = bc ? MathMin(bcf + 1, 4) : 0;
   scf = sc ? MathMin(scf + 1, 4) : 0;
   int rb = chop > 0.72 ? 3 : chop > 0.40 ? 2 : 1;
   bool sb = bc && bv == 3 && regime > gate + 0.26 && mom > 0.16 && eff > 0.42;
   bool ss = sc && sv == 3 && regime < -(gate + 0.26) && mom < -0.16 && eff > 0.42;
   bool br = (bcf >= rb || sb) && df < 0 && (dm < 0 || ds < 0);
   bool sr = (scf >= rb || ss) && df > 0 && (dm > 0 || ds > 0);
   int cd = 6 + (int)MathRound(chop * 4);
   bool done = i - lastFlip >= cd;
   int sig = 0;
   if(trendDir != 1 && br && (done || sb)) { trendDir = 1; lastFlip = i; bcf = scf = bsb = ssb = 0; sig = 1; }
   else if(trendDir != -1 && sr && (done || ss)) { trendDir = -1; lastFlip = i; bcf = scf = bsb = ssb = 0; sig = -1; }
   if(sig != 0)
   {
      double anchor = basis - sig * satr * InpSlAtr;
      slOut = sig == 1 ? MathMin(anchor, C[i] - 10 * tick) : MathMax(anchor, C[i] + 10 * tick);
   }
   return sig;
}

int OnInit()
{
   SmInit(sBasis, InpTrendLen, true); SmInit(sAtr, 14, false); SmInit(sMom, 5, true); SmInit(sNormal, 50, true);
   SmInit(sRsiU, 14, false); SmInit(sRsiD, 14, false); SmInit(sSlow, (int)MathMax(10, MathRound(InpTrendLen * 0.7)), true);
   SmInit(sReg, 3, true);
   SmInit(stF.atr, 9, false); SmInit(stM.atr, 14, false); SmInit(stS.atr, 21, false);
   stF.init = stM.init = stS.init = false; stF.dir = stM.dir = stS.dir = 1;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(100);
   ArrayInitialize(stN, 0); ArrayInitialize(stW, 0); ArrayInitialize(stR, 0); ArrayInitialize(stM2, 0);
   csvH = FileOpen(StringFormat("LK_%s_%s_trades.csv", _Symbol, EnumToString(_Period)), FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(csvH != INVALID_HANDLE) FileWrite(csvH, "entry_time", "exit_time", "side", "profit", "R");
   return INIT_SUCCEEDED;
}

void Book()
{
   double money = 0;
   if(HistorySelectByPosition(pos))
      for(int i = 0; i < HistoryDealsTotal(); i++)
      {
         ulong d = HistoryDealGetTicket(i);
         money += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
      }
   int s = posDir == 1 ? 0 : 1;
   double r = money / MathMax(riskMoney, 1e-9);
   stN[s]++; stR[s] += r; stM2[s] += money; if(money > 0) stW[s]++;
   if(csvH != INVALID_HANDLE)
      FileWrite(csvH, TimeToString(entryT, TIME_DATE | TIME_MINUTES), TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES),
                posDir == 1 ? "BUY" : "SELL", DoubleToString(money, 2), DoubleToString(r, 3));
   pos = 0; posDir = 0;
}

void Open(int d, double sl)
{
   double px = d == 1 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE); if(tick <= 0) tick = _Point;
   if(d * (px - sl) <= 0) return;
   sl = MathRound(sl / tick) * tick;
   double tp = MathRound((px + d * InpTargetR * MathAbs(px - sl)) / tick) * tick;
   ENUM_ORDER_TYPE ot = d == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double loss = 0;
   if(!OrderCalcProfit(ot, _Symbol, 1.0, px, sl, loss) || loss >= 0) return;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vol = MathMin(mx, MathMax(mn, MathFloor(AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0 / -loss / step) * step));
   bool ok = d == 1 ? trade.Buy(vol, _Symbol, 0, sl, tp, "LK") : trade.Sell(vol, _Symbol, 0, sl, tp, "LK");
   if(!ok || trade.ResultRetcode() != TRADE_RETCODE_DONE) return;
   if(!HistoryDealSelect(trade.ResultDeal())) return;
   pos = (ulong)HistoryDealGetInteger(trade.ResultDeal(), DEAL_POSITION_ID);
   if(!PositionSelectByTicket(pos)) { pos = 0; return; }
   posDir = d; entryT = TimeCurrent();
   double l2 = 0;
   if(OrderCalcProfit(ot, _Symbol, PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PRICE_OPEN), sl, l2)) riskMoney = -l2;
}

void OnTick()
{
   if(!(MQLInfoInteger(MQL_TESTER) || InpAllowLive)) return;
   if(pos != 0 && !PositionSelectByTicket(pos)) Book();
   if(!warm)
   {
      MqlRates hist[];
      ArraySetAsSeries(hist, false);
      int got = CopyRates(_Symbol, _Period, 1, InpWarmup, hist);
      if(got <= 0) return;
      double sl;
      for(int k = 0; k < got; k++) Process(hist[k], sl);
      lastBar = iTime(_Symbol, _Period, 0);
      warm = true;
      return;
   }
   datetime cur = iTime(_Symbol, _Period, 0);
   if(cur == lastBar) return;
   lastBar = cur;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, _Period, 1, 1, r) != 1) return;
   double sl;
   int sig = Process(r[0], sl);
   if(sig == 0) return;
   if(pos != 0 && posDir == -sig) { if(trade.PositionClose(pos) && trade.ResultRetcode() == TRADE_RETCODE_DONE) Book(); }
   if(pos == 0) Open(sig, sl);
}

double OnTester() { return stR[0] + stR[1]; }

void OnDeinit(const int reason)
{
   if(pos != 0 && PositionSelectByTicket(pos)) { trade.PositionClose(pos); Book(); }
   int n = stN[0] + stN[1];
   string s = StringFormat("%s %s LKSniper | trades %d win %.1f%% netR %+.1f money %+.2f | BUY %d win %.1f%% %+.1fR | SELL %d win %.1f%% %+.1fR",
      _Symbol, EnumToString(_Period), n, n ? 100.0 * (stW[0] + stW[1]) / n : 0, stR[0] + stR[1], stM2[0] + stM2[1],
      stN[0], stN[0] ? 100.0 * stW[0] / stN[0] : 0, stR[0], stN[1], stN[1] ? 100.0 * stW[1] / stN[1] : 0, stR[1]);
   Print(s);
   int fh = FileOpen(StringFormat("LK_%s_%s_summary.txt", _Symbol, EnumToString(_Period)), FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, s + "\n"); FileClose(fh); }
   if(csvH != INVALID_HANDLE) FileClose(csvH);
}
