#!/usr/bin/env python3
"""
OKX Multi-Agent Debate Trading Bot
3 agents (Bull, Bear, Moderator) debate using technical analysis + news sentiment.

Usage:
  python debate_bot.py                             # one-shot analysis
  python debate_bot.py --live --hours 72            # live trading simulation 3 days
  python debate_bot.py --symbol ETH/USDT            # different pair
  python debate_bot.py --fast --hours 72             # fast backtest
  python debate_bot.py --budget 5000                 # custom budget
"""

import argparse
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from agents import format_debate, run_debate
from news_sentiment import analyze_sentiment
from technical import compute_all

STOP = False


def handle_signal(sig, frame):
    global STOP
    print("\n[!] Stopping bot...")
    STOP = True


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


@dataclass
class Position:
    coin_balance: float = 0.0
    usdt_balance: float = 0.0
    total_budget: float = 0.0
    entry_prices: list = field(default_factory=list)
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
        self.entry_prices.append(price)
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


def fetch_candles(exchange, symbol: str, timeframe: str = "1h", limit: int = 100) -> list:
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


def one_shot(symbol: str):
    """Single analysis - run debate and print result."""
    print(f"\n[LOADING] Fetching data for {symbol}...")
    exchange = ccxt.okx({"enableRateLimit": True})

    candles = fetch_candles(exchange, symbol, "1h", 100)
    if len(candles) < 50:
        print("[ERROR] Not enough candle data.")
        return

    ta = compute_all(candles)
    coin = symbol.split("/")[0]
    sentiment = analyze_sentiment(coin)

    result = run_debate(ta, sentiment)
    print(format_debate(result, symbol, ta["price"]))

    print(f"  News Sentiment: {sentiment['label']} (score: {sentiment['score']})")
    print(f"  Headlines analyzed: {sentiment['headline_count']}")
    if sentiment["top_headlines"]:
        print(f"  Top headlines:")
        for h in sentiment["top_headlines"][:3]:
            print(f"    - {h[:70]}")
    print()


def run_backtest(symbol: str, budget: float, hours: float, debate_interval: float):
    """Fast backtest using historical 1h candles."""
    exchange = ccxt.okx({"enableRateLimit": True})
    print(f"\n[BACKTEST] {symbol} | Budget: ${budget:,.0f} | {hours:.0f}h | Debate every {debate_interval:.0f}h")

    lookback = int(hours) + 100
    print(f"[BACKTEST] Fetching {lookback} hourly candles...")
    candles = fetch_candles(exchange, symbol, "1h", lookback)
    if len(candles) < 100:
        print(f"[ERROR] Only {len(candles)} candles. Need at least 100.")
        return

    warmup = 50
    trade_candles = candles[warmup:]
    if len(trade_candles) < hours:
        print(f"[WARN] Only {len(trade_candles)}h of trade data available")

    pos = Position(usdt_balance=budget, total_budget=budget)
    entry_price = trade_candles[0][4]
    benchmark_qty = budget / entry_price

    print(f"[BACKTEST] Entry: ${entry_price:,.2f}")
    print(f"[BACKTEST] Running {len(trade_candles)} hours of simulation...\n")

    coin = symbol.split("/")[0]
    sentiment = analyze_sentiment(coin)

    debate_count = 0
    interval_candles = max(1, int(debate_interval))

    for i, candle in enumerate(trade_candles):
        if i >= hours:
            break

        ts = candle[0] / 1000
        price = candle[4]

        if i % interval_candles == 0 and i > 0:
            window = candles[warmup + i - 50: warmup + i + 1]
            if len(window) >= 50:
                ta = compute_all(window)
                result = run_debate(ta, sentiment)
                decision = result["decision"]
                debate_count += 1

                action_taken = ""
                if decision.direction == "BUY" and decision.confidence > 5:
                    buy_pct = min(40, max(5, decision.confidence / 2))
                    buy_amount = pos.usdt_balance * (buy_pct / 100)
                    if buy_amount > 5:
                        pos.buy(price, buy_amount, ts)
                        action_taken = f"BUY ${buy_amount:.0f}"

                elif decision.direction == "SELL" and decision.confidence > 5:
                    sell_pct = min(40, max(5, decision.confidence / 2))
                    if pos.coin_balance * price > 5:
                        pos.sell(price, sell_pct, ts)
                        action_taken = f"SELL {sell_pct:.0f}%"

                if action_taken or i % (interval_candles * 3) == 0:
                    pv = pos.portfolio_value(price)
                    bv = benchmark_qty * price
                    print(
                        f"  [{i:4d}h] ${price:>10,.2f} | "
                        f"Debate #{debate_count}: {decision.direction:4s} "
                        f"(conf {decision.confidence:.0f}%, score {decision.score:+.0f}) | "
                        f"Bot ${pv:,.0f} vs Mkt ${bv:,.0f} | "
                        f"{action_taken}"
                    )

    final_price = trade_candles[min(int(hours) - 1, len(trade_candles) - 1)][4]
    bot_pv = pos.portfolio_value(final_price)
    bot_roi = pos.roi(final_price)
    mkt_pv = benchmark_qty * final_price
    mkt_roi = (mkt_pv - budget) / budget * 100
    alpha = bot_roi - mkt_roi

    buys = sum(1 for t in pos.trades if t["side"] == "BUY")
    sells = sum(1 for t in pos.trades if t["side"] == "SELL")

    print(f"\n{'='*60}")
    print(f"  DEBATE BOT BACKTEST REPORT")
    print(f"{'='*60}")
    print(f"  Duration:    {hours:.0f}h ({hours/24:.1f} days)")
    print(f"  Debates:     {debate_count}")
    print(f"  Entry:       ${entry_price:,.2f}")
    print(f"  Exit:        ${final_price:,.2f} ({(final_price-entry_price)/entry_price*100:+.2f}%)")
    print(f"\n  --- BOT (Debate Strategy) ---")
    print(f"  Portfolio:   ${bot_pv:,.2f}")
    print(f"  ROI:         {bot_roi:+.4f}%")
    print(f"  Trades:      {buys} buys, {sells} sells")
    print(f"  Coin held:   {pos.coin_balance:.6f}")
    print(f"  USDT held:   ${pos.usdt_balance:,.2f}")
    print(f"  Fees:        ${pos.total_fees:,.2f}")
    print(f"\n  --- BENCHMARK (Buy & Hold) ---")
    print(f"  Portfolio:   ${mkt_pv:,.2f}")
    print(f"  ROI:         {mkt_roi:+.4f}%")
    print(f"\n  --- ALPHA: {alpha:+.4f}% ---")
    if alpha > 0:
        print(f"  >>> DEBATE BOT WINS by {alpha:.4f}% <<<")
    else:
        print(f"  >>> MARKET WINS by {abs(alpha):.4f}% <<<")
    print(f"{'='*60}\n")

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    report_path = data_dir / "debate_backtest.txt"
    with open(report_path, "w") as f:
        f.write(f"Debate Backtest: {symbol} | {hours}h | Budget ${budget}\n")
        f.write(f"Bot ROI: {bot_roi:+.4f}% | Market ROI: {mkt_roi:+.4f}% | Alpha: {alpha:+.4f}%\n")
        f.write(f"Trades: {buys} buys, {sells} sells | Fees: ${pos.total_fees:.2f}\n")
    print(f"[SAVED] {report_path}")


def run_live(symbol: str, budget: float, hours: float, debate_interval: float):
    """Live simulation with real-time debate decisions."""
    exchange = ccxt.okx({"enableRateLimit": True})

    print(f"\n{'='*55}")
    print(f"  OKX DEBATE BOT - LIVE SIMULATION")
    print(f"  Symbol:   {symbol}")
    print(f"  Budget:   ${budget:,.0f}")
    print(f"  Duration: {hours:.0f}h ({hours/24:.1f} days)")
    print(f"  Debate:   every {debate_interval:.0f}h")
    print(f"{'='*55}\n")

    ticker = exchange.fetch_ticker(symbol)
    entry_price = ticker["last"]
    pos = Position(usdt_balance=budget, total_budget=budget)
    benchmark_qty = budget / entry_price
    coin = symbol.split("/")[0]

    print(f"[START] Entry: ${entry_price:,.2f} | {datetime.now(timezone.utc).isoformat()}")
    print(f"[RUNNING] Debating every {debate_interval:.0f}h. Ctrl+C for report.\n")

    start = time.time()
    end = start + hours * 3600
    last_debate = start - debate_interval * 3600  # trigger first debate immediately
    debate_count = 0

    while not STOP and time.time() < end:
        try:
            now = time.time()

            if now - last_debate >= debate_interval * 3600:
                candles = fetch_candles(exchange, symbol, "1h", 100)
                if len(candles) >= 50:
                    ta = compute_all(candles)
                    sentiment = analyze_sentiment(coin)
                    result = run_debate(ta, sentiment)
                    decision = result["decision"]
                    debate_count += 1
                    price = ta["price"]

                    print(format_debate(result, symbol, price))

                    if decision.direction == "BUY" and decision.confidence > 5:
                        buy_pct = min(40, max(5, decision.confidence / 2))
                        buy_amount = pos.usdt_balance * (buy_pct / 100)
                        if buy_amount > 5:
                            pos.buy(price, buy_amount, now)
                            print(f"  >>> EXECUTED BUY ${buy_amount:.2f} @ ${price:,.2f}")

                    elif decision.direction == "SELL" and decision.confidence > 5:
                        sell_pct = min(40, max(5, decision.confidence / 2))
                        if pos.coin_balance * price > 5:
                            pos.sell(price, sell_pct, now)
                            print(f"  >>> EXECUTED SELL {sell_pct:.0f}% @ ${price:,.2f}")

                    pv = pos.portfolio_value(price)
                    bv = benchmark_qty * price
                    elapsed = (now - start) / 3600
                    print(
                        f"\n  [{elapsed:.1f}h] Bot: ${pv:,.2f} ({pos.roi(price):+.3f}%) | "
                        f"Market: ${bv:,.2f} ({(bv-budget)/budget*100:+.3f}%) | "
                        f"Alpha: {pos.roi(price) - (bv-budget)/budget*100:+.3f}%\n"
                    )

                    last_debate = now

            time.sleep(60)

        except ccxt.NetworkError as e:
            print(f"  [WARN] Network: {e}")
            time.sleep(10)
        except ccxt.ExchangeError as e:
            print(f"  [ERROR] Exchange: {e}")
            time.sleep(30)

    # Final report
    ticker = exchange.fetch_ticker(symbol)
    final_price = ticker["last"]
    bot_pv = pos.portfolio_value(final_price)
    bot_roi = pos.roi(final_price)
    mkt_pv = benchmark_qty * final_price
    mkt_roi = (mkt_pv - budget) / budget * 100

    buys = sum(1 for t in pos.trades if t["side"] == "BUY")
    sells = sum(1 for t in pos.trades if t["side"] == "SELL")

    print(f"\n{'='*60}")
    print(f"  FINAL REPORT - DEBATE BOT")
    print(f"{'='*60}")
    print(f"  Debates: {debate_count} | Buys: {buys} | Sells: {sells}")
    print(f"  Bot:    ${bot_pv:,.2f} (ROI {bot_roi:+.4f}%)")
    print(f"  Market: ${mkt_pv:,.2f} (ROI {mkt_roi:+.4f}%)")
    print(f"  Alpha:  {bot_roi - mkt_roi:+.4f}%")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="OKX Debate Trading Bot")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--budget", type=float, default=2000.0)
    parser.add_argument("--hours", type=float, default=72.0)
    parser.add_argument("--debate-interval", type=float, default=4.0, help="Hours between debates")
    parser.add_argument("--live", action="store_true", help="Live simulation mode")
    parser.add_argument("--fast", action="store_true", help="Fast backtest mode")
    args = parser.parse_args()

    if args.fast:
        run_backtest(args.symbol, args.budget, args.hours, args.debate_interval)
    elif args.live:
        run_live(args.symbol, args.budget, args.hours, args.debate_interval)
    else:
        one_shot(args.symbol)


if __name__ == "__main__":
    main()
