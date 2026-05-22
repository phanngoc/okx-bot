"""Convenience helper: run a Strategy via Engine+SimExecutor on a candle series.
Used by arena to integrate engine-based strategies alongside legacy ones."""

from dataclasses import dataclass

from config import FeeConfig
from strategy_engine.engine import Engine
from strategy_engine.sim_executor import SimExecutor
from strategy_engine.strategy import Strategy
from strategy_engine.types import PriceTick


@dataclass
class SimResult:
    pv:            float
    roi_pct:       float
    total_trades:  int
    total_intents: int
    total_fees:    float
    total_slippage: float
    final_quote:   float
    final_base:    float


def run_sim(strategy: Strategy, candles: list, symbol: str, budget: float,
            warmup: int = 50, fees: FeeConfig = None) -> SimResult:
    """Backtest `strategy` on `candles` with `budget` USDT.

    candles: list of [ts_ms, open, high, low, close, volume]
    warmup:  first N candles pre-fed to strategy as history (no ticks)
    Returns: SimResult with PV/ROI/trades/fees.
    """
    fees = fees or FeeConfig()
    warmup_closes = [c[4] for c in candles[:warmup]]
    trade_candles = candles[warmup:]
    if not trade_candles:
        raise ValueError("candles too short (no trade candles after warmup)")

    if hasattr(strategy, "feed_history"):
        strategy.feed_history(warmup_closes)

    exe = SimExecutor(fees=fees)
    exe.fund(budget)
    engine = Engine(strategy=strategy, executor=exe)

    for c in trade_candles:
        engine.step(PriceTick(
            symbol=symbol, price=c[4], high=c[2], low=c[3], ts=c[0] / 1000,
        ))

    final = trade_candles[-1][4]
    pv = exe.portfolio_value(symbol, final)
    return SimResult(
        pv=pv,
        roi_pct=(pv - budget) / budget * 100,
        total_trades=engine.fills_total,
        total_intents=engine.intents_total,
        total_fees=exe.total_fees,
        total_slippage=exe.total_slippage,
        final_quote=exe.quote_balance,
        final_base=exe.base_balance,
    )
