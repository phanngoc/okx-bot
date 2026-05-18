import time
from dataclasses import dataclass, field
from config import GridConfig, DCAConfig


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


@dataclass
class GridDCAStrategy:
    entry_price: float
    grid_cfg: GridConfig
    dca_cfg: DCAConfig
    total_budget: float

    grid_orders: list = field(default_factory=list)
    dca_orders: list = field(default_factory=list)
    filled_orders: list = field(default_factory=list)

    coin_balance: float = 0.0
    usdt_balance: float = 0.0
    usdt_allocated_grid: float = 0.0
    usdt_allocated_dca: float = 0.0
    last_dca_time: float = 0.0
    total_fees_paid: float = 0.0

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
                )
                self.grid_orders.append(order)
            elif level_price > self.entry_price:
                qty = self.grid_cfg.investment_per_grid / level_price
                order = Order(
                    side="sell",
                    price=round(level_price, 2),
                    amount_usdt=self.grid_cfg.investment_per_grid,
                    quantity=round(qty, 8),
                )
                self.grid_orders.append(order)

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
                fee_rate = 0.001  # 0.1% taker fee
                if order.side == "buy":
                    if self.usdt_balance >= order.amount_usdt:
                        fee = order.amount_usdt * fee_rate
                        net_usdt = order.amount_usdt - fee
                        qty_bought = net_usdt / price
                        self.coin_balance += qty_bought
                        self.usdt_balance -= order.amount_usdt
                        self.total_fees_paid += fee

                        order.filled = True
                        order.fill_price = price
                        order.fill_time = ts
                        order.quantity = qty_bought
                        filled.append(order)
                        self.filled_orders.append(order)

                        sell_price = price * (1 + self.grid_cfg.price_range_pct / 100 / self.grid_cfg.num_grids * 2)
                        new_orders.append(Order(
                            side="sell",
                            price=round(sell_price, 2),
                            amount_usdt=order.amount_usdt,
                            quantity=round(qty_bought, 8),
                        ))

                elif order.side == "sell":
                    if self.coin_balance >= order.quantity:
                        gross_usdt = order.quantity * price
                        fee = gross_usdt * fee_rate
                        net_usdt = gross_usdt - fee
                        self.coin_balance -= order.quantity
                        self.usdt_balance += net_usdt
                        self.total_fees_paid += fee

                        order.filled = True
                        order.fill_price = price
                        order.fill_time = ts
                        filled.append(order)
                        self.filled_orders.append(order)

                        buy_price = price * (1 - self.grid_cfg.price_range_pct / 100 / self.grid_cfg.num_grids * 2)
                        new_orders.append(Order(
                            side="buy",
                            price=round(buy_price, 2),
                            amount_usdt=order.amount_usdt,
                            quantity=round(order.amount_usdt / buy_price, 8),
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
        if buy_amount < 1.0:
            return []

        fee_rate = 0.001
        fee = buy_amount * fee_rate
        net = buy_amount - fee
        qty = net / price

        self.coin_balance += qty
        self.usdt_balance -= buy_amount
        self.usdt_allocated_dca -= buy_amount
        self.total_fees_paid += fee
        self.last_dca_time = ts

        order = Order(
            side="buy",
            price=round(price, 2),
            amount_usdt=buy_amount,
            quantity=round(qty, 8),
            filled=True,
            fill_price=price,
            fill_time=ts,
            order_type="dca",
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
            "grid_buys": grid_buys,
            "grid_sells": grid_sells,
            "dca_buys": len(dca_fills),
            "total_trades": len(self.filled_orders),
            "pending_grid_orders": len([o for o in self.grid_orders if not o.filled]),
        }
