"""Executor ABC: broker I/O. Translates Intents into actual orders."""

from abc import ABC, abstractmethod
from typing import Optional

from strategy_engine.types import Event, Intent, Order


class Executor(ABC):
    """Subclass to wrap a specific broker (or simulator)."""

    @abstractmethod
    def execute(self, intent: Intent) -> Optional[Order]:
        """Translate an intent into an order (or cancellation).
        Returns the placed Order, or None for CANCEL_* operations."""

    @abstractmethod
    def poll_events(self, tick_ts: float) -> list[Event]:
        """Pull all events that happened since the last poll.
        Sim: scan order book for limit fills against the latest tick.
        Live: diff open orders + fetch_my_trades since last call."""

    @abstractmethod
    def open_orders(self, symbol: str) -> list[Order]:
        """Current resting orders for a symbol."""

    @abstractmethod
    def balance(self, symbol: str) -> dict:
        """Return {'base': float, 'quote': float, 'base_value_usdt': float}.
        Used by the engine for equity tracking."""

    @abstractmethod
    def portfolio_value(self, symbol: str, mark_price: float) -> float:
        """Total equity in quote currency (USDT). For PnL calc."""
