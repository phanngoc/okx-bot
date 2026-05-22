"""MA_Grid+DCA strategy ported to the unified engine interface.

Behavior mirrors the legacy strategy.MAGridDCAStrategy:
  - On setup: place N buy limit orders below current price
  - On fill (buy):  place sell limit at (price × 1 + step_pct)
  - On fill (sell): place buy limit at (price × 1 - step_pct)
  - DCA timer:   market BUY (USDT-denominated) at adjusted size
  - Rebalance timer: recompute MA5/MA60; on trend change cancel buys + rebuild
"""

from dataclasses import dataclass, field
from typing import Optional

from strategy_engine.strategy import Strategy
from strategy_engine.types import Fill, Intent, IntentKind, PriceTick, TimerEvent


@dataclass
class MAGridDCAConfig:
    symbol:            str   = "BTC/USDT"
    allocation_usdt:   float = 2000.0
    num_grids:         int   = 20
    range_pct:         float = 5.0           # symmetric (neutral) range
    grid_step_pct:     float = 0.5           # profit margin per filled buy
    dca_interval_sec:  float = 4 * 3600
    dca_amount_usdt:   float = 10.0
    rebalance_sec:     float = 6 * 3600
    ma_short_period:   int   = 5
    ma_long_period:    int   = 60
    ma_threshold_pct:  float = 0.5


class MAGridDCA(Strategy):
    name = "MA_Grid+DCA"

    def __init__(self, cfg: MAGridDCAConfig):
        self.cfg = cfg
        self.current_trend: str = "neutral"
        self.dca_amount: float = cfg.dca_amount_usdt   # adjusted by trend
        self.prices: list[float] = []                  # for MA detection
        self.entry_price: Optional[float] = None

    def timers(self) -> dict[str, float]:
        return {
            "dca": self.cfg.dca_interval_sec,
            "rebalance": self.cfg.rebalance_sec,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_setup(self, tick: PriceTick) -> list[Intent]:
        self.entry_price = tick.price
        upper, lower = self._grid_bounds(self.current_trend)
        return self._build_buy_grid(tick.price, lower) + self._initial_dca()

    def on_price_tick(self, tick: PriceTick) -> list[Intent]:
        # Accumulate closes for MA computation; no orders emitted from ticks
        self.prices.append(tick.price)
        return []

    def on_fill(self, fill: Fill) -> list[Intent]:
        if not fill.tag.startswith("grid"):
            return []   # DCA / rebalance fills don't trigger grid replenishment
        if fill.side == "buy":
            # `fill.amount` here is the NET base credited (post-fee). Use it
            # directly so the SELL replenishment never exceeds available balance.
            sell_price = round(fill.price * (1 + self.cfg.grid_step_pct / 100), 1)
            return [Intent(
                kind=IntentKind.PLACE_LIMIT, symbol=fill.symbol, side="sell",
                amount=fill.amount, price=sell_price, tag="grid_repl_s",
            )]
        # sell fill → place buy below using NET USDT actually received
        # (fill.quote_amount is the post-fee USDT credited, signed positive on sell)
        buy_price  = round(fill.price * (1 - self.cfg.grid_step_pct / 100), 1)
        usdt_avail = abs(fill.quote_amount) if fill.quote_amount else fill.amount * fill.price
        amount     = round(usdt_avail / buy_price, 8)
        return [Intent(
            kind=IntentKind.PLACE_LIMIT, symbol=fill.symbol, side="buy",
            amount=amount, price=buy_price, tag="grid_repl_b",
        )]

    def on_timer(self, timer: TimerEvent) -> list[Intent]:
        if timer.name == "dca":
            return [Intent(
                kind=IntentKind.PLACE_MARKET_BUY, symbol=self.cfg.symbol,
                side="buy", amount=self.dca_amount, tag="dca",
            )]
        if timer.name == "rebalance":
            return self._rebalance()
        return []

    # ------------------------------------------------------------------
    # Persistence hooks
    # ------------------------------------------------------------------

    def feed_history(self, closes: list[float]) -> None:
        self.prices.extend(closes)

    def snapshot(self) -> dict:
        return {
            "current_trend": self.current_trend,
            "dca_amount":    self.dca_amount,
            "entry_price":   self.entry_price,
        }

    def restore(self, snapshot: dict) -> None:
        self.current_trend = snapshot.get("current_trend", "neutral")
        self.dca_amount    = snapshot.get("dca_amount", self.cfg.dca_amount_usdt)
        self.entry_price   = snapshot.get("entry_price")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _grid_bounds(self, trend: str) -> tuple[float, float]:
        if trend == "bull":  return 7.0, 3.0
        if trend == "bear":  return 3.0, 7.0
        return self.cfg.range_pct, self.cfg.range_pct

    def _build_buy_grid(self, mark: float, lower_pct: float) -> list[Intent]:
        low_price = mark * (1 - lower_pct / 100)
        n = self.cfg.num_grids
        per_order_usdt = self.cfg.allocation_usdt / n
        step = (mark - low_price) / n
        intents: list[Intent] = []
        for i in range(n):
            price = round(low_price + i * step, 1)
            amount = round(per_order_usdt / price, 8)
            if amount * price < 1.0:   # min order floor
                continue
            intents.append(Intent(
                kind=IntentKind.PLACE_LIMIT, symbol=self.cfg.symbol, side="buy",
                amount=amount, price=price, tag=f"grid_init{i:02d}",
            ))
        return intents

    def _initial_dca(self) -> list[Intent]:
        """Match legacy behavior: fire DCA on first tick (last_dca_ts starts at 0)."""
        return [Intent(
            kind=IntentKind.PLACE_MARKET_BUY, symbol=self.cfg.symbol,
            side="buy", amount=self.dca_amount, tag="dca_initial",
        )]

    def _detect_trend(self) -> tuple[str, float]:
        c = self.cfg
        if len(self.prices) < c.ma_long_period:
            return "neutral", 0.0
        ma_s = sum(self.prices[-c.ma_short_period:]) / c.ma_short_period
        ma_l = sum(self.prices[-c.ma_long_period:])  / c.ma_long_period
        spread = (ma_s - ma_l) / ma_l * 100
        if spread > c.ma_threshold_pct:  return "bull",    spread
        if spread < -c.ma_threshold_pct: return "bear",    spread
        return "neutral", spread

    def _rebalance(self) -> list[Intent]:
        trend, spread = self._detect_trend()
        if trend == self.current_trend:
            return []   # no change
        self.current_trend = trend
        # Adjust DCA size by trend
        if trend == "bull":   self.dca_amount = self.cfg.dca_amount_usdt * 1.3
        elif trend == "bear": self.dca_amount = self.cfg.dca_amount_usdt * 0.5
        else:                 self.dca_amount = self.cfg.dca_amount_usdt
        upper, lower = self._grid_bounds(trend)
        # Cancel buy-side then rebuild grid at current mark
        # (we don't have current mark here — strategy doesn't see balances,
        # so the executor will receive these intents and the next on_price_tick
        # will provide fresh mark. Use the last seen price.)
        mark = self.prices[-1] if self.prices else (self.entry_price or 0)
        return [
            Intent(kind=IntentKind.CANCEL_ALL_SIDE, symbol=self.cfg.symbol,
                   side="buy", tag="rebalance_cancel"),
        ] + self._build_buy_grid(mark, lower)
