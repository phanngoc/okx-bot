#!/usr/bin/env python3
"""
Strategy Arena: Run ALL strategies on the same historical data and rank them.

Strategies:
  1. Grid+DCA       — classic grid trading + dollar cost averaging
  2. Debate Agent   — Claude AI Bull/Bear/Moderator debate
  3. TrailingDCA    — 3Commas-style DCA with trailing take-profit
  4. BB_Breakout    — Bollinger squeeze breakout
  5. MeanRevert     — Mean reversion (buy oversold, sell overbought)
  6. Buy & Hold     — benchmark

Usage:
  python arena.py                        # 7 days BTC/USDT
  python arena.py --hours 336            # 14 days
  python arena.py --symbol ETH/USDT      # different pair
  python arena.py --budget 5000          # custom budget
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import ccxt

from agents import run_debate
from config import FeeConfig, GridConfig, DCAConfig
from news_sentiment import analyze_sentiment
from strategies import TrailingDCA, BollingerBreakout, MeanReversion
from strategy import GridDCAStrategy
from technical import compute_all


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


def run_arena(symbol, budget, hours, debate_interval):
    fee_cfg = FeeConfig()
    exchange = ccxt.okx({"enableRateLimit": True})

    print(f"\n{'='*72}")
    print(f"  STRATEGY ARENA — 5 Strategies Head-to-Head")
    print(f"  Symbol:   {symbol}")
    print(f"  Budget:   ${budget:,.0f} each (${budget*5:,.0f} total)")
    print(f"  Duration: {hours:.0f}h ({hours/24:.1f} days)")
    print(f"  Fees:     Maker {fee_cfg.maker_rate*100:.2f}% | Taker {fee_cfg.taker_rate*100:.2f}% | Slip {fee_cfg.slippage_pct:.2f}%")
    print(f"{'='*72}\n")

    lookback = int(hours) + 100
    print(f"[FETCH] Getting {lookback} hourly candles...")
    candles = fetch_candles(exchange, symbol, "1h", lookback)
    if len(candles) < 100:
        print(f"[ERROR] Only {len(candles)} candles.")
        return

    warmup = 50
    trade_candles = candles[warmup:]
    actual_hours = min(int(hours), len(trade_candles))
    entry_price = trade_candles[0][4]
    bh_qty = budget / entry_price

    print(f"[START] Entry: ${entry_price:,.2f} | Trading {actual_hours}h\n")

    # --- Init all strategies ---
    grid = GridDCAStrategy(
        entry_price=entry_price,
        grid_cfg=GridConfig(),
        dca_cfg=DCAConfig(),
        total_budget=budget,
        fees=fee_cfg,
    )
    grid.initialize()
    grid.last_dca_time = trade_candles[0][0] / 1000

    trailing = TrailingDCA(budget, fee_cfg)
    bb_breakout = BollingerBreakout(budget, fee_cfg)
    mean_revert = MeanReversion(budget, fee_cfg)

    # Debate setup
    from dual_runner import DebatePosition
    debate_pos = DebatePosition(usdt_balance=budget, total_budget=budget, fees=fee_cfg)
    coin = symbol.split("/")[0]
    sentiment = analyze_sentiment(coin)
    debate_count = 0
    interval_candles = max(1, int(debate_interval))

    report_every = max(1, actual_hours // 6)

    # --- Run simulation ---
    for i in range(actual_hours):
        candle = trade_candles[i]
        ts = candle[0] / 1000
        price = candle[4]
        high = candle[2]
        low = candle[3]

        # Grid+DCA
        grid.tick(low, ts)
        grid.tick(high, ts)
        grid.tick(price, ts)

        # Trailing DCA
        trailing.tick(price, ts)

        # BB Breakout
        bb_breakout.tick(price, ts)

        # Mean Reversion
        mean_revert.tick(price, ts)

        # Debate
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

                # Re-fetch sentiment every 12h
                if debate_count % 4 == 0:
                    sentiment = analyze_sentiment(coin)

        # Periodic report
        if i > 0 and i % report_every == 0:
            bh_pv = bh_qty * price
            bh_roi = (bh_pv - budget) / budget * 100
            gs = grid.stats(price)
            ts_stat = trailing.stats(price)
            bbs = bb_breakout.stats(price)
            mrs = mean_revert.stats(price)
            dp = debate_pos.portfolio_value(price)
            dr = debate_pos.roi(price)

            print(f"  [{i:5d}h] ${price:>10,.2f}")
            print(f"    Grid+DCA    : ${gs['portfolio_value']:>10,.2f}  ROI {gs['roi_pct']:+.3f}%  trades {gs['total_trades']}")
            print(f"    TrailingDCA : ${ts_stat['portfolio_value']:>10,.2f}  ROI {ts_stat['roi_pct']:+.3f}%  trades {ts_stat['total_trades']}")
            print(f"    BB_Breakout : ${bbs['portfolio_value']:>10,.2f}  ROI {bbs['roi_pct']:+.3f}%  trades {bbs['total_trades']}")
            print(f"    MeanRevert  : ${mrs['portfolio_value']:>10,.2f}  ROI {mrs['roi_pct']:+.3f}%  trades {mrs['total_trades']}")
            print(f"    Debate      : ${dp:>10,.2f}  ROI {dr:+.3f}%  debates {debate_count}")
            print(f"    Buy&Hold    : ${bh_pv:>10,.2f}  ROI {bh_roi:+.3f}%")
            print()

    # --- Final Report ---
    final_price = trade_candles[actual_hours - 1][4]
    bh_pv = bh_qty * final_price
    bh_roi = (bh_pv - budget) / budget * 100

    gs = grid.stats(final_price)
    ts_stat = trailing.stats(final_price)
    bbs = bb_breakout.stats(final_price)
    mrs = mean_revert.stats(final_price)
    dp = debate_pos.portfolio_value(final_price)
    dr = debate_pos.roi(final_price)

    grid_cost = gs["total_fees"] + gs["slippage_cost"]
    strategies = [
        ("Grid+DCA", gs["roi_pct"], gs["total_trades"], grid_cost,
         gs["total_fees"], gs["slippage_cost"],
         f"maker ${gs['maker_fees']:.2f} + taker ${gs['taker_fees']:.2f} + slip ${gs['slippage_cost']:.2f}"),
        ("TrailingDCA", ts_stat["roi_pct"], ts_stat["total_trades"], ts_stat["total_cost"],
         ts_stat["total_fees"], ts_stat["total_slippage"],
         f"taker ${ts_stat['total_fees']:.2f} + slip ${ts_stat['total_slippage']:.2f}"),
        ("BB_Breakout", bbs["roi_pct"], bbs["total_trades"], bbs["total_cost"],
         bbs["total_fees"], bbs["total_slippage"],
         f"taker ${bbs['total_fees']:.2f} + slip ${bbs['total_slippage']:.2f}"),
        ("MeanRevert", mrs["roi_pct"], mrs["total_trades"], mrs["total_cost"],
         mrs["total_fees"], mrs["total_slippage"],
         f"taker ${mrs['total_fees']:.2f} + slip ${mrs['total_slippage']:.2f}"),
        ("Debate", dr, len(debate_pos.trades),
         debate_pos.total_fees + debate_pos.total_slippage_cost,
         debate_pos.total_fees, debate_pos.total_slippage_cost,
         f"taker ${debate_pos.total_fees:.2f} + slip ${debate_pos.total_slippage_cost:.2f}"),
        ("Buy&Hold", bh_roi, 0, 0, 0, 0, "no fees (hold only)"),
    ]

    strategies.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'='*72}")
    print(f"  ARENA FINAL RESULTS — {symbol} | {actual_hours}h ({actual_hours/24:.1f} days)")
    print(f"  Entry: ${entry_price:,.2f} → Exit: ${final_price:,.2f} ({(final_price-entry_price)/entry_price*100:+.2f}%)")
    print(f"{'='*72}\n")

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"]
    print(f"  {'Rank':<6} {'Strategy':<14} {'ROI':>10} {'Alpha':>10} {'Trades':>7} {'Cost':>8} {'Fee Breakdown'}")
    print(f"  {'─'*6} {'─'*14} {'─'*10} {'─'*10} {'─'*7} {'─'*8} {'─'*30}")

    for i, (name, roi, trades, cost, fees, slip, fee_detail) in enumerate(strategies):
        alpha = roi - bh_roi
        print(f"  {medals[i]:<6} {name:<14} {roi:>+9.4f}% {alpha:>+9.4f}% {trades:>7} ${cost:>7.2f} {fee_detail}")

    winner = strategies[0][0]
    margin = strategies[0][1] - strategies[1][1]
    print(f"\n  >>> {winner} WINS by {margin:.4f}% <<<")
    print(f"{'='*72}\n")

    # Save to SQLite
    from db import get_conn, create_session, save_result, end_session
    conn = get_conn()
    session_id = create_session(conn, symbol, budget * 5, actual_hours, entry_price, mode="backtest")
    for rank, (name, roi, trades, cost, fees, slip, _) in enumerate(strategies, 1):
        alpha = roi - bh_roi
        pv = budget * (1 + roi / 100)
        save_result(conn, session_id, name, roi, alpha, trades, fees, slip, cost, pv, rank)
    end_session(conn, session_id, final_price)
    conn.close()
    print(f"[DB] Session #{session_id} saved to SQLite")

    # Save JSON backup
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = {
        "symbol": symbol, "hours": actual_hours, "budget": budget,
        "entry": entry_price, "exit": final_price,
        "results": [
            {"strategy": name, "roi": roi, "trades": trades, "cost": cost}
            for name, roi, trades, cost, fees, slip, _ in strategies
        ],
    }
    path = data_dir / f"arena_{ts_str}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[JSON] {path}")


def main():
    parser = argparse.ArgumentParser(description="Strategy Arena")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--budget", type=float, default=2000.0)
    parser.add_argument("--hours", type=float, default=168.0)
    parser.add_argument("--debate-interval", type=float, default=4.0)
    args = parser.parse_args()

    run_arena(args.symbol, args.budget, args.hours, args.debate_interval)


if __name__ == "__main__":
    main()
