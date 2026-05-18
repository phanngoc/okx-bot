"""Advanced trading strategies inspired by top crypto bots.
All strategies share the same interface: tick(price, ts) -> list[dict]"""

import time
from dataclasses import dataclass, field
from config import FeeConfig


@dataclass
class Trade:
    time: float
    side: str
    price: float
    fill_price: float
    qty: float
    usdt: float
    fee: float
    slippage: float
    strategy: str
    reason: str


class BaseStrategy:
    def __init__(self, budget: float, fees: FeeConfig = None):
        self.budget = budget
        self.total_budget = budget
        self.fees = fees or FeeConfig()
        self.coin_balance = 0.0
        self.usdt_balance = budget
        self.total_fees = 0.0
        self.total_slippage = 0.0
        self.trades: list[Trade] = []

    def _market_buy(self, price: float, usdt_amount: float, ts: float, reason: str) -> Trade | None:
        if usdt_amount > self.usdt_balance:
            usdt_amount = self.usdt_balance
        if usdt_amount < self.fees.min_order_usdt:
            return None
        slip = price * (self.fees.slippage_pct / 100)
        fill_price = price + slip
        fee = usdt_amount * self.fees.taker_rate
        net = usdt_amount - fee
        qty = net / fill_price
        self.coin_balance += qty
        self.usdt_balance -= usdt_amount
        self.total_fees += fee
        self.total_slippage += slip * qty
        t = Trade(ts, "BUY", price, round(fill_price, 2), qty, usdt_amount, fee, slip * qty, self.NAME, reason)
        self.trades.append(t)
        return t

    def _market_sell(self, price: float, pct: float, ts: float, reason: str) -> Trade | None:
        qty = self.coin_balance * (pct / 100)
        if qty * price < self.fees.min_order_usdt:
            return None
        slip = price * (self.fees.slippage_pct / 100)
        fill_price = price - slip
        gross = qty * fill_price
        fee = gross * self.fees.taker_rate
        net = gross - fee
        self.coin_balance -= qty
        self.usdt_balance += net
        self.total_fees += fee
        self.total_slippage += slip * qty
        t = Trade(ts, "SELL", price, round(fill_price, 2), qty, net, fee, slip * qty, self.NAME, reason)
        self.trades.append(t)
        return t

    def portfolio_value(self, price: float) -> float:
        return self.usdt_balance + self.coin_balance * price

    def roi(self, price: float) -> float:
        return (self.portfolio_value(price) - self.total_budget) / self.total_budget * 100

    def stats(self, price: float) -> dict:
        buys = sum(1 for t in self.trades if t.side == "BUY")
        sells = sum(1 for t in self.trades if t.side == "SELL")
        return {
            "portfolio_value": round(self.portfolio_value(price), 2),
            "roi_pct": round(self.roi(price), 4),
            "coin_balance": round(self.coin_balance, 8),
            "usdt_balance": round(self.usdt_balance, 2),
            "total_fees": round(self.total_fees, 2),
            "total_slippage": round(self.total_slippage, 2),
            "total_cost": round(self.total_fees + self.total_slippage, 2),
            "buys": buys,
            "sells": sells,
            "total_trades": buys + sells,
        }


class TrailingDCA(BaseStrategy):
    """3Commas-style DCA with trailing take-profit.
    - Scale into position on dips (safety orders at -3%, -6%, -12%, -20%)
    - Trailing take-profit: lock profit when price rises, sell if drops X% from peak
    """
    NAME = "TrailingDCA"

    def __init__(self, budget: float, fees: FeeConfig = None,
                 base_order_pct: float = 10,
                 safety_deviations: list = None,
                 tp_pct: float = 2.0,
                 trailing_pct: float = 0.8):
        super().__init__(budget, fees)
        self.base_order_pct = base_order_pct
        self.safety_deviations = safety_deviations or [3, 6, 12, 20, 30]
        self.tp_pct = tp_pct
        self.trailing_pct = trailing_pct

        self.entry_price = None
        self.avg_price = 0.0
        self.safety_filled = [False] * len(self.safety_deviations)
        self.trailing_active = False
        self.trailing_peak = 0.0
        self.base_filled = False

    def tick(self, price: float, ts: float) -> list[Trade]:
        result = []

        # First tick: place base order
        if self.entry_price is None:
            self.entry_price = price
            amount = self.total_budget * (self.base_order_pct / 100)
            t = self._market_buy(price, amount, ts, "base order")
            if t:
                result.append(t)
                self.avg_price = price
                self.base_filled = True
            return result

        if not self.base_filled:
            return result

        # Safety orders: buy more on dips
        for i, dev_pct in enumerate(self.safety_deviations):
            if self.safety_filled[i]:
                continue
            trigger = self.entry_price * (1 - dev_pct / 100)
            if price <= trigger:
                scale = 1.5 ** i
                amount = self.total_budget * (self.base_order_pct / 100) * scale
                t = self._market_buy(price, amount, ts, f"safety #{i+1} at -{dev_pct}%")
                if t:
                    result.append(t)
                    self.safety_filled[i] = True
                    total_cost = sum(tr.usdt for tr in self.trades if tr.side == "BUY")
                    total_qty = self.coin_balance
                    self.avg_price = total_cost / total_qty if total_qty > 0 else price

        # Take-profit with trailing
        if self.coin_balance > 0 and self.avg_price > 0:
            profit_pct = (price - self.avg_price) / self.avg_price * 100

            if profit_pct >= self.tp_pct:
                if not self.trailing_active:
                    self.trailing_active = True
                    self.trailing_peak = price

                if price > self.trailing_peak:
                    self.trailing_peak = price

                drop_from_peak = (self.trailing_peak - price) / self.trailing_peak * 100
                if drop_from_peak >= self.trailing_pct:
                    t = self._market_sell(price, 100, ts,
                        f"trailing TP: peak ${self.trailing_peak:,.0f}, drop {drop_from_peak:.1f}%")
                    if t:
                        result.append(t)
                        self._reset()
            else:
                self.trailing_active = False
                self.trailing_peak = 0

        return result

    def _reset(self):
        self.entry_price = None
        self.avg_price = 0.0
        self.safety_filled = [False] * len(self.safety_deviations)
        self.trailing_active = False
        self.trailing_peak = 0.0
        self.base_filled = False


class BollingerBreakout(BaseStrategy):
    """Volatility breakout strategy using Bollinger Band squeeze.
    - Detect squeeze: BB width < threshold = low volatility, pressure building
    - Breakout: price breaks upper/lower band on expanding volume
    - Confirm with RSI direction
    """
    NAME = "BB_Breakout"

    def __init__(self, budget: float, fees: FeeConfig = None,
                 bb_period: int = 20, bb_std: float = 2.0,
                 squeeze_threshold: float = 2.0,
                 rsi_period: int = 14,
                 position_pct: float = 25,
                 stop_loss_pct: float = 3.0):
        super().__init__(budget, fees)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.squeeze_threshold = squeeze_threshold
        self.rsi_period = rsi_period
        self.position_pct = position_pct
        self.stop_loss_pct = stop_loss_pct

        self.prices: list[float] = []
        self.in_squeeze = False
        self.position_entry = 0.0
        self.position_side = None  # "long" or None

    def tick(self, price: float, ts: float) -> list[Trade]:
        self.prices.append(price)
        result = []

        if len(self.prices) < self.bb_period + self.rsi_period:
            return result

        bb = self._bollinger()
        rsi = self._rsi()
        vol_ratio = self._volume_proxy()

        # Detect squeeze
        if bb["width_pct"] < self.squeeze_threshold:
            self.in_squeeze = True

        # Breakout from squeeze
        if self.in_squeeze and self.position_side is None:
            if price > bb["upper"] and rsi > 50:
                amount = self.total_budget * (self.position_pct / 100)
                t = self._market_buy(price, amount, ts,
                    f"BB breakout UP: width was {bb['width_pct']:.1f}%, RSI {rsi:.0f}")
                if t:
                    result.append(t)
                    self.position_entry = price
                    self.position_side = "long"
                    self.in_squeeze = False

        # Manage position
        if self.position_side == "long" and self.coin_balance > 0:
            # Stop loss
            loss_pct = (self.position_entry - price) / self.position_entry * 100
            if loss_pct >= self.stop_loss_pct:
                t = self._market_sell(price, 100, ts,
                    f"stop loss: -{loss_pct:.1f}% from entry ${self.position_entry:,.0f}")
                if t:
                    result.append(t)
                    self.position_side = None

            # Take profit at upper band rejection or RSI overbought
            elif price > bb["upper"] and rsi > 75:
                t = self._market_sell(price, 60, ts,
                    f"partial TP: RSI {rsi:.0f} overbought at upper BB")
                if t:
                    result.append(t)

            # Exit if price drops back below middle band
            elif price < bb["middle"] and self.position_side == "long":
                t = self._market_sell(price, 100, ts,
                    f"exit: price below BB middle ${bb['middle']:,.0f}")
                if t:
                    result.append(t)
                    self.position_side = None

        # Reset squeeze detection
        if bb["width_pct"] > self.squeeze_threshold * 1.5:
            self.in_squeeze = False

        return result

    def _bollinger(self) -> dict:
        import numpy as np
        data = self.prices[-self.bb_period:]
        mid = np.mean(data)
        std = np.std(data)
        upper = mid + self.bb_std * std
        lower = mid - self.bb_std * std
        width_pct = (upper - lower) / mid * 100
        return {"upper": upper, "middle": mid, "lower": lower, "width_pct": width_pct}

    def _rsi(self) -> float:
        import numpy as np
        closes = self.prices[-(self.rsi_period + 1):]
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _volume_proxy(self) -> float:
        if len(self.prices) < 20:
            return 1.0
        recent = [abs(self.prices[i] - self.prices[i-1]) for i in range(-5, 0)]
        avg = [abs(self.prices[i] - self.prices[i-1]) for i in range(-20, -5)]
        import numpy as np
        return np.mean(recent) / np.mean(avg) if np.mean(avg) > 0 else 1.0


class MeanReversion(BaseStrategy):
    """Mean reversion: buy oversold, sell overbought.
    Only active in ranging markets (ADX < 25).
    - Buy: RSI < 30 AND price < lower BB
    - Sell: RSI > 70 OR price > upper BB
    """
    NAME = "MeanRevert"

    def __init__(self, budget: float, fees: FeeConfig = None,
                 bb_period: int = 20, rsi_period: int = 14,
                 rsi_buy: float = 30, rsi_sell: float = 70,
                 position_pct: float = 20,
                 max_positions: int = 5):
        super().__init__(budget, fees)
        self.bb_period = bb_period
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.position_pct = position_pct
        self.max_positions = max_positions

        self.prices: list[float] = []
        self.open_positions = 0

    def tick(self, price: float, ts: float) -> list[Trade]:
        self.prices.append(price)
        result = []

        if len(self.prices) < max(self.bb_period, self.rsi_period + 1) + 20:
            return result

        rsi = self._rsi()
        bb = self._bollinger()
        adx = self._adx_proxy()

        # Only trade in ranging market
        if adx > 25:
            return result

        # Buy signal: oversold
        if rsi < self.rsi_buy and price <= bb["lower"] and self.open_positions < self.max_positions:
            amount = self.total_budget * (self.position_pct / 100)
            t = self._market_buy(price, amount, ts,
                f"mean revert BUY: RSI {rsi:.0f}, price at lower BB, ADX {adx:.0f}")
            if t:
                result.append(t)
                self.open_positions += 1

        # Sell signal: overbought / reverted to mean
        if self.coin_balance > 0:
            if rsi > self.rsi_sell or price >= bb["upper"]:
                t = self._market_sell(price, 100, ts,
                    f"mean revert SELL: RSI {rsi:.0f}, {'above upper BB' if price >= bb['upper'] else 'RSI overbought'}")
                if t:
                    result.append(t)
                    self.open_positions = 0

            # Cut loss if price drops further below lower BB
            elif self.coin_balance > 0 and price < bb["lower"] * 0.97:
                t = self._market_sell(price, 50, ts,
                    f"mean revert STOP: price 3% below lower BB")
                if t:
                    result.append(t)

        return result

    def _bollinger(self) -> dict:
        import numpy as np
        data = self.prices[-self.bb_period:]
        mid = np.mean(data)
        std = np.std(data)
        return {"upper": mid + 2 * std, "middle": mid, "lower": mid - 2 * std}

    def _rsi(self) -> float:
        import numpy as np
        closes = self.prices[-(self.rsi_period + 1):]
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        return 100 - (100 / (1 + avg_gain / avg_loss))

    def _adx_proxy(self) -> float:
        """Simplified trend strength: high price range = trending."""
        import numpy as np
        if len(self.prices) < 20:
            return 50
        recent = self.prices[-20:]
        range_pct = (max(recent) - min(recent)) / np.mean(recent) * 100
        if range_pct > 5:
            return 40
        elif range_pct > 3:
            return 25
        else:
            return 15
