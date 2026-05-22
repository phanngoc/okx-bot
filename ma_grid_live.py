"""Live MA_Grid+DCA adapter.

Translates the simulated MAGridDCAStrategy logic into real OKX orders:
  - Initial setup: place N buy limit orders below market (allocation/N each)
  - On BUY fill: place SELL limit above (capturing grid step profit)
  - On SELL fill: place BUY limit below (replenish grid)
  - DCA: scheduled market BUY every DCA_INTERVAL_HOURS
  - MA rebalance: every MA_REBALANCE_HOURS, recompute MA5/MA60 trend;
    on trend change, cancel buy-side orders and rebuild grid asymmetrically
  - Kill switch: cancel_all + optionally market-sell all base

State persisted to SQLite so the bot can resume after restart.
"""

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from okx_executor import OkxExecutor

log = logging.getLogger(__name__)


@dataclass
class GridConfig:
    range_pct:        float = 5.0
    num_grids:        int   = 20
    grid_step_pct:    float = 0.5   # take-profit margin per filled buy


@dataclass
class DCAConfig:
    interval_hours:   float = 4.0
    amount_usdt:      float = 10.0
    base_amount_usdt: float = 10.0  # reset target after MA rebalance


@dataclass
class MAConfig:
    short_period:     int   = 5
    long_period:      int   = 60
    rebalance_hours:  int   = 6
    threshold_pct:    float = 0.5


class LiveMAGrid:
    """Live trading bot using MA_Grid+DCA logic on real OKX orders."""

    def __init__(self,
                 executor: OkxExecutor,
                 symbol: str,
                 allocation_usdt: float,
                 grid: GridConfig = None,
                 dca:  DCAConfig  = None,
                 ma:   MAConfig   = None,
                 db_path: str     = "data/live_trader.db"):
        self.executor   = executor
        self.symbol     = symbol
        self.base_ccy   = symbol.split("/")[0]
        self.alloc      = allocation_usdt
        self.grid       = grid or GridConfig()
        self.dca        = dca  or DCAConfig()
        self.ma         = ma   or MAConfig()
        self.db_path    = db_path

        # Runtime state
        self.entry_price:    Optional[float] = None
        self.current_trend:  str   = "neutral"
        self.last_dca_ts:    float = 0.0
        self.last_rebalance_ts: float = 0.0
        self.last_known_order_ids: set[str] = set()

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    # Status enum (string-typed for SQLite simplicity)
    STATUS_RUNNING  = "running"
    STATUS_PAUSED   = "paused"
    STATUS_STOPPED  = "stopped"   # cancelled all, possibly sold (kill_switch)
    STATUS_ERRORED  = "errored"

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS live_session (
                    id INTEGER PRIMARY KEY,
                    started_at TEXT, symbol TEXT, allocation REAL,
                    entry_price REAL, status TEXT
                );
                CREATE TABLE IF NOT EXISTS live_orders (
                    id TEXT PRIMARY KEY,
                    cl_ord_id TEXT, side TEXT, price REAL, amount REAL,
                    status TEXT, kind TEXT,
                    created_at TEXT, filled_at TEXT
                );
                CREATE TABLE IF NOT EXISTS live_fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT, ts TEXT, price REAL, amount REAL, side TEXT,
                    fee REAL, fee_ccy TEXT, kind TEXT
                );
                CREATE TABLE IF NOT EXISTS live_equity (
                    ts TEXT PRIMARY KEY, equity REAL, cash REAL, coin REAL,
                    coin_value REAL, mark_price REAL
                );
                CREATE TABLE IF NOT EXISTS live_trend (
                    ts TEXT PRIMARY KEY, trend TEXT, spread_pct REAL, price REAL
                );
            """)
            # Idempotent column migrations (for resume support)
            self._add_column_if_missing(conn, "live_session", "start_usdt",        "REAL")
            self._add_column_if_missing(conn, "live_session", "start_base",        "REAL")
            self._add_column_if_missing(conn, "live_session", "last_dca_ts",       "REAL")
            self._add_column_if_missing(conn, "live_session", "last_rebalance_ts", "REAL")
            self._add_column_if_missing(conn, "live_session", "current_trend",     "TEXT")
            self._add_column_if_missing(conn, "live_session", "ended_at",          "TEXT")

    @staticmethod
    def _add_column_if_missing(conn, table: str, col: str, type_: str) -> None:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_}")

    def _save_order(self, order: dict, kind: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO live_orders
                (id, cl_ord_id, side, price, amount, status, kind, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (order["id"], order.get("clientOrderId") or order.get("info", {}).get("clOrdId"),
                  order["side"], order.get("price") or 0.0, order["amount"],
                  order.get("status") or "open", kind, datetime.now(timezone.utc).isoformat()))

    def _save_fill(self, order_id: str, price: float, amount: float, side: str,
                   fee: float = 0, fee_ccy: str = "USDT", kind: str = "grid"):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO live_fills (order_id, ts, price, amount, side, fee, fee_ccy, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, datetime.now(timezone.utc).isoformat(),
                  price, amount, side, fee, fee_ccy, kind))
            conn.execute("UPDATE live_orders SET status='closed', filled_at=? WHERE id=?",
                         (datetime.now(timezone.utc).isoformat(), order_id))

    def _save_equity(self, equity: float, cash: float, coin: float, mark: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO live_equity (ts, equity, cash, coin, coin_value, mark_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(),
                  equity, cash, coin, coin * mark, mark))

    def _save_trend(self, trend: str, spread: float, price: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO live_trend (ts, trend, spread_pct, price)
                VALUES (?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), trend, spread, price))

    def _persist_timer(self, column: str, value) -> None:
        """Update a single column in the current running session row.
        Idempotent — silently no-ops if no running session exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE live_session SET {column}=? WHERE status=?",
                (value, self.STATUS_RUNNING),
            )

    # ------------------------------------------------------------------
    # Grid setup
    # ------------------------------------------------------------------

    def setup_initial_grid(self, start_usdt: float = 0.0, start_base: float = 0.0) -> None:
        """Place N buy limit orders below current price.
        Total notional ≈ allocation. Each order ≈ allocation/N.
        Inserts live_session row FIRST so dashboard session-filter sees this run.
        start_usdt / start_base: wallet snapshot for equity isolation (persisted)."""
        ticker = self.executor.fetch_ticker(self.symbol)
        mark = ticker["last"]
        self.entry_price = mark

        # Record session BEFORE placing orders so order.created_at >= session.started_at
        # (dashboard filters by `WHERE created_at >= session.started_at`)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO live_session
                  (started_at, symbol, allocation, entry_price, status, start_usdt, start_base)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), self.symbol, self.alloc,
                  self.entry_price, self.STATUS_RUNNING, start_usdt, start_base))

        # Asymmetric grid based on current trend (neutral at start)
        upper_pct, lower_pct = self._grid_bounds(self.current_trend)

        # Place buy orders below mark
        low_price  = mark * (1 - lower_pct / 100)
        high_price = mark
        n_buys     = self.grid.num_grids
        per_order_usdt = self.alloc / n_buys

        step = (high_price - low_price) / n_buys
        orders = []
        for i in range(n_buys):
            price = round(low_price + i * step, 1)
            amount = round(per_order_usdt / price, 6)
            if amount * price < 5:  # OKX min order ≈ $5
                continue
            orders.append({"side": "buy", "amount": amount, "price": price,
                           "cl_ord_id": f"initb{i:02d}{int(time.time())}"[:32]})

        log.info(f"[GRID] placing {len(orders)} initial BUY orders "
                 f"in range ${low_price:,.0f}-${high_price:,.0f} "
                 f"(${per_order_usdt:.2f}/order)")

        # OKX batch limit = 20 per call
        results = []
        for i in range(0, len(orders), 20):
            chunk = orders[i:i+20]
            batch = self.executor.place_batch_limit(self.symbol, chunk)
            results.extend(batch)

        for r in results:
            self._save_order(r, kind="grid_init")
            self.last_known_order_ids.add(r["id"])

        log.info(f"[GRID] initial setup complete — entry ${self.entry_price:,.2f}")

    # ------------------------------------------------------------------
    # Resume / pause lifecycle
    # ------------------------------------------------------------------

    MAX_RESUME_AGE_SEC = 7 * 86400   # don't resume sessions older than a week

    def maybe_resume_session(self) -> Optional[dict]:
        """Return latest resumable session row, or None if must start fresh.
        Resumable = status in ('running', 'paused'), within MAX_RESUME_AGE_SEC,
        and same symbol + same allocation as current config."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM live_session
                WHERE status IN (?, ?)
                ORDER BY id DESC LIMIT 1
            """, (self.STATUS_RUNNING, self.STATUS_PAUSED)).fetchone()
        if not row:
            return None
        s = dict(row)
        # Validate
        try:
            started = datetime.fromisoformat(s["started_at"])
            age = (datetime.now(timezone.utc) - started).total_seconds()
        except Exception:
            log.warning(f"[RESUME] couldn't parse started_at={s['started_at']}, skip")
            return None
        if age > self.MAX_RESUME_AGE_SEC:
            log.warning(f"[RESUME] session #{s['id']} too old ({age/86400:.1f}d), start fresh")
            return None
        if s["symbol"] != self.symbol:
            log.warning(f"[RESUME] session #{s['id']} symbol mismatch ({s['symbol']} vs {self.symbol}), start fresh")
            return None
        if abs((s["allocation"] or 0) - self.alloc) > 0.01:
            log.warning(f"[RESUME] session #{s['id']} allocation changed "
                        f"(${s['allocation']:.2f} → ${self.alloc:.2f}), start fresh")
            return None
        return s

    def resume_from(self, session: dict) -> tuple[float, float]:
        """Reconcile state with OKX, restore in-memory timers/trend.
        Returns (start_usdt, start_base) for the engine's equity isolation."""
        log.info(f"[RESUME] session #{session['id']} status={session['status']} "
                 f"started {session['started_at']}")
        self.entry_price        = session["entry_price"]
        self.last_dca_ts        = session.get("last_dca_ts") or 0.0
        self.last_rebalance_ts  = session.get("last_rebalance_ts") or 0.0
        self.current_trend      = session.get("current_trend") or "neutral"

        # Reconcile open orders: OKX vs DB
        okx_open  = self.executor.fetch_open_orders(self.symbol)
        okx_ids   = {o["id"] for o in okx_open}

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            db_open = conn.execute(
                "SELECT id FROM live_orders WHERE status='open' AND created_at >= ?",
                (session["started_at"],)
            ).fetchall()
        db_ids = {r["id"] for r in db_open}

        known   = okx_ids & db_ids
        orphans = okx_ids - db_ids    # on OKX but missing in our DB
        missing = db_ids - okx_ids    # in our DB but gone from OKX (filled or cancelled)

        log.info(f"[RESUME] OKX={len(okx_ids)}  DB={len(db_ids)}  "
                 f"known={len(known)}  orphans={len(orphans)}  missing={len(missing)}")

        # Adopt orphan orders (e.g. bot crashed before saving them)
        for oid in orphans:
            order = next(o for o in okx_open if o["id"] == oid)
            self._save_order(order, kind="resumed_orphan")
            log.warning(f"[RESUME] adopting orphan order {oid} {order['side']} "
                        f"{order['amount']} @ ${order.get('price') or 0:,.2f}")

        # Resolve missing orders: filled or cancelled outside our knowledge?
        for oid in missing:
            try:
                order = self.executor.fetch_order(oid, self.symbol)
                if order.get("status") in ("closed", "filled"):
                    self._save_fill(
                        oid, order.get("price") or 0, order.get("filled") or 0,
                        order.get("side"),
                        fee=(order.get("fee") or {}).get("cost") or 0,
                        fee_ccy=(order.get("fee") or {}).get("currency") or "USDT",
                        kind="resumed_late",
                    )
                    log.info(f"[RESUME] order {oid} filled in our absence: "
                             f"{order['side']} {order.get('filled')} @ ${order.get('price') or 0:,.2f}")
                else:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute("UPDATE live_orders SET status=? WHERE id=?",
                                     ("cancelled", oid))
                    log.warning(f"[RESUME] order {oid} cancelled outside bot (status={order.get('status')})")
            except Exception as e:
                log.warning(f"[RESUME] couldn't resolve missing order {oid}: {e}")
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("UPDATE live_orders SET status=? WHERE id=?",
                                 ("lost", oid))

        # Take over tracking
        self.last_known_order_ids = okx_ids

        # Mark session running again
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE live_session SET status=?, ended_at=NULL WHERE id=?",
                (self.STATUS_RUNNING, session["id"]),
            )

        start_usdt = session.get("start_usdt") or 0.0
        start_base = session.get("start_base") or 0.0
        log.info(f"[RESUME] complete — entry ${self.entry_price:,.2f}  trend={self.current_trend}  "
                 f"DCA last={int(self.last_dca_ts)}  rebal last={int(self.last_rebalance_ts)}")
        return start_usdt, start_base

    def graceful_pause(self) -> None:
        """Mark session paused (keep orders on OKX so resume can continue).
        Called on SIGINT/SIGTERM via main loop's exit handler."""
        log.info("[PAUSE] marking session paused — orders remain on OKX")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE live_session SET
                    status = ?,
                    ended_at = ?,
                    last_dca_ts = ?,
                    last_rebalance_ts = ?,
                    current_trend = ?
                WHERE status = ?
            """, (self.STATUS_PAUSED, datetime.now(timezone.utc).isoformat(),
                  self.last_dca_ts, self.last_rebalance_ts, self.current_trend,
                  self.STATUS_RUNNING))

    def _grid_bounds(self, trend: str) -> tuple[float, float]:
        """Return (upper_pct, lower_pct) based on trend."""
        if trend == "bull":
            return 7.0, 3.0
        elif trend == "bear":
            return 3.0, 7.0
        return self.grid.range_pct, self.grid.range_pct

    # ------------------------------------------------------------------
    # Fill detection (poll-based for Phase 1; WS for Phase 2)
    # ------------------------------------------------------------------

    def poll_fills(self) -> list[dict]:
        """Compare current open orders to last-known set; orders that
        DISAPPEARED are likely filled (or cancelled by us — we ignore those)."""
        current = self.executor.fetch_open_orders(self.symbol)
        current_ids = {o["id"] for o in current}
        vanished = self.last_known_order_ids - current_ids

        fills = []
        for oid in vanished:
            try:
                order = self.executor.fetch_order(oid, self.symbol)
                if order.get("status") in ("closed", "filled"):
                    fills.append(order)
                    self._save_fill(
                        oid, order["price"], order["filled"], order["side"],
                        fee=order.get("fee", {}).get("cost", 0),
                        fee_ccy=order.get("fee", {}).get("currency", "USDT"),
                        kind="grid",
                    )
                    log.info(f"[FILL] {order['side']} {order['filled']} @ ${order['price']:,.2f}  id={oid}")
            except Exception as e:
                log.warning(f"[FILL] couldn't fetch vanished order {oid}: {e}")

        self.last_known_order_ids = current_ids
        return fills

    def replenish_after_fills(self, fills: list[dict]) -> None:
        """For each filled buy → place sell above; for each filled sell → place buy below."""
        replacements = []
        for fill in fills:
            price = fill["price"]
            amount = fill["filled"]
            if fill["side"] == "buy":
                new_price = round(price * (1 + self.grid.grid_step_pct / 100), 1)
                replacements.append({"side": "sell", "amount": amount, "price": new_price,
                                     "cl_ord_id": f"repls{int(time.time()*1000)}"[:32]})
            else:  # sell fill → buy below
                new_price = round(price * (1 - self.grid.grid_step_pct / 100), 1)
                new_amount = round(amount * price / new_price, 6)  # approx same USDT
                replacements.append({"side": "buy", "amount": new_amount, "price": new_price,
                                     "cl_ord_id": f"replb{int(time.time()*1000)}"[:32]})

        if not replacements:
            return

        log.info(f"[REPLENISH] placing {len(replacements)} replacement orders")
        for i in range(0, len(replacements), 20):
            chunk = replacements[i:i+20]
            try:
                batch = self.executor.place_batch_limit(self.symbol, chunk)
                for r in batch:
                    self._save_order(r, kind="grid_repl")
                    self.last_known_order_ids.add(r["id"])
            except Exception as e:
                log.error(f"[REPLENISH] failed: {e}")

    # ------------------------------------------------------------------
    # DCA — scheduled market buy
    # ------------------------------------------------------------------

    def dca_due(self, now_ts: float) -> bool:
        return (now_ts - self.last_dca_ts) >= self.dca.interval_hours * 3600

    def do_dca(self, now_ts: float) -> Optional[dict]:
        if not self.dca_due(now_ts):
            return None
        # Adjust DCA size by trend
        amount = self.dca.amount_usdt
        bal = self.executor.fetch_balance()
        cash = bal.get("USDT", {}).get("free", 0)
        if cash < amount:
            log.warning(f"[DCA] skip — insufficient cash (${cash:.2f} < ${amount:.2f})")
            return None
        try:
            order = self.executor.place_market_buy_usdt(self.symbol, amount,
                                                       cl_ord_id=f"dca{int(now_ts)}"[:32])
            self._save_order(order, kind="dca")
            # DCA market buys fill immediately; record fill too
            self._save_fill(order["id"], order.get("average") or order.get("price") or 0,
                            order.get("filled") or 0, "buy", kind="dca")
            self.last_dca_ts = now_ts
            self._persist_timer("last_dca_ts", now_ts)
            log.info(f"[DCA] bought ${amount:.2f} of {self.symbol}")
            return order
        except Exception as e:
            log.error(f"[DCA] failed: {e}")
            return None

    # ------------------------------------------------------------------
    # MA rebalance
    # ------------------------------------------------------------------

    def rebalance_due(self, now_ts: float) -> bool:
        return (now_ts - self.last_rebalance_ts) >= self.ma.rebalance_hours * 3600

    def detect_trend(self) -> tuple[str, float]:
        """Fetch recent 1h candles, compute MA5 vs MA60 spread."""
        # need at least ma_long candles
        candles = self.executor.exchange.fetch_ohlcv(self.symbol, "1h", limit=self.ma.long_period + 5)
        closes = [c[4] for c in candles]
        if len(closes) < self.ma.long_period:
            return "neutral", 0.0
        ma_s = sum(closes[-self.ma.short_period:]) / self.ma.short_period
        ma_l = sum(closes[-self.ma.long_period:]) / self.ma.long_period
        spread = (ma_s - ma_l) / ma_l * 100
        if spread > self.ma.threshold_pct:
            return "bull", spread
        if spread < -self.ma.threshold_pct:
            return "bear", spread
        return "neutral", spread

    def rebalance_check(self, now_ts: float) -> Optional[str]:
        """Returns new trend if changed, else None."""
        if not self.rebalance_due(now_ts):
            return None
        trend, spread = self.detect_trend()
        mark = self.executor.fetch_ticker(self.symbol)["last"]
        self._save_trend(trend, spread, mark)
        self.last_rebalance_ts = now_ts
        self._persist_timer("last_rebalance_ts", now_ts)

        if trend == self.current_trend:
            log.info(f"[MA] trend unchanged: {trend} (spread {spread:+.2f}%)")
            self._persist_timer("current_trend", trend)
            return None

        log.warning(f"[MA] TREND CHANGE: {self.current_trend} → {trend}  (spread {spread:+.2f}%)")
        # Cancel only buy-side grid orders (keep sells = profit targets)
        open_orders = self.executor.fetch_open_orders(self.symbol)
        buy_ids = [o["id"] for o in open_orders if o["side"] == "buy"]
        if buy_ids:
            log.info(f"[MA] cancelling {len(buy_ids)} buy orders to rebuild")
            for i in range(0, len(buy_ids), 20):
                chunk = buy_ids[i:i+20]
                try:
                    self.executor.exchange.cancel_orders(chunk, self.symbol)
                except Exception as e:
                    log.error(f"[MA] cancel chunk failed: {e}")
        self.current_trend = trend
        self._persist_timer("current_trend", trend)

        # Rebuild buys around current mark with new asymmetric range + DCA size
        upper_pct, lower_pct = self._grid_bounds(trend)
        if trend == "bull":
            self.dca.amount_usdt = self.dca.base_amount_usdt * 1.3
        elif trend == "bear":
            self.dca.amount_usdt = self.dca.base_amount_usdt * 0.5
        else:
            self.dca.amount_usdt = self.dca.base_amount_usdt
        log.info(f"[MA] new grid: -{lower_pct}% / +{upper_pct}%  DCA=${self.dca.amount_usdt:.2f}")
        self._rebuild_buy_grid(mark, lower_pct)
        return trend

    def _rebuild_buy_grid(self, mark: float, lower_pct: float) -> None:
        """Place fresh buy orders below current mark in (mark*(1-lower_pct/100), mark) range."""
        bal = self.executor.fetch_balance()
        cash = bal.get("USDT", {}).get("free", 0)
        if cash < 50:
            log.warning(f"[MA] only ${cash:.2f} cash — skipping buy grid rebuild")
            return
        # use 80% of free cash for new buy grid (leave 20% buffer for DCA)
        usable = cash * 0.8
        n = self.grid.num_grids
        per_order = usable / n
        low_price = mark * (1 - lower_pct / 100)
        step = (mark - low_price) / n
        orders = []
        for i in range(n):
            price = round(low_price + i * step, 1)
            amount = round(per_order / price, 6)
            if amount * price < 5:
                continue
            orders.append({"side": "buy", "amount": amount, "price": price,
                           "cl_ord_id": f"rebab{i:02d}{int(time.time())}"[:32]})

        for i in range(0, len(orders), 20):
            try:
                batch = self.executor.place_batch_limit(self.symbol, orders[i:i+20])
                for r in batch:
                    self._save_order(r, kind="grid_rebal")
                    self.last_known_order_ids.add(r["id"])
            except Exception as e:
                log.error(f"[MA] rebuild batch failed: {e}")

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def kill_switch(self, market_sell_base: bool = False, max_sell_amount: float = None) -> None:
        """Cancel all bot orders. Optionally market-sell base, capped at
        `max_sell_amount` so we don't liquidate pre-existing wallet holdings.
        """
        log.critical(f"[KILL] cancelling all orders for {self.symbol}")
        try:
            self.executor.cancel_all(self.symbol)
        except Exception as e:
            log.error(f"[KILL] cancel_all failed: {e}")
        if market_sell_base:
            bal = self.executor.fetch_balance()
            coin_free = bal.get(self.base_ccy, {}).get("free", 0)
            # Cap sell to whatever the bot accumulated (caller should pass max_sell_amount)
            sell_amt = coin_free if max_sell_amount is None else min(coin_free, max_sell_amount)
            if sell_amt > 0:
                log.critical(f"[KILL] market-selling {sell_amt:.6f} {self.base_ccy} "
                             f"(free={coin_free}, cap={max_sell_amount})")
                try:
                    self.executor.exchange.create_order(
                        self.symbol, "market", "sell", sell_amt, None,
                        {"tdMode": "cash", "clOrdId": f"kill{int(time.time())}"[:32]},
                    )
                except Exception as e:
                    log.error(f"[KILL] market-sell failed: {e}")
            else:
                log.info(f"[KILL] nothing to sell (free={coin_free}, cap={max_sell_amount})")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE live_session SET status=?, ended_at=? WHERE status IN (?, ?)",
                (self.STATUS_STOPPED, datetime.now(timezone.utc).isoformat(),
                 self.STATUS_RUNNING, self.STATUS_PAUSED),
            )
