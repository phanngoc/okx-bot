#!/usr/bin/env python3
"""Read-only web dashboard for the live MA_Grid bot.

Serves:
  GET  /                — HTML dashboard (dashboard.html)
  GET  /api/status      — current bot state (equity, PnL, trend, last tick)
  GET  /api/equity      — equity timeline (last N points)
  GET  /api/fills       — fill history (last N rows)
  GET  /api/trend       — MA trend detection history
  GET  /api/orders      — open orders summary

Run via: python dashboard.py     (or via pm2: pm2 start dashboard.py --name okx-dash)
Default port 5050.
"""

import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

DB_LIVE     = Path("data/live_trader.db")
DB_ARENA    = Path("data/trading.db")
DASH_HTML   = Path("dashboard.html")

SYMBOL      = os.getenv("SYMBOL", "BTC/USDT")
ALLOCATION  = float(os.getenv("ALLOCATION_USDT", "150"))

app = Flask(__name__)


def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------- HTML

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


# ---------------------------------------------------------------- API

@app.route("/api/status")
def api_status():
    """Latest equity row + summary metrics (filtered to current session)."""
    # Session info first — we filter all metrics by current session start (with buffer)
    session = _query(DB_LIVE, "SELECT * FROM live_session ORDER BY id DESC LIMIT 1")
    session_start = _session_start()

    rows = _query(DB_LIVE,
        "SELECT * FROM live_equity WHERE ts >= ? ORDER BY ts DESC LIMIT 1",
        (session_start,))
    if not rows:
        return jsonify({"status": "no_data", "allocation": ALLOCATION, "symbol": SYMBOL})

    latest = rows[0]
    # Source-of-truth allocation = whatever the session was started with,
    # not the current .env value (which may have changed)
    allocation = session[0]["allocation"] if session else ALLOCATION

    # Peak equity within current session only — avoids stale rows from older runs
    peak_row = _query(DB_LIVE,
        "SELECT MAX(equity) as peak FROM live_equity WHERE ts >= ?",
        (session_start,))
    peak = peak_row[0]["peak"] if peak_row and peak_row[0]["peak"] else latest["equity"]
    dd_pct = (peak - latest["equity"]) / peak * 100 if peak > 0 else 0

    # Latest trend (also session-scoped)
    trend = _query(DB_LIVE,
        "SELECT * FROM live_trend WHERE ts >= ? ORDER BY ts DESC LIMIT 1",
        (session_start,))

    # Counts (current session only)
    n_fills  = _query(DB_LIVE, "SELECT COUNT(*) as n FROM live_fills WHERE ts >= ?", (session_start,))[0]["n"]
    n_open   = _query(DB_LIVE, "SELECT COUNT(*) as n FROM live_orders WHERE status='open' AND created_at >= ?", (session_start,))[0]["n"]
    n_closed = _query(DB_LIVE, "SELECT COUNT(*) as n FROM live_orders WHERE status='closed' AND created_at >= ?", (session_start,))[0]["n"]
    n_grid   = _query(DB_LIVE, "SELECT COUNT(*) as n FROM live_fills WHERE kind='grid' AND ts >= ?", (session_start,))[0]["n"]
    n_dca    = _query(DB_LIVE, "SELECT COUNT(*) as n FROM live_fills WHERE kind='dca' AND ts >= ?", (session_start,))[0]["n"]

    return jsonify({
        "status":         session[0]["status"] if session else "unknown",
        "symbol":         SYMBOL,
        "allocation":     allocation,
        "equity":         latest["equity"],
        "cash":           latest["cash"],
        "coin":           latest["coin"],
        "coin_value":     latest["coin_value"],
        "mark_price":     latest["mark_price"],
        "total_pnl_pct":  (latest["equity"] - allocation) / allocation * 100,
        "drawdown_pct":   dd_pct,
        "peak_equity":    peak,
        "last_tick":      latest["ts"],
        "trend":          trend[0]["trend"]      if trend else "neutral",
        "trend_spread":   trend[0]["spread_pct"] if trend else 0.0,
        "n_fills":        n_fills,
        "n_grid_fills":   n_grid,
        "n_dca_fills":    n_dca,
        "n_open_orders":  n_open,
        "n_closed_orders":n_closed,
        "session_started": session[0]["started_at"] if session else None,
    })


def _session_start(buffer_sec: int = 60) -> str:
    """Return current session's started_at MINUS buffer_sec to catch any
    orders placed just before the session row was inserted (legacy data)."""
    from datetime import datetime as _dt, timedelta as _td
    s = _query(DB_LIVE, "SELECT started_at FROM live_session ORDER BY id DESC LIMIT 1")
    if not s:
        return "1970-01-01"
    try:
        t = _dt.fromisoformat(s[0]["started_at"])
        return (t - _td(seconds=buffer_sec)).isoformat()
    except Exception:
        return s[0]["started_at"]


@app.route("/api/equity")
def api_equity():
    """Equity timeline within current session."""
    limit = int(request.args.get("limit", 500))
    rows = _query(DB_LIVE,
        "SELECT ts, equity, mark_price, cash, coin FROM live_equity "
        "WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
        (_session_start(), limit))
    return jsonify(rows)


@app.route("/api/fills")
def api_fills():
    limit = int(request.args.get("limit", 100))
    rows = _query(DB_LIVE,
        "SELECT ts, side, price, amount, kind, fee, fee_ccy FROM live_fills "
        "WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
        (_session_start(), limit))
    return jsonify(rows)


@app.route("/api/trend")
def api_trend():
    limit = int(request.args.get("limit", 50))
    rows = _query(DB_LIVE,
        "SELECT ts, trend, spread_pct, price FROM live_trend "
        "WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
        (_session_start(), limit))
    return jsonify(rows)


@app.route("/api/orders")
def api_orders():
    """Open orders summary (current session)."""
    rows = _query(DB_LIVE,
        "SELECT id, side, price, amount, kind, created_at FROM live_orders "
        "WHERE status='open' AND created_at >= ? ORDER BY price DESC",
        (_session_start(),))
    return jsonify(rows)


@app.route("/api/arena")
def api_arena():
    """Backtest leaderboards from arena (read-only history)."""
    sessions = _query(DB_ARENA,
        "SELECT s.id, s.symbol, s.duration_hours, s.entry_price, s.exit_price, s.mode, "
        "       s.started_at "
        "FROM sessions s ORDER BY s.id DESC LIMIT 20")
    for s in sessions:
        s["results"] = _query(DB_ARENA,
            "SELECT strategy, final_roi_pct, alpha_vs_buyhold, total_trades, rank "
            "FROM results WHERE session_id=? ORDER BY rank ASC", (s["id"],))
    return jsonify(sessions)


# ---------------------------------------------------------------- main

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "5050"))
    print(f"\n┌─ OKX bot dashboard ─────────────────────────────────────────")
    print(f"│  http://127.0.0.1:{port}")
    print(f"│  Live DB:  {DB_LIVE}  exists={DB_LIVE.exists()}")
    print(f"│  Arena DB: {DB_ARENA} exists={DB_ARENA.exists()}")
    print(f"└─────────────────────────────────────────────────────────────\n")
    app.run(host="127.0.0.1", port=port, debug=False)
