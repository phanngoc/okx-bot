"""SQLite storage for long-term strategy performance tracking."""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "trading.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_tables(conn)
    return conn


def _init_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            ended_at TEXT,
            symbol TEXT NOT NULL,
            budget REAL NOT NULL,
            duration_hours REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            mode TEXT NOT NULL DEFAULT 'live',
            status TEXT NOT NULL DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            epoch REAL NOT NULL,
            price REAL NOT NULL,
            strategy TEXT NOT NULL,
            portfolio_value REAL NOT NULL,
            roi_pct REAL NOT NULL,
            coin_balance REAL NOT NULL DEFAULT 0,
            usdt_balance REAL NOT NULL DEFAULT 0,
            total_trades INTEGER NOT NULL DEFAULT 0,
            total_fees REAL NOT NULL DEFAULT 0,
            total_slippage REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            epoch REAL NOT NULL,
            strategy TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            fill_price REAL NOT NULL,
            qty REAL NOT NULL,
            usdt REAL NOT NULL,
            fee REAL NOT NULL DEFAULT 0,
            slippage REAL NOT NULL DEFAULT 0,
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS debates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            epoch REAL NOT NULL,
            price REAL NOT NULL,
            bull_score REAL,
            bear_score REAL,
            final_score REAL,
            direction TEXT,
            confidence REAL,
            news_sentiment TEXT,
            news_score REAL
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            strategy TEXT NOT NULL,
            final_roi_pct REAL NOT NULL,
            alpha_vs_buyhold REAL NOT NULL,
            total_trades INTEGER NOT NULL DEFAULT 0,
            total_fees REAL NOT NULL DEFAULT 0,
            total_slippage REAL NOT NULL DEFAULT 0,
            total_cost REAL NOT NULL DEFAULT 0,
            portfolio_value REAL NOT NULL,
            rank INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_session ON snapshots(session_id, strategy);
        CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id, strategy);
        CREATE INDEX IF NOT EXISTS idx_results_session ON results(session_id);
    """)
    conn.commit()


def create_session(conn, symbol, budget, hours, entry_price, mode="live") -> int:
    cur = conn.execute(
        "INSERT INTO sessions (symbol, budget, duration_hours, entry_price, mode) VALUES (?,?,?,?,?)",
        (symbol, budget, hours, entry_price, mode),
    )
    conn.commit()
    return cur.lastrowid


def end_session(conn, session_id, exit_price):
    conn.execute(
        "UPDATE sessions SET ended_at=datetime('now'), exit_price=?, status='completed' WHERE id=?",
        (exit_price, session_id),
    )
    conn.commit()


def save_snapshot(conn, session_id, epoch, price, strategy, pv, roi, coin, usdt, trades, fees, slippage):
    conn.execute(
        """INSERT INTO snapshots
           (session_id, epoch, price, strategy, portfolio_value, roi_pct,
            coin_balance, usdt_balance, total_trades, total_fees, total_slippage)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, epoch, price, strategy, pv, roi, coin, usdt, trades, fees, slippage),
    )
    conn.commit()


def save_trade(conn, session_id, epoch, strategy, side, price, fill_price, qty, usdt, fee, slippage, reason=""):
    conn.execute(
        """INSERT INTO trades
           (session_id, epoch, strategy, side, price, fill_price, qty, usdt, fee, slippage, reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, epoch, strategy, side, price, fill_price, qty, usdt, fee, slippage, reason),
    )
    conn.commit()


def save_debate(conn, session_id, epoch, price, bull_score, bear_score, final_score,
                direction, confidence, news_label, news_score):
    conn.execute(
        """INSERT INTO debates
           (session_id, epoch, price, bull_score, bear_score, final_score,
            direction, confidence, news_sentiment, news_score)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (session_id, epoch, price, bull_score, bear_score, final_score,
         direction, confidence, news_label, news_score),
    )
    conn.commit()


def save_result(conn, session_id, strategy, roi, alpha, trades, fees, slippage, cost, pv, rank):
    conn.execute(
        """INSERT INTO results
           (session_id, strategy, final_roi_pct, alpha_vs_buyhold, total_trades,
            total_fees, total_slippage, total_cost, portfolio_value, rank)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (session_id, strategy, roi, alpha, trades, fees, slippage, cost, pv, rank),
    )
    conn.commit()


# ── Query helpers for 2-month review ──

def leaderboard(conn, days=60) -> list[dict]:
    """Overall win rate and avg ROI per strategy over N days."""
    rows = conn.execute("""
        SELECT
            r.strategy,
            COUNT(*) as sessions,
            ROUND(AVG(r.final_roi_pct), 4) as avg_roi,
            ROUND(AVG(r.alpha_vs_buyhold), 4) as avg_alpha,
            SUM(CASE WHEN r.rank = 1 THEN 1 ELSE 0 END) as wins,
            ROUND(AVG(r.total_cost), 2) as avg_cost,
            SUM(r.total_trades) as total_trades
        FROM results r
        JOIN sessions s ON r.session_id = s.id
        WHERE s.started_at >= datetime('now', ? || ' days')
          AND s.status = 'completed'
        GROUP BY r.strategy
        ORDER BY avg_alpha DESC
    """, (f"-{days}",)).fetchall()
    return [dict(r) for r in rows]


def session_history(conn, days=60) -> list[dict]:
    """All completed sessions with winner."""
    rows = conn.execute("""
        SELECT
            s.id, s.started_at, s.symbol, s.budget, s.duration_hours,
            s.entry_price, s.exit_price, s.mode,
            r.strategy as winner, r.final_roi_pct as best_roi, r.alpha_vs_buyhold as best_alpha
        FROM sessions s
        JOIN results r ON r.session_id = s.id AND r.rank = 1
        WHERE s.started_at >= datetime('now', ? || ' days')
          AND s.status = 'completed'
        ORDER BY s.started_at DESC
    """, (f"-{days}",)).fetchall()
    return [dict(r) for r in rows]


def strategy_daily(conn, strategy, days=60) -> list[dict]:
    """Daily ROI for a specific strategy."""
    rows = conn.execute("""
        SELECT
            date(s.started_at) as day,
            ROUND(AVG(r.final_roi_pct), 4) as avg_roi,
            ROUND(AVG(r.alpha_vs_buyhold), 4) as avg_alpha,
            COUNT(*) as sessions
        FROM results r
        JOIN sessions s ON r.session_id = s.id
        WHERE r.strategy = ?
          AND s.started_at >= datetime('now', ? || ' days')
          AND s.status = 'completed'
        GROUP BY day
        ORDER BY day
    """, (strategy, f"-{days}")).fetchall()
    return [dict(r) for r in rows]


def print_leaderboard(days=60):
    """Print formatted leaderboard to console."""
    conn = get_conn()
    lb = leaderboard(conn, days)
    conn.close()

    if not lb:
        print("No completed sessions yet.")
        return

    print(f"\n{'='*72}")
    print(f"  LEADERBOARD — Last {days} Days")
    print(f"{'='*72}")
    print(f"  {'Strategy':<14} {'Sessions':>8} {'Wins':>6} {'Win%':>6} {'Avg ROI':>10} {'Avg Alpha':>10} {'Avg Cost':>9}")
    print(f"  {'─'*14} {'─'*8} {'─'*6} {'─'*6} {'─'*10} {'─'*10} {'─'*9}")

    for row in lb:
        win_pct = row["wins"] / row["sessions"] * 100 if row["sessions"] > 0 else 0
        print(
            f"  {row['strategy']:<14} {row['sessions']:>8} {row['wins']:>6} "
            f"{win_pct:>5.0f}% {row['avg_roi']:>+9.4f}% {row['avg_alpha']:>+9.4f}% "
            f"${row['avg_cost']:>8.2f}"
        )
    print(f"{'='*72}\n")
