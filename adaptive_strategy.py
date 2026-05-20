"""Adaptive (Hybrid) Strategy — dynamically switches sub-strategy based on regime.

Every check_interval candles, runs RegimeDetector on recent history.
If recommended strategy differs from current → liquidate to cash (paying taker
fee + slippage) and re-initialize with the new sub-strategy.

This is the "Hybrid" entry in arena: a real strategy that competes head-to-head
against the static strategies.
"""

from dataclasses import dataclass, field

from config import DCAConfig, FeeConfig, GridConfig
from regime_detector import RegimeDetector, RegimeResult
from strategies import BollingerBreakout, MeanReversion, TrailingDCA
from strategy import GridDCAStrategy


@dataclass
class SwitchEvent:
    hour: int
    from_strategy: str
    to_strategy: str
    regime: str
    price: float
    pv_at_switch: float
    coin_sold: float
    switch_cost: float  # fee + slippage


class AdaptiveStrategy:
    """Wraps the 4 sub-strategies. Switches between them based on regime detection."""

    NAME = "Adaptive"

    def __init__(self,
                 entry_price: float,
                 budget: float,
                 fees: FeeConfig,
                 initial_regime: RegimeResult,
                 check_interval: int = 24,
                 warmup_prices: list = None,
                 min_confidence: float = 0.7,
                 cooldown_hours: int = 48,
                 skip_if_winning_above_pct: float = 0.0):
        self.budget       = budget
        self.total_budget = budget
        self.fees         = fees
        self.check_interval = check_interval
        self.min_confidence = min_confidence
        self.cooldown_hours = cooldown_hours
        self.skip_if_winning_above_pct = skip_if_winning_above_pct
        self.detector     = RegimeDetector()
        self.candles_seen = 0
        self.last_switch_hour = -10**9  # no recent switch

        # Lifetime accumulators (sum across all retired sub-strategies)
        self.lifetime_trades    = 0
        self.lifetime_fees      = 0.0
        self.lifetime_slippage  = 0.0
        self.switches: list[SwitchEvent] = []
        # Skip counters for transparency
        self.skipped_cooldown    = 0
        self.skipped_low_conf    = 0
        self.skipped_winning     = 0

        # Initialize the first sub-strategy with warmup price history
        # sim_ts0 is set on first tick — until then use 0 as DCA epoch
        self.sim_ts = 0.0
        self.current_name   = initial_regime.recommended_strategy
        self.current_regime = initial_regime.regime
        self._active_kind, self._active = self._create(
            self.current_name, entry_price, budget, warmup_prices or [], ts=0.0)

    # ------------------------------------------------------------------
    # Sub-strategy factory
    # ------------------------------------------------------------------

    def _create(self, name: str, entry_price: float, budget: float,
                warmup_prices: list = None, ts: float = 0.0):
        """Return (kind, instance). kind ∈ {'grid', 'base'}.
        warmup_prices: recent price history to pre-populate the strategy's prices buffer
        ts: current simulation timestamp (used for Grid+DCA last_dca_time reset)
        """
        warmup_prices = warmup_prices or []
        if name == "Grid+DCA":
            s = GridDCAStrategy(
                entry_price=entry_price,
                grid_cfg=GridConfig(),
                dca_cfg=DCAConfig(),
                total_budget=budget,
                fees=self.fees,
            )
            s.initialize()
            # Override real-time DCA epoch with simulation timestamp
            # (so backtest DCA fires at the simulated cadence, not real-time)
            s.last_dca_time = ts
            return ("grid", s)
        if name == "TrailingDCA":
            s = TrailingDCA(budget, self.fees)
            return ("base", s)
        if name == "BB_Breakout":
            s = BollingerBreakout(budget, self.fees)
            s.prices = list(warmup_prices[-100:])
            return ("base", s)
        if name == "MeanRevert":
            s = MeanReversion(budget, self.fees)
            s.prices = list(warmup_prices[-100:])
            return ("base", s)
        return ("base", TrailingDCA(budget, self.fees))

    # ------------------------------------------------------------------
    # Main tick interface
    # ------------------------------------------------------------------

    def tick(self, candle: list, ts: float, history_candles: list) -> None:
        """Process one hourly candle.

        candle = [ts, open, high, low, close, volume]
        history_candles = all candles up to and including this one (for regime detection)
        """
        self.candles_seen += 1
        # First-tick: if initial Grid+DCA was created with ts=0, sync its DCA clock
        # to the actual simulation start time
        if self.candles_seen == 1 and self._active_kind == "grid" and self._active.last_dca_time == 0.0:
            self._active.last_dca_time = ts
        self.sim_ts = ts

        # Periodic regime check
        if (self.candles_seen > 0
                and self.candles_seen % self.check_interval == 0
                and len(history_candles) >= 50):
            recent = history_candles[-60:]
            new_regime = self.detector.detect(recent)

            # Switch only if all guards pass:
            #   (a) recommended strategy differs from current
            #   (b) confidence high enough
            #   (c) outside cool-down window after last switch
            #   (d) current sub-strategy is NOT profitably winning (don't kill a winner)
            different   = new_regime.recommended_strategy != self.current_name
            confident   = new_regime.confidence >= self.min_confidence
            in_cooldown = (self.candles_seen - self.last_switch_hour) < self.cooldown_hours
            cur_roi     = self._current_sub_roi(candle[4])
            is_winning  = cur_roi > self.skip_if_winning_above_pct

            if different:
                if not confident:
                    self.skipped_low_conf += 1
                elif in_cooldown:
                    self.skipped_cooldown += 1
                elif is_winning:
                    self.skipped_winning += 1
                else:
                    closes = [c[4] for c in history_candles]
                    self._switch_to(new_regime, candle[4], ts, closes)

        # Delegate to active sub-strategy
        price, high, low = candle[4], candle[2], candle[3]
        if self._active_kind == "grid":
            self._active.tick(low, ts)
            self._active.tick(high, ts)
            self._active.tick(price, ts)
        else:
            self._active.tick(price, ts)

    # ------------------------------------------------------------------
    # Switching logic — liquidate current position, transfer cash to new strat
    # ------------------------------------------------------------------

    def _switch_to(self, new_regime: RegimeResult, price: float, ts: float, warmup_prices: list = None) -> None:
        old_name = self.current_name
        kind, strat = self._active_kind, self._active

        # Snapshot current position
        if kind == "grid":
            coin_balance = strat.coin_balance
            usdt_balance = strat.usdt_balance
            cur_trades   = strat.stats(price)["total_trades"]
            cur_fees     = strat.total_fees_paid
            cur_slip     = strat.total_slippage_cost
        else:
            coin_balance = strat.coin_balance
            usdt_balance = strat.usdt_balance
            cur_trades   = len([t for t in strat.trades])
            cur_fees     = strat.total_fees
            cur_slip     = strat.total_slippage

        # Liquidate all coin via market sell (taker fee + slippage)
        switch_fee  = 0.0
        switch_slip = 0.0
        new_budget  = usdt_balance
        if coin_balance > 0:
            slip       = price * (self.fees.slippage_pct / 100)
            fill_price = price - slip
            gross      = coin_balance * fill_price
            switch_fee = gross * self.fees.taker_rate
            switch_slip = slip * coin_balance
            new_budget = usdt_balance + gross - switch_fee

        # Accumulate lifetime costs from retired sub-strategy + switch cost
        self.lifetime_trades   += cur_trades + (1 if coin_balance > 0 else 0)
        self.lifetime_fees     += cur_fees + switch_fee
        self.lifetime_slippage += cur_slip + switch_slip

        # Log the switch
        self.switches.append(SwitchEvent(
            hour=self.candles_seen,
            from_strategy=old_name,
            to_strategy=new_regime.recommended_strategy,
            regime=new_regime.regime.value,
            price=price,
            pv_at_switch=new_budget,
            coin_sold=coin_balance,
            switch_cost=switch_fee + switch_slip,
        ))

        # Create new sub-strategy with the liquidated cash as its budget
        # and pre-feed it with recent price history so indicators have warmup
        self.current_name   = new_regime.recommended_strategy
        self.current_regime = new_regime.regime
        self._active_kind, self._active = self._create(
            self.current_name, price, new_budget, warmup_prices, ts=ts)
        self.last_switch_hour = self.candles_seen

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _current_sub_roi(self, price: float) -> float:
        """ROI of the CURRENT sub-strategy (relative to its starting budget,
        which may differ from Adaptive's total budget if there have been switches)."""
        strat = self._active
        base  = strat.total_budget
        if base <= 0:
            return 0.0
        return (strat.portfolio_value(price) - base) / base * 100

    def portfolio_value(self, price: float) -> float:
        if self._active_kind == "grid":
            return self._active.portfolio_value(price)
        return self._active.portfolio_value(price)

    def roi(self, price: float) -> float:
        return (self.portfolio_value(price) - self.total_budget) / self.total_budget * 100

    def stats(self, price: float) -> dict:
        kind, strat = self._active_kind, self._active
        if kind == "grid":
            sub = strat.stats(price)
            cur_trades = sub["total_trades"]
            cur_fees   = sub["total_fees"]
            cur_slip   = sub["slippage_cost"]
        else:
            sub = strat.stats(price)
            cur_trades = sub["total_trades"]
            cur_fees   = sub["total_fees"]
            cur_slip   = sub["total_slippage"]

        pv = sub["portfolio_value"]
        return {
            "portfolio_value": pv,
            "roi_pct":         round((pv - self.total_budget) / self.total_budget * 100, 4),
            "total_trades":    self.lifetime_trades + cur_trades,
            "total_fees":      round(self.lifetime_fees + cur_fees, 4),
            "total_slippage":  round(self.lifetime_slippage + cur_slip, 4),
            "total_cost":      round(self.lifetime_fees + cur_fees + self.lifetime_slippage + cur_slip, 4),
            "active_strategy": self.current_name,
            "switches":        len(self.switches),
            "switch_history":  self.switches,
            "skipped_cooldown": self.skipped_cooldown,
            "skipped_low_conf": self.skipped_low_conf,
            "skipped_winning":  self.skipped_winning,
        }
