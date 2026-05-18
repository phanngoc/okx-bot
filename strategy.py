import time
from dataclasses import dataclass, field
from config import GridConfig, DCAConfig, FeeConfig


@dataclass
class Order:
    side: str           # "buy" or "sell"
    price: float
    amount_usdt: float
    quantity: float = 0.0
    filled: bool = False
    fill_price: float = 0.0
    fill_time: float = 0.0
    order_type: str = "grid"  # "grid" or "dca"
    fee_type: str = "maker"   # "maker" or "taker"
    fee_paid: float = 0.0
    slippage_cost: float = 0.0


@dataclass
class GridDCAStrategy:
    entry_price: float
    grid_cfg: GridConfig
    dca_cfg: DCAConfig
    total_budget: float
    fees: FeeConfig = field(default_factory=FeeConfig)

    grid_orders: list = field(default_factory=list)
    dca_orders: list = field(default_factory=list)
    filled_orders: list = field(default_factory=list)

    coin_balance: float = 0.0
    usdt_balance: float = 0.0
    usdt_allocated_grid: float = 0.0
    usdt_allocated_dca: float = 0.0
    last_dca_time: float = 0.0
    total_fees_paid: float = 0.0
    total_slippage_cost: float = 0.0
    total_maker_fees: float = 0.0
    total_taker_fees: float = 0.0

    _initialized: bool = False

    def initialize(self):
        grid_budget = self.total_budget * 0.65
        dca_budget = self.total_budget * 0.35

        self.usdt_allocated_grid = grid_budget
        self.usdt_allocated_dca = dca_budget
        self.usdt_balance = self.total_budget

        self._setup_grid()
        self.last_dca_time = time.time()
        self._initialized = True

    def _setup_grid(self):
        low = self.entry_price * (1 - self.grid_cfg.price_range_pct / 100)
        high = self.entry_price * (1 + self.grid_cfg.price_range_pct / 100)
        step = (high - low) / self.grid_cfg.num_grids

        self.grid_orders = []
        for i in range(self.grid_cfg.num_grids + 1):
            level_price = low + i * step
            if level_price < self.entry_price:
                qty = self.grid_cfg.investment_per_grid / level_price
                order = Order(
                    side="buy",
                    price=round(level_price, 2),
                    amount_usdt=self.grid_cfg.investment_per_grid,
                    quantity=round(qty, 8),
                    fee_type="maker",
                )
                self.grid_orders.append(order)
            elif level_price > self.entry_price:
                qty = self.grid_cfg.investment_per_grid / level_price
                order = Order(
                    side="sell",
                    price=round(level_price, 2),
                    amount_usdt=self.grid_cfg.investment_per_grid,
                    quantity=round(qty, 8),
                    fee_type="maker",
                )
                self.grid_orders.append(order)

    def _apply_fee(self, amount: float, fee_type: str) -> tuple[float, float]:
        """Return (net_amount, fee). Grid limit orders = maker, DCA/market = taker."""
        rate = self.fees.maker_rate if fee_type == "maker" else self.fees.taker_rate
        fee = amount * rate
        return amount - fee, fee

    def _apply_slippage(self, price: float, side: str) -> tuple[float, float]:
        """Simulate slippage on market orders. Limit orders have no slippage."""
        slip = price * (self.fees.slippage_pct / 100)
        if side == "buy":
            return price + slip, slip
        else:
            return price - slip, slip

    def tick(self, current_price: float, current_time: float) -> list[Order]:
        filled_this_tick = []

        filled_this_tick.extend(self._check_grid_fills(current_price, current_time))
        filled_this_tick.extend(self._check_dca(current_price, current_time))

        return filled_this_tick

    def _check_grid_fills(self, price: float, ts: float) -> list[Order]:
        filled = []
        new_orders = []

        for order in self.grid_orders:
            if order.filled:
                continue

            should_fill = (
                (order.side == "buy" and price <= order.price)
                or (order.side == "sell" and price >= order.price)
            )

            if should_fill:
                if order.side == "buy":
                    if self.usdt_balance >= order.amount_usdt:
                        # Grid = limit order = maker fee, no slippage
                        net_usdt, fee = self._apply_fee(order.amount_usdt, "maker")
                        qty_bought = net_usdt / price
                        self.coin_balance += qty_bought
                        self.usdt_balance -= order.amount_usdt
                        self.total_fees_paid += fee
                        self.total_maker_fees += fee

                        order.filled = True
                        order.fill_price = price
                        order.fill_time = ts
                        order.quantity = qty_bought
                        order.fee_paid = fee
                        order.fee_type = "maker"
                        filled.append(order)
                        self.filled_orders.append(order)

                        sell_price = price * (1 + self.grid_cfg.price_range_pct / 100 / self.grid_cfg.num_grids * 2)
                        new_orders.append(Order(
                            side="sell",
                            price=round(sell_price, 2),
                            amount_usdt=order.amount_usdt,
                            quantity=round(qty_bought, 8),
                            fee_type="maker",
                        ))

                elif order.side == "sell":
                    if self.coin_balance >= order.quantity:
                        # Grid sell = limit order = maker fee, no slippage
                        gross_usdt = order.quantity * price
                        net_usdt, fee = self._apply_fee(gross_usdt, "maker")
                        self.coin_balance -= order.quantity
                        self.usdt_balance += net_usdt
                        self.total_fees_paid += fee
                        self.total_maker_fees += fee

                        order.filled = True
                        order.fill_price = price
                        order.fill_time = ts
                        order.fee_paid = fee
                        order.fee_type = "maker"
                        filled.append(order)
                        self.filled_orders.append(order)

                        buy_price = price * (1 - self.grid_cfg.price_range_pct / 100 / self.grid_cfg.num_grids * 2)
                        new_orders.append(Order(
                            side="buy",
                            price=round(buy_price, 2),
                            amount_usdt=order.amount_usdt,
                            quantity=round(order.amount_usdt / buy_price, 8),
                            fee_type="maker",
                        ))

        self.grid_orders = [o for o in self.grid_orders if not o.filled]
        self.grid_orders.extend(new_orders)
        return filled

    def _check_dca(self, price: float, ts: float) -> list[Order]:
        interval_sec = self.dca_cfg.interval_hours * 3600
        if ts - self.last_dca_time < interval_sec:
            return []

        if self.usdt_allocated_dca <= 0:
            return []

        buy_amount = min(self.dca_cfg.amount_per_buy, self.usdt_allocated_dca, self.usdt_balance)
        if buy_amount < self.fees.min_order_usdt:
            return []

        # DCA = market order = taker fee + slippage
        fill_price, slip_cost = self._apply_slippage(price, "buy")
        net_usdt, fee = self._apply_fee(buy_amount, "taker")
        qty = net_usdt / fill_price

        self.coin_balance += qty
        self.usdt_balance -= buy_amount
        self.usdt_allocated_dca -= buy_amount
        self.total_fees_paid += fee
        self.total_taker_fees += fee
        self.total_slippage_cost += slip_cost * qty
        self.last_dca_time = ts

        order = Order(
            side="buy",
            price=round(price, 2),
            amount_usdt=buy_amount,
            quantity=round(qty, 8),
            filled=True,
            fill_price=round(fill_price, 2),
            fill_time=ts,
            order_type="dca",
            fee_type="taker",
            fee_paid=fee,
            slippage_cost=round(slip_cost * qty, 4),
        )
        self.filled_orders.append(order)
        return [order]

    def portfolio_value(self, current_price: float) -> float:
        return self.usdt_balance + self.coin_balance * current_price

    def stats(self, current_price: float) -> dict:
        pv = self.portfolio_value(current_price)
        pnl = pv - self.total_budget
        roi = (pnl / self.total_budget) * 100

        grid_fills = [o for o in self.filled_orders if o.order_type == "grid"]
        dca_fills = [o for o in self.filled_orders if o.order_type == "dca"]
        grid_buys = sum(1 for o in grid_fills if o.side == "buy")
        grid_sells = sum(1 for o in grid_fills if o.side == "sell")

        return {
            "portfolio_value": round(pv, 2),
            "pnl": round(pnl, 2),
            "roi_pct": round(roi, 4),
            "coin_balance": round(self.coin_balance, 8),
            "usdt_balance": round(self.usdt_balance, 2),
            "total_fees": round(self.total_fees_paid, 2),
            "maker_fees": round(self.total_maker_fees, 2),
            "taker_fees": round(self.total_taker_fees, 2),
            "slippage_cost": round(self.total_slippage_cost, 2),
            "grid_buys": grid_buys,
            "grid_sells": grid_sells,
            "dca_buys": len(dca_fills),
            "total_trades": len(self.filled_orders),
            "pending_grid_orders": len([o for o in self.grid_orders if not o.filled]),
        }
