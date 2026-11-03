// Checks actual pure helper expressions extracted from Pine source, not a copied model.
// This limited syntax adapter is NOT a Pine compiler/broker emulator. TradingView
// compilation, numeric formatting and execution lifecycle still need manual checks.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'pine/bytefx_ut_multi_asset.pine'), 'utf8');
const template = fs.readFileSync(path.join(root, 'examples/order-fill-alert.json.txt'), 'utf8').trim();

function helper(name) {
  const match = source.match(new RegExp(`^${name}\\(([^\\n]*)\\) =>\\r?\\n((?:    [^\\n]*\\r?\\n)+)`, 'm'));
  assert.ok(match, `Missing helper ${name}`);
  const params = match[1].replace(/\b(float|string|int|bool)\s+/g, '');
  const lines = match[2].trim().split(/\r?\n/).map(line => line.trim());
  assert.ok(lines.every(line => !/^(if|else|for|while)\b/.test(line)), 'Adapter only supports straight-line expressions');
  const body = lines.map((line, index) => {
    let js = line.replace(/^(float|string|int|bool)\s+/, 'let ').replace(/:=/g, '=');
    // Only selected helpers use `na` and `math` outside string literals.
    if (['f_num', 'f_int', 'f_quantity', 'f_tighten'].includes(name)) {
      js = js.replace(/\bna\(/g, 'isNa(').replace(/\bna\b/g, 'NaN').replace(/\bmath\./g, 'Math.');
    }
    return (index === lines.length - 1 ? 'return ' : '') + js + ';';
  }).join('\n');
  return `function ${name}(${params}) {\n${body}\n}`;
}

const context = vm.createContext({
  isNa: value => Number.isNaN(value) || value === null || value === undefined,
  str: {
    tostring: value => String(value), // Formatting itself must be checked in Pine.
    replace_all: (value, search, replacement) => value.split(search).join(replacement),
  },
  riskPercent: 0.5,
  exposurePercent: 95,
  brokerExecution: true,
  instanceTag: 'gold15-test-a',
  syminfo: { tickerid: 'TEST:XAUUSD', mintick: 0.01 },
  timeframe: { period: '15' },
});
for (const name of ['f_num', 'f_int', 'f_quantity', 'f_tighten', 'f_quote', 'f_payload']) {
  vm.runInContext(helper(name), context);
}

function payload(event = 'entry', side = 'LONG', target = 150, stopPrice = NaN, targetPrice = NaN) {
  return context.f_payload('test:trade:1', event, side, 1700000000000, 2000, 100, target, stopPrice, targetPrice);
}

test('entry and disabled-target payloads parse as JSON with genuine nulls', () => {
  const result = JSON.parse(payload('entry', 'LONG', NaN));
  assert.equal(result.stop_loss, null);
  assert.equal(result.take_profit, null);
  assert.equal(result.target_ticks, null);
  assert.equal(result.stop_ticks, 100);
  assert.equal(result.tick_size, 0.01);
  assert.equal(result.signal_time_ms, 1700000000000);
  assert.equal(result.reference_price, 2000);
  assert.equal(result.source, 'tradingview');
  assert.equal(result.risk_percent, 0.5);
  assert.equal(result.exit_owner, 'broker_fixed');
});

test('user-controlled instance tags are JSON escaped', () => {
  const original = context.instanceTag;
  try {
    context.instanceTag = 'quotes " slash \\ newline\n tab\t return\r';
    assert.equal(JSON.parse(payload()).instance, context.instanceTag);
    assert.equal(JSON.parse(context.f_quote(context.instanceTag)), context.instanceTag);
  } finally {
    context.instanceTag = original;
  }
});

test('exit events retain trade identity and have different deduplication keys', () => {
  const events = ['entry', 'reverse', 'stop_loss', 'take_profit', 'opposite_signal', 'daily_loss', 'date_end'];
  const messages = events.map(event => JSON.parse(payload(event, 'SHORT', 150, 2001, 1998.5)));
  assert.equal(new Set(messages.map(value => value.event_id)).size, events.length);
  assert.equal(new Set(messages.map(value => value.trade_id)).size, 1);
  assert.equal(messages[2].side, 'SHORT');
  assert.equal(messages[2].stop_loss, 2001);
  assert.equal(messages[2].take_profit, 1998.5);
});

test('alert template matches Pine annotation and renders a reversal without nested placeholders', () => {
  assert.equal(source.split(/\r?\n/)[1], '//@strategy_alert_message ' + template);
  const substitutions = {
    'strategy.order.alert_message': payload('reverse', 'SHORT'),
    'strategy.order.price': '2000.25',
    'strategy.order.action': 'sell',
    'strategy.order.contracts': '7', // close 3 long + open 4 short
    'strategy.market_position': 'short',
    'strategy.market_position_size': '4',
    'strategy.prev_market_position': 'long',
    timenow: '2026-01-01T10:00:00Z',
  };
  const rendered = template.replace(/\{\{([^}]+)\}\}/g, (_, key) => {
    assert.ok(key in substitutions, `Unknown placeholder ${key}`);
    return substitutions[key];
  });
  const result = JSON.parse(rendered);
  assert.equal(result.contracts, 7);
  assert.equal(result.position_size, 4);
  assert.equal(result.context.event, 'reverse');
  assert.equal(result.fill_price, 2000.25);
  assert.ok(!rendered.includes('{{'));
});

test('risk sizing handles contract value, fractional units and unaffordable minimums', () => {
  // 10k equity / 0.5% => 50 account-currency risk; $20 per-unit loss => 2 units.
  assert.equal(context.f_quantity(10000, 20, 2000, 1), 2);
  // Notional cap dominates a tiny risk distance: 9500 / 60000 => 0.158 units.
  assert.equal(context.f_quantity(10000, 100, 60000, 0.001), 0.158);
  // One expensive futures contract must be skipped, never rounded up to one.
  assert.equal(context.f_quantity(10000, 100, 250000, 1), 0);
  assert.equal(context.f_quantity(0, 20, 2000, 1), 0);
  assert.ok(Number.isNaN(context.f_quantity(10000, NaN, 2000, 1)));
  assert.ok(Number.isNaN(context.f_quantity(10000, 0, 2000, 1)));
});

test('sizing invariants over varied equity, quote conversions and quantity steps', () => {
  for (const equity of [100, 10000, 1000000]) {
    for (const conversion of [0.0067, 1, 1.3]) {
      for (const distance of [0.01, 5, 200]) {
        for (const pointValue of [1, 100]) {
          for (const step of [0.001, 1, 1000]) {
            const risk = distance * pointValue * conversion;
            const notional = 300 * pointValue * conversion;
            const qty = context.f_quantity(equity, risk, notional, step);
            assert.ok(qty >= 0);
            assert.ok(qty * risk <= equity * 0.005 + 1e-8);
            assert.ok(qty * notional <= equity * 0.95 + 1e-8);
            assert.ok(Math.abs(qty / step - Math.round(qty / step)) < 1e-7);
          }
        }
      }
    }
  }
});

test('trailing never loosens either side across whipsaws', () => {
  let longStop = 90;
  let shortStop = 110;
  for (const level of [92, 91, 95, 80, 105, 99]) {
    const nextLong = context.f_tighten(longStop, level, true);
    const nextShort = context.f_tighten(shortStop, level, false);
    assert.ok(nextLong >= longStop);
    assert.ok(nextShort <= shortStop);
    longStop = nextLong;
    shortStop = nextShort;
  }
  assert.equal(longStop, 105);
  assert.equal(shortStop, 80);
});

test('critical execution contracts remain explicit in source', () => {
  assert.match(source, /calc_on_every_tick = false/);
  assert.match(source, /calc_on_order_fills = false/);
  assert.match(source, /process_orders_on_close = false/);
  assert.match(source, /\[close\[1\], line\[1\]\]/);
  assert.match(source, /lookahead = barmerge.lookahead_on/);
  assert.match(source, /strategy\.exit\("LX", "Long", loss = lossTicks, profit = profitTicks/);
  assert.match(source, /strategy\.exit\("SX", "Short", loss = lossTicks, profit = profitTicks/);
  assert.match(source, /strategy\.opentrades\.entry_time\(0\) >= pendingTime/);
  assert.doesNotMatch(source, /strategy\.cancel\(/); // retain old protection on rejected reversal
  const orderCalls = source.split(/\r?\n/).filter(line => /strategy\.(entry|exit|close)\(/.test(line));
  assert.equal(orderCalls.length, 8);
  for (const line of orderCalls) assert.match(line, /alert_message = /);
});
