//+------------------------------------------------------------------+
//| GoldLedSilver.mq5 - trade silver in the direction of gold's Asian-range breakout
//| Run on an XAGUSD M5 chart. Gold (InpLeader) range = its high/low from RangeStart to
//| RangeEnd (server time). The FIRST M5 gold close beyond that range (before EntryUntil)
//| decides: BUY / SELL silver at once. Silver stop = StopMult x half of silver's own Asian
//| range, target = TargetR x risk, everything closed 5 minutes before ExitHour.
//| research: research/silver_scalp.py + gold-led test. Orders only in the Strategy Tester.
//+------------------------------------------------------------------+
#property copyright   "BYTEFX"
#property version     "1.00"
#property description "Silver follows gold's Asian-range breakout (M5) - Strategy Tester."
#include <Trade/Trade.mqh>

input string InpLeader     = "XAUUSD"; // Leader symbol (gold)
input int    InpRangeStart = 1;        // Range start hour (server)
input int    InpRangeEnd   = 9;        // Range end hour (server, exclusive)
input int    InpEntryUntil = 17;       // No new entries from this hour
input int    InpExitHour   = 23;       // Close 5 minutes before this hour
input double InpStopMult   = 1.5;      // Silver stop = this x half of silver's Asian range
input double InpTargetR    = 1.0;      // Target in R (0 = none)
input int    InpMinBars    = 24;       // Range needs at least this many M5 candles
input double InpRiskPct    = 1.0;      // Risk per trade (% of balance)
input ulong  InpMagic      = 720040;
input bool   InpAllowLive  = false;    // Allow live trading (keep OFF)

CTrade trade;
datetime lastBar = 0;
long   doneDay = -1;
ulong  pos = 0; int posDir = 0; double riskMoney = 0; datetime entryT = 0;
int stN[2], stW[2]; double stR[2], stM[2];
int csvH = INVALID_HANDLE;

int OnInit()
{
   SymbolSelect(InpLeader, true);
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(100);
   ArrayInitialize(stN, 0); ArrayInitialize(stW, 0); ArrayInitialize(stR, 0); ArrayInitialize(stM, 0);
   csvH = FileOpen(StringFormat("GLS_%s_trades.csv", _Symbol), FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
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
   stN[s]++; stR[s] += r; stM[s] += money; if(money > 0) stW[s]++;
   if(csvH != INVALID_HANDLE)
      FileWrite(csvH, TimeToString(entryT, TIME_DATE | TIME_MINUTES), TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES),
                posDir == 1 ? "BUY" : "SELL", DoubleToString(money, 2), DoubleToString(r, 3));
   pos = 0; posDir = 0;
}

// Asian range of `sym` for server day `today` from M5 candles (series order), false if incomplete
bool Range(string sym, long today, double &hi, double &lo)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(sym, PERIOD_M5, 0, 400, r);
   hi = -DBL_MAX; lo = DBL_MAX; int cnt = 0;
   for(int i = 0; i < n; i++)
   {
      if((long)r[i].time / 86400 != today) continue;
      MqlDateTime t; TimeToStruct(r[i].time, t);
      if(t.hour >= InpRangeStart && t.hour < InpRangeEnd) { hi = MathMax(hi, r[i].high); lo = MathMin(lo, r[i].low); cnt++; }
   }
   return cnt >= InpMinBars;
}

void OnTick()
{
   if(!(MQLInfoInteger(MQL_TESTER) || InpAllowLive)) return;
   if(pos != 0 && !PositionSelectByTicket(pos)) Book();
   datetime tnow = TimeCurrent();
   datetime exitAt = (datetime)((long)tnow / 86400 * 86400 + InpExitHour * 3600 - 300);
   if(pos != 0 && (tnow >= exitAt || (long)entryT / 86400 != (long)tnow / 86400))
      if(trade.PositionClose(pos) && trade.ResultRetcode() == TRADE_RETCODE_DONE) Book();
   datetime cur = iTime(_Symbol, PERIOD_M5, 0);
   if(cur == lastBar) return;
   lastBar = cur;
   long today = (long)cur / 86400;
   if(pos != 0 || doneDay == today || tnow >= exitAt) return;
   // gold's candle that just closed (same open time as silver's previous candle)
   MqlRates g[];
   ArraySetAsSeries(g, true);
   if(CopyRates(InpLeader, PERIOD_M5, 1, 1, g) != 1) return;
   if((long)g[0].time / 86400 != today) return;
   MqlDateTime b; TimeToStruct(g[0].time, b);
   if(b.hour < InpRangeEnd || b.hour >= InpEntryUntil) return;
   double ghi, glo, shi, slo;
   if(!Range(InpLeader, today, ghi, glo) || !Range(_Symbol, today, shi, slo)) return;
   int d = g[0].close > ghi ? 1 : g[0].close < glo ? -1 : 0;
   if(d == 0) return;
   doneDay = today;                                   // gold's first breakout of the day decides
   double px = d == 1 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE); if(tick <= 0) tick = _Point;
   double dist = InpStopMult * (shi - slo) / 2;
   if(dist <= 0) return;
   double sl = MathRound((px - d * dist) / tick) * tick;
   double tp = InpTargetR > 0 ? MathRound((px + d * InpTargetR * dist) / tick) * tick : 0;
   ENUM_ORDER_TYPE ot = d == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double loss = 0;
   if(!OrderCalcProfit(ot, _Symbol, 1.0, px, sl, loss) || loss >= 0) return;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vol = MathMin(mx, MathMax(mn, MathFloor(AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0 / -loss / step) * step));
   bool ok = d == 1 ? trade.Buy(vol, _Symbol, 0, sl, tp, "GLS") : trade.Sell(vol, _Symbol, 0, sl, tp, "GLS");
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
   string s = StringFormat("%s GoldLedSilver | trades %d win %.1f%% netR %+.1f money %+.2f | BUY %d win %.1f%% %+.1fR | SELL %d win %.1f%% %+.1fR",
      _Symbol, n, n ? 100.0 * (stW[0] + stW[1]) / n : 0, stR[0] + stR[1], stM[0] + stM[1],
      stN[0], stN[0] ? 100.0 * stW[0] / stN[0] : 0, stR[0], stN[1], stN[1] ? 100.0 * stW[1] / stN[1] : 0, stR[1]);
   Print(s);
   int fh = FileOpen(StringFormat("GLS_%s_summary.txt", _Symbol), FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, s + "\n"); FileClose(fh); }
   if(csvH != INVALID_HANDLE) FileClose(csvH);
}
