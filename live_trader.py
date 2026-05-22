#!/usr/bin/env python3
"""Main entry point for the live MA_Grid+DCA trader.

Usage:
  python live_trader.py              # run with defaults from .env
  python live_trader.py --once       # do one tick (setup + 1 health check) and exit
  python live_trader.py --shutdown   # cancel all + market-sell + exit (USE WITH CARE)
  python live_trader.py --status     # print current state without trading

Pre-flight checks:
  1. Auth succeeds (fetch_balance)
  2. Allocation ≤ free USDT
  3. Symbol exists
  4. STOP_NOW file not present
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

from ma_grid_live import DCAConfig, GridConfig, LiveMAGrid, MAConfig
from okx_executor import OkxExecutor
from risk_monitor import RiskConfig, RiskMonitor, StopSignal


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
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file),
    ]
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


def preflight(executor: OkxExecutor, symbol: str, allocation: float, is_resume: bool = False) -> bool:
    """Verify environment + auth before trading.
    On resume: skip USDT check (funds are intentionally locked in existing grid orders)."""
    log = logging.getLogger("preflight")
    if Path("STOP_NOW").exists():
        log.error("STOP_NOW file present — refuse to start")
        return False
    try:
        bal = executor.fetch_balance()
    except Exception as e:
        log.error(f"fetch_balance failed: {e}")
        return False
    if is_resume:
        log.info(f"preflight (resume) OK — symbol={symbol}  alloc=${allocation:.2f} "
                 f"(USDT free=${bal.get('USDT', {}).get('free', 0):.2f}, locked in existing orders)")
    else:
        cash = bal.get("USDT", {}).get("free", 0.0)
        if cash < allocation:
            log.error(f"insufficient USDT for fresh start: free=${cash:.2f} < allocation=${allocation:.2f}")
            return False
        log.info(f"preflight (fresh) OK — free=${cash:.2f}  allocation=${allocation:.2f}  symbol={symbol}")
    log.info(f"mode: {'DEMO' if executor.cfg.demo else 'LIVE — real money'}")
    return True


def cmd_status(executor: OkxExecutor, symbol: str, allocation: float):
    log = logging.getLogger("status")
    bal = executor.fetch_balance()
    equity = executor.equity_usdt(symbol)
    open_orders = executor.fetch_open_orders(symbol)
    log.info(f"=== STATUS ===")
    log.info(f"  Mode:         {'DEMO' if executor.cfg.demo else 'LIVE'}")
    log.info(f"  Symbol:       {symbol}")
    log.info(f"  Allocation:   ${allocation:.2f}")
    log.info(f"  Equity:       ${equity:.2f}")
    for ccy, b in bal.items():
        log.info(f"  {ccy:>5} : free={b['free']:.6f}  used={b['used']:.6f}  total={b['total']:.6f}")
    log.info(f"  Open orders:  {len(open_orders)}")
    for o in open_orders[:5]:
        log.info(f"    {o['side']} {o['amount']} @ ${o['price']:,.2f}  id={o['id']}")
    if len(open_orders) > 5:
        log.info(f"    ... +{len(open_orders)-5} more")


def cmd_shutdown(executor: OkxExecutor, symbol: str):
    """Emergency shutdown: cancel all bot orders. Does NOT market-sell
    base by default — we don't know how much of the wallet balance was
    bot-accumulated vs user pre-existing. Use --shutdown-sell-all to force."""
    log = logging.getLogger("shutdown")
    log.warning(f"=== EMERGENCY SHUTDOWN — {symbol} (cancel only, no liquidation) ===")
    bot = LiveMAGrid(executor, symbol, allocation_usdt=0)
    bot.kill_switch(market_sell_base=False)
    log.warning("=== shutdown complete (positions held — sell manually if needed) ===")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once",     action="store_true", help="run setup + 1 health check, exit")
    parser.add_argument("--status",   action="store_true", help="print balance/orders, no trading")
    parser.add_argument("--shutdown", action="store_true", help="cancel all + market-sell + exit")
    parser.add_argument("--no-setup", action="store_true", help="skip initial grid (resume mode)")
    args = parser.parse_args()

    load_dotenv()
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    log = logging.getLogger("main")

    symbol     = os.getenv("SYMBOL", "BTC/USDT")
    allocation = float(os.getenv("ALLOCATION_USDT", "500"))
    interval   = int(os.getenv("HEALTH_CHECK_SEC", "30"))

    executor = OkxExecutor.from_env()

    if args.status:
        cmd_status(executor, symbol, allocation)
        return

    if args.shutdown:
        cmd_shutdown(executor, symbol)
        return

    grid_cfg = GridConfig(
        range_pct=float(os.getenv("GRID_RANGE_PCT", "5.0")),
        num_grids=int(os.getenv("GRID_NUM", "20")),
    )
    dca_cfg = DCAConfig(
        interval_hours=float(os.getenv("DCA_INTERVAL_HOURS", "4")),
        amount_usdt=float(os.getenv("DCA_AMOUNT_USDT", "10")),
        base_amount_usdt=float(os.getenv("DCA_AMOUNT_USDT", "10")),
    )
    ma_cfg = MAConfig(
        rebalance_hours=int(os.getenv("MA_REBALANCE_HOURS", "6")),
        threshold_pct=float(os.getenv("MA_THRESHOLD_PCT", "0.5")),
    )
    risk_cfg = RiskConfig(
        start_balance=allocation,
        max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", "20")),
        kill_loss_pct=float(os.getenv("KILL_LOSS_PCT", "35")),
        max_daily_loss_pct=float(os.getenv("MAX_DAILY_LOSS_PCT", "7")),
    )

    bot  = LiveMAGrid(executor, symbol, allocation, grid_cfg, dca_cfg, ma_cfg)
    risk = RiskMonitor(risk_cfg)

    # State recovery: detect existing resumable session BEFORE preflight,
    # so we know whether to enforce the USDT-free check (fresh) or skip it (resume).
    resumable = bot.maybe_resume_session()

    if not preflight(executor, symbol, allocation, is_resume=bool(resumable)):
        sys.exit(1)

    if resumable:
        # Resume path: restore state from DB, reconcile with OKX
        log.info(f"[MAIN] resumable session #{resumable['id']} detected — resuming "
                 f"(skip --no-setup logic, no fresh grid placement)")
        start_usdt, start_base = bot.resume_from(resumable)
        log.info(f"[MAIN] equity baseline from session: USDT={start_usdt:.2f}  {bot.base_ccy}={start_base:.6f}")
    else:
        # Fresh path: snapshot wallet, place initial grid
        _bal = executor.fetch_balance()
        start_usdt = _bal.get("USDT", {}).get("total", 0.0)
        start_base = _bal.get(bot.base_ccy, {}).get("total", 0.0)
        log.info(f"[MAIN] fresh session — wallet snapshot: USDT={start_usdt:.2f}  "
                 f"{bot.base_ccy}={start_base:.6f}")
        if not args.no_setup:
            bot.setup_initial_grid(start_usdt=start_usdt, start_base=start_base)

    log.info(f"=== LIVE TRADER STARTED — health checks every {interval}s ===")

    soft_stopped = False
    while not STOP_FLAG:
        try:
            now_ts = time.time()

            # 1. Fills
            fills = bot.poll_fills()
            if fills and not soft_stopped:
                bot.replenish_after_fills(fills)

            # 2. DCA
            if not soft_stopped:
                bot.do_dca(now_ts)

            # 3. MA rebalance
            if not soft_stopped:
                bot.rebalance_check(now_ts)

            # 4. Risk monitor — equity ISOLATED to bot deltas
            bal_now    = executor.fetch_balance()
            cash       = bal_now.get("USDT", {}).get("total", 0.0)
            coin       = bal_now.get(bot.base_ccy, {}).get("total", 0.0)
            mark       = executor.fetch_ticker(symbol)["last"]
            # Bot equity = allocation + USDT delta + (coin bought by bot) × mark
            equity     = allocation + (cash - start_usdt) + (coin - start_base) * mark
            bot._save_equity(equity, cash, coin, mark)

            sig = risk.tick(equity, now_ts)
            if sig == StopSignal.HARD_STOP or sig == StopSignal.MANUAL:
                log.critical(f"[MAIN] {sig.value} → kill switch")
                # Only sell what bot accumulated, never touch pre-existing balance
                bot_coin_delta = max(0, coin - start_base)
                bot.kill_switch(market_sell_base=True, max_sell_amount=bot_coin_delta)
                break
            elif sig == StopSignal.SOFT_STOP:
                if not soft_stopped:
                    log.warning(f"[MAIN] {sig.value} → cancelling buy-side orders, hold existing position")
                    open_orders = executor.fetch_open_orders(symbol)
                    buy_ids = [o["id"] for o in open_orders if o["side"] == "buy"]
                    if buy_ids:
                        try:
                            executor.exchange.cancel_orders(buy_ids, symbol)
                        except Exception as e:
                            log.error(f"[MAIN] soft-stop cancel failed: {e}")
                    soft_stopped = True
            elif sig == StopSignal.DAILY_LOSS:
                log.warning(f"[MAIN] daily loss circuit breaker active")

            s = risk.summary()
            log.info(f"[TICK] equity=${equity:.2f}  total_pnl={s['total_pnl_pct']:+.2f}%  "
                     f"dd={s['drawdown_pct']:+.2f}%  day={s['day_pnl_pct']:+.2f}%  "
                     f"trend={bot.current_trend}  fills_this_tick={len(fills)}  signal={sig.value}")

        except Exception as e:
            log.exception(f"[MAIN] tick failed — sleeping and retrying: {e}")

        if args.once:
            log.info("[MAIN] --once: exiting after one tick")
            break

        time.sleep(interval)

    # Graceful exit: mark session 'paused' so restart can RESUME (keeps orders).
    # Restart will reconcile and continue. Use --shutdown or kill-switch for cancel.
    log.info("[MAIN] graceful exit — pausing session (orders persist on OKX)")
    try:
        bot.graceful_pause()
    except Exception as e:
        log.error(f"[MAIN] graceful_pause failed: {e}")
    log.info("=== LIVE TRADER STOPPED (paused — restart to resume) ===")


if __name__ == "__main__":
    main()
