"""Mean reversion: buy oversold, sell overbought — Strategy ABC port.

Only active in ranging markets (ADX proxy < 25).
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from strategy_engine.strategy import Strategy
from strategy_engine.types import Fill, Intent, IntentKind, PriceTick, TimerEvent


@dataclass
class MeanRevertConfig:
    symbol:          str   = "BTC/USDT"
    allocation_usdt: float = 2000.0
    bb_period:       int   = 20
    rsi_period:      int   = 14
    rsi_buy:         float = 30
    rsi_sell:        float = 70
    position_pct:    float = 20.0
    max_positions:   int   = 5


class MeanRevert(Strategy):
    name = "MeanRevert"

    def __init__(self, cfg: MeanRevertConfig):
        self.cfg = cfg
        self.prices: list[float] = []
        self.open_positions: int = 0
        self.total_qty: float = 0.0      # base accumulated in open positions

    def timers(self) -> dict[str, float]:
        return {}

    def feed_history(self, closes: list[float]) -> None:
        self.prices.extend(closes)

    def on_setup(self, tick: PriceTick) -> list[Intent]:
        return []

    def on_timer(self, timer: TimerEvent) -> list[Intent]:
        return []

    def on_fill(self, fill: Fill) -> list[Intent]:
        if fill.side == "buy" and fill.tag == "mr_buy":
            self.open_positions += 1
            self.total_qty += fill.amount
        elif fill.side == "sell" and fill.tag.startswith("mr_sell"):
            self.open_positions = 0
            self.total_qty = 0.0
        return []

    def on_price_tick(self, tick: PriceTick) -> list[Intent]:
        self.prices.append(tick.price)
        warmup_needed = max(self.cfg.bb_period, self.cfg.rsi_period + 1) + 20
        if len(self.prices) < warmup_needed:
            return []

        rsi = self._rsi()
        bb  = self._bollinger()
        adx = self._adx_proxy()

        # Only trade in ranging market
        if adx > 25:
            return []

        intents: list[Intent] = []

        # Buy oversold
        if (rsi < self.cfg.rsi_buy and tick.price <= bb["lower"]
                and self.open_positions < self.cfg.max_positions):
            buy_usdt = self.cfg.allocation_usdt * (self.cfg.position_pct / 100)
            intents.append(Intent(
                kind=IntentKind.PLACE_MARKET_BUY, symbol=self.cfg.symbol,
                side="buy", amount=buy_usdt, tag="mr_buy",
            ))

        # Sell overbought / mean revert
        if self.total_qty > 0:
            if rsi > self.cfg.rsi_sell or tick.price >= bb["upper"]:
                intents.append(Intent(
                    kind=IntentKind.PLACE_MARKET_SELL, symbol=self.cfg.symbol,
                    side="sell", amount=self.total_qty, tag="mr_sell",
                ))
            elif tick.price < bb["lower"] * 0.97:
                # Stop loss: bail half if price keeps falling
                intents.append(Intent(
                    kind=IntentKind.PLACE_MARKET_SELL, symbol=self.cfg.symbol,
                    side="sell", amount=self.total_qty * 0.5, tag="mr_sell_stop",
                ))

        return intents

    # ------------------------------------------------------------------

    def _bollinger(self) -> dict:
        data = self.prices[-self.cfg.bb_period:]
        mid = float(np.mean(data))
        std = float(np.std(data))
        return {"upper": mid + 2 * std, "middle": mid, "lower": mid - 2 * std}

    def _rsi(self) -> float:
        closes = self.prices[-(self.cfg.rsi_period + 1):]
        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))
        if avg_loss == 0:
            return 100.0
        return 100 - (100 / (1 + avg_gain / avg_loss))

    def _adx_proxy(self) -> float:
        """Simplified trend strength via 20-candle range/mean ratio."""
        if len(self.prices) < 20:
            return 50
        recent = self.prices[-20:]
        rng = (max(recent) - min(recent)) / float(np.mean(recent)) * 100
        if rng > 5:   return 40
        if rng > 3:   return 25
        return 15
