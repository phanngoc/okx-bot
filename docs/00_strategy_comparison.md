# Strategy Comparison Overview

## The Arena

Five active strategies + Buy&Hold benchmark compete head-to-head on the same historical price data. All strategies start with the same budget ($2,000), the same entry price, and the same fee model (OKX spot rates).

## Quick Comparison

| Strategy | Type | Inspired By | Trades/Week | Avg Cost | Best Market |
|----------|------|-------------|-------------|----------|-------------|
| Grid+DCA | Mechanical | Pionex, Bitsgap | 140+ | $5-6 | Sideways |
| TrailingDCA | Event-driven | 3Commas | 1-10 | $0-2 | V-shaped recovery |
| BB_Breakout | Momentum | Bollinger/Carter | 5-15 | $3-5 | Post-squeeze breakout |
| MeanRevert | Contrarian | Stat arb, Hummingbot | 8-15 | $4-6 | Range-bound |
| Debate | AI-driven | Research (MIT 2023) | 8-15 | $3-5 | News-driven |
| Buy&Hold | Passive | Buffett, Bogle | 0 | $0 | Bull market |

## Arena Results (7-day BTC/USDT, market -2.72%)

```
Rank  Strategy       ROI        Alpha     Trades  Cost
#1    MeanRevert    +0.46%     +3.18%     10     $5.31
#2    TrailingDCA   -0.28%     +2.43%      1     $0.24
#3    Grid+DCA      -0.28%     +2.43%    144     $5.66
#4    BB_Breakout   -0.37%     +2.34%      8     $3.59
#5    Debate        -0.84%     +1.87%     12     $3.54
#6    Buy&Hold      -2.72%      0.00%      0     $0.00
```

## Strategy DNA

### By Market Regime

```
                 Bull Rally    Sideways     Bear Dip     Crash
Grid+DCA         Poor          BEST         Good         Poor
TrailingDCA      Fair          Fair         Good         BEST (if V-recovery)
BB_Breakout      BEST          Poor         Poor         Poor
MeanRevert       Poor          BEST         Good         Fair
Debate           Fair          Fair         Fair         Fair
Buy&Hold         BEST          Poor         Poor         Poor
```

### By Signal Source

| Strategy | Technical | News | AI/LLM | Time-based |
|----------|-----------|------|--------|------------|
| Grid+DCA | Price levels | - | - | DCA interval |
| TrailingDCA | Price deviation | - | - | - |
| BB_Breakout | BB + RSI | - | - | - |
| MeanRevert | BB + RSI + ADX | - | - | - |
| Debate | RSI, MACD, BB, SMA, Vol, S/R | RSS feeds | Claude Haiku | Debate interval |
| Buy&Hold | - | - | - | - |

### By Fee Efficiency

| Strategy | Order Type | Fee Rate | Fee Advantage |
|----------|-----------|----------|---------------|
| Grid+DCA | Limit (grid) + Market (DCA) | 0.08% / 0.12% | Lowest per-trade (grid) |
| TrailingDCA | Market | 0.12% | Fewest total trades |
| BB_Breakout | Market | 0.12% | Moderate frequency |
| MeanRevert | Market | 0.12% | Moderate frequency |
| Debate | Market | 0.12% | + LLM cost (~$6/week) |
| Buy&Hold | None | 0% | Zero cost |

## Strengths vs Weaknesses Matrix

| Strategy | Core Strength | Core Weakness |
|----------|--------------|---------------|
| Grid+DCA | Profits from ANY oscillation | Bleeds in strong trends |
| TrailingDCA | Catches crash-and-bounce | Idle in calm markets |
| BB_Breakout | Catches explosive moves | False breakouts kill returns |
| MeanRevert | Statistical edge in ranges | Wrong during regime changes |
| Debate | Adapts to news/context | Slow, inconsistent, expensive |
| Buy&Hold | Zero cost, full upside capture | Zero downside protection |

## Risk Profile

| Strategy | Max Drawdown Risk | Capital at Risk | Recovery Speed |
|----------|-------------------|-----------------|----------------|
| Grid+DCA | Medium (all buys fill, no sells) | 65% grid + 35% DCA | Slow (needs grid repricing) |
| TrailingDCA | High (Martingale scaling) | Up to 100% if all safety orders fire | Medium (reset after TP) |
| BB_Breakout | Low (25% position + 3% stop) | Max 0.75% per trade | Fast (quick stop + re-entry) |
| MeanRevert | Medium (20% per position, 5 max) | Up to 100% if all 5 positions open | Medium (wait for mean reversion) |
| Debate | Medium (5-40% per trade) | Depends on LLM decisions | Unpredictable |
| Buy&Hold | Maximum (100% always invested) | 100% | Depends on market cycle |

## Complementary Pairs

These strategies complement each other when run together:

**Grid+DCA + MeanRevert**: Grid profits from small oscillations; MeanRevert catches the bigger oversold bounces. Together they cover both micro and macro range trading.

**TrailingDCA + BB_Breakout**: TrailingDCA profits from crashes (safety orders buy the dip); BB_Breakout profits from the recovery (catches the breakout after the crash). They cover both sides of a V-shape.

**Debate + Any**: The Debate bot provides a "human-like" overlay. It can be used as a confirmation filter: only trade when the rule-based strategy AND the debate agree.

## What 2 Months Will Tell Us

After 60 days of daily arena sessions, we'll know:

1. **Win rate**: How often does each strategy finish #1?
2. **Consistency**: Standard deviation of ROI across sessions
3. **Regime dependence**: Does MeanRevert always win in ranging markets? Does Grid+DCA dominate in oscillating markets?
4. **Fee drag**: Do high-frequency strategies (Grid) lose their edge over time due to accumulated fees?
5. **LLM value**: Does the Debate bot improve with more data, or is it consistently the weakest?
6. **Optimal portfolio**: What allocation across strategies maximizes risk-adjusted returns?

## File Reference

| Document | Strategy |
|----------|----------|
| [01_grid_dca.md](01_grid_dca.md) | Grid + DCA |
| [02_trailing_dca.md](02_trailing_dca.md) | Trailing DCA |
| [03_bollinger_breakout.md](03_bollinger_breakout.md) | Bollinger Breakout |
| [04_mean_reversion.md](04_mean_reversion.md) | Mean Reversion |
| [05_debate_agent.md](05_debate_agent.md) | Multi-Agent Debate |
| [06_buy_and_hold.md](06_buy_and_hold.md) | Buy & Hold (Benchmark) |
