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

from adaptive_strategy import AdaptiveStrategy
from agents import run_debate
from config import FeeConfig, GridConfig, DCAConfig
from news_sentiment import analyze_sentiment
from regime_detector import RegimeDetector, print_regime_report
from strategies import TrailingDCA, BollingerBreakout, MeanReversion
from strategy import GridDCAStrategy, MAGridDCAStrategy
from technical import compute_all


def fetch_candles(exchange, symbol, timeframe="1h", limit=100, since_ms=None):
    """Fetch `limit` 1h candles ending at the most recent (default)
    OR starting from `since_ms` (Unix epoch ms) for historical backtests."""
    all_candles = []
    if since_ms is None:
        since = exchange.milliseconds() - limit * 3600 * 1000
    else:
        since = since_ms
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


def run_arena(symbol, budget, hours, debate_interval, since_date=None, no_debate=False):
    fee_cfg = FeeConfig()
    exchange = ccxt.okx({"enableRateLimit": True})

    since_ms = None
    if since_date:
        from datetime import datetime as _dt, timezone as _tz
        since_ms = int(_dt.strptime(since_date, "%Y-%m-%d")
                       .replace(tzinfo=_tz.utc).timestamp() * 1000)
        print(f"[HISTORICAL] Backtesting from {since_date}")

    print(f"\n{'='*72}")
    print(f"  STRATEGY ARENA — 6 Strategies Head-to-Head")
    print(f"  Symbol:   {symbol}")
    print(f"  Budget:   ${budget:,.0f} each (${budget*8:,.0f} total)")
    print(f"  Duration: {hours:.0f}h ({hours/24:.1f} days)")
    print(f"  Fees:     Maker {fee_cfg.maker_rate*100:.2f}% | Taker {fee_cfg.taker_rate*100:.2f}% | Slip {fee_cfg.slippage_pct:.2f}%")
    print(f"{'='*72}\n")

    lookback = int(hours) + 100
    print(f"[FETCH] Getting {lookback} hourly candles...")
    # For historical runs, start `warmup` candles BEFORE since_date so that
    # the trading window begins on since_date
    fetch_since = since_ms - 50 * 3600 * 1000 if since_ms else None
    candles = fetch_candles(exchange, symbol, "1h", lookback, since_ms=fetch_since)
    if len(candles) < 100:
        print(f"[ERROR] Only {len(candles)} candles.")
        return

    warmup = 50
    trade_candles = candles[warmup:]
    actual_hours = min(int(hours), len(trade_candles))
    entry_price = trade_candles[0][4]
    bh_qty = budget / entry_price

    print(f"[START] Entry: ${entry_price:,.2f} | Trading {actual_hours}h")

    # --- Regime Detection (using warmup window) ---
    detector = RegimeDetector()
    initial_regime = detector.detect(candles[:warmup + 1])
    print_regime_report(initial_regime, warmup + 1)
    adaptive_strategy_name = initial_regime.recommended_strategy

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

    # Pre-feed warmup closes to indicator-based strategies for fair comparison
    warmup_closes = [c[4] for c in candles[:warmup]]

    # MA-enhanced Grid+DCA
    ma_grid = MAGridDCAStrategy(
        entry_price=entry_price,
        total_budget=budget,
        fees=fee_cfg,
        rebalance_interval=6,
    )
    ma_grid._grid.last_dca_time = trade_candles[0][0] / 1000
    ma_grid.prices = list(warmup_closes)

    trailing = TrailingDCA(budget, fee_cfg)
    bb_breakout = BollingerBreakout(budget, fee_cfg)
    bb_breakout.prices = list(warmup_closes)
    mean_revert = MeanReversion(budget, fee_cfg)
    mean_revert.prices = list(warmup_closes)

    # Adaptive (Hybrid) — switches sub-strategy every 24h based on regime
    adaptive = AdaptiveStrategy(
        entry_price=entry_price,
        budget=budget,
        fees=fee_cfg,
        initial_regime=initial_regime,
        check_interval=24,
        warmup_prices=warmup_closes,
    )

    # Debate setup
    from dual_runner import DebatePosition
    debate_pos = DebatePosition(usdt_balance=budget, total_budget=budget, fees=fee_cfg)
    debate_count = 0
    sentiment = None
    if not no_debate:
        coin = symbol.split("/")[0]
        sentiment = analyze_sentiment(coin)
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

        # MA Grid+DCA
        ma_grid.tick(low, ts)
        ma_grid.tick(high, ts)
        ma_grid.tick(price, ts)
        ma_grid.on_candle_close(price)

        # Trailing DCA
        trailing.tick(price, ts)

        # BB Breakout
        bb_breakout.tick(price, ts)

        # Mean Reversion
        mean_revert.tick(price, ts)

        # Adaptive (Hybrid) — needs full candle + history for regime detection
        history_so_far = candles[:warmup + i + 1]
        adaptive.tick(candle, ts, history_so_far)

        # Debate (skip if --no-debate)
        if not no_debate and i % interval_candles == 0 and i > 0:
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

                coin = symbol.split("/")[0]
                if debate_count % 4 == 0:
                    sentiment = analyze_sentiment(coin)

        # Periodic report (every ~report_every hours)
        if i > 0 and i % report_every == 0:
            bh_pv = bh_qty * price
            bh_roi = (bh_pv - budget) / budget * 100
            gs = grid.stats(price)
            mgs = ma_grid.stats(price)
            ts_stat = trailing.stats(price)
            bbs = bb_breakout.stats(price)
            mrs = mean_revert.stats(price)
            ads = adaptive.stats(price)
            dp = debate_pos.portfolio_value(price)
            dr = debate_pos.roi(price)

            # Re-detect regime every 24h
            regime_updated = None
            if i % 24 == 0:
                window_start = max(0, warmup + i - 49)
                current_regime = detector.detect(candles[window_start: warmup + i + 1])
                if current_regime.regime != initial_regime.regime:
                    regime_updated = current_regime

            print(f"  [{i:5d}h] ${price:>10,.2f}")
            print(f"    Grid+DCA    : ${gs['portfolio_value']:>10,.2f}  ROI {gs['roi_pct']:+.3f}%  trades {gs['total_trades']}")
            print(f"    MA_Grid     : ${mgs['portfolio_value']:>10,.2f}  ROI {mgs['roi_pct']:+.3f}%  trades {mgs['total_trades']}  trend={mgs['trend']}")
            print(f"    TrailingDCA : ${ts_stat['portfolio_value']:>10,.2f}  ROI {ts_stat['roi_pct']:+.3f}%  trades {ts_stat['total_trades']}")
            print(f"    BB_Breakout : ${bbs['portfolio_value']:>10,.2f}  ROI {bbs['roi_pct']:+.3f}%  trades {bbs['total_trades']}")
            print(f"    MeanRevert  : ${mrs['portfolio_value']:>10,.2f}  ROI {mrs['roi_pct']:+.3f}%  trades {mrs['total_trades']}")
            print(f"    Adaptive    : ${ads['portfolio_value']:>10,.2f}  ROI {ads['roi_pct']:+.3f}%  trades {ads['total_trades']}  active={ads['active_strategy']}  switches={ads['switches']}")
            print(f"    Debate      : ${dp:>10,.2f}  ROI {dr:+.3f}%  debates {debate_count}")
            print(f"    Buy&Hold    : ${bh_pv:>10,.2f}  ROI {bh_roi:+.3f}%")
            if regime_updated:
                from regime_detector import LABELS
                print(f"    ⚡ REGIME SHIFT → {LABELS[regime_updated.regime]}  "
                      f"(was {LABELS[initial_regime.regime].split()[0]}) "
                      f"→ suggest switching to {regime_updated.recommended_strategy}")
            print()

    # --- Final Report ---
    final_price = trade_candles[actual_hours - 1][4]
    bh_pv = bh_qty * final_price
    bh_roi = (bh_pv - budget) / budget * 100

    gs = grid.stats(final_price)
    mgs = ma_grid.stats(final_price)
    ts_stat = trailing.stats(final_price)
    bbs = bb_breakout.stats(final_price)
    mrs = mean_revert.stats(final_price)
    ads = adaptive.stats(final_price)
    dp = debate_pos.portfolio_value(final_price)
    dr = debate_pos.roi(final_price)

    # Engine-backed runs (new strategy_engine path) — verify parity inline
    # and provide a forward-compatible reference for future strategies.
    from strategy_engine.sim_runner import run_sim
    from strategy_engine.strategies import (
        AdaptiveStrategy as EngineAdaptive, AdaptiveConfig,
        MAGridDCA, MAGridDCAConfig,
    )
    engine_runs = []
    try:
        eng_cfg = MAGridDCAConfig(symbol=symbol, allocation_usdt=budget)
        eng_res = run_sim(MAGridDCA(eng_cfg), candles[:warmup + actual_hours],
                          symbol, budget, warmup=warmup, fees=fee_cfg)
        engine_runs.append(("Engine_MAGrid", eng_res))
    except Exception as e:
        print(f"[WARN] engine MAGrid run failed: {e}")
    try:
        ad_cfg = AdaptiveConfig(symbol=symbol, allocation_usdt=budget)
        ad_strat = EngineAdaptive(ad_cfg)
        ad_res = run_sim(ad_strat, candles[:warmup + actual_hours],
                         symbol, budget, warmup=warmup, fees=fee_cfg)
        ad_label = f"Engine_Adaptive [{len(ad_strat.switches)}sw]"
        engine_runs.append((ad_label, ad_res))
    except Exception as e:
        print(f"[WARN] engine Adaptive run failed: {e}")

    grid_cost = gs["total_fees"] + gs["slippage_cost"]
    ma_grid_cost = mgs["total_fees"] + mgs["slippage_cost"]
    adaptive_label = f"Adaptive [{ads['switches']}sw]"
    ma_grid_label = f"MA_Grid [{mgs['trend_changes']}t]"
    strategies = [
        ("Grid+DCA", gs["roi_pct"], gs["total_trades"], grid_cost,
         gs["total_fees"], gs["slippage_cost"],
         f"maker ${gs['maker_fees']:.2f} + taker ${gs['taker_fees']:.2f} + slip ${gs['slippage_cost']:.2f}"),
        (ma_grid_label, mgs["roi_pct"], mgs["total_trades"], ma_grid_cost,
         mgs["total_fees"], mgs["slippage_cost"],
         f"maker ${mgs['maker_fees']:.2f} + taker ${mgs['taker_fees']:.2f} + slip ${mgs['slippage_cost']:.2f} | trend={mgs['trend']}"),
        ("TrailingDCA", ts_stat["roi_pct"], ts_stat["total_trades"], ts_stat["total_cost"],
         ts_stat["total_fees"], ts_stat["total_slippage"],
         f"taker ${ts_stat['total_fees']:.2f} + slip ${ts_stat['total_slippage']:.2f}"),
        ("BB_Breakout", bbs["roi_pct"], bbs["total_trades"], bbs["total_cost"],
         bbs["total_fees"], bbs["total_slippage"],
         f"taker ${bbs['total_fees']:.2f} + slip ${bbs['total_slippage']:.2f}"),
        ("MeanRevert", mrs["roi_pct"], mrs["total_trades"], mrs["total_cost"],
         mrs["total_fees"], mrs["total_slippage"],
         f"taker ${mrs['total_fees']:.2f} + slip ${mrs['total_slippage']:.2f}"),
        (adaptive_label, ads["roi_pct"], ads["total_trades"], ads["total_cost"],
         ads["total_fees"], ads["total_slippage"],
         f"fees ${ads['total_fees']:.2f} + slip ${ads['total_slippage']:.2f} | now={ads['active_strategy']}"),
        ("Debate", dr, len(debate_pos.trades),
         debate_pos.total_fees + debate_pos.total_slippage_cost,
         debate_pos.total_fees, debate_pos.total_slippage_cost,
         f"taker ${debate_pos.total_fees:.2f} + slip ${debate_pos.total_slippage_cost:.2f}"),
        ("Buy&Hold", bh_roi, 0, 0, 0, 0, "no fees (hold only)"),
    ]
    # Append engine-backed runs as additional competitors
    for name, r in engine_runs:
        strategies.append((
            name, r.roi_pct, r.total_trades,
            r.total_fees + r.total_slippage, r.total_fees, r.total_slippage,
            f"fees ${r.total_fees:.2f} + slip ${r.total_slippage:.4f} | (engine path)",
        ))

    strategies.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'='*72}")
    print(f"  ARENA FINAL RESULTS — {symbol} | {actual_hours}h ({actual_hours/24:.1f} days)")
    print(f"  Entry: ${entry_price:,.2f} → Exit: ${final_price:,.2f} ({(final_price-entry_price)/entry_price*100:+.2f}%)")
    from regime_detector import LABELS
    print(f"  Regime at start: {LABELS[initial_regime.regime]}  "
          f"(confidence {initial_regime.confidence:.0%}) → recommended {adaptive_strategy_name}")
    print(f"{'='*72}\n")

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    print(f"  {'Rank':<6} {'Strategy':<18} {'ROI':>10} {'Alpha':>10} {'Trades':>7} {'Cost':>8} {'Fee Breakdown'}")
    print(f"  {'─'*6} {'─'*18} {'─'*10} {'─'*10} {'─'*7} {'─'*8} {'─'*30}")

    for i, (name, roi, trades, cost, fees, slip, fee_detail) in enumerate(strategies):
        alpha = roi - bh_roi
        tag = ""
        if name == adaptive_strategy_name:
            tag = " ◀ initial regime pick"
        if name.startswith("Adaptive"):
            tag = " ◀◀ HYBRID"
        print(f"  {medals[i]:<6} {name:<18} {roi:>+9.4f}% {alpha:>+9.4f}% {trades:>7} ${cost:>7.2f} {fee_detail}{tag}")

    winner = strategies[0][0]
    margin = strategies[0][1] - strategies[1][1]
    print(f"\n  >>> {winner} WINS by {margin:.4f}% <<<")

    # Adaptive switch trail
    if ads["switches"] > 0:
        print(f"\n  ⚙️  Adaptive switch trail ({ads['switches']} switches):")
        print(f"     Start → {adaptive_strategy_name} @ ${entry_price:,.0f}")
        for sw in ads["switch_history"]:
            print(f"     [{sw.hour:>3}h] {sw.from_strategy} → {sw.to_strategy:<12} @ ${sw.price:,.0f}  "
                  f"(regime: {sw.regime}, cost ${sw.switch_cost:.2f})")
    else:
        print(f"\n  ⚙️  Adaptive: no switches — held {adaptive_strategy_name} entire run")

    skipped_total = ads['skipped_cooldown'] + ads['skipped_low_conf'] + ads['skipped_winning']
    if skipped_total > 0:
        print(f"     Skipped: {ads['skipped_winning']} winning, "
              f"{ads['skipped_cooldown']} cooldown, "
              f"{ads['skipped_low_conf']} low-conf")

    # MA Grid trend trail
    if mgs["trend_history"]:
        changes = [t for t in mgs["trend_history"] if t["changed"]]
        print(f"\n  📊 MA_Grid trend trail ({mgs['rebalances']} rebalances, {len(changes)} trend changes):")
        for t in changes[:10]:
            arrow = "🟢" if t["trend"] == "bull" else ("🔴" if t["trend"] == "bear" else "⚪")
            print(f"     [{t['hour']:>3}h] {arrow} {t['trend']:<8} spread={t['spread']:+.4f}%  "
                  f"grid=[{t['lower_pct']:.0f}%↓ / {t['upper_pct']:.0f}%↑]  @ ${t['price']:,.0f}")

    # Initial regime pick verdict (the STATIC recommendation, not Adaptive)
    initial_pick_roi = next((r[1] for r in strategies if r[0] == adaptive_strategy_name), None)
    if initial_pick_roi is not None:
        correct = adaptive_strategy_name == winner
        verdict = "CORRECT ✓" if correct else f"BEATEN BY {winner}"
        print(f"  >>> Initial regime pick ({adaptive_strategy_name}): {verdict}  |  "
              f"ROI={initial_pick_roi:+.4f}%  alpha={initial_pick_roi-bh_roi:+.4f}%")
    adaptive_alpha = ads["roi_pct"] - bh_roi
    print(f"  >>> Adaptive (Hybrid):              ROI={ads['roi_pct']:+.4f}%  alpha={adaptive_alpha:+.4f}%")
    print(f"{'='*72}\n")

    # Save to SQLite
    from db import get_conn, create_session, save_result, end_session
    conn = get_conn()
    session_id = create_session(conn, symbol, budget * len(strategies), actual_hours, entry_price, mode="backtest")
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
    parser.add_argument("--since", default=None,
                        help="YYYY-MM-DD: start backtest from this historical date")
    parser.add_argument("--no-debate", action="store_true",
                        help="Skip debate LLM calls for faster backtests")
    args = parser.parse_args()

    run_arena(args.symbol, args.budget, args.hours, args.debate_interval, args.since, args.no_debate)


if __name__ == "__main__":
    main()
