import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class Snapshot:
    timestamp: float
    price: float
    portfolio_value: float
    benchmark_value: float
    coin_balance: float
    usdt_balance: float
    total_trades: int


@dataclass
class PerformanceTracker:
    initial_investment: float
    entry_price: float
    snapshots: list = field(default_factory=list)
    benchmark_coin_qty: float = 0.0
    data_dir: Path = field(default_factory=lambda: Path("data"))

    def __post_init__(self):
        self.data_dir.mkdir(exist_ok=True)
        self.benchmark_coin_qty = self.initial_investment / self.entry_price

    def record(self, ts: float, price: float, bot_stats: dict):
        benchmark_val = self.benchmark_coin_qty * price
        snap = Snapshot(
            timestamp=ts,
            price=price,
            portfolio_value=bot_stats["portfolio_value"],
            benchmark_value=round(benchmark_val, 2),
            coin_balance=bot_stats["coin_balance"],
            usdt_balance=bot_stats["usdt_balance"],
            total_trades=bot_stats["total_trades"],
        )
        self.snapshots.append(snap)

    def report(self, current_price: float, bot_stats: dict) -> str:
        if not self.snapshots:
            return "No data recorded yet."

        benchmark_val = self.benchmark_coin_qty * current_price
        benchmark_pnl = benchmark_val - self.initial_investment
        benchmark_roi = (benchmark_pnl / self.initial_investment) * 100

        bot_pv = bot_stats["portfolio_value"]
        bot_pnl = bot_stats["pnl"]
        bot_roi = bot_stats["roi_pct"]

        alpha = bot_roi - benchmark_roi

        prices = [s.price for s in self.snapshots]
        max_price = max(prices)
        min_price = min(prices)
        volatility = ((max_price - min_price) / self.entry_price) * 100

        pvs = [s.portfolio_value for s in self.snapshots]
        peak = pvs[0]
        max_dd = 0.0
        for v in pvs:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd

        hours_elapsed = (self.snapshots[-1].timestamp - self.snapshots[0].timestamp) / 3600

        lines = [
            "=" * 60,
            "  GRID + DCA BOT vs MARKET - PERFORMANCE REPORT",
            "=" * 60,
            "",
            f"  Duration:        {hours_elapsed:.1f} hours ({hours_elapsed/24:.1f} days)",
            f"  Symbol:          BTC/USDT",
            f"  Initial Capital: ${self.initial_investment:,.2f}",
            f"  Entry Price:     ${self.entry_price:,.2f}",
            f"  Current Price:   ${current_price:,.2f}",
            f"  Price Change:    {((current_price - self.entry_price) / self.entry_price) * 100:+.2f}%",
            f"  Volatility:      {volatility:.2f}% (range: ${min_price:,.2f} - ${max_price:,.2f})",
            "",
            "-" * 60,
            "  BOT PERFORMANCE (Grid + DCA Combo)",
            "-" * 60,
            f"  Portfolio Value: ${bot_pv:,.2f}",
            f"  P&L:            ${bot_pnl:+,.2f}",
            f"  ROI:            {bot_roi:+.4f}%",
            f"  Coin Balance:   {bot_stats['coin_balance']:.8f} BTC",
            f"  USDT Balance:   ${bot_stats['usdt_balance']:,.2f}",
            f"  Total Fees:     ${bot_stats['total_fees']:,.2f}",
            f"  Grid Buys:      {bot_stats['grid_buys']}",
            f"  Grid Sells:     {bot_stats['grid_sells']}",
            f"  DCA Buys:       {bot_stats['dca_buys']}",
            f"  Total Trades:   {bot_stats['total_trades']}",
            f"  Max Drawdown:   {max_dd:.2f}%",
            "",
            "-" * 60,
            "  BENCHMARK (Buy & Hold)",
            "-" * 60,
            f"  Portfolio Value: ${benchmark_val:,.2f}",
            f"  P&L:            ${benchmark_pnl:+,.2f}",
            f"  ROI:            {benchmark_roi:+.4f}%",
            "",
            "-" * 60,
            f"  ALPHA (Bot - Market): {alpha:+.4f}%",
            "-" * 60,
        ]

        if alpha > 0:
            lines.append(f"  >>> BOT WINS by {alpha:.4f}% over buy-and-hold <<<")
        elif alpha < 0:
            lines.append(f"  >>> MARKET WINS by {abs(alpha):.4f}% over the bot <<<")
        else:
            lines.append("  >>> TIE - Bot matches market exactly <<<")

        lines.extend(["", "=" * 60])
        return "\n".join(lines)

    def save_csv(self, filename: str = "performance.csv"):
        if not self.snapshots:
            return
        rows = []
        for s in self.snapshots:
            rows.append({
                "timestamp": s.timestamp,
                "datetime": pd.Timestamp(s.timestamp, unit="s").isoformat(),
                "price": s.price,
                "portfolio_value": s.portfolio_value,
                "benchmark_value": s.benchmark_value,
                "coin_balance": s.coin_balance,
                "usdt_balance": s.usdt_balance,
                "total_trades": s.total_trades,
            })
        df = pd.DataFrame(rows)
        path = self.data_dir / filename
        df.to_csv(path, index=False)
        return str(path)

    def save_report(self, report_text: str, filename: str = "report.txt"):
        path = self.data_dir / filename
        path.write_text(report_text)
        return str(path)
