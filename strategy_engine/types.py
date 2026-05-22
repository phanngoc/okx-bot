"""Core data types for the strategy engine.

Design notes:
- Intents are frozen dataclasses (immutable, hashable, easy to log)
- Order has both 'id' (broker-assigned) and 'cl_ord_id' (client-side)
  so we can correlate even before the broker confirms
- Fill is what the executor emits when an order completes (full or partial)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class IntentKind(str, Enum):
    PLACE_LIMIT       = "place_limit"
    PLACE_MARKET_BUY  = "place_market_buy"   # amount is QUOTE (USDT)
    PLACE_MARKET_SELL = "place_market_sell"  # amount is BASE
    CANCEL            = "cancel"
    CANCEL_ALL_SIDE   = "cancel_all_side"


class OrderStatus(str, Enum):
    OPEN      = "open"
    FILLED    = "filled"
    CANCELLED = "cancelled"
    REJECTED  = "rejected"


@dataclass(frozen=True)
class Intent:
    """Strategy emits an intent saying 'I want to do X'.
    Pure data — no I/O until the Executor receives it."""
    kind:      IntentKind
    symbol:    str
    side:      Optional[str]   = None    # "buy" / "sell"
    amount:    Optional[float] = None    # base qty, or quote USDT for market_buy
    price:     Optional[float] = None    # only for PLACE_LIMIT
    order_id:  Optional[str]   = None    # only for CANCEL
    tag:       str             = ""      # free-form: "grid_init" / "grid_repl" / "dca" / "rebalance"


@dataclass(frozen=True)
class Order:
    """Concrete order known to a broker (real or simulated)."""
    id:         str
    cl_ord_id:  str
    symbol:     str
    side:       str
    kind:       str            # "limit" / "market"
    amount:     float          # base qty
    price:      Optional[float] = None
    status:     OrderStatus     = OrderStatus.OPEN
    filled_amount: float = 0.0
    fill_price:    float = 0.0
    tag:           str   = ""


@dataclass(frozen=True)
class Fill:
    """A previous order has been filled.

    `amount` is the NET base balance change after fees:
      - BUY fill:  amount = base actually credited to your account (post-fee)
      - SELL fill: amount = base deducted from your account (the order's qty)
    `quote_amount` is the NET quote balance change:
      - BUY fill:  -order.amount * price (full cost paid, no fee on quote side)
      - SELL fill: +net USDT received (post-fee)

    Using NET amounts lets strategies compute follow-up orders that
    won't be rejected due to fee shortfall.
    """
    order_id:     str
    symbol:       str
    side:         str
    price:        float
    amount:       float
    ts:           float
    quote_amount: float = 0.0       # signed net USDT delta from this fill
    fee:          float = 0.0
    fee_ccy:      str   = "USDT"
    tag:          str   = ""


@dataclass(frozen=True)
class PriceTick:
    """A new price observation. Sim feeds these from candles; live from ticker poll.

    `pv_hint` is the current total equity (quote + base × price) snapshot at this tick.
    Engine populates it before forwarding so strategies that need PV context (e.g.
    Adaptive's skip-if-winning guard) can read it without coupling to an Executor.
    Defaults to 0.0 — strategies that don't care can ignore it.
    """
    symbol:  str
    price:   float        # close / last
    high:    float        # for limit fill check across candle
    low:     float
    ts:      float
    pv_hint: float = 0.0


@dataclass(frozen=True)
class TimerEvent:
    """Scheduled trigger emitted by the Engine based on strategy.timers()."""
    name: str            # matches a key from strategy.timers()
    ts:   float          # when this fired


Event = Union[Fill, PriceTick, TimerEvent]
