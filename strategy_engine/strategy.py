"""Strategy ABC: pure decision logic, no broker I/O."""

from abc import ABC, abstractmethod
from typing import Optional

from strategy_engine.types import Fill, Intent, PriceTick, TimerEvent


class Strategy(ABC):
    """Subclass to define a trading strategy.

    Methods emit `Intent` lists. The Engine forwards them to an Executor
    which decides HOW to execute (sim fills, real OKX orders, etc).
    """

    name: str = "strategy"

    @abstractmethod
    def on_setup(self, tick: PriceTick) -> list[Intent]:
        """Called once at the start of a session. Emit initial orders."""

    @abstractmethod
    def on_price_tick(self, tick: PriceTick) -> list[Intent]:
        """Called on every price observation.
        For most strategies this is a no-op (logic triggered by fills/timers)."""

    @abstractmethod
    def on_fill(self, fill: Fill) -> list[Intent]:
        """Called when an order is filled. Typical use: place a follow-up."""

    @abstractmethod
    def on_timer(self, timer: TimerEvent) -> list[Intent]:
        """Called when a scheduled timer fires (e.g. DCA cadence)."""

    @abstractmethod
    def timers(self) -> dict[str, float]:
        """Return {timer_name: interval_seconds}. Engine schedules these."""

    # Optional snapshot/restore for state recovery
    def snapshot(self) -> dict:
        """Serialize strategy-internal state. Override if state matters."""
        return {}

    def restore(self, snapshot: dict) -> None:
        """Restore from a previous snapshot."""
        pass

    # Optional: warmup
    def feed_history(self, closes: list[float]) -> None:
        """Pre-feed historical closes so indicators don't need in-period warmup."""
        pass
