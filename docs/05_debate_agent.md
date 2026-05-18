# Multi-Agent Debate Strategy

## Origin

The multi-agent debate framework originates from AI research, particularly **"Improving Factuality and Reasoning in Language Models through Multiagent Debate"** (Du et al., 2023, MIT). The paper showed that having multiple LLM agents argue from different perspectives produces better reasoning than a single agent.

Applied to trading, this mirrors the structure of a professional **investment committee**: a bull analyst (long thesis), a bear analyst (short thesis), and a portfolio manager (final decision). Hedge funds like Bridgewater Associates famously use this "radical transparency" debate format for investment decisions.

No existing crypto bot platforms offer an LLM-powered debate system. This strategy is unique to our implementation.

## How It Works

### Architecture: Three Agents

```
         Technical Indicators + News
                    |
            +-------+-------+
            |               |
        BULL AGENT      BEAR AGENT
        (find reasons    (find reasons
         to BUY)          to SELL)
            |               |
            +-------+-------+
                    |
             MODERATOR AGENT
             (weigh arguments,
              final decision)
                    |
            BUY / SELL / HOLD
```

### Agent 1: Bull Agent

**Bias**: Optimistic. Actively looks for reasons to buy.

**Input**: Technical indicators (RSI, MACD, SMA, BB, volume, support/resistance) + news sentiment

**LLM Prompt**: "You are the BULLISH analyst. Look for oversold conditions as buying opportunities, positive momentum forming, support levels holding, positive news as catalysts."

**Output**: `Signal(direction, confidence, reasoning, score)` where score ranges from -100 to +100 (biased positive)

**Rule-based Fallback** (when LLM times out or refuses):
```
RSI < 30:         +30 points ("oversold - strong buy zone")
MACD histogram > 0: +20 points ("positive momentum")
Price > SMA20 > SMA50: +25 points ("uptrend confirmed")
Price at lower BB: +20 points ("bounce expected")
Volume > 1.5x avg: +10 points ("strong interest")
Near support:     +15 points ("support holding")
Bullish news:     +20 points
```

### Agent 2: Bear Agent

**Bias**: Pessimistic. Actively looks for reasons to sell or avoid buying.

**LLM Prompt**: "You are the BEARISH analyst. Look for overbought conditions as sell signals, weakening momentum and divergences, resistance levels about to reject price, negative news as warning signs."

**Rule-based Fallback**:
```
RSI > 70:         -30 points ("overbought")
MACD histogram < 0: -20 points ("negative momentum")
Price < SMA20 < SMA50: -25 points ("downtrend")
Price at upper BB: -20 points ("rejection expected")
Low volume:       -10 points ("weak rally")
Near resistance:  -15 points ("about to reject")
Bearish news:     -20 points
```

### Agent 3: Moderator

**Role**: Weighs bull vs bear arguments, considers consensus/divergence, makes final call.

**Decision Logic**:
1. **Weighted average**: `combined_score = bull_score * 0.50 + bear_score * 0.50`
2. **Consensus bonus**: If both agents agree on direction, add +/-15 points
3. **Divergence handling**: If scores diverge by >60 points, follow the stronger signal with 15% weight bonus
4. **Volatility damping**: If BB width > 5%, reduce score by 20% (be cautious in high volatility)
5. **News amplifier**: If news score > 40, add 10% of news score to combined

**Position Sizing**:
```
BUY:  position_pct = min(40%, max(5%, combined_score / 2))
SELL: position_pct = min(40%, max(5%, |combined_score| / 2))
HOLD: no action
```

### Execution in Arena

The debate runs every **4 hours** (configurable). Between debates, the position is held unchanged. Each debate cycle:

1. Fetch latest 50 candles for technical analysis
2. Compute all indicators (RSI, MACD, SMA, BB, volume, support/resistance)
3. Feed to Bull and Bear agents (LLM with rule-based fallback)
4. Moderator synthesizes and decides
5. Execute trade if direction is BUY or SELL with confidence > 5

### News Integration

Every 12 hours (every 4th debate), news sentiment is refreshed:
- 7 RSS feeds crawled (CoinTelegraph, CoinDesk, Decrypt, TheBlock, etc.)
- Headlines filtered by coin keyword
- Bull/bear word scoring (-100 to +100)
- Fed into both agents as additional context

## Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `debate_interval` | 4h | Hours between debate cycles |
| `confidence_threshold` | 5 | Minimum confidence to act |
| `max_buy_pct` | 40% | Maximum position size per buy |
| `min_buy_pct` | 5% | Minimum position size per buy |
| `news_refresh_interval` | 12h | Hours between news sentiment updates |

## Fee Model

All orders are **market orders**: taker fee 0.10% + slippage 0.02% = 0.12% per trade. Trade frequency depends entirely on LLM decisions -- in the arena test, 12 trades over 7 days (roughly 1.7 per day).

## Strengths

1. **Adaptive to any market condition**: Unlike rule-based strategies that have fixed parameters, the LLM agents can reason about unprecedented situations. When news breaks about a regulatory change, the agents can factor in context that no fixed indicator would capture.

2. **Balanced perspective**: The bull-bear-moderator structure prevents single-perspective bias. A solo LLM might be consistently bullish or bearish; the debate format forces both sides to present their case.

3. **Integrates multiple data sources**: Technical analysis + news sentiment + LLM reasoning. No other strategy in the arena combines quantitative indicators with qualitative news analysis.

4. **Self-documenting decisions**: Every trade comes with a full reasoning log (bull arguments, bear arguments, moderator decision). This is invaluable for post-hoc analysis and strategy improvement.

5. **Rule-based fallback ensures reliability**: When the LLM times out (happened 3x in the arena test), the rule-based system takes over seamlessly. The bot never freezes waiting for an API call.

6. **Consensus mechanism reduces noise**: The moderator's consensus bonus (+15 for agreement) and divergence handling create a natural noise filter. Random LLM outputs that contradict each other lead to HOLD decisions, which is the correct default.

## Weaknesses

1. **Slowest strategy to execute**: Each debate cycle requires 3 LLM calls (bull, bear, moderator). With 30-45 second timeouts, a single debate cycle can take 2-3 minutes. In the arena, this made the backtest 10x slower than pure rule-based strategies.

2. **LLM inconsistency**: The same technical data can produce different recommendations on different calls. LLMs are non-deterministic, so the strategy's decisions have a random component. In one test, the bull agent might say "buy" with 70% confidence; re-running with identical data might yield 45% confidence.

3. **Worst ROI in the arena (-0.84%)**: Among the 5 active strategies, the debate bot performed the worst. The LLM decisions didn't consistently outperform simple rule-based strategies. The -0.84% ROI suggests the bot made several bad calls.

4. **High latency = missed opportunities**: With 4-hour debate intervals, the bot can miss rapid market moves. A flash crash at hour 1 won't trigger a response until hour 4, by which time the opportunity may be gone.

5. **Cost per decision**: Each debate uses 3 Claude Haiku calls at ~$0.05 budget each. Over 42 debates (7 days), that's ~$6.30 in LLM costs -- not counted in the trading fees but a real operational expense.

6. **Prompt engineering sensitivity**: The quality of trading decisions is highly dependent on how the prompts are written. A poorly phrased prompt can lead the LLM to be too cautious (always HOLD) or too aggressive (always BUY). The current prompts work but aren't optimized.

7. **News sentiment is crude**: The bull/bear keyword scoring is simplistic. "Bitcoin crashes to new low" and "Bitcoin crashes through resistance to new high" would both score as bearish due to the word "crashes."

## Ideal Market Conditions

- **Best**: News-driven markets where fundamental analysis matters (regulatory announcements, ETF approvals, major hacks). The LLM can interpret context that no technical indicator captures.
- **Good**: Transition periods between bull and bear markets where human-like judgment helps
- **Poor**: Calm, technical markets where simple indicators (RSI, BB) are sufficient
- **Worst**: Flash crash scenarios (too slow to react) or strongly trending markets (LLM waffles between bull and bear)

## Arena Results (7-day BTC/USDT backtest)

```
Market: $80,267 -> $78,088 (-2.72%)
Debate:  ROI -0.84%  |  Alpha +1.87%  |  12 trades  |  Cost $3.54
```

Placed 5th (last among active strategies). Let's analyze the timeline:

- **28h**: 7 debates, 0 trades. All decisions were HOLD -- likely because confidence was below the threshold.
- **56h**: 14 debates, trades started. ROI +0.34% -- the bot bought during the mini rally to $81,860.
- **84h**: 21 debates, ROI dropped to -0.38%. The bot bought near the top and the market reversed.
- **112h**: 28 debates, ROI -0.81%. Market at $79,361. LLM kept holding losing positions.
- **140h**: 35 debates, ROI -0.18%. Some recovery as market bounced to $80,581.
- **168h (final)**: 42 debates, ROI -0.84%. Final market drop to $78,088 hurt the positions.

The pattern shows the LLM made a bad timing call: buying during a brief rally that turned out to be a dead cat bounce.

## Bot Equivalents

There are no direct equivalents in existing crypto bot platforms. The closest analogies:

| Platform | Feature | Difference |
|----------|---------|------------|
| **TradingView** | Community signals | Human analysts, not LLM agents |
| **Dash2Trade** | AI-powered signals | Proprietary model, single perspective |
| **Numerai** | Ensemble models | Crowd-sourced ML models, not debate format |
| **CryptoGPT** | AI-assisted trading | Single LLM, no adversarial structure |

## When to Use

Use the Debate strategy when:
- You want a "second opinion" alongside rule-based strategies
- Major news events are expected and you want AI interpretation
- You're running it as an ensemble member (not sole strategy)
- You value explainability (every decision has documented reasoning)

Avoid it when:
- You need fast execution (4-hour debate interval is too slow for scalping)
- You want deterministic, reproducible results
- Operating costs matter (LLM calls add up)
- Market is purely technical (no news catalysts)

## Optimization Ideas

1. **Faster model**: Switch from Haiku to a faster/cheaper model for bull/bear, keep Haiku for moderator only
2. **Shorter interval**: Run debates every 1 hour instead of 4 for faster response
3. **Memory across debates**: Give the moderator access to previous debate results -- currently each debate is independent with no memory
4. **Better news processing**: Use LLM to summarize news rather than keyword scoring
5. **Confidence calibration**: Track accuracy of past predictions and weight future decisions by historical accuracy
6. **Ensemble with rules**: Use LLM decisions as a modifier on rule-based signals, not as standalone decisions
7. **Multi-model debate**: Use different LLM models for bull vs bear to increase perspective diversity
