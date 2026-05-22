"""Engine: drives a Strategy + Executor pair through time.

For backtest: caller feeds PriceTick from each candle, calls step().
For live:     caller polls the broker at fixed interval, calls step().

Same code path either way → no logic drift between backtest and live.
"""

from dataclasses import dataclass, field, replace
from typing import Optional

from strategy_engine.executor import Executor
from strategy_engine.strategy import Strategy
from strategy_engine.types import Event, Fill, Intent, PriceTick, TimerEvent


@dataclass
class Engine:
    strategy: Strategy
    executor: Executor
    setup_done: bool = False
    last_fired: dict[str, float] = field(default_factory=dict)
    fills_total: int = 0
    intents_total: int = 0

    def _execute_intents(self, intents: list[Intent]) -> None:
        for intent in intents:
            self.intents_total += 1
            try:
                self.executor.execute(intent)
            except Exception as e:
                # Don't kill the engine on a single bad intent — log + skip
                import logging
                logging.getLogger(__name__).error(f"[ENGINE] execute({intent.kind}) failed: {e}")

    def step(self, tick: PriceTick) -> list[Fill]:
        """Advance one tick. Returns fills that happened (for logging/persistence).

        Order of operations:
          1. Feed tick into executor (sim uses for fill detection)
          2. on_setup if first tick
          3. on_price_tick
          4. Check + fire any due timers → on_timer
          5. Execute all emitted intents
          6. Poll executor for events (fills) → on_fill → more intents → execute
        """
        # Sim-only: hand the tick to executor so it knows current price
        if hasattr(self.executor, "feed_tick"):
            self.executor.feed_tick(tick)

        # Populate pv_hint so strategies can read current equity without
        # holding an executor reference. Skip if executor errors (live mode
        # may have transient API failures — strategies fall back to 0.0).
        try:
            pv = self.executor.portfolio_value(tick.symbol, tick.price)
            if pv > 0 and tick.pv_hint == 0.0:
                tick = replace(tick, pv_hint=pv)
        except Exception:
            pass  # leave pv_hint at 0.0

        intents: list[Intent] = []

        if not self.setup_done:
            intents.extend(self.strategy.on_setup(tick))
            self.setup_done = True
            # Initialize all timers to now (so they fire after interval, not immediately)
            for name in self.strategy.timers():
                self.last_fired[name] = tick.ts

        intents.extend(self.strategy.on_price_tick(tick))

        # Timers
        for name, interval in self.strategy.timers().items():
            last = self.last_fired.get(name, 0.0)
            if tick.ts - last >= interval:
                self.last_fired[name] = tick.ts
                intents.extend(self.strategy.on_timer(TimerEvent(name=name, ts=tick.ts)))

        # Execute all intents in order
        self._execute_intents(intents)

        # Process events emitted by executor (fills, etc.)
        events = self.executor.poll_events(tick.ts)
        fills: list[Fill] = []
        for ev in events:
            if isinstance(ev, Fill):
                self.fills_total += 1
                fills.append(ev)
                # Strategy reacts to the fill — may emit replenishment intents
                followups = self.strategy.on_fill(ev)
                if followups:
                    self._execute_intents(followups)

        return fills
