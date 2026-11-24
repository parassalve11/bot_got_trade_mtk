//+------------------------------------------------------------------+
//| MeanReversion15.mq5                                              |
//| The three 15-minute mean-reversion strategies of                 |
//| research/hiwin15.py, for the MT5 Strategy Tester:                |
//|  RSI2 : BUY close > SMA200 and RSI(2) < th, exit close > SMA5    |
//|  BB   : BUY close < lower Bollinger(20,2) and > SMA200,          |
//|         exit close > middle band                                 |
//|  VWAP : BUY close < VWAP - th x stdev and > SMA200, exit > VWAP  |
//| SELL = mirror. Entry at the next candle's open, hard stop        |
//| = stop x ATR(14) on the server, time stop after N candles.       |
//| Stocks: no entries in the last 2 candles before the session end, |
//| close the trade at the session end.                              |
//| SAFETY: orders only in the Strategy Tester unless allowed.       |
//+------------------------------------------------------------------+
#property copyright   "BYTEFX"
#property version     "1.00"
#property description "15-minute mean reversion (RSI2 / Bollinger / VWAP) for the Strategy Tester."
#include <Trade/Trade.mqh>

enum ENUM_MR_FAM { MR_RSI2 = 0, MR_BB = 1, MR_VWAP = 2 };
enum ENUM_MR_DIR { MR_BOTH = 0, MR_LONG = 1, MR_SHORT = -1 };

input ENUM_MR_FAM InpFam     = MR_RSI2;  // Strategy
input ENUM_MR_DIR InpDir     = MR_BOTH;  // Direction
input double      InpTh      = 10;       // RSI2: oversold level / VWAP: stdev distance
input double      InpStopAtr = 1.0;      // Hard stop (x ATR 14)
input int         InpTmax    = 8;        // Time stop (candles, entry candle included)
input bool        InpStock   = false;    // Stock: no late entries, close at the session end
input double      InpRiskPct = 1.0;      // Risk per trade (% of balance)
input ulong       InpMagic   = 720015;   // Magic number
input bool        InpAllowLive = false;  // Allow live trading (keep OFF)

CTrade trade;
int hSma200, hSma5, hSma20, hBB;
datetime lastBar = 0;
ulong  posTicket = 0;
int    posDir = 0, barsHeld = 0;
double riskMoney = 0;
datetime entryTime = 0;
int    stN[2], stW[2]; double stR[2], stM[2];
int    csvH = INVALID_HANDLE;
bool   allowed = false;

int OnInit()
{
   hSma200 = iMA(_Symbol, _Period, 200, 0, MODE_SMA, PRICE_CLOSE);
   hSma5   = iMA(_Symbol, _Period, 5, 0, MODE_SMA, PRICE_CLOSE);
   hSma20  = iMA(_Symbol, _Period, 20, 0, MODE_SMA, PRICE_CLOSE);
   hBB     = iBands(_Symbol, _Period, 20, 0, 2.0, PRICE_CLOSE);
   if(hSma200 == INVALID_HANDLE || hSma5 == INVALID_HANDLE || hBB == INVALID_HANDLE) return INIT_FAILED;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(50);
   allowed = MQLInfoInteger(MQL_TESTER) || InpAllowLive;
   ArrayInitialize(stN, 0); ArrayInitialize(stW, 0); ArrayInitialize(stR, 0); ArrayInitialize(stM, 0);
   csvH = FileOpen(StringFormat("MR15_%s_%d_trades.csv", _Symbol, (int)InpFam), FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',');
   if(csvH != INVALID_HANDLE) FileWrite(csvH, "entry_time", "exit_time", "side", "profit", "R");
   return INIT_SUCCEEDED;
}

double Buf(int h, int buf, int shift) { double v[1]; if(CopyBuffer(h, buf, shift, 1, v) != 1) return EMPTY_VALUE; return v[0]; }

// Wilder RSI(2) and ATR(14) on closed bars (shift 1 = last closed)
bool CalcRsiAtr(double &rsi2, double &atr)
{
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, _Period, 1, 400, r);
   if(n < 100) return false;
   double up = 0, dn = 0, a = 0;
   for(int i = 1; i <= 2; i++) { double d = r[i].close - r[i - 1].close; up += MathMax(d, 0); dn += MathMax(-d, 0); }
   up /= 2; dn /= 2;
   for(int i = 3; i < n; i++) { double d = r[i].close - r[i - 1].close; up = (MathMax(d, 0) + up) / 2; dn = (MathMax(-d, 0) + dn) / 2; }
   rsi2 = dn == 0 ? 100 : 100 - 100 / (1 + up / dn);
   for(int i = 1; i <= 14; i++) a += MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - r[i - 1].close), MathAbs(r[i].low - r[i - 1].close)));
   a /= 14;
   for(int i = 15; i < n; i++)
   {
      double tr = MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - r[i - 1].close), MathAbs(r[i].low - r[i - 1].close)));
      a = (tr + 13 * a) / 14;
   }
   atr = a;
   return true;
}

// session VWAP (tick volume) and its stdev up to the last closed bar
bool CalcVwap(double &vw, double &sd)
{
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, _Period, 1, 200, r);
   if(n < 2) return false;
   long day = (long)r[0].time / 86400;
   double s1 = 0, s2 = 0, s3 = 0;
   for(int i = 0; i < n && (long)r[i].time / 86400 == day; i++)
   {
      double w = r[i].tick_volume > 0 ? (double)r[i].tick_volume : 1.0;
      double p = (r[i].high + r[i].low + r[i].close) / 3;
      s1 += w; s2 += w * p; s3 += w * p * p;
   }
   vw = s2 / s1;
   sd = MathSqrt(MathMax(s3 / s1 - vw * vw, 0));
   return true;
}

datetime SessionEnd()
{
   MqlDateTime t; TimeToStruct(TimeCurrent(), t);
   datetime from, to, best = 0;
   for(int k = 0; k < 4; k++)
      if(SymbolInfoSessionTrade(_Symbol, (ENUM_DAY_OF_WEEK)t.day_of_week, k, from, to)) best = MathMax(best, to);
      else break;
   if(best == 0) return 0;
   return (datetime)((long)TimeCurrent() / 86400 * 86400 + (long)best % 86400 + ((long)best % 86400 == 0 ? 86400 : 0));
}

void Book(string why)
{
   double money = 0;
   if(HistorySelectByPosition(posTicket))
      for(int i = 0; i < HistoryDealsTotal(); i++)
      {
         ulong d = HistoryDealGetTicket(i);
         money += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_SWAP);
      }
   int s = posDir == 1 ? 0 : 1;
   double r = money / MathMax(riskMoney, 1e-9);
   stN[s]++; stR[s] += r; stM[s] += money; if(money > 0) stW[s]++;
   if(csvH != INVALID_HANDLE)
      FileWrite(csvH, TimeToString(entryTime, TIME_DATE | TIME_MINUTES), TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES),
                posDir == 1 ? "BUY" : "SELL", DoubleToString(money, 2), DoubleToString(r, 3));
   posTicket = 0; posDir = 0;
}

void OnTick()
{
   if(!allowed) return;
   // position closed by the server stop?
   if(posTicket != 0 && !PositionSelectByTicket(posTicket)) Book("stop");
   // stocks: flat at the session end
   datetime se = InpStock ? SessionEnd() : 0;
   if(posTicket != 0 && InpStock && se > 0 && TimeCurrent() >= se - 30)
   {
      trade.PositionClose(posTicket); Book("session end");
   }
   datetime cur = iTime(_Symbol, _Period, 0);
   if(cur == lastBar) return;
   bool first = lastBar == 0;
   lastBar = cur;
   if(first) return;

   // ----- the candle at shift 1 just closed -----
   double c = iClose(_Symbol, _Period, 1);
   double s200 = Buf(hSma200, 0, 1), s5 = Buf(hSma5, 0, 1), s20 = Buf(hSma20, 0, 1);
   double bbU = Buf(hBB, 1, 1), bbL = Buf(hBB, 2, 1);
   double rsi2 = 50, atr = 0, vw = c, vsd = 0;
   if(s200 == EMPTY_VALUE || !CalcRsiAtr(rsi2, atr)) return;
   CalcVwap(vw, vsd);
   bool xL, xS, sigL, sigS;
   bool up = c > s200, dn = c < s200;
   if(InpFam == MR_RSI2)     { sigL = up && rsi2 < InpTh; sigS = dn && rsi2 > 100 - InpTh; xL = c > s5; xS = c < s5; }
   else if(InpFam == MR_BB)  { sigL = up && c < bbL; sigS = dn && c > bbU; xL = c > s20; xS = c < s20; }
   else                      { sigL = up && c < vw - InpTh * vsd; sigS = dn && c > vw + InpTh * vsd; xL = c > vw; xS = c < vw; }

   // manage the open trade on the closed candle
   if(posTicket != 0)
   {
      barsHeld++;
      bool ex = (posDir == 1 && xL) || (posDir == -1 && xS) || barsHeld >= InpTmax;
      if(ex) { trade.PositionClose(posTicket); Book("exit"); }
      return;                                   // like the research: no new entry on the exit candle
   }
   int d = 0;
   if(sigL && InpDir != MR_SHORT) d = 1;
   else if(sigS && InpDir != MR_LONG) d = -1;
   if(d == 0 || atr <= 0) return;
   if(InpStock && se > 0 && TimeCurrent() >= se - 2 * PeriodSeconds(_Period)) return;   // too late in the day

   double px = d == 1 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE); if(tick <= 0) tick = _Point;
   double sl = MathRound((px - d * InpStopAtr * atr) / tick) * tick;
   double loss = 0;
   ENUM_ORDER_TYPE ot = d == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcProfit(ot, _Symbol, 1.0, px, sl, loss) || loss >= 0) return;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vol = MathFloor(AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPct / 100.0 / -loss / step) * step;
   vol = MathMin(mx, MathMax(mn, vol));
   bool ok = d == 1 ? trade.Buy(vol, _Symbol, 0, sl, 0, "MR15") : trade.Sell(vol, _Symbol, 0, sl, 0, "MR15");
   if(!ok || trade.ResultRetcode() != TRADE_RETCODE_DONE) return;
   ulong deal = trade.ResultDeal();
   if(!HistoryDealSelect(deal)) return;
   posTicket = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   if(!PositionSelectByTicket(posTicket)) { posTicket = 0; return; }
   posDir = d; barsHeld = 0; entryTime = TimeCurrent();
   double l2 = 0;
   if(OrderCalcProfit(ot, _Symbol, PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PRICE_OPEN), sl, l2)) riskMoney = -l2;
}

double OnTester() { return stR[0] + stR[1]; }

void OnDeinit(const int reason)
{
   if(posTicket != 0 && PositionSelectByTicket(posTicket)) { trade.PositionClose(posTicket); Book("test end"); }
   int n = stN[0] + stN[1];
   string s = StringFormat("%s fam=%d dir=%d th=%.1f stop=%.1f tmax=%d | trades %d win %.1f%% netR %+.1f money %+.2f | BUY %d win %.1f%% %+.1fR | SELL %d win %.1f%% %+.1fR",
      _Symbol, (int)InpFam, (int)InpDir, InpTh, InpStopAtr, InpTmax, n, n ? 100.0 * (stW[0] + stW[1]) / n : 0, stR[0] + stR[1], stM[0] + stM[1],
      stN[0], stN[0] ? 100.0 * stW[0] / stN[0] : 0, stR[0], stN[1], stN[1] ? 100.0 * stW[1] / stN[1] : 0, stR[1]);
   Print(s);
   int fh = FileOpen(StringFormat("MR15_%s_%d_summary.txt", _Symbol, (int)InpFam), FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(fh != INVALID_HANDLE) { FileWriteString(fh, s + "\n"); FileClose(fh); }
   if(csvH != INVALID_HANDLE) FileClose(csvH);
}
//+------------------------------------------------------------------+
