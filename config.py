import os
from dataclasses import dataclass, field
from enum import Enum


class Mode(Enum):
    DEMO = "demo"
    SIMULATION = "simulation"


@dataclass
class GridConfig:
    price_range_pct: float = 5.0       # +/- 5% from entry price
    num_grids: int = 20                 # number of grid levels
    investment_per_grid: float = 50.0   # USDT per grid order

@dataclass
class DCAConfig:
    interval_hours: float = 4.0         # buy every 4 hours
    amount_per_buy: float = 30.0        # USDT per DCA buy

@dataclass
class BotConfig:
    mode: Mode = Mode.SIMULATION
    fee_rate: float = 0.001  # OKX spot taker: 0.1%
    symbol: str = "BTC/USDT"
    total_budget_usdt: float = 2000.0
    grid: GridConfig = field(default_factory=GridConfig)
    dca: DCAConfig = field(default_factory=DCAConfig)
    test_duration_hours: float = 72.0   # 3 days
    tick_interval_sec: float = 30.0     # check every 30s

    # OKX API (set via env vars)
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""

    def __post_init__(self):
        self.api_key = os.getenv("OKX_API_KEY", "")
        self.api_secret = os.getenv("OKX_API_SECRET", "")
        self.api_passphrase = os.getenv("OKX_API_PASSPHRASE", "")
