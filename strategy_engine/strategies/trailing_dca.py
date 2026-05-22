"""3Commas-style Trailing DCA — Strategy ABC port.

Base order on setup, safety orders at deeper drawdowns (-3, -6, -12, -20, -30%),
trailing take-profit (lock when +2% above avg, exit if drops 0.8% from peak).
"""

from dataclasses import dataclass, field

from strategy_engine.strategy import Strategy
from strategy_engine.types import Fill, Intent, IntentKind, PriceTick, TimerEvent


@dataclass
class TrailingDCAConfig:
    symbol:            str   = "BTC/USDT"
    allocation_usdt:   float = 2000.0
    base_order_pct:    float = 10.0                     # % alloc for base buy
    safety_deviations: list  = field(default_factory=lambda: [3, 6, 12, 20, 30])
    safety_scale:      float = 1.5                      # 1.5^i multiplier per safety order
    tp_pct:            float = 2.0                      # arm trailing once +2% above avg
    trailing_pct:      float = 0.8                      # exit if -0.8% from peak


class TrailingDCA(Strategy):
    name = "TrailingDCA"

    def __init__(self, cfg: TrailingDCAConfig):
        self.cfg = cfg
        self.entry_price: float = 0.0          # first base buy reference for safety triggers
        self.avg_price: float = 0.0
        self.total_qty: float = 0.0
        self.total_cost_usdt: float = 0.0
        self.safety_filled: list[bool] = [False] * len(cfg.safety_deviations)
        self.trailing_active: bool = False
        self.trailing_peak: float = 0.0

    def timers(self) -> dict[str, float]:
        return {}

    def on_setup(self, tick: PriceTick) -> list[Intent]:
        self.entry_price = tick.price
        base_usdt = self.cfg.allocation_usdt * (self.cfg.base_order_pct / 100)
        return [Intent(
            kind=IntentKind.PLACE_MARKET_BUY, symbol=self.cfg.symbol,
            side="buy", amount=base_usdt, tag="td_base",
        )]

    def on_timer(self, timer: TimerEvent) -> list[Intent]:
        return []

    def on_fill(self, fill: Fill) -> list[Intent]:
        if fill.side == "buy":
            cost = abs(fill.quote_amount) if fill.quote_amount else fill.amount * fill.price
            self.total_qty += fill.amount
            self.total_cost_usdt += cost
            self.avg_price = self.total_cost_usdt / self.total_qty if self.total_qty > 0 else 0
        elif fill.side == "sell" and fill.tag == "td_exit":
            # Full exit — reset
            self.entry_price = 0.0
            self.avg_price = 0.0
            self.total_qty = 0.0
            self.total_cost_usdt = 0.0
            self.safety_filled = [False] * len(self.cfg.safety_deviations)
            self.trailing_active = False
            self.trailing_peak = 0.0
        return []

    def on_price_tick(self, tick: PriceTick) -> list[Intent]:
        if self.entry_price == 0:    # before setup ran
            return []

        intents: list[Intent] = []

        # Safety orders
        for i, dev_pct in enumerate(self.cfg.safety_deviations):
            if self.safety_filled[i]:
                continue
            trigger = self.entry_price * (1 - dev_pct / 100)
            if tick.price <= trigger:
                scale = self.cfg.safety_scale ** i
                amt_usdt = self.cfg.allocation_usdt * (self.cfg.base_order_pct / 100) * scale
                intents.append(Intent(
                    kind=IntentKind.PLACE_MARKET_BUY, symbol=self.cfg.symbol,
                    side="buy", amount=amt_usdt, tag=f"td_safety{i}",
                ))
                self.safety_filled[i] = True

        # Trailing take-profit
        if self.total_qty > 0 and self.avg_price > 0:
            profit_pct = (tick.price - self.avg_price) / self.avg_price * 100
            if profit_pct >= self.cfg.tp_pct:
                if not self.trailing_active:
                    self.trailing_active = True
                    self.trailing_peak = tick.price
                if tick.price > self.trailing_peak:
                    self.trailing_peak = tick.price
                drop_pct = (self.trailing_peak - tick.price) / self.trailing_peak * 100
                if drop_pct >= self.cfg.trailing_pct:
                    intents.append(Intent(
                        kind=IntentKind.PLACE_MARKET_SELL, symbol=self.cfg.symbol,
                        side="sell", amount=self.total_qty, tag="td_exit",
                    ))
            else:
                # Disarm trailing if we drop below TP threshold without exit
                self.trailing_active = False
                self.trailing_peak = 0.0

        return intents
