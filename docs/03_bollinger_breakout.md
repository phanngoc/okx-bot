# Bollinger Band Breakout Strategy

## Origin

Bollinger Bands were developed by **John Bollinger** in the 1980s and published in his 2001 book *Bollinger on Bollinger Bands*. The "squeeze" concept -- where narrowing bands precede explosive moves -- became a widely traded pattern, especially after **John Carter** popularized the TTM Squeeze indicator.

In crypto trading, **Bitsgap**, **TradeSanta**, and **Quadency** all offer Bollinger-based bots. The breakout variant is particularly suited to crypto because of the asset class's tendency toward volatility compression followed by explosive moves.

## How It Works

### The Theory: Volatility Mean-Reverts

Bollinger Bands measure volatility using standard deviation. When bands narrow (low volatility), it means the market is "coiling" -- building pressure for a directional move. Like a spring being compressed, the tighter the squeeze, the more violent the eventual breakout.

```
BB Width = (Upper Band - Lower Band) / Middle Band * 100

Wide (>4%):   High volatility, active market
Normal (2-4%): Average conditions
Squeeze (<2%): Compression, breakout imminent
```

### Step 1: Detect Squeeze

The bot continuously monitors BB width. When `width_pct < 2.0%` (the squeeze threshold), it sets `in_squeeze = True`. This is the alert phase -- a breakout is being anticipated.

### Step 2: Confirm Breakout

Once in squeeze, the bot watches for price to break above the upper band **AND** RSI > 50 (confirming bullish momentum). Both conditions must be true:

```python
if self.in_squeeze and self.position_side is None:
    if price > bb["upper"] and rsi > 50:
        # BREAKOUT CONFIRMED -> BUY
```

On confirmation, the bot buys with 25% of the total budget.

### Step 3: Manage Position

Once in a position, three exit conditions are monitored:

1. **Stop Loss (3%)**: If price drops 3% from entry, sell 100% immediately
   ```
   Entry: $80,000 -> Stop at $77,600
   ```

2. **Partial Take-Profit**: If price is above upper BB AND RSI > 75 (overbought), sell 60% of the position
   ```
   Lock profits while keeping 40% exposure for further upside
   ```

3. **Mean Reversion Exit**: If price drops below the middle band, sell 100%
   ```
   The breakout has failed -- price reverted to the mean
   ```

### Step 4: Reset Squeeze Detection

When BB width exceeds `squeeze_threshold * 1.5` (3.0%), the squeeze flag resets. This prevents re-entering too quickly after a false breakout.

## Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `bb_period` | 20 | Bollinger Band lookback period |
| `bb_std` | 2.0 | Standard deviations for bands |
| `squeeze_threshold` | 2.0% | BB width below this = squeeze |
| `rsi_period` | 14 | RSI lookback period |
| `position_pct` | 25% | Budget per position |
| `stop_loss_pct` | 3.0% | Maximum loss before exit |

## Fee Model

All orders are **market orders**: taker fee 0.10% + slippage 0.02% = 0.12% per trade. The strategy trades moderately -- 8 trades in the 7-day test, mostly entry + stop-loss or entry + mean-reversion-exit pairs.

## Strengths

1. **Catches explosive moves**: When a true breakout occurs after a long squeeze, the move can be 5-15% in a day. The strategy is designed to be positioned exactly when this happens.

2. **Clear risk management**: The 3% stop loss limits downside per trade. With 25% position sizing, the maximum loss per trade is:
   ```
   25% of budget * 3% stop loss = 0.75% of total portfolio
   ```

3. **Partial profit taking**: The 60% partial sell at overbought conditions locks in profits while keeping 40% exposure. This balances greed and caution.

4. **Physics of volatility**: Volatility is one of the few mean-reverting properties in financial markets. Low volatility *does* precede high volatility -- this is empirically proven across all asset classes.

5. **Works in both directions**: Although our implementation only goes long, the squeeze pattern works for both breakouts and breakdowns. (A bearish version could short on downward breakouts.)

6. **Moderate trade frequency**: 8 trades in 7 days means roughly 1 trade per day. Low enough for low fees, high enough to capture opportunities.

## Weaknesses

1. **False breakouts are the killer**: The #1 problem. Price breaks above the upper band, the bot buys, then price immediately reverses back inside. The stop loss triggers at -3%, and the bot loses. In crypto, false breakouts happen frequently, especially around resistance levels.

   In the arena test, the strategy had **negative ROI (-0.37%)** -- likely multiple false breakouts that hit the stop loss.

2. **Lagging indicators**: Bollinger Bands are calculated from past prices. By the time the squeeze is detected and the breakout confirmed, the move may already be partially complete. You're buying after the initial burst.

3. **Long-only limitation**: In a bear market with downward breakouts, the strategy sits idle. It can only profit from upward moves, missing half of all breakout opportunities.

4. **RSI filter is crude**: RSI > 50 as a confirmation is loose. In choppy markets, RSI oscillates around 50 rapidly, causing frequent false signals. A stronger filter (like volume confirmation or multi-timeframe analysis) would reduce false positives.

5. **Volume proxy is weak**: Our implementation uses a price-change proxy instead of actual volume data. Real volume data would significantly improve breakout confirmation. The `_volume_proxy()` method approximates volume by measuring recent price movement magnitude vs average -- this correlates with but doesn't equal actual volume.

6. **Single timeframe**: The bot only analyzes 1-hour candles. Professional breakout traders typically confirm on multiple timeframes (e.g., daily squeeze + hourly breakout for entry).

## Ideal Market Conditions

- **Best**: Extended consolidation (1-2 weeks of low volatility) followed by news catalyst or technical breakout
- **Good**: Trending market with regular consolidation pauses
- **Poor**: Choppy market with frequent false breakouts (the most common crypto condition)
- **Worst**: Slow bear market with downward breakouts (can't profit from short side)

## Arena Results (7-day BTC/USDT backtest)

```
Market: $80,267 -> $78,088 (-2.72%)
BB_Breakout:  ROI -0.37%  |  Alpha +2.34%  |  8 trades  |  Cost $3.59
```

Placed 4th in the arena. The negative ROI suggests multiple false breakouts hit the stop loss. However, the strategy still generated +2.34% alpha vs Buy&Hold because it was mostly in cash (75% of budget never deployed) during the decline.

### Trade Pattern Analysis

From the periodic reports:
- **28h**: 0 trades -- waiting for squeeze
- **56h**: 2 trades -- first breakout attempt
- **84h**: 2 trades -- no new action (still in same positions or stopped out)
- **112h**: 4 trades -- more attempts, ROI dropped to -0.52%
- **140h**: 8 trades -- continued churn, losing on false breakouts

The pattern shows the strategy tried multiple breakout entries but kept getting stopped out.

## Bot Equivalents

| Bot | Feature Name | Key Difference |
|-----|-------------|----------------|
| **TradeSanta** | Bollinger-based triggers | Part of their composite signal system |
| **Bitsgap** | Technical Analysis bots | Combines BB with other indicators |
| **Quadency** | Smart Trading | BB breakout as one of many pre-built strategies |
| **TradingView** | Strategy alerts | BB squeeze alerts trigger external bots |

## When to Use

Use Bollinger Breakout when:
- The market has been in a tight range for >1 week (look at daily BB width)
- You want to catch the start of a new trend
- You have patience for false breakouts (the cost of the stop loss is the "premium" you pay)

Avoid it when:
- The market is already highly volatile (no squeeze to break out of)
- You need consistent returns (this strategy has long idle periods punctuated by big wins or small losses)
- You're in a confirmed bear market (long-only breakouts won't work)

## Optimization Ideas

1. **Add volume confirmation**: Use actual exchange volume data, require 1.5x average volume for breakout confirmation
2. **Multi-timeframe**: Require daily BB squeeze before looking for hourly breakout entries
3. **Adaptive stop loss**: Use ATR (Average True Range) instead of fixed 3% for dynamic stop loss sizing
4. **Short-side breakouts**: Add ability to short when price breaks below lower BB after squeeze
5. **Filter by trend**: Only take long breakouts when the 50-period MA is rising (trend-following filter)
