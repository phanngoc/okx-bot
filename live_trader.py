#!/usr/bin/env python3
"""Live MA_Grid+DCA trader — Engine-based main loop.

Uses the unified strategy_engine: MAGridDCA Strategy + OkxLiveExecutor.
Same code path as backtest (arena), with broker I/O swapped from SimExecutor
to OkxLiveExecutor.

Usage:
  python live_trader.py              # run with defaults from .env
  python live_trader.py --once       # one tick (setup + 1 health check) then exit
  python live_trader.py --shutdown   # cancel all + mark session stopped (no liquidation)
  python live_trader.py --status     # read-only status snapshot
"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from okx_executor import OkxExecutor
from okx_live_executor import LiveSessionDB, OkxLiveExecutor
from risk_monitor import RiskConfig, RiskMonitor, StopSignal
from strategy_engine import Engine
from strategy_engine.strategies import MAGridDCA, MAGridDCAConfig
from strategy_engine.types import PriceTick


STOP_FLAG = False


def _handle_signal(sig, _frame):
    global STOP_FLAG
    logging.warning(f"[MAIN] received signal {sig} — graceful shutdown")
    STOP_FLAG = True


signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def setup_logging(level: str = "INFO"):
    log_dir = Path("data")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "live_trader.log"
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )


def preflight(okx: OkxExecutor, symbol: str, allocation: float, is_resume: bool) -> bool:
    log = logging.getLogger("preflight")
    if Path("STOP_NOW").exists():
        log.error("STOP_NOW file present — refuse to start")
        return False
    try:
        bal = okx.fetch_balance()
    except Exception as e:
        log.error(f"fetch_balance failed: {e}")
        return False
    free_usdt = bal.get("USDT", {}).get("free", 0.0)
    if is_resume:
        log.info(f"preflight (resume) OK — symbol={symbol}  alloc=${allocation:.2f}  "
                 f"free=${free_usdt:.2f} (locked in existing orders)")
    else:
        if free_usdt < allocation:
            log.error(f"insufficient USDT for fresh start: free=${free_usdt:.2f} < ${allocation:.2f}")
            return False
        log.info(f"preflight (fresh) OK — free=${free_usdt:.2f}  alloc=${allocation:.2f}  symbol={symbol}")
    log.info(f"mode: {'DEMO' if okx.cfg.demo else 'LIVE — real money'}")
    return True


def cmd_status(okx: OkxExecutor, symbol: str):
    log = logging.getLogger("status")
    bal = okx.fetch_balance()
    open_orders = okx.fetch_open_orders(symbol)
    log.info(f"=== STATUS ===")
    log.info(f"  Mode:         {'DEMO' if okx.cfg.demo else 'LIVE'}")
    log.info(f"  Symbol:       {symbol}")
    for ccy, b in bal.items():
        log.info(f"  {ccy:>5}: free={b['free']:.6f}  used={b['used']:.6f}  total={b['total']:.6f}")
    log.info(f"  Open orders:  {len(open_orders)}")
    for o in open_orders[:5]:
        log.info(f"    {o['side']} {o['amount']} @ ${o['price']:,.2f}  id={o['id']}")
    if len(open_orders) > 5:
        log.info(f"    ... +{len(open_orders)-5} more")


def cmd_shutdown(okx: OkxExecutor, symbol: str, db: LiveSessionDB):
    log = logging.getLogger("shutdown")
    log.warning(f"=== EMERGENCY SHUTDOWN — {symbol} (cancel only, no liquidation) ===")
    try:
        okx.cancel_all(symbol)
    except Exception as e:
        log.error(f"cancel_all failed: {e}")
    db.mark_stopped()
    log.warning("=== shutdown complete (positions held — sell manually if needed) ===")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once",     action="store_true")
    parser.add_argument("--status",   action="store_true")
    parser.add_argument("--shutdown", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    log = logging.getLogger("main")

    symbol     = os.getenv("SYMBOL", "BTC/USDT")
    allocation = float(os.getenv("ALLOCATION_USDT", "150"))
    interval   = int(os.getenv("HEALTH_CHECK_SEC", "30"))
    base_ccy   = symbol.split("/")[0]

    okx = OkxExecutor.from_env()
    db  = LiveSessionDB()

    if args.status:
        cmd_status(okx, symbol)
        return

    if args.shutdown:
        cmd_shutdown(okx, symbol, db)
        return

    # ----- Build strategy + executor + engine -----
    strat_cfg = MAGridDCAConfig(
        symbol=symbol,
        allocation_usdt=allocation,
        num_grids=int(os.getenv("GRID_NUM", "20")),
        range_pct=float(os.getenv("GRID_RANGE_PCT", "5.0")),
        dca_interval_sec=float(os.getenv("DCA_INTERVAL_HOURS", "4")) * 3600,
        dca_amount_usdt=float(os.getenv("DCA_AMOUNT_USDT", "10")),
        rebalance_sec=float(os.getenv("MA_REBALANCE_HOURS", "6")) * 3600,
        ma_threshold_pct=float(os.getenv("MA_THRESHOLD_PCT", "0.5")),
    )
    strategy = MAGridDCA(strat_cfg)
    executor = OkxLiveExecutor(okx, symbol, db=db,
                              max_order_usdt=float(os.getenv("MAX_ORDER_USDT", "100")))
    engine   = Engine(strategy=strategy, executor=executor)

    risk = RiskMonitor(RiskConfig(
        start_balance=allocation,
        max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", "20")),
        kill_loss_pct=float(os.getenv("KILL_LOSS_PCT", "35")),
        max_daily_loss_pct=float(os.getenv("MAX_DAILY_LOSS_PCT", "7")),
    ))

    # ----- State recovery -----
    session = db.maybe_resume(symbol, allocation)

    if not preflight(okx, symbol, allocation, is_resume=bool(session)):
        sys.exit(1)

    if session:
        # Resume path
        log.info(f"[MAIN] resumable session #{session.id} detected — engine resume")
        recon = executor.adopt_existing(session.started_at)
        log.info(f"[MAIN] reconciliation: known={recon['known']}  "
                 f"orphans={recon['orphans']}  missing={recon['missing']}")
        # Hydrate strategy state
        strategy.restore({
            "current_trend": session.current_trend,
            "entry_price":   session.entry_price,
        })
        # Hydrate engine timers from persisted timestamps
        if session.last_dca_ts:
            engine.last_fired["dca"] = session.last_dca_ts
        if session.last_rebalance_ts:
            engine.last_fired["rebalance"] = session.last_rebalance_ts
        engine.setup_done = True   # skip re-setup
        # Pre-feed price history for MA detection
        recent_candles = okx.exchange.fetch_ohlcv(symbol, "1h", limit=120)
        strategy.feed_history([c[4] for c in recent_candles])
        db.mark_running(session.id)
        start_usdt = session.start_usdt
        start_base = session.start_base
        log.info(f"[MAIN] equity baseline: USDT={start_usdt:.2f}  {base_ccy}={start_base:.6f}")
    else:
        # Fresh session: snapshot wallet, then engine.step() will run on_setup
        bal = okx.fetch_balance()
        start_usdt = bal.get("USDT", {}).get("total", 0.0)
        start_base = bal.get(base_ccy, {}).get("total", 0.0)
        # Pre-feed MA history
        recent_candles = okx.exchange.fetch_ohlcv(symbol, "1h", limit=120)
        strategy.feed_history([c[4] for c in recent_candles])
        ticker = okx.fetch_ticker(symbol)
        entry_price = ticker["last"]
        session_id = db.create_session(symbol, allocation, entry_price, start_usdt, start_base)
        log.info(f"[MAIN] fresh session #{session_id} — wallet: USDT={start_usdt:.2f}  "
                 f"{base_ccy}={start_base:.6f}  entry=${entry_price:,.2f}")

    log.info(f"=== LIVE TRADER STARTED — engine path, tick every {interval}s ===")

    soft_stopped = False
    while not STOP_FLAG:
        try:
            now_ts = time.time()
            ticker = okx.fetch_ticker(symbol)
            tick = PriceTick(
                symbol=symbol,
                price=ticker["last"],
                high=ticker.get("high") or ticker["last"],
                low=ticker.get("low")  or ticker["last"],
                ts=now_ts,
            )

            # Drive engine (handles fills, timers, intent execution)
            if not soft_stopped:
                fills = engine.step(tick)
            else:
                fills = []   # soft-stop: drain fills but don't act

            # Persist timer + trend snapshot to DB after each step (cheap, ~ms)
            db.persist_timer("last_dca_ts",       engine.last_fired.get("dca", 0.0))
            db.persist_timer("last_rebalance_ts", engine.last_fired.get("rebalance", 0.0))
            db.persist_timer("current_trend",     strategy.current_trend)

            # Equity isolation: bot equity excludes pre-existing wallet PnL
            bal = okx.fetch_balance()
            cash = bal.get("USDT", {}).get("total", 0.0)
            coin = bal.get(base_ccy, {}).get("total", 0.0)
            mark = tick.price
            equity = allocation + (cash - start_usdt) + (coin - start_base) * mark
            db.save_equity(equity, cash, coin, mark)

            sig = risk.tick(equity, now_ts)
            if sig in (StopSignal.HARD_STOP, StopSignal.MANUAL):
                log.critical(f"[MAIN] {sig.value} → kill switch")
                bot_coin_delta = max(0, coin - start_base)
                executor._cancel_all_side(None)
                if bot_coin_delta > 0:
                    try:
                        okx.exchange.create_order(
                            symbol, "market", "sell", bot_coin_delta, None,
                            {"tdMode": "cash", "clOrdId": f"kill{int(now_ts)}"[:32]},
                        )
                    except Exception as e:
                        log.error(f"[MAIN] kill-sell failed: {e}")
                db.mark_stopped()
                break
            elif sig == StopSignal.SOFT_STOP and not soft_stopped:
                log.warning(f"[MAIN] {sig.value} → cancel buys, hold existing")
                executor._cancel_all_side("buy")
                soft_stopped = True
            elif sig == StopSignal.DAILY_LOSS:
                log.warning(f"[MAIN] daily loss circuit breaker active")

            s = risk.summary()
            log.info(f"[TICK] equity=${equity:.2f}  total_pnl={s['total_pnl_pct']:+.2f}%  "
                     f"dd={s['drawdown_pct']:+.2f}%  day={s['day_pnl_pct']:+.2f}%  "
                     f"trend={strategy.current_trend}  fills={len(fills)}  signal={sig.value}")

        except Exception as e:
            log.exception(f"[MAIN] tick failed: {e}")

        if args.once:
            log.info("[MAIN] --once: exiting after one tick")
            break

        time.sleep(interval)

    # Graceful pause: keep orders, mark paused — restart will resume
    log.info("[MAIN] graceful exit — pausing session (orders persist on OKX)")
    try:
        db.mark_paused({
            "last_dca_ts":       engine.last_fired.get("dca", 0.0),
            "last_rebalance_ts": engine.last_fired.get("rebalance", 0.0),
            "current_trend":     strategy.current_trend,
        })
    except Exception as e:
        log.error(f"mark_paused failed: {e}")
    log.info("=== LIVE TRADER STOPPED (paused — restart to resume) ===")


if __name__ == "__main__":
    main()
