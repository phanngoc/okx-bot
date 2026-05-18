# Trailing DCA Strategy

## Origin

This strategy is directly inspired by **3Commas** DCA Bot, the most popular automated trading bot for crypto (500K+ users). The core concept was adapted from traditional stock DCA but enhanced with **safety orders** (scale-in on dips) and **trailing take-profit** (lock gains by riding momentum up, then sell on pullback).

**Pionex** offers a similar "DCA Bot" and **Bitsgap** has a "DCA Bot" with "trailing" mode. The idea comes from **Martingale theory** -- doubling down on losing positions, but with bounded risk through position sizing limits.

## How It Works

### Phase 1: Base Order

On the first tick, the bot places a **base order** using 10% of the budget ($200 of $2,000). This establishes the initial position.

### Phase 2: Safety Orders (Scaling In)

As price drops from entry, the bot places increasingly larger buy orders:

```
Safety Order #1: -3%  from entry -> buy $200 * 1.5^0 = $200
Safety Order #2: -6%  from entry -> buy $200 * 1.5^1 = $300
Safety Order #3: -12% from entry -> buy $200 * 1.5^2 = $450
Safety Order #4: -20% from entry -> buy $200 * 1.5^3 = $675
Safety Order #5: -30% from entry -> buy $200 * 1.5^4 = $1,012
```

Each safety order is **1.5x larger** than the previous one. This aggressive scaling lowers the average entry price quickly, so a smaller bounce is needed to reach profit.

**Example**: If BTC enters at $80,000 and drops to $72,000 (-10%), safety orders #1-#3 fire. The average cost might be ~$76,000. A bounce to $77,520 (+2% from average) triggers take-profit -- even though the price is still 3% below entry.

### Phase 3: Trailing Take-Profit

When unrealized profit reaches the **take-profit threshold** (2% above average cost):

1. Trailing mode activates, tracking the price peak
2. If price continues rising, the peak updates (locking more profit)
3. If price drops **0.8% from the peak**, the bot sells 100% of the position
4. After selling, the entire cycle resets and waits for the next entry

```
avg_cost = $76,000
TP trigger = $77,520 (avg + 2%)
Price hits $78,000 -> trailing peak = $78,000
Price hits $78,500 -> trailing peak = $78,500
Price drops to $77,872 (0.8% below peak) -> SELL ALL
Profit: ~2.5% on the position
```

### Phase 4: Reset

After selling, the bot resets completely:
- Entry price cleared
- All safety order flags reset
- Trailing state cleared
- Ready for a new cycle

## Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `base_order_pct` | 10% | Budget % for initial buy |
| `safety_deviations` | [3, 6, 12, 20, 30] | Price drop % to trigger each safety order |
| `tp_pct` | 2.0% | Take-profit threshold above avg cost |
| `trailing_pct` | 0.8% | Drop from peak to trigger sell |
| `scale_factor` | 1.5x | Each safety order is 1.5x the previous |

## Fee Model

All orders are **market orders** (taker fee 0.10% + slippage 0.02%). The strategy trades infrequently -- in the 7-day test, it made only **1 trade** (the base order), meaning safety orders never triggered because the price didn't drop enough from entry.

## Strengths

1. **Excellent in V-shaped recoveries**: This is the strategy's sweet spot. If price drops 10% then bounces back, the safety orders buy heavily at the bottom, and the trailing TP locks in profits on the way up. The aggressive scaling (1.5x) means you buy MORE at LOWER prices.

2. **Built-in risk management**: The position size is bounded. Maximum total investment across all safety orders:
   ```
   $200 + $200 + $300 + $450 + $675 + $1,012 = $2,837
   But budget is only $2,000, so later orders get capped.
   ```

3. **Trailing TP captures momentum**: Instead of selling at a fixed target (which might sell right before a 5% rally), trailing TP rides the wave up and only exits on a confirmed reversal.

4. **Low trade frequency = low fees**: In the arena test, only $0.24 total cost. This is the cheapest active strategy.

5. **Automatic averaging**: The average cost calculation ensures you always know exactly how much profit you need to break even + TP.

6. **Full reset after profit**: Each cycle is independent. Past performance doesn't contaminate future decisions.

## Weaknesses

1. **Frozen in slow bleeds**: If price drops slowly (1% per day for 30 days), safety orders trigger one by one, averaging down into a losing position. The price never bounces enough to trigger TP, and you're stuck holding an underwater position indefinitely.

2. **Inactive in mild markets**: In the arena test, the price only moved -2.7% from entry over 7 days. Only the base order triggered, and the TP never hit. The strategy was effectively idle -- $200 invested, $1,800 sitting as cash. ROI: -0.28%.

3. **One direction only (long)**: There's no short-side logic. In a confirmed bear market, the bot keeps buying dips that keep dipping.

4. **Martingale risk**: The 1.5x scaling means late safety orders are very large. If all 5 fire, you've deployed your entire budget at a moment of maximum fear. If the price drops further, you're fully exposed with no cash left.

5. **No partial exits**: The trailing TP sells 100% of the position. There's no concept of taking partial profits or scaling out, which could be more profitable in certain scenarios.

6. **Gap risk**: In crypto, flash crashes can blow past all safety order levels in minutes. You might go from entry to -35% instantly, deploying all capital at a single (bad) price level.

## Ideal Market Conditions

- **Best**: Sharp dips followed by V-shaped recoveries (flash crashes, FUD events that reverse)
- **Good**: Regular oscillations with 5-15% swings
- **Poor**: Slow steady decline (safety orders fire one by one, no recovery)
- **Worst**: Prolonged bear market (maximum capital deployed at worst prices)

## Arena Results (7-day BTC/USDT backtest)

```
Market: $80,267 -> $78,088 (-2.72%)
TrailingDCA:  ROI -0.28%  |  Alpha +2.43%  |  1 trade  |  Cost $0.24
```

Placed 2nd in the arena -- essentially tied with Grid+DCA. However, this was a deceptive result: the strategy was mostly idle (only the base order of $200 was invested). The remaining $1,800 was in USDT, which naturally protected the portfolio value during the downturn. In a sense, TrailingDCA "won" by not playing.

## Bot Equivalents

| Bot | Feature Name | Key Difference |
|-----|-------------|----------------|
| **3Commas** | DCA Bot | The original; supports long/short, TradingView signals |
| **Pionex** | DCA Bot | Simpler interface, built-in to exchange |
| **Bitsgap** | DCA Bot | Trailing mode, integrated portfolio view |
| **Cornix** | DCA Bot | Telegram-integrated for signal groups |

## When to Use

Use TrailingDCA when you expect **volatile but ultimately recovering** markets. It's ideal for:
- Trading altcoins that have sharp drawdowns but tend to bounce
- Holding during uncertain macro periods (safety orders buy the fear)
- Running alongside a grid bot as a "crash insurance" strategy

Avoid it in slow grinds down or in very calm markets where the safety orders never trigger and the capital sits idle.

## Optimization Ideas

1. **Tighter safety deviations** for BTC (e.g., [1.5, 3, 6, 10, 15]) since BTC is less volatile than altcoins
2. **Multiple cycles**: Allow the bot to restart after TP instead of waiting for the full duration
3. **Scale factor tuning**: 1.5x is aggressive; 1.2x is safer for larger budgets
4. **Time-based exit**: If no TP is hit after X hours, reduce position size instead of holding indefinitely
