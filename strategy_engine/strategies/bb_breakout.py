"""Bollinger squeeze breakout — ported to Strategy ABC.

Behavior:
  - Detect BB squeeze (width < threshold) on every tick
  - Buy on breakout above upper band with RSI > 50, only when in squeeze
  - Stop-loss at -3%; partial TP when RSI > 75 at upper band;
    full exit on close below middle band
  - No timers
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from strategy_engine.strategy import Strategy
from strategy_engine.types import Fill, Intent, IntentKind, PriceTick, TimerEvent


@dataclass
class BBBreakoutConfig:
    symbol:            str   = "BTC/USDT"
    allocation_usdt:   float = 2000.0
    bb_period:         int   = 20
    bb_std:            float = 2.0
    squeeze_threshold: float = 2.0     # BB width % below which we call squeeze
    rsi_period:        int   = 14
    position_pct:      float = 25.0    # % of allocation per breakout
    stop_loss_pct:     float = 3.0


class BBBreakout(Strategy):
    name = "BB_Breakout"

    def __init__(self, cfg: BBBreakoutConfig):
        self.cfg = cfg
        self.prices: list[float] = []
        self.in_squeeze: bool = False
        self.position_entry: float = 0.0
        self.position_qty:   float = 0.0
        self.partial_taken:  bool  = False

    def timers(self) -> dict[str, float]:
        return {}

    def feed_history(self, closes: list[float]) -> None:
        self.prices.extend(closes)

    # ------------------------------------------------------------------

    def on_setup(self, tick: PriceTick) -> list[Intent]:
        return []

    def on_timer(self, timer: TimerEvent) -> list[Intent]:
        return []

    def on_fill(self, fill: Fill) -> list[Intent]:
        if fill.side == "buy" and fill.tag == "bb_entry":
            self.position_entry = fill.price
            self.position_qty   = fill.amount
            self.partial_taken  = False
            self.in_squeeze     = False    # consumed
        elif fill.side == "sell":
            if fill.tag in ("bb_stop", "bb_exit"):
                self.position_entry = 0.0
                self.position_qty   = 0.0
                self.partial_taken  = False
            elif fill.tag == "bb_partial":
                # Keep position, just remove partial qty
                self.position_qty = max(0.0, self.position_qty - fill.amount)
                self.partial_taken = True
        return []

    def on_price_tick(self, tick: PriceTick) -> list[Intent]:
        self.prices.append(tick.price)
        if len(self.prices) < self.cfg.bb_period + self.cfg.rsi_period:
            return []

        bb = self._bollinger()
        rsi = self._rsi()

        # Track squeeze
        if bb["width_pct"] < self.cfg.squeeze_threshold:
            self.in_squeeze = True
        elif bb["width_pct"] > self.cfg.squeeze_threshold * 1.5:
            self.in_squeeze = False

        intents: list[Intent] = []

        # Breakout entry (only if no position)
        if self.in_squeeze and self.position_qty == 0:
            if tick.price > bb["upper"] and rsi > 50:
                buy_usdt = self.cfg.allocation_usdt * (self.cfg.position_pct / 100)
                intents.append(Intent(
                    kind=IntentKind.PLACE_MARKET_BUY, symbol=self.cfg.symbol,
                    side="buy", amount=buy_usdt, tag="bb_entry",
                ))
                return intents

        # Position management
        if self.position_qty > 0:
            loss_pct = (self.position_entry - tick.price) / self.position_entry * 100
            if loss_pct >= self.cfg.stop_loss_pct:
                intents.append(Intent(
                    kind=IntentKind.PLACE_MARKET_SELL, symbol=self.cfg.symbol,
                    side="sell", amount=self.position_qty, tag="bb_stop",
                ))
            elif tick.price > bb["upper"] and rsi > 75 and not self.partial_taken:
                partial = self.position_qty * 0.60
                intents.append(Intent(
                    kind=IntentKind.PLACE_MARKET_SELL, symbol=self.cfg.symbol,
                    side="sell", amount=partial, tag="bb_partial",
                ))
            elif tick.price < bb["middle"]:
                intents.append(Intent(
                    kind=IntentKind.PLACE_MARKET_SELL, symbol=self.cfg.symbol,
                    side="sell", amount=self.position_qty, tag="bb_exit",
                ))

        return intents

    # ------------------------------------------------------------------

    def _bollinger(self) -> dict:
        data = self.prices[-self.cfg.bb_period:]
        mid = float(np.mean(data))
        std = float(np.std(data))
        upper = mid + self.cfg.bb_std * std
        lower = mid - self.cfg.bb_std * std
        return {"upper": upper, "middle": mid, "lower": lower,
                "width_pct": (upper - lower) / mid * 100}

    def _rsi(self) -> float:
        closes = self.prices[-(self.cfg.rsi_period + 1):]
        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
