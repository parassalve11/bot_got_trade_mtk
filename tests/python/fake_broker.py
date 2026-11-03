from dataclasses import replace

from app.trading.broker import Account, Position, Symbol, Tick
from app.trading.errors import Retryable


class FakeBroker:
    """Deterministic broker simulator. Used only by tests, never selectable in production."""

    def __init__(self, clock):
        self.clock = clock
        self.account_value = Account(123456, "Test-Demo", 10000, 10000, 0, True)
        self.symbols = {
            "EURUSD": Symbol("EURUSD", 0.00001, 0.00001, 5, 0.01, 100, 0.01, 5, 0, 1, 2, 4),
            "GBPUSD": Symbol("GBPUSD", 0.00001, 0.00001, 5, 0.01, 100, 0.01, 5, 0, 1, 2, 4),
        }
        self.quotes = {"EURUSD": (1.10000, 1.10002), "GBPUSD": (1.20000, 1.20002)}
        self.live = []
        self.history = []
        self.pending = []
        self.sent = []
        self.checked = []
        self.offline = False
        self.fail_positions = False
        self.next_behaviors = []
        self.check_retcode = 0
        self.slippage = 0
        self.next_ticket = 1000
        self.tick_age = 0

    def connect(self):
        if self.offline:
            raise Retryable("mt5_disconnected")

    def shutdown(self):
        pass

    def account(self):
        self.connect()
        return self.account_value

    def symbol(self, name):
        return self.symbols[name]

    def tick(self, name):
        return Tick(*self.quotes[name], self.clock() - self.tick_age)

    def positions(self):
        self.connect()
        if self.fail_positions:
            raise Retryable("positions_unavailable")
        return list(self.live)

    def orders(self):
        return list(self.pending)

    def deals(self, since):
        return [d for d in self.history if d["time"] >= since]

    def position_deals(self, identifier):
        return [d for d in self.history if d["position_id"] == identifier]

    def profit(self, side, symbol, volume, entry, exit):
        return (exit - entry) * (1 if side == "LONG" else -1) * 100000 * volume

    def margin(self, side, symbol, volume, price):
        return volume * 1000

    def check(self, request):
        assert "_meta" not in request
        self.checked.append(request.copy())
        return {"retcode": self.check_retcode, "comment": "test", "margin": 0, "margin_free": 10000}

    def add_deal(self, *, identifier, order, side, entry, volume, price, symbol, magic, comment):
        self.next_ticket += 1
        deal = dict(
            ticket=self.next_ticket,
            order=order,
            position_id=identifier,
            type=0 if side == "LONG" else 1,
            entry=entry,
            volume=volume,
            price=price,
            symbol=symbol,
            magic=magic,
            comment=comment,
            time=int(self.clock()),
            time_msc=int(self.clock() * 1000),
        )
        self.history.append(deal)
        return deal

    def send(self, request):
        self.sent.append(request.copy())
        behavior = self.next_behaviors.pop(0) if self.next_behaviors else "ok"
        if behavior == "reject":
            return {"retcode": 10019, "order": 0, "deal": 0, "volume": 0, "price": 0}
        if behavior == "timeout_no_fill":
            return {"retcode": 10012, "order": 0, "deal": 0, "volume": 0, "price": 0}
        if request["action"] == 6:
            pos = next(p for p in self.live if p.ticket == request["position"])
            self.live[self.live.index(pos)] = replace(pos, sl=request["sl"], tp=request["tp"])
            result = dict(retcode=10009, order=0, deal=0, volume=0, price=0)
        elif request.get("position"):
            pos = next(p for p in self.live if p.ticket == request["position"])
            volume = request["volume"] / 2 if behavior == "partial" else request["volume"]
            if volume >= pos.volume:
                self.live.remove(pos)
            else:
                self.live[self.live.index(pos)] = replace(pos, volume=pos.volume - volume)
            self.next_ticket += 1
            order = self.next_ticket
            deal = self.add_deal(
                identifier=pos.identifier,
                order=order,
                side="SHORT" if pos.side == "LONG" else "LONG",
                entry=1,
                volume=volume,
                price=request["price"],
                symbol=pos.symbol,
                magic=request["magic"],
                comment=request["comment"],
            )
            result = dict(
                retcode=10010 if behavior == "partial" else 10009,
                order=order,
                deal=deal["ticket"],
                volume=volume,
                price=request["price"],
            )
        else:
            self.next_ticket += 1
            ticket = self.next_ticket
            volume = request["volume"] / 2 if behavior == "partial" else request["volume"]
            side = "LONG" if request["type"] == 0 else "SHORT"
            price = request["price"] + self.slippage * (1 if side == "LONG" else -1)
            pos = Position(
                ticket,
                ticket,
                request["symbol"],
                side,
                volume,
                price,
                0 if behavior == "missing_protection" else request["sl"],
                request["tp"],
                request["magic"],
                request["comment"],
            )
            self.live.append(pos)
            deal = self.add_deal(
                identifier=ticket,
                order=ticket,
                side=side,
                entry=0,
                volume=volume,
                price=price,
                symbol=pos.symbol,
                magic=pos.magic,
                comment=pos.comment,
            )
            result = dict(
                retcode=10010 if behavior == "partial" else 10009,
                order=ticket,
                deal=deal["ticket"],
                volume=volume,
                price=price,
            )
        if behavior == "timeout_after_fill":
            return {"retcode": 10012, "order": 0, "deal": 0, "volume": 0, "price": 0}
        if behavior == "exception_after_fill":
            raise OSError("test transport lost response")
        if behavior == "none_after_fill":
            return None
        return result

    def broker_exit(self, position, *, magic=None):
        self.live.remove(position)
        self.add_deal(
            identifier=position.identifier,
            order=99999,
            side="SHORT" if position.side == "LONG" else "LONG",
            entry=1,
            volume=position.volume,
            price=position.sl,
            symbol=position.symbol,
            magic=position.magic if magic is None else magic,
            comment="[sl]",
        )
