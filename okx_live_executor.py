"""OkxLiveExecutor — Executor ABC backed by real OKX trading.

Translates engine `Intent`s into ccxt calls, tracks placed orders, detects
fills by polling `fetch_open_orders` for vanished IDs and resolving via
`fetch_order`. Persists state to SQLite for dashboard + resume.

Also bundles LiveSessionDB: session lifecycle + reconciliation logic
previously embedded in `ma_grid_live.LiveMAGrid`.
"""

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from okx_executor import OkxExecutor
from strategy_engine.executor import Executor
from strategy_engine.types import (
    Event,
    Fill,
    Intent,
    IntentKind,
    Order,
    OrderStatus,
)

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Session persistence (extracted from ma_grid_live.LiveMAGrid)
# ----------------------------------------------------------------------

@dataclass
class SessionRecord:
    """Frozen-ish view of a live_session row."""
    id:            int
    started_at:    str
    symbol:        str
    allocation:    float
    entry_price:   float
    status:        str
    start_usdt:    float
    start_base:    float
    last_dca_ts:   float
    last_rebalance_ts: float
    current_trend: str


class LiveSessionDB:
    """SQLite-backed session + order + fill + equity store.
    Identical schema to ma_grid_live for dashboard compatibility."""

    STATUS_RUNNING = "running"
    STATUS_PAUSED  = "paused"
    STATUS_STOPPED = "stopped"
    STATUS_ERRORED = "errored"
    MAX_RESUME_AGE_SEC = 7 * 86400

    def __init__(self, db_path: str = "data/live_trader.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
            # Idempotent migrations
            for col, typ in [
                ("start_usdt", "REAL"), ("start_base", "REAL"),
                ("last_dca_ts", "REAL"), ("last_rebalance_ts", "REAL"),
                ("current_trend", "TEXT"), ("ended_at", "TEXT"),
            ]:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(live_session)").fetchall()]
                if col not in cols:
                    conn.execute(f"ALTER TABLE live_session ADD COLUMN {col} {typ}")

    def create_session(self, symbol: str, allocation: float, entry_price: float,
                       start_usdt: float, start_base: float) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("""
                INSERT INTO live_session
                  (started_at, symbol, allocation, entry_price, status, start_usdt, start_base)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), symbol, allocation,
                  entry_price, self.STATUS_RUNNING, start_usdt, start_base))
            return cur.lastrowid

    def maybe_resume(self, symbol: str, allocation: float) -> Optional[SessionRecord]:
        """Return latest resumable session matching symbol + allocation."""
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
        try:
            started = datetime.fromisoformat(s["started_at"])
            age = (datetime.now(timezone.utc) - started).total_seconds()
        except Exception:
            log.warning(f"[RESUME] bad started_at, skip session #{s['id']}")
            return None
        if age > self.MAX_RESUME_AGE_SEC:
            log.warning(f"[RESUME] session #{s['id']} too old ({age/86400:.1f}d), start fresh")
            return None
        if s["symbol"] != symbol:
            log.warning(f"[RESUME] session #{s['id']} symbol mismatch, start fresh")
            return None
        if abs((s["allocation"] or 0) - allocation) > 0.01:
            log.warning(f"[RESUME] session #{s['id']} alloc changed, start fresh")
            return None
        return SessionRecord(
            id=s["id"], started_at=s["started_at"], symbol=s["symbol"],
            allocation=s["allocation"], entry_price=s["entry_price"], status=s["status"],
            start_usdt=s.get("start_usdt") or 0.0,
            start_base=s.get("start_base") or 0.0,
            last_dca_ts=s.get("last_dca_ts") or 0.0,
            last_rebalance_ts=s.get("last_rebalance_ts") or 0.0,
            current_trend=s.get("current_trend") or "neutral",
        )

    def mark_running(self, session_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE live_session SET status=?, ended_at=NULL WHERE id=?",
                (self.STATUS_RUNNING, session_id),
            )

    def mark_paused(self, snapshot: dict) -> None:
        """Save strategy snapshot fields + flip running session to paused."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE live_session SET
                    status=?, ended_at=?,
                    last_dca_ts=?, last_rebalance_ts=?, current_trend=?
                WHERE status=?
            """, (self.STATUS_PAUSED, now,
                  snapshot.get("last_dca_ts", 0.0),
                  snapshot.get("last_rebalance_ts", 0.0),
                  snapshot.get("current_trend", "neutral"),
                  self.STATUS_RUNNING))

    def mark_stopped(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE live_session SET status=?, ended_at=? WHERE status IN (?, ?)",
                (self.STATUS_STOPPED, now, self.STATUS_RUNNING, self.STATUS_PAUSED),
            )

    def save_order(self, order_id: str, cl_ord_id: str, side: str, price: float,
                   amount: float, status: str, kind: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO live_orders
                  (id, cl_ord_id, side, price, amount, status, kind, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, cl_ord_id, side, price, amount,
                  status, kind, datetime.now(timezone.utc).isoformat()))

    def save_fill(self, fill: Fill, kind: str = "grid") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO live_fills (order_id, ts, price, amount, side, fee, fee_ccy, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (fill.order_id, now, fill.price, fill.amount, fill.side,
                  fill.fee, fill.fee_ccy, kind))
            conn.execute("UPDATE live_orders SET status=?, filled_at=? WHERE id=?",
                         ("closed", now, fill.order_id))

    def save_equity(self, equity: float, cash: float, coin: float, mark: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO live_equity (ts, equity, cash, coin, coin_value, mark_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now, equity, cash, coin, coin * mark, mark))

    def save_trend(self, trend: str, spread: float, price: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO live_trend (ts, trend, spread_pct, price)
                VALUES (?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), trend, spread, price))

    def persist_timer(self, column: str, value) -> None:
        """Update a single session column on the currently-running row."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE live_session SET {column}=? WHERE status=?",
                (value, self.STATUS_RUNNING),
            )

    def open_order_ids_for_session(self, session_started_at: str) -> set[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id FROM live_orders WHERE status='open' AND created_at >= ?",
                (session_started_at,),
            ).fetchall()
        return {r[0] for r in rows}


# ----------------------------------------------------------------------
# OkxLiveExecutor — implements engine Executor ABC against real OKX
# ----------------------------------------------------------------------

class OkxLiveExecutor(Executor):
    """Live broker adapter. Engine drives this with Intents; we translate
    to ccxt calls + track resulting orders + detect fills."""

    def __init__(self, okx: OkxExecutor, symbol: str,
                 db: Optional[LiveSessionDB] = None,
                 max_order_usdt: float = 100.0):
        self.okx = okx
        self.symbol = symbol
        self.db = db
        self.max_order_usdt = max_order_usdt
        self.tracked_ids: set[str] = set()       # all our placed orders
        self.id_tag: dict[str, str] = {}         # id → strategy tag
        self.id_kind: dict[str, str] = {}        # id → "limit"/"market"

    # ------------------------------------------------------------------
    # Resume support
    # ------------------------------------------------------------------

    def adopt_existing(self, started_at: str) -> dict:
        """Reconcile DB-known + OKX-actual open orders.
        Returns counts: {known, orphans, missing}."""
        if not self.db:
            return {"known": 0, "orphans": 0, "missing": 0}
        okx_open = self.okx.fetch_open_orders(self.symbol)
        okx_ids = {o["id"] for o in okx_open}
        db_ids = self.db.open_order_ids_for_session(started_at)

        known   = okx_ids & db_ids
        orphans = okx_ids - db_ids    # on exchange but missing in DB
        missing = db_ids - okx_ids    # in DB but gone from exchange

        # Adopt orphans
        for oid in orphans:
            order = next(o for o in okx_open if o["id"] == oid)
            self.db.save_order(oid, order.get("clientOrderId") or "",
                              order["side"], order.get("price") or 0,
                              order["amount"], "open", "resumed_orphan")
            log.warning(f"[ADOPT] orphan order {oid} {order['side']} "
                        f"{order['amount']} @ ${order.get('price') or 0:,.2f}")

        # Resolve missing
        for oid in missing:
            try:
                order = self.okx.fetch_order(oid, self.symbol)
                if order.get("status") in ("closed", "filled"):
                    fill = Fill(
                        order_id=oid, symbol=self.symbol, side=order.get("side"),
                        price=order.get("price") or 0,
                        amount=order.get("filled") or 0,
                        ts=time.time(),
                        fee=(order.get("fee") or {}).get("cost") or 0,
                        fee_ccy=(order.get("fee") or {}).get("currency") or "USDT",
                        tag="resumed_late",
                    )
                    self.db.save_fill(fill, kind="resumed_late")
                else:
                    with sqlite3.connect(self.db.db_path) as conn:
                        conn.execute("UPDATE live_orders SET status='cancelled' WHERE id=?", (oid,))
            except Exception as e:
                log.warning(f"[ADOPT] couldn't resolve missing order {oid}: {e}")

        self.tracked_ids = okx_ids
        return {"known": len(known), "orphans": len(orphans), "missing": len(missing)}

    # ------------------------------------------------------------------
    # Executor interface
    # ------------------------------------------------------------------

    def execute(self, intent: Intent) -> Optional[Order]:
        try:
            if intent.kind == IntentKind.PLACE_LIMIT:
                return self._place_limit(intent)
            if intent.kind == IntentKind.PLACE_MARKET_BUY:
                return self._place_market_buy(intent)
            if intent.kind == IntentKind.PLACE_MARKET_SELL:
                return self._place_market_sell(intent)
            if intent.kind == IntentKind.CANCEL:
                self._cancel(intent.order_id)
                return None
            if intent.kind == IntentKind.CANCEL_ALL_SIDE:
                self._cancel_all_side(intent.side)
                return None
        except Exception as e:
            log.error(f"[OKX-EXEC] {intent.kind} failed: {e}")
            return None
        return None

    def poll_events(self, tick_ts: float) -> list[Event]:
        """Diff our tracked orders against OKX open orders. Vanished = filled or cancelled."""
        try:
            current = self.okx.fetch_open_orders(self.symbol)
        except Exception as e:
            log.warning(f"[OKX-EXEC] fetch_open_orders failed: {e}")
            return []
        current_ids = {o["id"] for o in current}
        vanished = self.tracked_ids - current_ids
        events: list[Event] = []
        for oid in vanished:
            try:
                order = self.okx.fetch_order(oid, self.symbol)
                if order.get("status") not in ("closed", "filled"):
                    log.info(f"[OKX-EXEC] order {oid} {order.get('status')} (not a fill)")
                    continue
                tag = self.id_tag.get(oid, "")
                price = order.get("price") or order.get("average") or 0
                amount = order.get("filled") or 0
                fee = (order.get("fee") or {}).get("cost") or 0
                fee_ccy = (order.get("fee") or {}).get("currency") or "USDT"
                # Quote delta computation: for BUY, paid amount × price (full cost),
                # for SELL, received gross - fee
                if order.get("side") == "buy":
                    quote_delta = -(amount * price)
                else:
                    quote_delta = amount * price - (fee if fee_ccy == "USDT" else 0)
                fill = Fill(
                    order_id=oid, symbol=self.symbol, side=order.get("side"),
                    price=price, amount=amount, ts=tick_ts,
                    quote_amount=quote_delta, fee=fee, fee_ccy=fee_ccy, tag=tag,
                )
                events.append(fill)
                if self.db:
                    self.db.save_fill(fill, kind=tag.split("_")[0] if tag else "grid")
                log.info(f"[FILL] {order.get('side')} {amount} @ ${price:,.2f}  id={oid}  tag={tag}")
            except Exception as e:
                log.warning(f"[OKX-EXEC] couldn't resolve vanished order {oid}: {e}")
        self.tracked_ids = current_ids
        return events

    def open_orders(self, symbol: str) -> list[Order]:
        raw = self.okx.fetch_open_orders(symbol)
        result = []
        for o in raw:
            result.append(Order(
                id=o["id"], cl_ord_id=o.get("clientOrderId") or "",
                symbol=symbol, side=o["side"], kind=o.get("type", "limit"),
                amount=o["amount"], price=o.get("price"),
                status=OrderStatus.OPEN,
                tag=self.id_tag.get(o["id"], ""),
            ))
        return result

    def balance(self, symbol: str) -> dict:
        bal = self.okx.fetch_balance()
        base_ccy = symbol.split("/")[0]
        return {
            "base":  bal.get(base_ccy, {}).get("total", 0.0),
            "quote": bal.get("USDT", {}).get("total", 0.0),
        }

    def portfolio_value(self, symbol: str, mark_price: float) -> float:
        b = self.balance(symbol)
        return b["quote"] + b["base"] * mark_price

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _place_limit(self, intent: Intent) -> Optional[Order]:
        order = self.okx.place_limit(self.symbol, intent.side, intent.amount, intent.price)
        oid = order["id"]
        self.tracked_ids.add(oid)
        self.id_tag[oid] = intent.tag
        self.id_kind[oid] = "limit"
        if self.db:
            self.db.save_order(
                oid, order.get("clientOrderId") or "",
                intent.side, intent.price, intent.amount, "open", intent.tag,
            )
        return Order(
            id=oid, cl_ord_id=order.get("clientOrderId") or "",
            symbol=self.symbol, side=intent.side, kind="limit",
            amount=intent.amount, price=intent.price,
            status=OrderStatus.OPEN, tag=intent.tag,
        )

    def _place_market_buy(self, intent: Intent) -> Optional[Order]:
        # OKX: market BUY size is QUOTE (USDT)
        order = self.okx.place_market_buy_usdt(self.symbol, intent.amount)
        oid = order["id"]
        self.id_tag[oid] = intent.tag
        self.id_kind[oid] = "market"
        # Market orders fill immediately — persist + emit fill synthetically
        # in next poll (or we could buffer here; engine handles either)
        if self.db:
            avg = order.get("average") or order.get("price") or 0
            filled = order.get("filled") or 0
            self.db.save_order(oid, order.get("clientOrderId") or "",
                              "buy", avg, filled, "closed", intent.tag)
            fill = Fill(
                order_id=oid, symbol=self.symbol, side="buy",
                price=avg, amount=filled, ts=time.time(),
                quote_amount=-intent.amount, tag=intent.tag,
            )
            self.db.save_fill(fill, kind=intent.tag.split("_")[0] if intent.tag else "dca")
        return Order(
            id=oid, cl_ord_id=order.get("clientOrderId") or "",
            symbol=self.symbol, side="buy", kind="market",
            amount=order.get("filled") or 0,
            price=order.get("average") or order.get("price"),
            status=OrderStatus.FILLED,
            filled_amount=order.get("filled") or 0,
            fill_price=order.get("average") or order.get("price") or 0,
            tag=intent.tag,
        )

    def _place_market_sell(self, intent: Intent) -> Optional[Order]:
        # `amount` is BASE for market sell
        order = self.okx.place_market_sell(self.symbol, intent.amount)
        oid = order["id"]
        self.id_tag[oid] = intent.tag
        self.id_kind[oid] = "market"
        if self.db:
            avg = order.get("average") or order.get("price") or 0
            filled = order.get("filled") or 0
            self.db.save_order(oid, order.get("clientOrderId") or "",
                              "sell", avg, filled, "closed", intent.tag)
        return Order(
            id=oid, cl_ord_id=order.get("clientOrderId") or "",
            symbol=self.symbol, side="sell", kind="market",
            amount=order.get("filled") or 0,
            price=order.get("average") or order.get("price"),
            status=OrderStatus.FILLED,
            filled_amount=order.get("filled") or 0,
            fill_price=order.get("average") or order.get("price") or 0,
            tag=intent.tag,
        )

    def _cancel(self, order_id: str) -> None:
        self.okx.cancel(order_id, self.symbol)
        self.tracked_ids.discard(order_id)

    def _cancel_all_side(self, side: Optional[str]) -> None:
        opens = self.okx.fetch_open_orders(self.symbol)
        ids = [o["id"] for o in opens if side is None or o["side"] == side]
        if not ids:
            return
        for i in range(0, len(ids), 20):
            chunk = ids[i:i+20]
            try:
                self.okx.exchange.cancel_orders(chunk, self.symbol)
                for oid in chunk:
                    self.tracked_ids.discard(oid)
            except Exception as e:
                log.error(f"[OKX-EXEC] cancel chunk failed: {e}")
