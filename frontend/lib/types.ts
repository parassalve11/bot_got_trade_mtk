export type Side = "LONG" | "SHORT";

export type Signal = {
  at: number;
  source: "mt5_engine" | "tradingview";
  instance: string | null;
  symbol: string | null;
  broker_symbol: string | null;
  timeframe: string | null;
  event: string | null;
  side: Side | null;
  price: number | null;
  status: string;
  reason: string | null;
};

export type OpenPosition = {
  instance: string;
  trade_id: string;
  symbol: string;
  tv_symbol: string;
  side: Side;
  volume: number;
  entry_price: number;
  sl: number;
  tp: number;
  profit: number | null;
  opened_at: number | null;
  ticket: number | null;
  risk_budget: number;
};

export type ClosedPosition = {
  instance: string;
  trade_id: string;
  symbol: string;
  side: Side;
  volume: number;
  entry_price: number;
  exit_price: number | null;
  sl: number;
  tp: number;
  opened_at: number | null;
  closed_at: number | null;
  profit: number | null;
  risk_budget: number;
};

export type Summary = {
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  gross_profit: number;
  gross_loss: number;
  net: number;
};

export type Overview = {
  now: number;
  health: {
    api: boolean;
    worker: boolean;
    mt5: boolean;
    ready: boolean;
    reason: string | null;
    trading_mode: string;
    engine_mode: string;
  };
  entries: {
    paused: boolean;
    safety_hold: { reason: string; at: number } | null;
    trading_enabled: boolean;
    uncertain_operations: number;
  };
  account: {
    login: string;
    server: string;
    currency: string;
    balance: number | null;
    equity: number | null;
    margin_free: number | null;
    floating: number | null;
    snapshot_at: number | null;
  };
  daily: {
    starting_equity: number | null;
    today_pl: number | null;
    loss_limit_percent: number;
    loss_used_percent: number;
    entries: number;
    max_entries: number;
    paused_by_loss: boolean;
  };
  limits: { max_open_positions: number; max_risk_percent: number; max_total_risk_percent: number };
  positions: OpenPosition[];
  signals: Signal[];
  summary: Summary;
};

export type Backtest = {
  period: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  net: number;
  gross_profit: number | null;
  gross_loss: number | null;
  max_drawdown: number | null;
  note: string;
};

export type StrategyMode = "off" | "watch" | "trade";

export type Strategy = {
  instance: string;
  tv_symbol: string;
  broker_symbol: string | null;
  symbol_enabled: boolean;
  timeframe: string;
  settings: {
    sensitivity: number;
    atr_length: number;
    stop_mode: string;
    stop_atr: number;
    target_mode: string;
    reward_ratio: number;
    opposite_mode: string;
    direction: string;
    htf_filter: string;
    risk_percent: number;
  };
  mode: StrategyMode;
  live: Summary & { signals: number };
  backtest: Backtest | null;
};

export type AuditRow = { id: number; at: number; action: string; details: Record<string, unknown> };

export type CloseRequest = {
  id: number;
  instance: string;
  trade_id: string;
  note: string;
  requested_by: string;
  requested_at: number;
  status: string;
  finished_at: number | null;
  error: string | null;
};

export type RiskConfig = {
  risk: Record<string, number>;
  symbols: {
    tv_symbol: string;
    broker_symbol: string;
    enabled: boolean;
    max_spread_points: number;
    max_lot: number;
  }[];
  trading_mode: string;
  engine_mode: string;
};
