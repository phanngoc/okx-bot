"""Technical analysis indicators computed from OHLCV candles."""

import numpy as np


def sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return np.mean(closes[-period:])


def ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    arr = np.array(closes, dtype=float)
    multiplier = 2 / (period + 1)
    ema_val = arr[0]
    for price in arr[1:]:
        ema_val = (price - ema_val) * multiplier + ema_val
    return ema_val


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    if len(closes) < slow + signal:
        return None
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = fast_ema - slow_ema

    macd_history = []
    for i in range(signal + 5):
        idx = len(closes) - signal - 5 + i
        if idx < slow:
            continue
        subset = closes[:idx + 1]
        f = ema(subset, fast)
        s = ema(subset, slow)
        if f is not None and s is not None:
            macd_history.append(f - s)

    signal_line = np.mean(macd_history[-signal:]) if len(macd_history) >= signal else macd_line
    histogram = macd_line - signal_line

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def bollinger_bands(closes: list[float], period: int = 20, std_dev: float = 2.0) -> dict | None:
    if len(closes) < period:
        return None
    data = closes[-period:]
    middle = np.mean(data)
    std = np.std(data)
    return {
        "upper": middle + std_dev * std,
        "middle": middle,
        "lower": middle - std_dev * std,
        "width": (2 * std_dev * std) / middle * 100,
    }


def volume_profile(volumes: list[float], period: int = 20) -> dict | None:
    if len(volumes) < period:
        return None
    recent = volumes[-period:]
    avg = np.mean(recent)
    current = volumes[-1]
    return {
        "current": current,
        "average": avg,
        "ratio": current / avg if avg > 0 else 1.0,
    }


def support_resistance(highs: list[float], lows: list[float], closes: list[float], period: int = 50) -> dict | None:
    if len(closes) < period:
        return None
    h = highs[-period:]
    l = lows[-period:]
    return {
        "resistance": max(h),
        "support": min(l),
        "current": closes[-1],
        "distance_to_resistance_pct": (max(h) - closes[-1]) / closes[-1] * 100,
        "distance_to_support_pct": (closes[-1] - min(l)) / closes[-1] * 100,
    }


def compute_all(candles: list) -> dict:
    """Compute all indicators from OHLCV candles.
    candles: list of [timestamp, open, high, low, close, volume]
    """
    if len(candles) < 50:
        return {}

    opens = [c[1] for c in candles]
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    closes = [c[4] for c in candles]
    volumes = [c[5] for c in candles]

    price = closes[-1]
    prev_price = closes[-2] if len(closes) > 1 else price

    return {
        "price": price,
        "price_change_pct": (price - prev_price) / prev_price * 100,
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "ema_12": ema(closes, 12),
        "ema_26": ema(closes, 26),
        "rsi_14": rsi(closes, 14),
        "macd": macd(closes),
        "bollinger": bollinger_bands(closes),
        "volume": volume_profile(volumes),
        "support_resistance": support_resistance(highs, lows, closes),
    }
