#!/usr/bin/env python3
"""
Dual Bot Runner: Grid+DCA vs Debate Bot — running in parallel
Shares the same OKX price feed, compares performance in real-time.

Usage:
  python dual_runner.py                          # live sim 72h BTC/USDT
  python dual_runner.py --fast --hours 168       # fast backtest 7 days
  python dual_runner.py --symbol ETH/USDT        # different pair
  python dual_runner.py --budget 5000            # custom budget each
"""

import argparse
import json
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import numpy as np

from agents import run_debate, format_debate
from config import GridConfig, DCAConfig
from news_sentiment import analyze_sentiment
from strategy import GridDCAStrategy
from technical import compute_all
from tracker import PerformanceTracker

STOP = False


def handle_signal(sig, frame):
    global STOP
    STOP = True


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


@dataclass
class DebatePosition:
    coin_balance: float = 0.0
    usdt_balance: float = 0.0
    total_budget: float = 0.0
    trades: list = field(default_factory=list)
    total_fees: float = 0.0

    def buy(self, price: float, usdt_amount: float, ts: float):
        if usdt_amount > self.usdt_balance:
            usdt_amount = self.usdt_balance
        if usdt_amount < 1:
            return
        fee = usdt_amount * 0.001
        net = usdt_amount - fee
        qty = net / price
        self.coin_balance += qty
        self.usdt_balance -= usdt_amount
        self.total_fees += fee
        self.trades.append({"time": ts, "side": "BUY", "price": price, "qty": qty, "usdt": usdt_amount})

    def sell(self, price: float, pct: float, ts: float):
        qty = self.coin_balance * (pct / 100)
        if qty * price < 1:
            return
        gross = qty * price
        fee = gross * 0.001
        net = gross - fee
        self.coin_balance -= qty
        self.usdt_balance += net
        self.total_fees += fee
        self.trades.append({"time": ts, "side": "SELL", "price": price, "qty": qty, "usdt": net})

    def portfolio_value(self, price: float) -> float:
        return self.usdt_balance + self.coin_balance * price

    def roi(self, price: float) -> float:
        pv = self.portfolio_value(price)
        return (pv - self.total_budget) / self.total_budget * 100


def fetch_candles(exchange, symbol, timeframe="1h", limit=100):
    all_candles = []
    since = exchange.milliseconds() - limit * 3600 * 1000
    batch_size = 100
    while len(all_candles) < limit:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=batch_size)
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + 3600000
        if len(batch) < batch_size:
            break
        time.sleep(0.12)
    return all_candles[:limit]


def print_header(symbol, budget, hours, mode):
    print(f"\n{'='*70}")
    print(f"  DUAL BOT BATTLE: Grid+DCA vs Debate Agent")
    print(f"  Mode:     {mode}")
    print(f"  Symbol:   {symbol}")
    print(f"  Budget:   ${budget:,.0f} each (${budget*2:,.0f} total)")
    print(f"  Duration: {hours:.0f}h ({hours/24:.1f} days)")
    print(f"{'='*70}\n")


def print_comparison(elapsed_h, price, grid_pv, grid_roi, debate_pv, debate_roi, bh_pv, bh_roi):
    leader = "GRID+DCA" if grid_roi > debate_roi else "DEBATE"
    if grid_roi == debate_roi:
        leader = "TIE"

    print(f"\n  {'─'*66}")
    print(f"  [{elapsed_h:6.1f}h] Price: ${price:>10,.2f}")
    print(f"  ├─ Grid+DCA : ${grid_pv:>10,.2f}  ROI {grid_roi:+.3f}%")
    print(f"  ├─ Debate   : ${debate_pv:>10,.2f}  ROI {debate_roi:+.3f}%")
    print(f"  ├─ Buy&Hold : ${bh_pv:>10,.2f}  ROI {bh_roi:+.3f}%")
    print(f"  └─ Leader: {leader} (alpha vs market: Grid {grid_roi - bh_roi:+.3f}% | Debate {debate_roi - bh_roi:+.3f}%)")
    print(f"  {'─'*66}")


def print_final_report(symbol, hours, budget, entry_price, final_price,
                        grid_stats, grid_tracker,
                        debate_pos, debate_count,
                        bh_qty):
    grid_pv = grid_stats["portfolio_value"]
    grid_roi = grid_stats["roi_pct"]
    debate_pv = debate_pos.portfolio_value(final_price)
    debate_roi = debate_pos.roi(final_price)
    bh_pv = bh_qty * final_price
    bh_roi = (bh_pv - budget) / budget * 100

    d_buys = sum(1 for t in debate_pos.trades if t["side"] == "BUY")
    d_sells = sum(1 for t in debate_pos.trades if t["side"] == "SELL")

    print(f"\n{'='*70}")
    print(f"  FINAL BATTLE REPORT")
    print(f"{'='*70}")
    print(f"  Symbol:    {symbol}")
    print(f"  Duration:  {hours:.0f}h ({hours/24:.1f} days)")
    print(f"  Entry:     ${entry_price:,.2f}")
    print(f"  Exit:      ${final_price:,.2f} ({(final_price-entry_price)/entry_price*100:+.2f}%)")

    print(f"\n  {'─'*30} GRID+DCA {'─'*30}")
    print(f"  Portfolio:  ${grid_pv:,.2f}")
    print(f"  ROI:        {grid_roi:+.4f}%")
    print(f"  Trades:     {grid_stats['total_trades']}")
    print(f"  Coin held:  {grid_stats.get('coin_balance', 0):.6f}")
    print(f"  USDT held:  ${grid_stats.get('usdt_balance', 0):,.2f}")
    print(f"  Fees:       ${grid_stats.get('total_fees', 0):,.2f}")

    print(f"\n  {'─'*30} DEBATE {'─'*31}")
    print(f"  Portfolio:  ${debate_pv:,.2f}")
    print(f"  ROI:        {debate_roi:+.4f}%")
    print(f"  Debates:    {debate_count}")
    print(f"  Trades:     {d_buys} buys, {d_sells} sells")
    print(f"  Coin held:  {debate_pos.coin_balance:.6f}")
    print(f"  USDT held:  ${debate_pos.usdt_balance:,.2f}")
    print(f"  Fees:       ${debate_pos.total_fees:,.2f}")

    print(f"\n  {'─'*30} BUY&HOLD {'─'*30}")
    print(f"  Portfolio:  ${bh_pv:,.2f}")
    print(f"  ROI:        {bh_roi:+.4f}%")

    print(f"\n  {'='*30} SCOREBOARD {'='*28}")
    results = [
        ("Grid+DCA", grid_roi),
        ("Debate", debate_roi),
        ("Buy&Hold", bh_roi),
    ]
    results.sort(key=lambda x: x[1], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    for i, (name, roi) in enumerate(results):
        alpha = roi - bh_roi
        print(f"  {medals[i]} {name:10s}  ROI {roi:+.4f}%  Alpha {alpha:+.4f}%")

    winner = results[0][0]
    margin = results[0][1] - results[1][1]
    print(f"\n  >>> {winner} WINS by {margin:.4f}% <<<")
    print(f"{'='*70}\n")

    return {
        "symbol": symbol,
        "hours": hours,
        "budget": budget,
        "entry_price": entry_price,
        "exit_price": final_price,
        "grid_roi": grid_roi,
        "debate_roi": debate_roi,
        "buyhold_roi": bh_roi,
        "winner": winner,
        "grid_trades": grid_stats["total_trades"],
        "debate_trades": d_buys + d_sells,
        "debate_count": debate_count,
    }


def run_fast_dual(symbol, budget, hours, debate_interval, grid_cfg, dca_cfg):
    """Fast backtest both bots on the same historical candles."""
    exchange = ccxt.okx({"enableRateLimit": True})
    print_header(symbol, budget, hours, "FAST BACKTEST")

    lookback = int(hours) + 100
    print(f"[FETCH] Getting {lookback} hourly candles for {symbol}...")
    candles = fetch_candles(exchange, symbol, "1h", lookback)
    if len(candles) < 100:
        print(f"[ERROR] Only {len(candles)} candles available.")
        return

    warmup = 50
    trade_candles = candles[warmup:]
    actual_hours = min(int(hours), len(trade_candles))
    entry_price = trade_candles[0][4]
    bh_qty = budget / entry_price

    print(f"[START] Entry: ${entry_price:,.2f} | Trading {actual_hours}h\n")

    # --- Init Grid+DCA ---
    grid_strategy = GridDCAStrategy(
        entry_price=entry_price,
        grid_cfg=grid_cfg,
        dca_cfg=dca_cfg,
        total_budget=budget,
    )
    grid_strategy.initialize()
    grid_tracker = PerformanceTracker(initial_investment=budget, entry_price=entry_price)
    grid_strategy.last_dca_time = trade_candles[0][0] / 1000

    # --- Init Debate ---
    debate_pos = DebatePosition(usdt_balance=budget, total_budget=budget)
    coin = symbol.split("/")[0]
    sentiment = analyze_sentiment(coin)
    debate_count = 0
    interval_candles = max(1, int(debate_interval))

    report_every = max(1, actual_hours // 8)

    for i in range(actual_hours):
        candle = trade_candles[i]
        ts = candle[0] / 1000
        price = candle[4]
        high = candle[2]
        low = candle[3]

        # Grid+DCA tick
        grid_strategy.tick(low, ts)
        grid_strategy.tick(high, ts)
        grid_strategy.tick(price, ts)

        # Debate tick
        if i % interval_candles == 0 and i > 0:
            window = candles[warmup + i - 50: warmup + i + 1]
            if len(window) >= 50:
                ta = compute_all(window)
                result = run_debate(ta, sentiment)
                decision = result["decision"]
                debate_count += 1

                if decision.direction == "BUY" and decision.confidence > 5:
                    buy_pct = min(40, max(5, decision.confidence / 2))
                    buy_amount = debate_pos.usdt_balance * (buy_pct / 100)
                    if buy_amount > 5:
                        debate_pos.buy(price, buy_amount, ts)

                elif decision.direction == "SELL" and decision.confidence > 5:
                    sell_pct = min(40, max(5, decision.confidence / 2))
                    if debate_pos.coin_balance * price > 5:
                        debate_pos.sell(price, sell_pct, ts)

        # Periodic report
        if i > 0 and i % report_every == 0:
            grid_stats = grid_strategy.stats(price)
            grid_tracker.record(ts, price, grid_stats)
            grid_pv = grid_stats["portfolio_value"]
            grid_roi = grid_stats["roi_pct"]
            debate_pv = debate_pos.portfolio_value(price)
            debate_roi = debate_pos.roi(price)
            bh_pv = bh_qty * price
            bh_roi = (bh_pv - budget) / budget * 100
            print_comparison(i, price, grid_pv, grid_roi, debate_pv, debate_roi, bh_pv, bh_roi)

    # Final
    final_price = trade_candles[actual_hours - 1][4]
    grid_stats = grid_strategy.stats(final_price)
    grid_tracker.record(trade_candles[actual_hours - 1][0] / 1000, final_price, grid_stats)

    report_data = print_final_report(
        symbol, actual_hours, budget, entry_price, final_price,
        grid_stats, grid_tracker, debate_pos, debate_count, bh_qty
    )

    save_results(report_data)


def run_live_dual(symbol, budget, hours, debate_interval, grid_cfg, dca_cfg):
    """Live simulation: both bots use the same real-time price feed."""
    exchange = ccxt.okx({"enableRateLimit": True})
    print_header(symbol, budget, hours, "LIVE SIMULATION")

    ticker = exchange.fetch_ticker(symbol)
    entry_price = ticker["last"]
    bh_qty = budget / entry_price
    coin = symbol.split("/")[0]

    print(f"[START] Entry: ${entry_price:,.2f} | {datetime.now(timezone.utc).isoformat()}\n")

    # --- Init Grid+DCA ---
    grid_strategy = GridDCAStrategy(
        entry_price=entry_price,
        grid_cfg=grid_cfg,
        dca_cfg=dca_cfg,
        total_budget=budget,
    )
    grid_strategy.initialize()
    grid_tracker = PerformanceTracker(initial_investment=budget, entry_price=entry_price)

    # --- Init Debate ---
    debate_pos = DebatePosition(usdt_balance=budget, total_budget=budget)
    debate_count = 0

    start = time.time()
    end = start + hours * 3600
    last_debate = start - debate_interval * 3600
    last_report = start
    tick_count = 0

    print("[RUNNING] Both bots active. Ctrl+C for final report.\n")

    while not STOP and time.time() < end:
        try:
            now = time.time()
            price = exchange.fetch_ticker(symbol)["last"]
            elapsed_h = (now - start) / 3600

            # Grid+DCA tick
            filled = grid_strategy.tick(price, now)
            for order in filled:
                tag = "GRID" if order.order_type == "grid" else "DCA "
                print(
                    f"  [{elapsed_h:6.1f}h] [GRID+DCA] [{tag}] {order.side.upper():4s} "
                    f"@ ${order.fill_price:,.2f} | Qty: {order.quantity:.6f}"
                )

            tick_count += 1
            if tick_count % 10 == 0:
                grid_stats = grid_strategy.stats(price)
                grid_tracker.record(now, price, grid_stats)

            # Debate tick
            if now - last_debate >= debate_interval * 3600:
                candles = fetch_candles(exchange, symbol, "1h", 100)
                if len(candles) >= 50:
                    ta = compute_all(candles)
                    sentiment = analyze_sentiment(coin)
                    result = run_debate(ta, sentiment)
                    decision = result["decision"]
                    debate_count += 1

                    dir_emoji = {"BUY": "📈", "SELL": "📉", "HOLD": "⏸️"}.get(decision.direction, "?")
                    print(
                        f"\n  [{elapsed_h:6.1f}h] [DEBATE #{debate_count}] "
                        f"{dir_emoji} {decision.direction} (score {decision.score:+.0f}, "
                        f"conf {decision.confidence:.0f}%)"
                    )
                    print(f"    Bull: {result['bull'].score:+.0f} | Bear: {result['bear'].score:+.0f}")

                    if decision.direction == "BUY" and decision.confidence > 5:
                        buy_pct = min(40, max(5, decision.confidence / 2))
                        buy_amount = debate_pos.usdt_balance * (buy_pct / 100)
                        if buy_amount > 5:
                            debate_pos.buy(price, buy_amount, now)
                            print(f"    >>> DEBATE BUY ${buy_amount:.2f} @ ${price:,.2f}")

                    elif decision.direction == "SELL" and decision.confidence > 5:
                        sell_pct = min(40, max(5, decision.confidence / 2))
                        if debate_pos.coin_balance * price > 5:
                            debate_pos.sell(price, sell_pct, now)
                            print(f"    >>> DEBATE SELL {sell_pct:.0f}% @ ${price:,.2f}")

                    last_debate = now

            # Periodic comparison
            if now - last_report >= 1800:
                grid_stats = grid_strategy.stats(price)
                grid_pv = grid_stats["portfolio_value"]
                grid_roi = grid_stats["roi_pct"]
                debate_pv = debate_pos.portfolio_value(price)
                debate_roi = debate_pos.roi(price)
                bh_pv = bh_qty * price
                bh_roi = (bh_pv - budget) / budget * 100
                print_comparison(elapsed_h, price, grid_pv, grid_roi, debate_pv, debate_roi, bh_pv, bh_roi)
                last_report = now

            time.sleep(30)

        except ccxt.NetworkError as e:
            print(f"  [WARN] Network: {e}")
            time.sleep(10)
        except ccxt.ExchangeError as e:
            print(f"  [ERROR] Exchange: {e}")
            time.sleep(30)

    # Final report
    try:
        final_price = exchange.fetch_ticker(symbol)["last"]
    except Exception:
        final_price = price

    grid_stats = grid_strategy.stats(final_price)
    grid_tracker.record(time.time(), final_price, grid_stats)

    report_data = print_final_report(
        symbol, hours, budget, entry_price, final_price,
        grid_stats, grid_tracker, debate_pos, debate_count, bh_qty
    )

    save_results(report_data)


def save_results(data):
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = data_dir / f"dual_battle_{ts}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"[SAVED] {path}")


def main():
    parser = argparse.ArgumentParser(description="Dual Bot Battle: Grid+DCA vs Debate")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--budget", type=float, default=2000.0, help="Budget for EACH bot")
    parser.add_argument("--hours", type=float, default=72.0)
    parser.add_argument("--fast", action="store_true", help="Fast backtest mode")
    parser.add_argument("--debate-interval", type=float, default=4.0, help="Hours between debates")
    parser.add_argument("--grids", type=int, default=20)
    parser.add_argument("--grid-range", type=float, default=5.0)
    parser.add_argument("--grid-invest", type=float, default=50.0)
    parser.add_argument("--dca-interval", type=float, default=4.0)
    parser.add_argument("--dca-amount", type=float, default=30.0)
    args = parser.parse_args()

    grid_cfg = GridConfig(
        price_range_pct=args.grid_range,
        num_grids=args.grids,
        investment_per_grid=args.grid_invest,
    )
    dca_cfg = DCAConfig(
        interval_hours=args.dca_interval,
        amount_per_buy=args.dca_amount,
    )

    if args.fast:
        run_fast_dual(args.symbol, args.budget, args.hours, args.debate_interval, grid_cfg, dca_cfg)
    else:
        run_live_dual(args.symbol, args.budget, args.hours, args.debate_interval, grid_cfg, dca_cfg)


if __name__ == "__main__":
    main()
