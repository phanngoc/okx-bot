#!/usr/bin/env python3
"""Sweep MAGridDCAStrategy.trend_threshold across N values on the 9-scenario benchmark.

For each (scenario, threshold) pair, fetch candles once and run MA_Grid in
isolation (no debate, no other strategies) so the sweep is fast — about 1s
per (scenario, threshold) cell.

Output: per-scenario ROI table + avg ROI per threshold + winner highlighted.
"""

import argparse
import time
from datetime import datetime, timezone

import ccxt

from config import DCAConfig, FeeConfig, GridConfig
from strategy import MAGridDCAStrategy


SCENARIOS = [
    # (label, symbol, hours, since_date)
    ("1_BTC72h_recent",  "BTC/USDT",  72, None),
    ("2_BTC168h_recent", "BTC/USDT", 168, None),
    ("3_ETH72h_recent",  "ETH/USDT",  72, None),
    ("4_SmoothUP",       "BTC/USDT", 168, "2025-04-18"),
    ("5_VolatileUP",     "BTC/USDT", 168, "2025-07-01"),
    ("6_Crash",          "BTC/USDT", 168, "2026-01-23"),
    ("7_Sideways",       "BTC/USDT", 168, "2025-12-23"),
    ("8_Vshape",         "BTC/USDT", 168, "2026-03-03"),
    ("9_StrongUP",       "BTC/USDT", 168, "2025-09-27"),
]

THRESHOLDS_DEFAULT = [0.2, 0.3, 0.5, 0.7, 1.0, 1.5]
BUDGET   = 2000.0
WARMUP   = 50


def fetch_candles(exchange, symbol, hours, since_date):
    limit = int(hours) + WARMUP + 50
    if since_date:
        since_ms = int(datetime.strptime(since_date, "%Y-%m-%d")
                       .replace(tzinfo=timezone.utc).timestamp() * 1000)
        since = since_ms - WARMUP * 3600 * 1000
    else:
        since = exchange.milliseconds() - limit * 3600 * 1000
    all_candles = []
    while len(all_candles) < limit:
        batch = exchange.fetch_ohlcv(symbol, "1h", since=since, limit=100)
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + 3600000
        if len(batch) < 100:
            break
        time.sleep(0.12)
    return all_candles[:limit]


def run_ma_grid(candles, threshold):
    """Run MA_Grid on pre-fetched candles, return (roi_pct, trades, trend_changes, bh_roi)."""
    warmup_closes = [c[4] for c in candles[:WARMUP]]
    trade_candles = candles[WARMUP:]
    entry_price   = trade_candles[0][4]
    fee_cfg = FeeConfig()

    ma_grid = MAGridDCAStrategy(
        entry_price=entry_price,
        total_budget=BUDGET,
        fees=fee_cfg,
        rebalance_interval=6,
        trend_threshold=threshold,
    )
    ma_grid._grid.last_dca_time = trade_candles[0][0] / 1000
    ma_grid.prices = list(warmup_closes)

    for candle in trade_candles:
        ts    = candle[0] / 1000
        price = candle[4]
        ma_grid.tick(candle[3], ts)  # low
        ma_grid.tick(candle[2], ts)  # high
        ma_grid.tick(price, ts)
        ma_grid.on_candle_close(price)

    final_price = trade_candles[-1][4]
    stats = ma_grid.stats(final_price)
    bh_roi = (final_price - entry_price) / entry_price * 100
    return stats["roi_pct"], stats["total_trades"], stats["trend_changes"], bh_roi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--thresholds", default=",".join(str(t) for t in THRESHOLDS_DEFAULT),
                        help="comma-separated trend_threshold values")
    args = parser.parse_args()
    thresholds = [float(t) for t in args.thresholds.split(",")]

    exchange = ccxt.okx({"enableRateLimit": True})

    print(f"\n{'='*100}")
    print(f"  MA_Grid trend_threshold Sweep — {len(SCENARIOS)} scenarios × {len(thresholds)} thresholds")
    print(f"  Default threshold = 0.3% | Budget = ${BUDGET:,.0f}")
    print(f"{'='*100}\n")

    # Fetch candles once per scenario, then run MA_Grid for each threshold
    results = {}  # threshold -> [(label, roi, trades, changes, bh_roi)]

    for t in thresholds:
        results[t] = []

    for label, symbol, hours, since_date in SCENARIOS:
        print(f"[{label}] fetching {symbol} {hours}h since={since_date or 'recent'}...", end=" ", flush=True)
        candles = fetch_candles(exchange, symbol, hours, since_date)
        if len(candles) < WARMUP + hours:
            print(f"insufficient candles ({len(candles)}, need ≥{WARMUP+hours}) — skipping")
            continue
        print(f"got {len(candles)} candles, entry ${candles[WARMUP][4]:,.2f}")

        for t in thresholds:
            roi, trades, changes, bh = run_ma_grid(candles[:WARMUP + hours], t)
            results[t].append((label, roi, trades, changes, bh))
            print(f"    threshold={t:.1f}%  ROI={roi:+.4f}%  trades={trades:>3}  changes={changes:>2}  (B&H {bh:+.2f}%)")

    # Per-threshold averages
    print(f"\n{'='*100}")
    print(f"  PER-THRESHOLD AVERAGE ROI")
    print(f"{'='*100}\n")
    print(f"  {'Threshold':<10} {'Avg ROI':>10} {'Avg Alpha':>11} {'Avg Trades':>11} {'Avg Changes':>12}   per-scenario ROI")
    print(f"  {'─'*10} {'─'*10} {'─'*11} {'─'*11} {'─'*12} {'─'*60}")

    best_threshold = None
    best_avg       = -1e9
    for t in thresholds:
        rows = results[t]
        if not rows:
            continue
        avg_roi    = sum(r[1] for r in rows) / len(rows)
        avg_alpha  = sum(r[1] - r[4] for r in rows) / len(rows)
        avg_trades = sum(r[2] for r in rows) / len(rows)
        avg_chg    = sum(r[3] for r in rows) / len(rows)
        marker = ""
        if avg_roi > best_avg:
            best_avg = avg_roi
            best_threshold = t
        per_scen = "  ".join(f"{r[1]:+.2f}" for r in rows)
        print(f"  {t:>6.1f}%    {avg_roi:>+9.4f}%  {avg_alpha:>+10.4f}%  {avg_trades:>10.0f}   {avg_chg:>10.1f}    [{per_scen}]")

    print(f"\n  >>> BEST threshold: {best_threshold:.1f}%  (avg ROI {best_avg:+.4f}%) <<<")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
