"""AdaptiveStrategy — engine-ABC port of the regime-switching meta-strategy.

Delegates to a child Strategy (MAGridDCA / BBBreakout / MeanRevert / TrailingDCA)
chosen by `RegimeDetector`. On every `check_interval_candles` price ticks, runs
detection on the recent closes and SOFT-switches the child if:
  - recommended strategy differs from current
  - confidence ≥ min_confidence
  - outside cooldown_candles since last switch

Soft switch = cancel all child's open orders, instantiate new child of the
chosen class, run new child's `on_setup`. Portfolio (coin + USDT) stays
in the broker/sim — the new child just sees it through the executor.

NOTE: the "skip switch if current child is profitable" guard from the legacy
AdaptiveStrategy is NOT yet ported — Strategy ABC has no portfolio_value
access. Adding it requires either an Executor reference or a PV hint
field on PriceTick. Left for a follow-up.
"""

from dataclasses import dataclass, field
from typing import Optional

import logging

from regime_detector import Regime, RegimeDetector, RegimeResult
from strategy_engine.strategy import Strategy
from strategy_engine.strategies.bb_breakout  import BBBreakout, BBBreakoutConfig
from strategy_engine.strategies.ma_grid_dca  import MAGridDCA, MAGridDCAConfig
from strategy_engine.strategies.mean_revert  import MeanRevert, MeanRevertConfig
from strategy_engine.strategies.trailing_dca import TrailingDCA, TrailingDCAConfig
from strategy_engine.types import Fill, Intent, IntentKind, PriceTick, TimerEvent

log = logging.getLogger(__name__)


@dataclass
class AdaptiveConfig:
    symbol:                 str   = "BTC/USDT"
    allocation_usdt:        float = 2000.0
    check_interval_candles: int   = 24            # how often to re-detect regime
    min_confidence:         float = 0.7           # min regime confidence to switch
    cooldown_candles:       int   = 48            # don't switch again within this window
    initial_strategy_name:  str   = "Grid+DCA"    # fallback when no warmup data
    skip_if_winning_above_pct: float = 0.0        # don't switch a profitable child


class AdaptiveStrategy(Strategy):
    name = "Adaptive"

    def __init__(self, cfg: AdaptiveConfig):
        self.cfg = cfg
        self.detector = RegimeDetector()
        self.recent_closes: list[float] = []
        self.candle_count = 0
        self.last_check_candle = 0
        self.last_switch_candle = -10**9
        self.current_child: Optional[Strategy] = None
        self.current_strategy_name: str = cfg.initial_strategy_name
        self.current_regime: Optional[Regime] = None
        # Diagnostics
        self.skipped_low_conf = 0
        self.skipped_cooldown = 0
        self.skipped_winning  = 0
        self.switches: list[dict] = []

    # ------------------------------------------------------------------
    # Required by Strategy ABC
    # ------------------------------------------------------------------

    def timers(self) -> dict[str, float]:
        """Return whatever the CURRENT child wants scheduled. Engine calls this
        every tick so swapping children updates the active timer set."""
        if self.current_child is None:
            return {}
        return self.current_child.timers()

    def feed_history(self, closes: list[float]) -> None:
        self.recent_closes.extend(closes)

    def on_setup(self, tick: PriceTick) -> list[Intent]:
        # Pick initial child from regime if we have warmup, else use config default
        if len(self.recent_closes) >= 50:
            result = self._detect()
            self.current_strategy_name = result.recommended_strategy
            self.current_regime        = result.regime
            log.info(f"[ADAPTIVE] initial regime: {result.regime.value} "
                     f"(conf {result.confidence:.0%}) → {result.recommended_strategy}")
        self.current_child = self._build_child(self.current_strategy_name)
        return self.current_child.on_setup(tick)

    def on_price_tick(self, tick: PriceTick) -> list[Intent]:
        self.recent_closes.append(tick.price)
        self.candle_count += 1
        intents = list(self.current_child.on_price_tick(tick)) if self.current_child else []

        # Periodic regime re-check
        if (self.candle_count - self.last_check_candle >= self.cfg.check_interval_candles
                and len(self.recent_closes) >= 50):
            self.last_check_candle = self.candle_count
            new = self._detect()
            if new.recommended_strategy != self.current_strategy_name:
                if new.confidence < self.cfg.min_confidence:
                    self.skipped_low_conf += 1
                elif self.candle_count - self.last_switch_candle < self.cfg.cooldown_candles:
                    self.skipped_cooldown += 1
                elif self._child_is_winning(tick):
                    # Don't kill a winner — current child has open profit
                    self.skipped_winning += 1
                    log.info(f"[ADAPTIVE] skip switch — {self.current_strategy_name} "
                             f"is winning ({(tick.pv_hint - self.cfg.allocation_usdt) / self.cfg.allocation_usdt * 100:+.2f}%)")
                else:
                    intents.extend(self._switch_to(new, tick))
        return intents

    def _child_is_winning(self, tick: PriceTick) -> bool:
        """True iff current child's PnL (via engine-provided pv_hint) exceeds
        the configured threshold. pv_hint=0 means Engine didn't populate it
        (e.g. live API error) — treat as "no info" → don't skip."""
        if tick.pv_hint <= 0:
            return False
        roi_pct = (tick.pv_hint - self.cfg.allocation_usdt) / self.cfg.allocation_usdt * 100
        return roi_pct > self.cfg.skip_if_winning_above_pct

    def on_fill(self, fill: Fill) -> list[Intent]:
        if self.current_child is None:
            return []
        return list(self.current_child.on_fill(fill))

    def on_timer(self, timer: TimerEvent) -> list[Intent]:
        if self.current_child is None:
            return []
        return list(self.current_child.on_timer(timer))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _detect(self) -> RegimeResult:
        """Wrap close prices in OHLCV-shaped tuples so the existing detector works."""
        window = self.recent_closes[-60:]
        fake_candles = [[i * 3600_000, p, p, p, p, 0.0] for i, p in enumerate(window)]
        return self.detector.detect(fake_candles)

    def _build_child(self, name: str) -> Strategy:
        sym, alloc = self.cfg.symbol, self.cfg.allocation_usdt
        if name in ("Grid+DCA", "MA_Grid+DCA"):
            child = MAGridDCA(MAGridDCAConfig(symbol=sym, allocation_usdt=alloc))
        elif name == "BB_Breakout":
            child = BBBreakout(BBBreakoutConfig(symbol=sym, allocation_usdt=alloc))
        elif name == "MeanRevert":
            child = MeanRevert(MeanRevertConfig(symbol=sym, allocation_usdt=alloc))
        elif name == "TrailingDCA":
            child = TrailingDCA(TrailingDCAConfig(symbol=sym, allocation_usdt=alloc))
        else:
            log.warning(f"[ADAPTIVE] unknown strategy '{name}', falling back to MAGridDCA")
            child = MAGridDCA(MAGridDCAConfig(symbol=sym, allocation_usdt=alloc))
        # Pre-feed history so indicator-based children have warmup on day-1
        if self.recent_closes:
            child.feed_history(self.recent_closes)
        return child

    def _switch_to(self, new: RegimeResult, tick: PriceTick) -> list[Intent]:
        """Soft switch: cancel existing orders, swap child, run new on_setup."""
        old = self.current_strategy_name
        log.info(f"[ADAPTIVE] switch {old} → {new.recommended_strategy}  "
                 f"(regime={new.regime.value}, conf={new.confidence:.0%}, "
                 f"price=${tick.price:,.2f})")
        intents: list[Intent] = [Intent(
            kind=IntentKind.CANCEL_ALL_SIDE, symbol=self.cfg.symbol,
            side=None, tag="adaptive_cancel",
        )]
        new_child = self._build_child(new.recommended_strategy)
        self.current_child         = new_child
        self.current_strategy_name = new.recommended_strategy
        self.current_regime        = new.regime
        self.last_switch_candle    = self.candle_count
        self.switches.append({
            "candle": self.candle_count, "from": old, "to": new.recommended_strategy,
            "regime": new.regime.value, "price": tick.price,
        })
        intents.extend(new_child.on_setup(tick))
        return intents
