"""Market regime classifier using multi-indicator scoring.

Regimes → Recommended strategy:
  STRONG_UPTREND   → BB_Breakout   (trend continuation after squeeze)
  MILD_UPTREND     → Grid+DCA      (sell into strength, accumulate on dips)
  SIDEWAYS         → Grid+DCA      (grid profits from oscillation)
  MILD_DOWNTREND   → MeanRevert    (catch oversold bounces)
  STRONG_DOWNTREND → BB_Breakout   (0-trade mode preserves capital)
  SQUEEZE          → BB_Breakout   (positioned for imminent breakout)
  HIGH_VOLATILITY  → TrailingDCA   (safety orders + trailing TP for big swings)
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np

from technical import bollinger_bands, macd, rsi


class Regime(Enum):
    STRONG_UPTREND   = "strong_uptrend"
    MILD_UPTREND     = "mild_uptrend"
    SIDEWAYS         = "sideways"
    MILD_DOWNTREND   = "mild_downtrend"
    STRONG_DOWNTREND = "strong_downtrend"
    SQUEEZE          = "squeeze"
    HIGH_VOLATILITY  = "high_volatility"


LABELS = {
    Regime.STRONG_UPTREND:   "Strong Uptrend   📈",
    Regime.MILD_UPTREND:     "Mild Uptrend     🔼",
    Regime.SIDEWAYS:         "Sideways/Ranging ↔️",
    Regime.MILD_DOWNTREND:   "Mild Downtrend   🔽",
    Regime.STRONG_DOWNTREND: "Strong Downtrend 📉",
    Regime.SQUEEZE:          "BB Squeeze       🗜️",
    Regime.HIGH_VOLATILITY:  "High Volatility  ⚡",
}

STRATEGY_MAP = {
    Regime.STRONG_UPTREND:   "Grid+DCA",    # Buy&Hold-like exposure with safety
    Regime.MILD_UPTREND:     "Grid+DCA",
    Regime.SIDEWAYS:         "Grid+DCA",
    Regime.MILD_DOWNTREND:   "MeanRevert",
    Regime.STRONG_DOWNTREND: "BB_Breakout", # near-zero trades = capital preservation
    Regime.SQUEEZE:          "Grid+DCA",    # range-bound — grid profits from oscillation
    Regime.HIGH_VOLATILITY:  "TrailingDCA",
}

STRATEGY_REASON = {
    Regime.STRONG_UPTREND:   "accumulates on grid dips, captures upside via DCA",
    Regime.MILD_UPTREND:     "sells into strength, accumulates on grid dips",
    Regime.SIDEWAYS:         "grid profits from oscillation, DCA accumulates",
    Regime.MILD_DOWNTREND:   "catches oversold RSI/BB bounces (ADX filter active)",
    Regime.STRONG_DOWNTREND: "near-zero trades — preserves capital in strong decline",
    Regime.SQUEEZE:          "grid bands the consolidation range, profits from oscillation",
    Regime.HIGH_VOLATILITY:  "safety orders absorb dips, trailing TP locks gains",
}


@dataclass
class RegimeResult:
    regime: Regime
    confidence: float        # 0.0 – 1.0
    score: int               # raw trend score (-6 to +6)
    recommended_strategy: str
    reasoning: str           # human-readable summary
    signals: dict            # raw indicator values


class RegimeDetector:
    """Classify market regime from OHLCV candles using multi-signal scoring."""

    MIN_CANDLES = 50

    def detect(self, candles: list) -> RegimeResult:
        if len(candles) < self.MIN_CANDLES:
            return RegimeResult(
                regime=Regime.SIDEWAYS,
                confidence=0.0,
                score=0,
                recommended_strategy="Grid+DCA",
                reasoning="Insufficient data (< 50 candles) — defaulting to Grid+DCA",
                signals={},
            )

        closes = [c[4] for c in candles]
        highs  = [c[2] for c in candles]
        lows   = [c[3] for c in candles]

        signals  = self._compute_signals(closes, highs, lows)
        regime, confidence, score, reasoning = self._classify(signals)

        return RegimeResult(
            regime=regime,
            confidence=confidence,
            score=score,
            recommended_strategy=STRATEGY_MAP[regime],
            reasoning=reasoning,
            signals=signals,
        )

    # ------------------------------------------------------------------
    # Signal computation
    # ------------------------------------------------------------------

    def _compute_signals(self, closes: list, highs: list, lows: list) -> dict:
        price = closes[-1]

        # SMA slopes
        sma20     = float(np.mean(closes[-20:]))
        sma50     = float(np.mean(closes[-50:]))
        sma20_old = float(np.mean(closes[-25:-5])) if len(closes) >= 25 else sma20
        sma20_slope = (sma20 - sma20_old) / sma20_old * 100  # %/5h

        price_vs_sma20 = (price - sma20) / sma20 * 100
        price_vs_sma50 = (price - sma50) / sma50 * 100

        # RSI
        rsi_val = rsi(closes, 14) or 50.0

        # MACD
        macd_data = macd(closes)
        macd_hist = macd_data["histogram"] if macd_data else 0.0

        # Bollinger Bands
        bb       = bollinger_bands(closes, 20) or {}
        bb_width = bb.get("width", 4.0)
        bb_lower = bb.get("lower", price * 0.98)
        bb_upper = bb.get("upper", price * 1.02)
        bb_pos   = ((price - bb_lower) / (bb_upper - bb_lower)
                    if bb_upper != bb_lower else 0.5)

        # Directional Efficiency — how much of movement is directional vs noise
        window      = closes[-20:]
        net_move    = abs(window[-1] - window[0]) / window[0] * 100
        total_moves = sum(abs(window[i] - window[i - 1]) / window[i - 1] * 100
                         for i in range(1, len(window)))
        dir_eff = net_move / total_moves if total_moves > 0 else 0.0

        # ATR proxy (avg true range % over 20 candles) — volatility measure
        trs = []
        for i in range(-20, 0):
            idx = i + len(closes)
            if idx < 1:
                continue
            hi   = highs[idx] if idx < len(highs) else closes[idx]
            lo   = lows[idx]  if idx < len(lows)  else closes[idx]
            prev = closes[idx - 1]
            trs.append(max(hi - lo, abs(hi - prev), abs(lo - prev)) / closes[idx] * 100)
        atr_pct = float(np.mean(trs)) if trs else bb_width / 4

        return {
            "price":          price,
            "sma20":          sma20,
            "sma50":          sma50,
            "sma20_slope":    sma20_slope,
            "price_vs_sma20": price_vs_sma20,
            "price_vs_sma50": price_vs_sma50,
            "rsi":            rsi_val,
            "macd_hist":      macd_hist,
            "bb_width":       bb_width,
            "bb_pos":         bb_pos,
            "dir_eff":        dir_eff,
            "atr_pct":        atr_pct,
        }

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(self, s: dict) -> tuple[Regime, float, int, str]:
        # Special case: BB squeeze (breakout imminent)
        if s["bb_width"] < 2.0:
            conf = min(1.0, 0.65 + (2.0 - s["bb_width"]) / 2.0)
            return (Regime.SQUEEZE, round(conf, 2), 0,
                    f"BB squeeze width={s['bb_width']:.1f}% → breakout loading")

        # Special case: high volatility + no clear direction (wide BB + choppy)
        if s["bb_width"] > 4.0 and s["dir_eff"] < 0.25:
            conf = min(1.0, 0.40 + (s["bb_width"] - 4.5) / 8.0)
            return (Regime.HIGH_VOLATILITY, round(conf, 2), 0,
                    f"BB wide={s['bb_width']:.1f}%, dir_eff={s['dir_eff']:.2f} → choppy/volatile")

        # Multi-signal trend score (-6 to +6)
        score   = 0
        reasons = []

        # SMA20 slope (±2 pts — highest weight)
        if s["sma20_slope"] > 0.4:
            score += 2; reasons.append(f"SMA20↑ +{s['sma20_slope']:.2f}%/5h")
        elif s["sma20_slope"] > 0.1:
            score += 1; reasons.append("SMA20 slightly rising")
        elif s["sma20_slope"] < -0.4:
            score -= 2; reasons.append(f"SMA20↓ {s['sma20_slope']:.2f}%/5h")
        elif s["sma20_slope"] < -0.1:
            score -= 1; reasons.append("SMA20 slightly falling")

        # Price vs SMA20 (±1 pt)
        if s["price_vs_sma20"] > 1.0:
            score += 1; reasons.append(f"price {s['price_vs_sma20']:+.1f}% vs SMA20")
        elif s["price_vs_sma20"] < -1.0:
            score -= 1; reasons.append(f"price {s['price_vs_sma20']:+.1f}% vs SMA20")

        # Price vs SMA50 (±1 pt)
        if s["price_vs_sma50"] > 2.0:
            score += 1; reasons.append(f"price {s['price_vs_sma50']:+.1f}% vs SMA50")
        elif s["price_vs_sma50"] < -2.0:
            score -= 1; reasons.append(f"price {s['price_vs_sma50']:+.1f}% vs SMA50")

        # RSI (±1 pt)
        if s["rsi"] > 58:
            score += 1; reasons.append(f"RSI {s['rsi']:.0f} bullish")
        elif s["rsi"] < 42:
            score -= 1; reasons.append(f"RSI {s['rsi']:.0f} bearish")

        # MACD histogram (±1 pt)
        if s["macd_hist"] > 0:
            score += 1; reasons.append("MACD hist +")
        elif s["macd_hist"] < 0:
            score -= 1; reasons.append("MACD hist -")

        is_trending = s["dir_eff"] > 0.45  # directional efficiency modifier
        confidence  = round(min(1.0, abs(score) / 5), 2)

        if score >= 3:
            regime = Regime.STRONG_UPTREND if is_trending else Regime.MILD_UPTREND
        elif score >= 1:
            regime = Regime.MILD_UPTREND
        elif score <= -3:
            regime = Regime.STRONG_DOWNTREND if is_trending else Regime.MILD_DOWNTREND
        elif score <= -1:
            regime = Regime.MILD_DOWNTREND
        else:
            regime = Regime.SIDEWAYS

        reasoning = f"score={score:+d} | dir_eff={s['dir_eff']:.2f} | " + " | ".join(reasons[:4])
        return regime, confidence, score, reasoning


def print_regime_report(result: RegimeResult, candle_count: int) -> None:
    """Pretty-print a RegimeResult."""
    label    = LABELS[result.regime]
    strategy = result.recommended_strategy
    s        = result.signals

    print(f"\n  ┌─ REGIME DETECTION ({candle_count} candles) {'─'*40}")
    print(f"  │  Regime:     {label}")
    print(f"  │  Confidence: {result.confidence:.0%}  (score {result.score:+d}/6)")
    print(f"  │  Signals:    SMA20_slope={s.get('sma20_slope', 0):+.2f}%/5h  "
          f"RSI={s.get('rsi', 0):.0f}  BB_width={s.get('bb_width', 0):.1f}%  "
          f"dir_eff={s.get('dir_eff', 0):.2f}")
    print(f"  │  Reasoning:  {result.reasoning}")
    print(f"  │  → Best strategy: {strategy}")
    print(f"  │    ({STRATEGY_REASON[result.regime]})")
    print(f"  └{'─'*55}\n")
