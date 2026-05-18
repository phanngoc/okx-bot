# Buy & Hold (Benchmark)

## Origin

Buy & Hold is the oldest investment strategy, championed by **Warren Buffett**, **John Bogle** (Vanguard founder), and **Burton Malkiel** (*A Random Walk Down Wall Street*, 1973). The efficient market hypothesis (EMH) argues that since markets incorporate all available information, active trading cannot consistently beat a simple buy-and-hold approach after accounting for fees.

In the crypto arena, Buy & Hold serves as the **benchmark** -- any strategy that can't beat it is destroying value compared to simply buying and sitting.

## How It Works

```
Step 1: Buy $2,000 worth of BTC at the entry price
Step 2: Hold for the entire duration
Step 3: Calculate final portfolio value at exit price
```

That's it. No indicators, no decisions, no trades, no fees.

```python
bh_qty = budget / entry_price    # e.g., 2000 / 80267 = 0.02492 BTC
bh_pv = bh_qty * final_price     # e.g., 0.02492 * 78088 = $1,945.69
bh_roi = (bh_pv - budget) / budget * 100  # = -2.72%
```

## Parameters

None. This is the zero-parameter strategy.

## Fee Model

**Zero fees, zero slippage.** This is actually slightly unrealistic -- a real Buy & Hold would incur a one-time taker fee (0.10%) and slippage (0.02%) on the initial buy. For a $2,000 position, that's ~$2.40 in total cost. We ignore this because Buy & Hold is meant as an idealized benchmark.

## Strengths

1. **Captures 100% of any uptrend**: If BTC goes up 50% in a month, Buy & Hold captures the full 50%. No strategy that takes partial positions or exits early can match this in a strong bull run.

2. **Zero fees**: No trading means no friction. Over long periods, this compounds significantly. A strategy that trades 10x per day at 0.12% per trade pays ~1.2% daily in fees -- over a month, that's 36% lost to trading costs. Buy & Hold pays nothing.

3. **Zero emotional decisions**: No sell too early, no buy too late, no panic exits. The strategy is immune to behavioral finance biases.

4. **Historically superior**: Over Bitcoin's 15-year history, Buy & Hold has been the best strategy for any holding period > 4 years. From 2009 to 2025, BTC went from $0 to $80,000+. Any active trading during that period almost certainly underperformed holding.

5. **Zero operational complexity**: No servers to run, no API keys, no LLM costs, no monitoring needed. The ultimate "set and forget" approach.

6. **Benchmark for alpha**: Alpha is defined as `strategy_ROI - buyhold_ROI`. Any positive alpha means the strategy added value beyond simple holding.

## Weaknesses

1. **100% exposure to drawdowns**: If BTC drops 70% (as it did in 2022), Buy & Hold drops 70%. There's no risk management, no stop loss, no rebalancing. In our arena test, the -2.72% market drop became a -2.72% portfolio loss -- the worst of all strategies.

2. **No profit taking**: Even if the portfolio is up 100%, Buy & Hold never sells. It can ride a massive gain all the way back down to breakeven or below.

3. **Opportunity cost during ranging markets**: In a sideways market, the capital is locked up doing nothing. Strategies like Grid+DCA and MeanReversion actively profit from price oscillations during these periods.

4. **Requires infinite time horizon**: Buy & Hold only reliably works if you can hold "forever." On any finite timeframe, you might buy at a peak and exit at a trough. The 7-day arena window was exactly this scenario.

5. **No adaptability**: If fundamental conditions change (an exchange hack, a regulatory ban), Buy & Hold doesn't react. It's the exact opposite of adaptive strategies like the Debate bot.

## Ideal Market Conditions

- **Best**: Strong, sustained bull market (parabolic rally)
- **Good**: Mild uptrend over long periods (years)
- **Poor**: Sideways/ranging market (dead capital, active strategies do better)
- **Worst**: Bear market / crash (full exposure to all losses)

## Arena Results (7-day BTC/USDT backtest)

```
Market: $80,267 -> $78,088 (-2.72%)
Buy&Hold:  ROI -2.72%  |  Alpha +0.00%  |  0 trades  |  Cost $0
```

**Dead last.** Every active strategy beat Buy & Hold during this period. The +2-3% alpha from active strategies represents the value of tactical trading during a down market.

### Why Buy & Hold Lost

The arena period was a **mildly bearish week**. BTC dropped 2.72% with a range of about $79K-$82K. Active strategies profited from:
- MeanReversion: bought oversold bounces within the range
- Grid+DCA: captured small profits from grid oscillations
- TrailingDCA: preserved capital by keeping 90% in USDT

Buy & Hold was fully invested from hour 0 and absorbed the entire decline.

### When Buy & Hold Would Have Won

If BTC had rallied 10% during the week (e.g., $80K -> $88K):
- Buy & Hold: +10.00%
- MeanRevert: ~+2% (ADX filter would have blocked most trades in trending market)
- Grid+DCA: ~+5% (grid sells early, misses upper portion)
- TrailingDCA: ~+3% (small base order, safety orders never trigger in uptrend)

In bull markets, Buy & Hold is very hard to beat.

## The Real Question

Buy & Hold answers the question: **"Should I be trading at all?"**

If no strategy consistently beats Buy & Hold after fees over a 2-month period, the answer is no -- you should just buy and hold BTC.

This is why we run it as the benchmark. After 60 days of daily arena sessions, the leaderboard will show definitively whether active trading adds value in the current market regime.

## Historical Context: Bitcoin Buy & Hold

| Period | BTC Price Change | Would Active Strategies Win? |
|--------|-----------------|------------------------------|
| 2017 (bull) | +1,300% | No -- no strategy beats this |
| 2018 (bear) | -73% | Yes -- any risk management helps |
| 2019-2020 | +95% | Borderline -- depends on timing |
| 2021 (bull) | +60% | No -- momentum too strong |
| 2022 (bear) | -65% | Yes -- sell signals save capital |
| 2023-2024 | +150% | No -- buy and hold wins again |
| 2025 (current) | Ranging | Yes -- active strategies capture range |

The pattern: Buy & Hold wins in bull markets, active strategies win in bear/ranging markets. The challenge is knowing which regime you're in.
