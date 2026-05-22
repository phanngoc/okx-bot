"""Unified strategy engine: separate Decision (logic) from Execution (broker).

Architecture:
  Strategy(ABC).on_event(event) → list[Intent]      ← pure logic
  Executor(ABC).execute(intent) → Order             ← broker I/O
  Engine(strategy, executor).step(tick)             ← drives the loop

Implementations:
  SimExecutor — synthetic order book for backtests
  OkxLiveExecutor — wraps OkxExecutor for live trading

Strategies use this single interface for both backtest and live, eliminating
the previous duplication between arena's `MAGridDCAStrategy.tick()` and
live's `LiveMAGrid.poll_fills + replenish + do_dca + rebalance_check`.
"""

from strategy_engine.types import (
    Intent, IntentKind,
    Fill, PriceTick, TimerEvent, Event,
    Order, OrderStatus,
)
from strategy_engine.strategy import Strategy
from strategy_engine.executor import Executor
from strategy_engine.sim_executor import SimExecutor
from strategy_engine.engine import Engine

__all__ = [
    "Intent", "IntentKind",
    "Fill", "PriceTick", "TimerEvent", "Event",
    "Order", "OrderStatus",
    "Strategy",
    "Executor",
    "SimExecutor",
    "Engine",
]
