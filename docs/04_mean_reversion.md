# Mean Reversion Strategy

## Origin

Mean reversion is one of the oldest concepts in statistics, formulated by **Francis Galton** in 1886 as "regression toward the mean." In finance, the idea is that prices tend to return to their average value after extreme deviations. **Pairs trading** (a hedge fund staple since the 1980s at Morgan Stanley) and **statistical arbitrage** are both based on mean reversion.

In crypto, **Hummingbot** (open-source market maker) and **Freqtrade** (Python bot framework) both implement mean reversion strategies. The approach is contrarian by nature: buy when others are fearful (oversold), sell when others are greedy (overbought).

## How It Works

### Core Principle

The strategy buys when price is statistically "too low" and sells when it's "too high." It uses two confirmation signals and one market regime filter:

**Buy Signal** (all three must be true):
1. RSI < 30 (oversold -- momentum has exhausted to the downside)
2. Price <= Lower Bollinger Band (price is statistically extreme -- 2 standard deviations below mean)
3. ADX < 25 (market is ranging, not trending -- mean reversion works in ranges, not trends)

**Sell Signal** (either one):
1. RSI > 70 (overbought -- momentum has exhausted to the upside)
2. Price >= Upper Bollinger Band (price has reverted past the mean to the other extreme)

**Emergency Stop**:
- If price drops 3% below the lower Bollinger Band, sell 50% of position to limit losses

### The ADX Filter (Why This Matters)

The most critical component is the **ADX proxy** that filters out trending markets:

```
ADX proxy logic:
  Price range in last 20 candles > 5% -> ADX = 40 (TRENDING, do not trade)
  Price range in last 20 candles > 3% -> ADX = 25 (BORDERLINE, do not trade)
  Price range in last 20 candles < 3% -> ADX = 15 (RANGING, trade allowed)
```

**Why this matters**: Mean reversion is WRONG during trends. If BTC is in a confirmed downtrend, an RSI of 28 doesn't mean "oversold bounce imminent" -- it means "trend is strong, will probably continue lower." The ADX filter prevents the strategy from catching falling knives.

In the arena test, this filter was key: the strategy only traded during the calm, ranging periods and stayed out during the trending phase at the end (when BTC dropped from $80.5K to $78K).

### Position Management

```
Max positions: 5
Position size: 20% of budget per entry ($400 each)
Max exposure: 100% of budget (5 * 20%)
```

Multiple positions can be open simultaneously at different price levels, providing a natural averaging effect.

## Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `bb_period` | 20 | Bollinger Band lookback |
| `rsi_period` | 14 | RSI lookback |
| `rsi_buy` | 30 | Buy below this RSI |
| `rsi_sell` | 70 | Sell above this RSI |
| `position_pct` | 20% | Budget per position |
| `max_positions` | 5 | Maximum concurrent positions |

## Fee Model

All orders are **market orders**: taker fee 0.10% + slippage 0.02% = 0.12% per trade. The strategy made 10 trades in 7 days -- moderate frequency. Total cost: $5.31.

## Strengths

1. **Won the arena**: MeanRevert was the only strategy with **positive ROI (+0.46%)** in a -2.72% market. This is significant -- in a down market, it didn't just lose less, it actually made money.

2. **Statistical edge is well-established**: Mean reversion is one of the few market phenomena with strong academic backing. Prices do revert to their mean in ranging markets. This isn't a pattern-matching hope -- it's a statistical property of financial time series.

3. **ADX filter prevents trend-following mistakes**: The biggest killer of mean reversion strategies is trading against a strong trend. The ADX filter correctly identifies when to sit out, which is arguably more important than knowing when to trade.

4. **Asymmetric risk/reward**: Buying at the lower Bollinger Band means you're buying at a 2-standard-deviation discount. If the statistical distribution holds, there's a ~95% probability that price will revert above the lower band.

5. **Multiple position averaging**: By allowing up to 5 positions, the strategy naturally averages into oversold conditions. If the first buy at RSI 28 is too early, subsequent buys at RSI 22 and RSI 18 lower the average cost.

6. **Clear sell rules**: The sell at RSI > 70 or upper BB provides concrete exit points. No subjective "I think it's time to sell" decisions.

## Weaknesses

1. **Dependent on range detection**: The ADX proxy is simplified -- it uses a crude price range calculation instead of the actual ADX indicator. This could miss trending markets that appear calm on a 20-candle window but are clearly trending on longer timeframes.

2. **Dangerous in regime changes**: Mean reversion works until it doesn't. When a market transitions from ranging to trending (e.g., after a major news event), the strategy's buys at "oversold" levels become losing trades in a new trend.

3. **The "knife catching" problem**: Even with the ADX filter, there are scenarios where the filter shows "ranging" but a fast crash is developing. The 3% emergency stop helps but only after you've already lost.

4. **Slow in trending markets**: If BTC goes on a 30% rally, the strategy sits in USDT the entire time (ADX > 25, no trade). Buy&Hold would massively outperform during bull runs.

5. **RSI boundaries are fixed**: RSI < 30 works differently at different timescales. In a 1-hour chart, RSI < 30 might recover in hours. In a daily chart, it might take weeks. The fixed thresholds don't adapt to the timeframe.

6. **Full sell at overbought**: When RSI > 70, the strategy sells 100% of the position. But in strong uptrends (which the ADX filter might not catch immediately), RSI > 70 can persist for days while price keeps rising.

## Ideal Market Conditions

- **Best**: Choppy, range-bound market with clear support/resistance levels. BTC trading between $75K-$82K for weeks. Mean reversion is almost "free money" in this environment.
- **Good**: Mild downtrend with regular oversold bounces (each bounce captured by buy signal)
- **Poor**: Strong trending market in either direction (ADX filter keeps strategy idle)
- **Worst**: Black swan crash that blows through all support levels (3% stop is too wide)

## Arena Results (7-day BTC/USDT backtest)

```
Market: $80,267 -> $78,088 (-2.72%)
MeanRevert:  ROI +0.46%  |  Alpha +3.18%  |  10 trades  |  Cost $5.31
```

**The arena winner.** Let's analyze why:

### Trade Timeline
- **0-56h**: 0 trades. Market was ranging mildly (+1.5% to +2%), but RSI never hit 30 and price never touched the lower BB. Strategy waited.
- **84h**: 1 trade. Price dipped to $80,642 and RSI briefly hit oversold territory. Strategy bought.
- **112h**: 4 trades. Market dropped to $79,361. Multiple buys triggered as price hit lower BB repeatedly. Average cost was lowered.
- **140h**: 5 trades. Market recovered to $80,581. Some sells triggered at RSI > 70 or upper BB. ROI jumped to +1.18%.
- **168h (final)**: 10 trades. Final price $78,088. Some late sells locked in profits, but the final drop reduced unrealized gains.

The strategy correctly identified the ranging period (hours 56-140) and traded it profitably. When the market broke down at the end, it had already taken profits on earlier trades.

## Bot Equivalents

| Bot | Feature Name | Key Difference |
|-----|-------------|----------------|
| **Hummingbot** | Pure Market Making | Uses bid/ask spread instead of BB/RSI |
| **Freqtrade** | Custom strategies | Open-source Python, highly configurable |
| **Mudrex** | Strategy canvas | Visual strategy builder with mean reversion templates |
| **Cryptohopper** | Strategy Designer | Combines multiple indicator signals |

## When to Use

Use MeanReversion when:
- Market has been ranging for >5 days with no clear trend
- Implied/realized volatility is moderate (not too low, not too high)
- You're comfortable being contrarian (buying dips when sentiment is fearful)
- You want a statistically-grounded approach rather than momentum-chasing

Avoid it when:
- A clear trend is forming (bull or bear)
- Major macro events are expected (FOMC, CPI release, halving)
- Volatility is extremely high (mean reversion fails in panic)

## Why It Won (And When It Won't)

The arena test happened during a **mildly bearish, range-bound week**. This is MeanReversion's optimal environment. In a strong trending market (bull run or crash), this strategy would likely underperform Grid+DCA or even Buy&Hold.

The +0.46% ROI in a -2.72% market translates to **+3.18% alpha** -- the highest of any strategy. But one week is not a statistically significant sample. Over 2 months of daily arenas, the true picture will emerge.

## Optimization Ideas

1. **True ADX calculation**: Replace the price-range proxy with the actual ADX formula (Directional Movement Index by Welles Wilder)
2. **Dynamic RSI thresholds**: Use RSI percentiles instead of fixed 30/70. In a bull market, "oversold" might be RSI 40.
3. **Z-score entry**: Instead of BB + RSI, use a price z-score > 2 as the signal (pure statistical approach)
4. **Partial exits**: Sell 50% at RSI 60, remaining 50% at RSI 70 -- capture the full reversion without giving back all gains
5. **Time-based exit**: If a position hasn't hit TP in 48h, reduce by 25% -- don't hold losing positions indefinitely
