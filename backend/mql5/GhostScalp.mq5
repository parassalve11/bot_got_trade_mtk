//+------------------------------------------------------------------+
//| GhostScalp.mq5 - the "Ghost Scalp" part of the user's "Wolfs Radar+" TradingView script
//| (auto_treading_bot/wolf_radar.pine), default inputs, for the Strategy Tester:
//| liquidity sweep of a stored 5/5 swing level (>= MinSweep pips beyond), sweep candle closes
//| back inside with wick >= 35%, body <= 65%, range >= MinRange pips; within 2 candles a
//| confirming candle (bullish/bearish body, beyond EMA50, beyond the sweep candle's middle)
//| -> entry. Fixed TP / SL in pips (gold pip 0.01, others = point), 10-candle cooldown,
//| one trade at a time. Orders only in the Strategy Tester unless allowed.
//+------------------------------------------------------------------+
#property copyright   "BYTEFX"
#property version     "1.00"
#property description "Ghost Scalp (Wolfs Radar+) for the Strategy Tester."
#include <Trade/Trade.mqh>

input int    InpTpPips    = 2000;  // Take profit (pips)
input int    InpSlPips    = 500;   // Stop loss (pips)
input int    InpMinSweep  = 30;    // Minimum sweep distance (pips)
input int    InpMinRange  = 20;    // Minimum candle range (pips)
input double InpMinWick   = 0.35;  // Minimum sweep wick %
input double InpMaxBody   = 0.65;  // Maximum body %
input int    InpWindow    = 2;     // Max bars after sweep for confirmation
input int    InpCooldown  = 10;    // Cooldown bars between signals
input int    InpEmaLen    = 50;    // EMA length
input double InpRiskPct   = 1.0;   // Risk per trade (% of balance)
input ulong  InpMagic     = 720050;
input bool   InpAllowLive = false; // Allow live trading (keep OFF)

CTrade trade;
int hEma;
datetime lastBar = 0;
long barNo = 0;
double hl[], ll[]; long hb[], lb[];
long pb = -1, sb = -1; double pbm = 0, sbm = 0;
long lastSig = -1000000;
ulong pos = 0; int posDir = 0; double riskMoney = 0; datetime entryT = 0;
int stN[2], stW[2]; double stR[2], stM[2];
int csvH = INVALID_HANDLE;
double pip;

int OnInit()
{
   hEma = iMA(_Symbol, _Period, InpEmaLen, 0, MODE_EMA, PRICE_CLOSE);
   pip = StringFind(_Symbol, "XAU") >= 0 ? 0.01 : _Point;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(100);
   ArrayInitialize(stN, 0); ArrayInitialize(stW, 0); ArrayInitialize(stR, 0); ArrayInitialize(stM, 0);
   csvH = FileOpen(StringFormat("GS_%s_%s_trades.csv", _Symbol, EnumToString(_Period)), FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(csvH != INVALID_HANDLE) FileWrite(csvH, "entry_time", "exit_time", "side", "profit", "R");
   return INIT_SUCCEEDED;
}

void Push(double &lv[], long &lbar[], double p, long b)
{
   int k = ArraySize(lv);
   ArrayResize(lv, k + 1); ArrayResize(lbar, k + 1);
   lv[k] = p; lbar[k] = b;
   if(k + 1 > 20) { ArrayRemove(lv, 0, 1); ArrayRemove(lbar, 0, 1); }
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
   stN[s]++; stR[s] += r; stM[s] += money; if(money > 0) stW[s]++;
   if(csvH != INVALID_HANDLE)
      FileWrite(csvH, TimeToString(entryT, TIME_DATE | TIME_MINUTES), TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES),
                posDir == 1 ? "BUY" : "SELL", DoubleToString(money, 2), DoubleToString(r, 3));
   pos = 0; posDir = 0;
}

void OnTick()
{
   if(!(MQLInfoInteger(MQL_TESTER) || InpAllowLive)) return;
   if(pos != 0 && !PositionSelectByTicket(pos)) Book();
   datetime cur = iTime(_Symbol, _Period, 0);
   if(cur == lastBar) return;
   lastBar = cur;
   barNo++;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, _Period, 1, 12, r) < 12) return;
   double e[1];
   if(CopyBuffer(hEma, 0, 1, 1, e) != 1) return;
   long i = barNo;                       // index of the candle that just closed
   // pivot confirmed now: candle r[5] (5 left: r[6..10], 5 right: r[0..4])
   bool okH = true, okL = true;
   for(int k = 6; k <= 10; k++) { if(!(r[k].high < r[5].high)) okH = false; if(!(r[k].low > r[5].low)) okL = false; }
   for(int k = 0; k <= 4; k++)  { if(!(r[k].high <= r[5].high)) okH = false; if(!(r[k].low >= r[5].low)) okL = false; }
   if(okH) Push(hl, hb, r[5].high, i - 5);
   if(okL) Push(ll, lb, r[5].low, i - 5);
   double o = r[0].open, h = r[0].high, lo = r[0].low, c = r[0].close, rng = h - lo;
   double bodyp = rng > 0 ? MathAbs(c - o) / rng : 0, upw = rng > 0 ? (h - MathMax(o, c)) / rng : 0, dnw = rng > 0 ? (MathMin(o, c) - lo) / rng : 0;
   double msw = InpMinSweep * pip, mrg = InpMinRange * pip;
   double shl = 0, sll = 0; bool hasH = false, hasL = false;
   for(int k = ArraySize(hl) - 1; k >= 0; k--) if(hb[k] < i && h > hl[k] && h - hl[k] >= msw) { shl = hl[k]; hasH = true; break; }
   for(int k = ArraySize(ll) - 1; k >= 0; k--) if(lb[k] < i && lo < ll[k] && ll[k] - lo >= msw) { sll = ll[k]; hasL = true; break; }
   if(hasL && c > sll && dnw >= InpMinWick && bodyp <= InpMaxBody && rng >= mrg) { pb = i; pbm = (h + lo) / 2; }
   if(hasH && c < shl && upw >= InpMinWick && bodyp <= InpMaxBody && rng >= mrg) { sb = i; sbm = (h + lo) / 2; }
   bool buy = pb >= 0 && i - pb <= InpWindow && c > o && c > e[0] && c > pbm;
   bool sell = sb >= 0 && i - sb <= InpWindow && c < o && c < e[0] && c < sbm;
   bool cool = i - lastSig > InpCooldown;
   buy = buy && cool;
   sell = sell && cool && !buy;
   bool active = pos != 0;
   if(buy || sell) lastSig = i;
   if(buy || (pb >= 0 && i - pb > InpWindow)) pb = -1;
   if(sell || (sb >= 0 && i - sb > InpWindow)) sb = -1;
   if(active || !(buy || sell)) return;
   int d = buy ? 1 : -1;
   double px = d == 1 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE); if(tick <= 0) tick = _Point;
   double sl = MathRound((px - d * InpSlPips * pip) / tick) * tick, tp = MathRound((px + d * InpTpPips * pip) / tick) * tick;
   ENUM_ORDER_TYPE ot = d == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double loss = 0;
   if(!OrderCalcProfit(ot, _Symbol, 1.0, px, sl, loss) || loss >= 0) return;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vol = MathMin(mx, MathMax(mn, MathFloor(AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0 / -loss / step) * step));
   bool ok = d == 1 ? trade.Buy(vol, _Symbol, 0, sl, tp, "GS") : trade.Sell(vol, _Symbol, 0, sl, tp, "GS");
   if(!ok || trade.ResultRetcode() != TRADE_RETCODE_DONE) return;
   if(!HistoryDealSelect(trade.ResultDeal())) return;
   pos = (ulong)HistoryDealGetInteger(trade.ResultDeal(), DEAL_POSITION_ID);
   if(!PositionSelectByTicket(pos)) { pos = 0; return; }
   posDir = d; entryT = TimeCurrent();
   double l2 = 0;
   if(OrderCalcProfit(ot, _Symbol, PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PRICE_OPEN), sl, l2)) riskMoney = -l2;
}

double OnTester() { return stR[0] + stR[1]; }

void OnDeinit(const int reason)
{
   if(pos != 0 && PositionSelectByTicket(pos)) { trade.PositionClose(pos); Book(); }
   int n = stN[0] + stN[1];
   string s = StringFormat("%s %s GhostScalp | trades %d win %.1f%% netR %+.1f money %+.2f | BUY %d win %.1f%% %+.1fR | SELL %d win %.1f%% %+.1fR",
      _Symbol, EnumToString(_Period), n, n ? 100.0 * (stW[0] + stW[1]) / n : 0, stR[0] + stR[1], stM[0] + stM[1],
      stN[0], stN[0] ? 100.0 * stW[0] / stN[0] : 0, stR[0], stN[1], stN[1] ? 100.0 * stW[1] / stN[1] : 0, stR[1]);
   Print(s);
   int fh = FileOpen(StringFormat("GS_%s_%s_summary.txt", _Symbol, EnumToString(_Period)), FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, s + "\n"); FileClose(fh); }
   if(csvH != INVALID_HANDLE) FileClose(csvH);
}
