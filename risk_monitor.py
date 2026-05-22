"""Risk monitor — multi-layer kill switch for live trading.

Tracks equity over time and triggers stop signals when thresholds breach:
  1. SOFT_STOP   — drawdown ≥ MAX_DRAWDOWN_PCT  → cancel new orders, run-off existing
  2. HARD_STOP   — drawdown ≥ KILL_LOSS_PCT      → cancel ALL + market-sell base
  3. DAILY_LOSS  — day_pnl ≤ -MAX_DAILY_LOSS_PCT → pause until next UTC midnight
  4. MANUAL      — file `STOP_NOW` exists in cwd → graceful shutdown

Layer 5 (structural) is enforced by OKX subaccount funding cap, not here.
"""

import enum
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class StopSignal(enum.Enum):
    NONE       = "none"
    SOFT_STOP  = "soft_stop"    # cancel new orders, hold existing
    HARD_STOP  = "hard_stop"    # cancel all + market-sell base
    DAILY_LOSS = "daily_loss"   # pause until UTC midnight
    MANUAL     = "manual"       # STOP_NOW file present


@dataclass
class RiskState:
    start_balance:   float
    peak_equity:     float
    day_start_equity: float
    day_start_epoch: float                       # UTC midnight timestamp
    paused_until:    Optional[float] = None      # for DAILY_LOSS
    soft_triggered:  bool = False
    hard_triggered:  bool = False
    last_equity:     float = 0.0
    last_check_ts:   float = 0.0


@dataclass
class RiskConfig:
    start_balance:       float
    max_drawdown_pct:    float = 20.0
    kill_loss_pct:       float = 35.0
    max_daily_loss_pct:  float = 7.0
    stop_file:           str = "STOP_NOW"


class RiskMonitor:
    """Stateful equity tracker. Call `tick(equity_now)` periodically.
    Returns StopSignal that drives the main loop."""

    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        now_ts = time.time()
        day_start = self._utc_midnight(now_ts)
        self.state = RiskState(
            start_balance=cfg.start_balance,
            peak_equity=cfg.start_balance,
            day_start_equity=cfg.start_balance,
            day_start_epoch=day_start,
            last_equity=cfg.start_balance,
            last_check_ts=now_ts,
        )
        log.info(f"[RISK] monitor armed — start ${cfg.start_balance:.2f}  "
                 f"soft@-{cfg.max_drawdown_pct}%  hard@-{cfg.kill_loss_pct}%  "
                 f"daily@-{cfg.max_daily_loss_pct}%")

    # ------------------------------------------------------------------

    @staticmethod
    def _utc_midnight(ts: float) -> float:
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        midnight = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        return midnight.timestamp()

    def _check_new_day(self, now_ts: float, equity: float) -> None:
        """Reset day_start at UTC midnight rollover."""
        if now_ts >= self.state.day_start_epoch + 86400:
            log.info(f"[RISK] UTC day rollover — reset daily counters "
                     f"(was: start=${self.state.day_start_equity:.2f} → equity=${equity:.2f})")
            self.state.day_start_equity = equity
            self.state.day_start_epoch  = self._utc_midnight(now_ts)
            self.state.paused_until = None

    def _check_manual(self) -> bool:
        return Path(self.cfg.stop_file).exists()

    # ------------------------------------------------------------------

    def tick(self, equity: float, now_ts: Optional[float] = None) -> StopSignal:
        """Check all risk layers. Returns the SEVEREST signal triggered."""
        now_ts = now_ts or time.time()
        self._check_new_day(now_ts, equity)

        self.state.last_equity   = equity
        self.state.last_check_ts = now_ts
        self.state.peak_equity   = max(self.state.peak_equity, equity)

        # Highest severity first
        if self._check_manual():
            log.critical(f"[RISK] MANUAL stop file detected → HARD_STOP")
            return StopSignal.MANUAL

        dd_from_start = (self.cfg.start_balance - equity) / self.cfg.start_balance * 100
        if dd_from_start >= self.cfg.kill_loss_pct:
            if not self.state.hard_triggered:
                log.critical(f"[RISK] HARD STOP — drawdown {dd_from_start:.2f}% ≥ {self.cfg.kill_loss_pct}%")
                self.state.hard_triggered = True
            return StopSignal.HARD_STOP

        if dd_from_start >= self.cfg.max_drawdown_pct:
            if not self.state.soft_triggered:
                log.warning(f"[RISK] SOFT STOP — drawdown {dd_from_start:.2f}% ≥ {self.cfg.max_drawdown_pct}%")
                self.state.soft_triggered = True
            return StopSignal.SOFT_STOP

        day_pnl_pct = (equity - self.state.day_start_equity) / self.state.day_start_equity * 100
        if day_pnl_pct <= -self.cfg.max_daily_loss_pct:
            if self.state.paused_until is None:
                next_midnight = self.state.day_start_epoch + 86400
                self.state.paused_until = next_midnight
                log.warning(f"[RISK] DAILY LOSS — day_pnl {day_pnl_pct:.2f}% ≤ -{self.cfg.max_daily_loss_pct}%; "
                            f"paused until {datetime.fromtimestamp(next_midnight, tz=timezone.utc).isoformat()}")
            return StopSignal.DAILY_LOSS

        if self.state.paused_until and now_ts < self.state.paused_until:
            return StopSignal.DAILY_LOSS  # still paused from earlier trigger

        return StopSignal.NONE

    def summary(self) -> dict:
        s = self.state
        return {
            "start":         s.start_balance,
            "equity":        s.last_equity,
            "peak":          s.peak_equity,
            "total_pnl_pct": (s.last_equity - s.start_balance) / s.start_balance * 100,
            "day_pnl_pct":   (s.last_equity - s.day_start_equity) / s.day_start_equity * 100,
            "drawdown_pct":  (s.peak_equity  - s.last_equity)   / s.peak_equity   * 100,
            "soft_triggered": s.soft_triggered,
            "hard_triggered": s.hard_triggered,
            "paused_until":   s.paused_until,
        }


# ----------------------------------------------------------------------
# Self-test
# ----------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = RiskConfig(
        start_balance=500.0,
        max_drawdown_pct=20.0,
        kill_loss_pct=35.0,
        max_daily_loss_pct=7.0,
    )
    rm = RiskMonitor(cfg)

    scenarios = [
        ("normal",          500.0),
        ("small loss",      480.0),
        ("daily loss 7%",   465.0),  # 500 → 465 = -7%
        ("recovery",        490.0),
        ("soft stop 20%",   395.0),  # 500 → 395 = -21%
        ("hard stop 35%",   320.0),  # 500 → 320 = -36%
    ]
    for label, eq in scenarios:
        sig = rm.tick(eq)
        s = rm.summary()
        print(f"[{label:>14}] eq=${eq:>6.2f}  total_pnl={s['total_pnl_pct']:+6.2f}%  "
              f"day_pnl={s['day_pnl_pct']:+6.2f}%  drawdown={s['drawdown_pct']:+6.2f}%  → {sig.value}")
