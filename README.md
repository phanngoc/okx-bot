# OKX Trading Bot — Multi-Strategy Simulator

Two trading strategies running in parallel on real OKX market data, competing against Buy & Hold benchmark. **Paper trading only — no real money involved.**

## Strategies

### Grid + DCA Bot
- Places grid orders at fixed price intervals around entry price
- Dollar-cost averages on a schedule (default: every 4h)
- Profits from sideways/choppy markets

### Multi-Agent Debate Bot
- **Bull Agent**: Looks for reasons to buy (oversold, momentum, support)
- **Bear Agent**: Looks for reasons to sell (overbought, resistance, distribution)
- **Moderator**: Weighs both arguments, considers risk, makes final call
- Agents powered by **Claude AI** via CLI proxy (falls back to rule-based if unavailable)
- Fetches real-time news from 7 RSS feeds + CryptoCompare API

## Architecture

```
┌─────────────────────────────────────────────┐
│              dual_runner.py                 │
│         (runs both bots in parallel)        │
├──────────────────┬──────────────────────────┤
│   Grid+DCA Bot   │   Debate Bot             │
│   run.py         │   debate_bot.py          │
│   strategy.py    │   agents.py (Bull/Bear/  │
│   config.py      │              Moderator)  │
│   tracker.py     │   llm_proxy.py (Claude)  │
│                  │   news_sentiment.py (RSS) │
│                  │   technical.py (TA)       │
└──────────────────┴──────────────────────────┘
         │                    │
         └────── ccxt ────────┘
              (OKX API)
```

## Quick Start

```bash
pip install -r requirements.txt

# One-shot debate analysis
python debate_bot.py

# Fast backtest 7 days — both bots
python dual_runner.py --fast --hours 168

# Live simulation 72h — both bots, debate every 3h
python dual_runner.py --hours 72 --debate-interval 3

# Grid+DCA only
python run.py --hours 72

# Debate bot only
python debate_bot.py --live --hours 72
```

## Claude AI Integration

The debate agents use Claude via the locally authenticated Claude Code CLI — no API key needed:

```
claude -p --model haiku --no-session-persistence "analyze BTC..."
```

If Claude CLI is unavailable or times out, agents automatically fall back to rule-based analysis.

## RSS News Sources

- CoinTelegraph, CoinDesk, Decrypt, The Block
- Bitcoin Magazine, CryptoSlate, news.bitcoin.com
- CryptoCompare API (backup)

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--symbol` | BTC/USDT | Trading pair |
| `--budget` | 2000 | Budget per bot (USDT) |
| `--hours` | 72 | Simulation duration |
| `--fast` | off | Fast backtest mode |
| `--debate-interval` | 4 | Hours between debates |
| `--grids` | 20 | Number of grid levels |
| `--grid-range` | 5.0 | Grid range +/- % |
| `--dca-interval` | 4.0 | DCA buy interval (hours) |
| `--dca-amount` | 30.0 | USDT per DCA buy |

## Disclaimer

This is an educational paper trading simulator. Not financial advice. No real funds are used.
