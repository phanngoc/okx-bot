# Grid + DCA Strategy

## Origin

Grid Trading was popularized by **Pionex** (2019) and later adopted by **Bitsgap**, **3Commas**, and **KuCoin Bot**. The concept dates back to traditional forex markets where traders placed buy/sell orders at fixed price intervals to profit from range-bound movement. DCA (Dollar Cost Averaging) is one of the oldest investment strategies, formalized by Benjamin Graham in *The Intelligent Investor* (1949).

Our implementation combines both: a grid of limit orders captures sideways volatility, while periodic DCA market buys provide steady accumulation regardless of price direction.

## How It Works

### Grid Component (65% of budget)

1. At initialization, the strategy calculates a price range: `entry_price +/- 5%`
2. This range is divided into 20 equal levels (grid lines)
3. **Buy orders** are placed below entry price, **sell orders** above
4. Each grid order uses $50 USDT
5. When a buy fills, a new sell order is placed one grid level above (and vice versa)
6. Grid orders are **limit orders** = **maker fee (0.08%)**, no slippage

The grid profits from the spread between buy and sell levels. In a $80,000 BTC price with 5% range, each grid level is ~$400 apart. Every complete buy-sell cycle on one level earns approximately:

```
$400 spread / $80,000 price = 0.5% gross per cycle
- 0.08% maker fee (buy) - 0.08% maker fee (sell) = 0.34% net per cycle
```

### DCA Component (35% of budget)

1. Every 4 hours, places a **market buy** for $30 USDT
2. Uses **taker fee (0.10%)** + **slippage (0.02%)**
3. Provides consistent accumulation on a schedule
4. No sell logic -- DCA only accumulates

### Budget Allocation

```
Total Budget: $2,000
  Grid: $1,300 (65%) -- 26 grid levels @ $50 each
  DCA:  $700  (35%) -- ~58 buys @ $30 over 72h+ (every 4h)
```

## Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `price_range_pct` | 5.0% | Grid range above/below entry |
| `num_grids` | 20 | Number of grid levels |
| `investment_per_grid` | $50 | USDT per grid order |
| `interval_hours` | 4.0 | DCA buy interval |
| `amount_per_buy` | $30 | USDT per DCA buy |

## Fee Model

| Order Type | Fee | Slippage | Total Cost |
|------------|-----|----------|------------|
| Grid (limit) | 0.08% maker | None | 0.08% |
| DCA (market) | 0.10% taker | 0.02% | 0.12% |

Grid orders are significantly cheaper because they add liquidity to the order book. This is a real advantage over strategies that only use market orders.

## Strengths

1. **Consistent in sideways markets**: Every price oscillation within the grid range triggers buy-sell cycles, generating small profits regardless of direction. This is the strategy's core edge.

2. **Low fee structure**: Grid limit orders pay only maker fees (0.08%), the cheapest available. Most competing strategies pay taker fees (0.10%) + slippage.

3. **Mechanical discipline**: No emotional decisions, no indicators to misinterpret. The grid executes systematically.

4. **High trade frequency**: In our 7-day arena test, Grid+DCA made **144 trades** -- far more than any other strategy. Each trade captures a small profit.

5. **DCA smoothing**: Even if the grid range is wrong, DCA ensures ongoing accumulation at averaged prices.

6. **Self-replenishing**: When a grid buy fills, a new sell is placed; when a sell fills, a new buy is placed. The grid regenerates itself.

## Weaknesses

1. **Bleeds in strong trends**: If price drops 10%+ (breaking below the grid), all buy orders fill but no sells execute. You're left holding a bag at higher average cost. In our test, the strategy went negative (-0.28%) during the 2.7% market drop.

2. **Opportunity cost in strong rallies**: If BTC jumps 15%, the grid sells all positions early at lower levels. You capture only the grid-width profit, missing the bulk of the move. Buy&Hold would massively outperform.

3. **High capital requirement**: 20 grid levels at $50 each ties up $1,000 in pending orders. Capital efficiency is poor -- most of the budget sits idle as unfilled orders.

4. **Range dependency**: The 5% grid range is arbitrary. If volatility is 1%, the grid never triggers. If volatility is 15%, the grid is exhausted and becomes a one-way accumulator.

5. **DCA is always buying**: There's no sell-side DCA. In a bear market, DCA just keeps buying into falling prices, increasing losses.

6. **Accumulated fees on high frequency**: 144 trades at 0.08% each = $5.66 total cost. While each trade is cheap, the volume adds up.

## Ideal Market Conditions

- **Best**: Sideways/ranging market with 3-8% oscillations (choppy, no clear trend)
- **Good**: Mild uptrend with regular pullbacks
- **Poor**: Strong downtrend (buys fill, sells don't)
- **Worst**: Parabolic rally (sells early, misses most of the move)

## Arena Results (7-day BTC/USDT backtest)

```
Market: $80,267 -> $78,088 (-2.72%)
Grid+DCA:  ROI -0.28%  |  Alpha +2.43%  |  144 trades  |  Cost $5.66
```

Grid+DCA placed 3rd in the arena but generated massive alpha vs Buy&Hold (+2.43%). The strategy preserved capital far better than holding during the drop. Its high trade count means it was actively capturing small profits throughout the period.

## Bot Equivalents

| Bot | Feature Name | Key Difference |
|-----|-------------|----------------|
| **Pionex** | Grid Trading Bot | Supports arithmetic + geometric grids |
| **Bitsgap** | GRID Bot | Has "trailing up" to shift grid with trend |
| **3Commas** | Grid Bot | Integrates with 18+ exchanges |
| **KuCoin** | Spot Grid | AI parameter suggestion based on volatility |

## When to Use

Use Grid+DCA when you believe the market will be **range-bound** for the foreseeable future. It's the "boring but reliable" strategy -- it won't win big, but it won't lose big either. The combination of grid trading (profits from oscillation) and DCA (profits from time-averaged buying) provides a balanced approach.

Avoid it when you have strong directional conviction. If you think BTC will rally 20%, just buy and hold. If you think it'll crash 20%, stay in USDT.
