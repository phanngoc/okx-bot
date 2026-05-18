#!/usr/bin/env python3
"""
OKX Grid + DCA Combo Bot
- SIMULATION mode: real price data from OKX, simulated orders locally
- DEMO mode: OKX Demo Trading (virtual funds, real market data)

Usage:
  python run.py                          # simulation, 3 days, BTC/USDT
  python run.py --hours 24               # simulation, 1 day
  python run.py --mode demo              # OKX demo trading (needs API keys)
  python run.py --symbol ETH/USDT       # different pair
  python run.py --fast                   # fast backtest using 1m candles
  python run.py --budget 5000            # custom budget
"""

import argparse
import signal
import time
from datetime import datetime, timezone

import ccxt

from config import BotConfig, DCAConfig, GridConfig, Mode
from strategy import GridDCAStrategy
from tracker import PerformanceTracker

STOP = False


def handle_signal(sig, frame):
    global STOP
    print("\n[!] Graceful shutdown requested...")
    STOP = True


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def create_exchange(cfg: BotConfig) -> ccxt.okx:
    options = {"enableRateLimit": True}
    if cfg.mode == Mode.DEMO:
        options.update({
            "apiKey": cfg.api_key,
            "secret": cfg.api_secret,
            "password": cfg.api_passphrase,
            "options": {"defaultType": "spot", "sandboxMode": True},
        })
    exchange = ccxt.okx(options)
    return exchange


def fetch_price(exchange: ccxt.okx, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    return ticker["last"]


def run_fast_backtest(cfg: BotConfig, exchange: ccxt.okx):
    """Backtest using historical 1m candles — runs in seconds."""
    print(f"\n[FAST BACKTEST] {cfg.symbol} | Budget: ${cfg.total_budget_usdt:,.0f}")
    print(f"[FAST BACKTEST] Fetching {cfg.test_duration_hours:.0f}h of 1m candles...\n")

    total_candles = int(cfg.test_duration_hours * 60)
    all_candles = []
    limit = 100  # OKX returns max 100 candles per request
    since = exchange.milliseconds() - int(cfg.test_duration_hours * 3600 * 1000)

    print(f"[FAST BACKTEST] Paginating... (need {total_candles} candles, {limit}/batch)")
    while len(all_candles) < total_candles:
        batch = exchange.fetch_ohlcv(cfg.symbol, "1m", since=since, limit=limit)
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + 60000
        if len(batch) < limit:
            break
        if len(all_candles) % 500 == 0:
            print(f"  ... fetched {len(all_candles)}/{total_candles} candles")
        time.sleep(0.12)

    if not all_candles:
        print("[ERROR] No candle data fetched.")
        return

    candles = all_candles[:total_candles]
    print(f"[FAST BACKTEST] Got {len(candles)} candles ({len(candles)/60:.1f}h of data)")

    entry_price = candles[0][4]  # close of first candle
    strategy = GridDCAStrategy(
        entry_price=entry_price,
        grid_cfg=cfg.grid,
        dca_cfg=cfg.dca,
        total_budget=cfg.total_budget_usdt,
    )
    strategy.initialize()

    tracker = PerformanceTracker(
        initial_investment=cfg.total_budget_usdt,
        entry_price=entry_price,
    )

    start_ts = candles[0][0] / 1000
    strategy.last_dca_time = start_ts

    print(f"[FAST BACKTEST] Entry price: ${entry_price:,.2f}")
    print(f"[FAST BACKTEST] Running simulation...\n")

    report_interval = max(1, len(candles) // 10)
    for i, candle in enumerate(candles):
        ts = candle[0] / 1000
        high = candle[2]
        low = candle[3]
        close = candle[4]

        strategy.tick(low, ts)
        strategy.tick(high, ts)
        filled = strategy.tick(close, ts)

        if i % 60 == 0:  # snapshot every hour
            stats = strategy.stats(close)
            tracker.record(ts, close, stats)

        if i % report_interval == 0 and i > 0:
            elapsed_h = (ts - start_ts) / 3600
            stats = strategy.stats(close)
            print(
                f"  [{elapsed_h:6.1f}h] Price: ${close:>10,.2f} | "
                f"PV: ${stats['portfolio_value']:>10,.2f} | "
                f"Trades: {stats['total_trades']:>4d} | "
                f"ROI: {stats['roi_pct']:+.3f}%"
            )

    final_price = candles[-1][4]
    final_stats = strategy.stats(final_price)
    tracker.record(candles[-1][0] / 1000, final_price, final_stats)

    report = tracker.report(final_price, final_stats)
    print(report)

    csv_path = tracker.save_csv("backtest_performance.csv")
    report_path = tracker.save_report(report, "backtest_report.txt")
    print(f"\n[SAVED] CSV:    {csv_path}")
    print(f"[SAVED] Report: {report_path}")


def run_live(cfg: BotConfig, exchange: ccxt.okx):
    """Live simulation or demo trading with real-time price feeds."""
    print(f"\n{'='*50}")
    print(f"  OKX GRID + DCA COMBO BOT")
    print(f"  Mode:     {cfg.mode.value.upper()}")
    print(f"  Symbol:   {cfg.symbol}")
    print(f"  Budget:   ${cfg.total_budget_usdt:,.0f}")
    print(f"  Duration: {cfg.test_duration_hours:.0f}h ({cfg.test_duration_hours/24:.1f} days)")
    print(f"  Grid:     {cfg.grid.num_grids} levels, +/-{cfg.grid.price_range_pct}%")
    print(f"  DCA:      ${cfg.dca.amount_per_buy} every {cfg.dca.interval_hours}h")
    print(f"{'='*50}\n")

    entry_price = fetch_price(exchange, cfg.symbol)
    print(f"[START] Entry price: ${entry_price:,.2f}")
    print(f"[START] Time: {datetime.now(timezone.utc).isoformat()}\n")

    strategy = GridDCAStrategy(
        entry_price=entry_price,
        grid_cfg=cfg.grid,
        dca_cfg=cfg.dca,
        total_budget=cfg.total_budget_usdt,
    )
    strategy.initialize()

    tracker = PerformanceTracker(
        initial_investment=cfg.total_budget_usdt,
        entry_price=entry_price,
    )

    start_time = time.time()
    end_time = start_time + cfg.test_duration_hours * 3600
    last_report = start_time
    tick_count = 0

    print("[RUNNING] Bot is active. Ctrl+C to stop and get report.\n")

    while not STOP and time.time() < end_time:
        try:
            now = time.time()
            price = fetch_price(exchange, cfg.symbol)
            filled = strategy.tick(price, now)

            for order in filled:
                elapsed = (now - start_time) / 3600
                tag = "GRID" if order.order_type == "grid" else "DCA "
                print(
                    f"  [{elapsed:6.1f}h] [{tag}] {order.side.upper():4s} "
                    f"@ ${order.fill_price:,.2f} | "
                    f"Qty: {order.quantity:.6f} | "
                    f"${order.amount_usdt:.2f}"
                )

            tick_count += 1
            if tick_count % 10 == 0:
                stats = strategy.stats(price)
                tracker.record(now, price, stats)

            if now - last_report >= 1800:  # report every 30 min
                stats = strategy.stats(price)
                elapsed_h = (now - start_time) / 3600
                print(
                    f"\n  --- [{elapsed_h:.1f}h] Status: "
                    f"Price ${price:,.2f} | "
                    f"PV ${stats['portfolio_value']:,.2f} | "
                    f"ROI {stats['roi_pct']:+.3f}% | "
                    f"Trades {stats['total_trades']} ---\n"
                )
                last_report = now

            time.sleep(cfg.tick_interval_sec)

        except ccxt.NetworkError as e:
            print(f"  [WARN] Network error: {e}. Retrying in 10s...")
            time.sleep(10)
        except ccxt.ExchangeError as e:
            print(f"  [ERROR] Exchange error: {e}. Retrying in 30s...")
            time.sleep(30)

    final_price = fetch_price(exchange, cfg.symbol)
    final_stats = strategy.stats(final_price)
    tracker.record(time.time(), final_price, final_stats)

    report = tracker.report(final_price, final_stats)
    print(report)

    csv_path = tracker.save_csv("live_performance.csv")
    report_path = tracker.save_report(report, "live_report.txt")
    print(f"\n[SAVED] CSV:    {csv_path}")
    print(f"[SAVED] Report: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="OKX Grid + DCA Bot")
    parser.add_argument("--mode", choices=["simulation", "demo"], default="simulation")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--budget", type=float, default=2000.0)
    parser.add_argument("--hours", type=float, default=72.0)
    parser.add_argument("--grids", type=int, default=20)
    parser.add_argument("--grid-range", type=float, default=5.0, help="Grid range +/- percent")
    parser.add_argument("--grid-invest", type=float, default=50.0, help="USDT per grid")
    parser.add_argument("--dca-interval", type=float, default=4.0, help="DCA interval hours")
    parser.add_argument("--dca-amount", type=float, default=30.0, help="USDT per DCA buy")
    parser.add_argument("--fast", action="store_true", help="Fast backtest using candles")
    args = parser.parse_args()

    cfg = BotConfig(
        mode=Mode.DEMO if args.mode == "demo" else Mode.SIMULATION,
        symbol=args.symbol,
        total_budget_usdt=args.budget,
        grid=GridConfig(
            price_range_pct=args.grid_range,
            num_grids=args.grids,
            investment_per_grid=args.grid_invest,
        ),
        dca=DCAConfig(
            interval_hours=args.dca_interval,
            amount_per_buy=args.dca_amount,
        ),
        test_duration_hours=args.hours,
    )

    exchange = create_exchange(cfg)

    if args.fast:
        run_fast_backtest(cfg, exchange)
    else:
        run_live(cfg, exchange)


if __name__ == "__main__":
    main()
