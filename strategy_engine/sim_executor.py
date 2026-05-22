"""SimExecutor — synthetic order book for backtests.

Models OKX fees realistically (maker 0.08%, taker 0.10%, slippage 0.02%).
Limit orders fill when the candle's high/low crosses the price.
Market orders fill at current price with slippage + taker fee.
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional

from config import FeeConfig
from strategy_engine.executor import Executor
from strategy_engine.types import (
    Event,
    Fill,
    Intent,
    IntentKind,
    Order,
    OrderStatus,
    PriceTick,
)


@dataclass
class SimExecutor(Executor):
    fees: FeeConfig = field(default_factory=FeeConfig)
    base_balance:  float = 0.0          # coin held
    quote_balance: float = 0.0          # USDT held
    initial_quote: float = 0.0

    # Internal order book
    _orders: dict[str, Order] = field(default_factory=dict)   # id → Order
    _last_tick: Optional[PriceTick] = None
    _next_id: int = 0

    # Lifetime accumulators
    total_fees:      float = 0.0
    total_slippage:  float = 0.0
    fills_buffer:    list[Fill] = field(default_factory=list)

    def fund(self, quote_amount: float) -> None:
        """Initial budget. Call once before running."""
        self.quote_balance = quote_amount
        self.initial_quote = quote_amount

    # ------------------------------------------------------------------
    # Executor interface
    # ------------------------------------------------------------------

    def execute(self, intent: Intent) -> Optional[Order]:
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
        raise ValueError(f"unknown intent kind: {intent.kind}")

    def poll_events(self, tick_ts: float) -> list[Event]:
        """Scan resting limit orders for fills against the latest tick."""
        if self._last_tick is None:
            return []
        events: list[Event] = []
        # Iterate over a copy because we mutate during the loop
        for order in list(self._orders.values()):
            if order.status != OrderStatus.OPEN or order.kind != "limit":
                continue
            crossed = (
                (order.side == "buy"  and self._last_tick.low  <= order.price) or
                (order.side == "sell" and self._last_tick.high >= order.price)
            )
            if crossed:
                events.append(self._fill_limit(order, tick_ts))
        # Flush any synthetic fills queued by market orders this tick
        events.extend(self.fills_buffer)
        self.fills_buffer.clear()
        return events

    def open_orders(self, symbol: str) -> list[Order]:
        return [o for o in self._orders.values()
                if o.symbol == symbol and o.status == OrderStatus.OPEN]

    def balance(self, symbol: str) -> dict:
        return {
            "base":  self.base_balance,
            "quote": self.quote_balance,
        }

    def portfolio_value(self, symbol: str, mark_price: float) -> float:
        """Total equity = free quote + free base value + locked funds in open orders.
        Locked BUY orders: their cost (amount × price) is tied up in quote.
        Locked SELL orders: their amount × mark_price is tied up in base."""
        free_value   = self.quote_balance + self.base_balance * mark_price
        locked_value = 0.0
        for o in self._orders.values():
            if o.status != OrderStatus.OPEN or o.symbol != symbol:
                continue
            if o.side == "buy":
                locked_value += o.amount * o.price        # USDT locked
            else:
                locked_value += o.amount * mark_price     # base locked, value at mark
        return free_value + locked_value

    # ------------------------------------------------------------------
    # Tick feeding (sim-specific)
    # ------------------------------------------------------------------

    def feed_tick(self, tick: PriceTick) -> None:
        """Called by Engine before each step. Sim uses it to evaluate fills."""
        self._last_tick = tick

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _new_id(self) -> str:
        self._next_id += 1
        return f"sim{self._next_id:08d}"

    def _place_limit(self, intent: Intent) -> Optional[Order]:
        if not intent.amount or not intent.price:
            return None
        if intent.side == "buy":
            cost = intent.amount * intent.price
            if cost > self.quote_balance:
                return None  # silently reject (mirrors real broker behavior)
            self.quote_balance -= cost
        else:
            if intent.amount > self.base_balance:
                return None
            self.base_balance -= intent.amount
        order = Order(
            id=self._new_id(),
            cl_ord_id=f"sim{uuid.uuid4().hex[:8]}",
            symbol=intent.symbol,
            side=intent.side,
            kind="limit",
            amount=intent.amount,
            price=intent.price,
            status=OrderStatus.OPEN,
            tag=intent.tag,
        )
        self._orders[order.id] = order
        return order

    def _place_market_buy(self, intent: Intent) -> Optional[Order]:
        """Market BUY: amount is in QUOTE (USDT)."""
        if not intent.amount or self._last_tick is None:
            return None
        usdt = intent.amount
        if usdt > self.quote_balance:
            usdt = self.quote_balance
        if usdt < self.fees.min_order_usdt:
            return None
        slip = self._last_tick.price * (self.fees.slippage_pct / 100)
        fill_price = self._last_tick.price + slip
        fee = usdt * self.fees.taker_rate
        net_usdt = usdt - fee
        qty = net_usdt / fill_price

        self.quote_balance -= usdt
        self.base_balance  += qty
        self.total_fees    += fee
        self.total_slippage += slip * qty

        order = Order(
            id=self._new_id(),
            cl_ord_id=f"sim{uuid.uuid4().hex[:8]}",
            symbol=intent.symbol, side="buy", kind="market",
            amount=qty, price=fill_price,
            status=OrderStatus.FILLED, filled_amount=qty, fill_price=fill_price,
            tag=intent.tag,
        )
        self._orders[order.id] = order
        self.fills_buffer.append(Fill(
            order_id=order.id, symbol=intent.symbol, side="buy",
            price=fill_price, amount=qty, ts=self._last_tick.ts,
            fee=fee, fee_ccy="USDT", tag=intent.tag,
        ))
        return order

    def _place_market_sell(self, intent: Intent) -> Optional[Order]:
        if not intent.amount or self._last_tick is None:
            return None
        qty = intent.amount
        if qty > self.base_balance:
            qty = self.base_balance
        if qty * self._last_tick.price < self.fees.min_order_usdt:
            return None
        slip = self._last_tick.price * (self.fees.slippage_pct / 100)
        fill_price = self._last_tick.price - slip
        gross = qty * fill_price
        fee = gross * self.fees.taker_rate
        net = gross - fee

        self.base_balance  -= qty
        self.quote_balance += net
        self.total_fees    += fee
        self.total_slippage += slip * qty

        order = Order(
            id=self._new_id(),
            cl_ord_id=f"sim{uuid.uuid4().hex[:8]}",
            symbol=intent.symbol, side="sell", kind="market",
            amount=qty, price=fill_price,
            status=OrderStatus.FILLED, filled_amount=qty, fill_price=fill_price,
            tag=intent.tag,
        )
        self._orders[order.id] = order
        self.fills_buffer.append(Fill(
            order_id=order.id, symbol=intent.symbol, side="sell",
            price=fill_price, amount=qty, ts=self._last_tick.ts,
            fee=fee, fee_ccy="USDT", tag=intent.tag,
        ))
        return order

    def _fill_limit(self, order: Order, ts: float) -> Fill:
        """Convert a resting limit order into a fill. Maker fee, no slippage."""
        price = order.price
        if order.side == "buy":
            # Funds (full cost) already deducted at placement; receive coin minus fee
            gross_qty   = order.amount
            fee_usdt    = (gross_qty * price) * self.fees.maker_rate
            net_qty     = gross_qty - (fee_usdt / price)
            self.base_balance += net_qty
            fill_amount = net_qty                          # what's actually available now
            quote_delta = -(gross_qty * price)             # already deducted at placement
            fee_ccy     = order.symbol.split("/")[0]
            fee_amt     = fee_usdt / price                 # fee in base for reporting
        else:
            # Coin already deducted at placement; receive USDT minus fee
            gross_usdt  = order.amount * price
            fee_usdt    = gross_usdt * self.fees.maker_rate
            net_usdt    = gross_usdt - fee_usdt
            self.quote_balance += net_usdt
            fill_amount = order.amount                     # gross qty sold
            quote_delta = net_usdt                         # net USDT received
            fee_ccy     = "USDT"
            fee_amt     = fee_usdt

        self.total_fees += fee_usdt
        order_dict = order.__dict__.copy()
        order_dict["status"] = OrderStatus.FILLED
        order_dict["filled_amount"] = order.amount
        order_dict["fill_price"] = price
        self._orders[order.id] = Order(**order_dict)
        return Fill(
            order_id=order.id, symbol=order.symbol, side=order.side,
            price=price, amount=fill_amount, ts=ts,
            quote_amount=quote_delta,
            fee=fee_amt, fee_ccy=fee_ccy,
            tag=order.tag,
        )

    def _cancel(self, order_id: str) -> None:
        order = self._orders.get(order_id)
        if not order or order.status != OrderStatus.OPEN:
            return
        # Return locked funds
        if order.kind == "limit":
            if order.side == "buy":
                self.quote_balance += order.amount * order.price
            else:
                self.base_balance += order.amount
        order_dict = order.__dict__.copy()
        order_dict["status"] = OrderStatus.CANCELLED
        self._orders[order_id] = Order(**order_dict)

    def _cancel_all_side(self, side: Optional[str]) -> None:
        for oid, o in list(self._orders.items()):
            if o.status == OrderStatus.OPEN and (side is None or o.side == side):
                self._cancel(oid)
