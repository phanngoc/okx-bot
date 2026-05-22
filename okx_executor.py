"""OKX order execution wrapper.

Thin layer around ccxt that:
  - Loads credentials from .env
  - Handles OKX-specific quirks (tdMode='cash' for spot, market-BUY size in USDT)
  - Wraps every API call with retry + exponential backoff
  - Logs every request/response for audit
  - Exposes per-order $cap safety check

All methods are synchronous. WebSocket fill listener lives in a separate
module to keep this file small.
"""

import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import ccxt
from dotenv import load_dotenv

log = logging.getLogger(__name__)


@dataclass
class ExecutorConfig:
    api_key: str
    api_secret: str
    api_passphrase: str
    demo: bool = True
    max_order_usdt: float = 100.0          # per-order $cap safety
    max_retries: int = 3
    backoff_base_sec: float = 1.0


def load_config(env_path: Optional[str] = None) -> ExecutorConfig:
    """Load credentials + safety params from .env."""
    load_dotenv(env_path) if env_path else load_dotenv()
    return ExecutorConfig(
        api_key=os.environ["OKX_API_KEY"],
        api_secret=os.environ["OKX_API_SECRET"],
        api_passphrase=os.environ["OKX_API_PASSPHRASE"],
        demo=os.getenv("DEMO_MODE", "true").lower() == "true",
        max_order_usdt=float(os.getenv("MAX_ORDER_USDT", "100")),
    )


class OkxExecutor:
    """Synchronous OKX V5 spot trading wrapper.

    Use `OkxExecutor.from_env()` to construct; call methods to trade.
    Every method retries on transient errors (NetworkError, RateLimit).
    Per-order $USDT cap enforced before placement.
    """

    def __init__(self, cfg: ExecutorConfig):
        self.cfg = cfg
        self.exchange = ccxt.okx({
            "apiKey":           cfg.api_key,
            "secret":           cfg.api_secret,
            "password":         cfg.api_passphrase,  # ccxt uses 'password' for OKX passphrase
            "enableRateLimit":  True,
        })
        if cfg.demo:
            self.exchange.set_sandbox_mode(True)
        env_tag = "DEMO" if cfg.demo else "LIVE"
        log.info(f"[OKX] initialized in {env_tag} mode")

    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> "OkxExecutor":
        return cls(load_config(env_path))

    # ----------------------------------------------------------------
    # Retry decorator
    # ----------------------------------------------------------------

    def _retry(self, fn, *args, **kwargs):
        last_err = None
        for attempt in range(self.cfg.max_retries):
            try:
                return fn(*args, **kwargs)
            except (ccxt.NetworkError, ccxt.RateLimitExceeded, ccxt.ExchangeNotAvailable) as e:
                wait = self.cfg.backoff_base_sec * (2 ** attempt)
                log.warning(f"[OKX] {type(e).__name__} on {fn.__name__} (attempt {attempt+1}): {e}; retry in {wait}s")
                last_err = e
                time.sleep(wait)
            except ccxt.AuthenticationError:
                raise  # never retry auth errors
            except ccxt.InvalidOrder as e:
                log.error(f"[OKX] invalid order rejected: {e}")
                raise
        raise last_err

    # ----------------------------------------------------------------
    # Read-only
    # ----------------------------------------------------------------

    def fetch_balance(self) -> dict:
        """Returns {ccy: {'free': X, 'used': X, 'total': X}, ...}."""
        bal = self._retry(self.exchange.fetch_balance)
        result = {}
        for ccy in bal.get("total", {}):
            total = bal["total"].get(ccy) or 0.0
            if total > 0:
                result[ccy] = {
                    "free":  bal["free"].get(ccy) or 0.0,
                    "used":  bal["used"].get(ccy) or 0.0,
                    "total": total,
                }
        return result

    def equity_usdt(self, symbol: str) -> float:
        """Approximate total equity in USDT terms (cash + base × mark price)."""
        bal = self.fetch_balance()
        base = symbol.split("/")[0]
        cash = bal.get("USDT", {}).get("total", 0.0)
        coin = bal.get(base, {}).get("total", 0.0)
        if coin > 0:
            ticker = self.fetch_ticker(symbol)
            cash += coin * ticker["last"]
        return cash

    def fetch_ticker(self, symbol: str) -> dict:
        return self._retry(self.exchange.fetch_ticker, symbol)

    def fetch_open_orders(self, symbol: Optional[str] = None) -> list:
        return self._retry(self.exchange.fetch_open_orders, symbol)

    def fetch_order(self, order_id: str, symbol: str) -> dict:
        return self._retry(self.exchange.fetch_order, order_id, symbol)

    def fetch_my_trades(self, symbol: str, since_ms: Optional[int] = None) -> list:
        return self._retry(self.exchange.fetch_my_trades, symbol, since_ms)

    # ----------------------------------------------------------------
    # Order placement
    # ----------------------------------------------------------------

    def _check_order_cap(self, usdt_amount: float, label: str) -> None:
        if usdt_amount > self.cfg.max_order_usdt:
            raise ValueError(
                f"[SAFETY] {label} ${usdt_amount:.2f} exceeds MAX_ORDER_USDT "
                f"${self.cfg.max_order_usdt:.2f} — rejected"
            )

    @staticmethod
    def _gen_clord(prefix: str) -> str:
        # OKX clOrdId: alphanumeric ONLY (a-z A-Z 0-9), max 32 chars — no hyphens/underscores
        clean_prefix = "".join(c for c in prefix if c.isalnum())
        return f"{clean_prefix}{uuid.uuid4().hex[:16]}"[:32]

    def place_limit(self, symbol: str, side: str, amount: float, price: float,
                    cl_ord_id: Optional[str] = None) -> dict:
        """Place a limit order. `amount` is in BASE currency (e.g. BTC)."""
        usdt_value = amount * price
        self._check_order_cap(usdt_value, f"limit {side} {amount} {symbol} @ ${price}")
        params = {
            "tdMode": "cash",  # spot
            "clOrdId": cl_ord_id or self._gen_clord("lim"),
        }
        log.info(f"[OKX] LIMIT {side} {amount} {symbol} @ ${price:,.2f} (=${usdt_value:.2f})  clOrdId={params['clOrdId']}")
        order = self._retry(self.exchange.create_order, symbol, "limit", side, amount, price, params)
        log.info(f"[OKX]   → id={order.get('id')}  status={order.get('status')}")
        return order

    def place_market_buy_usdt(self, symbol: str, usdt_amount: float,
                              cl_ord_id: Optional[str] = None) -> dict:
        """Market BUY where size is QUOTE (USDT). OKX-specific gotcha."""
        self._check_order_cap(usdt_amount, f"market buy {symbol} ${usdt_amount}")
        params = {
            "tdMode": "cash",
            "clOrdId": cl_ord_id or self._gen_clord("mb"),
        }
        # ccxt OKX: for market buy, pass amount in quote (USDT) and createMarketBuyOrderRequiresPrice=False
        params["createMarketBuyOrderRequiresPrice"] = False
        log.info(f"[OKX] MKT BUY {symbol} ${usdt_amount:.2f}  clOrdId={params['clOrdId']}")
        order = self._retry(self.exchange.create_order, symbol, "market", "buy", usdt_amount, None, params)
        log.info(f"[OKX]   → id={order.get('id')}  filled={order.get('filled')}  cost={order.get('cost')}")
        return order

    def place_market_sell(self, symbol: str, base_amount: float,
                          cl_ord_id: Optional[str] = None) -> dict:
        """Market SELL where size is BASE (e.g. BTC qty)."""
        # Estimate USDT value for cap check
        ticker = self.fetch_ticker(symbol)
        usdt_value = base_amount * ticker["bid"]
        self._check_order_cap(usdt_value, f"market sell {base_amount} {symbol}")
        params = {
            "tdMode": "cash",
            "clOrdId": cl_ord_id or self._gen_clord("ms"),
        }
        log.info(f"[OKX] MKT SELL {base_amount} {symbol} (≈${usdt_value:.2f})  clOrdId={params['clOrdId']}")
        order = self._retry(self.exchange.create_order, symbol, "market", "sell", base_amount, None, params)
        log.info(f"[OKX]   → id={order.get('id')}  filled={order.get('filled')}")
        return order

    def place_batch_limit(self, symbol: str, orders: list[dict]) -> list[dict]:
        """Batch place up to 20 limit orders in ONE API call.
        orders = [{'side': 'buy', 'amount': X, 'price': Y, 'cl_ord_id': Z?}, ...]
        """
        if len(orders) > 20:
            raise ValueError(f"OKX batch limit is 20 orders, got {len(orders)}")
        ccxt_orders = []
        total_usdt = 0.0
        for o in orders:
            usdt_value = o["amount"] * o["price"]
            self._check_order_cap(usdt_value, f"batch {o['side']} {o['amount']} @ ${o['price']}")
            total_usdt += usdt_value
            ccxt_orders.append({
                "symbol": symbol,
                "type":   "limit",
                "side":   o["side"],
                "amount": o["amount"],
                "price":  o["price"],
                "params": {
                    "tdMode":   "cash",
                    "clOrdId":  o.get("cl_ord_id") or self._gen_clord("bch"),
                },
            })
        log.info(f"[OKX] BATCH {len(ccxt_orders)} orders {symbol} (total ≈${total_usdt:.2f})")
        results = self._retry(self.exchange.create_orders, ccxt_orders)
        for i, r in enumerate(results):
            log.info(f"[OKX]   [{i}] id={r.get('id')} status={r.get('status')}")
        return results

    # ----------------------------------------------------------------
    # Cancellation
    # ----------------------------------------------------------------

    def cancel(self, order_id: str, symbol: str) -> Any:
        log.info(f"[OKX] CANCEL {order_id}")
        return self._retry(self.exchange.cancel_order, order_id, symbol)

    def cancel_all(self, symbol: str) -> list:
        """Cancel ALL open orders for a symbol. Returns list of cancelled IDs."""
        open_orders = self.fetch_open_orders(symbol)
        if not open_orders:
            log.info(f"[OKX] no open orders for {symbol}")
            return []
        ids = [o["id"] for o in open_orders]
        log.warning(f"[OKX] CANCEL_ALL — {len(ids)} orders for {symbol}")
        # OKX supports batch cancel up to 20 per call
        results = []
        for i in range(0, len(ids), 20):
            chunk = ids[i:i+20]
            res = self._retry(self.exchange.cancel_orders, chunk, symbol)
            results.extend(res if isinstance(res, list) else [res])
        return results


if __name__ == "__main__":
    # Smoke test
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ex = OkxExecutor.from_env()
    print("\n--- Balance ---")
    for ccy, bal in ex.fetch_balance().items():
        print(f"  {ccy}: total={bal['total']}  free={bal['free']}")
    print("\n--- Ticker ---")
    t = ex.fetch_ticker("BTC/USDT")
    print(f"  BTC/USDT  last=${t['last']:,.2f}  bid=${t['bid']:,.2f}  ask=${t['ask']:,.2f}")
    print("\n--- Open orders ---")
    print(f"  {len(ex.fetch_open_orders('BTC/USDT'))} open BTC/USDT orders")
