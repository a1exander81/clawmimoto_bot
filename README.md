# CLAW TRADE — Institutional 5M Crypto Trading Bot

**Telegram-native, ISOLATED margin, 3 trades/day max, $CLUSDT mock ledger.**

[![CI](https://github.com/your-org/clawforge/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/clawforge/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/your-org/clawforge/branch/main/graph/badge.svg)](https://codecov.io/gh/your-org/clawforge)
[![CodeRabbit](https://img.shields.io/coderabbit/pr/your-org/clawforge?style=flat-square)](https://coderabbit.ai)

---

## 🚀 Features

- **5M TF Sniper** — Institutional-grade technical analysis on 5-minute candles
- **BingX Integration** — Spot & futures, ISOLATED margin only
- **Telegram 0-Type UI** — Pure button-driven interface, no typing
- **Mock Trading** — $10,000 $CLUSDT virtual balance for risk-free testing
- **Auto-Broadcast** — Winning trades auto-post to @RightclawTrade with meme cards
- **StepFun Sentiment** — Optional LLM filter for market context
- **Risk-First** — 20% hard SL, 50% trailing lock, 1-2% risk per trade

---

## 📦 Quick Start

### Docker (Recommended)
```bash
docker-compose up -d
```

### Local Development
```bash
python -m venv venv
source venv/bin/activate
pip install -e .[dev]
freqtrade trade --strategy Claw5MSniper --dry-run
```

---

## 🔧 Configuration

See `configs/config.json` for all parameters. Key settings:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `timeframe` | `5m` | 5-minute candles only |
| `max_open_trades` | `3` | Max concurrent (one per session) |
| `stoploss` | `-0.25` | 25% hard stop loss |
| `trailing_stop_positive` | `0.5` | Move SL to breakeven at +50% |
| `minimal_roi` | `{"0": 1.0}` | Exit at 100% profit |
| `margin_mode` | `isolated` | One-way only, no hedging |

---

## 🧪 Testing

```bash
# Run unit tests
pytest tests/

# Backtest strategy
freqtrade backtesting --strategy Claw5MSniper --timerange 20260101-20260401

# Dry-run (simulated)
freqtrade trade --dry-run --strategy Claw5MSniper
```

---

## 📡 Telegram Commands (0-Type)

All interactions via inline buttons — no typing required.

| Button | Action |
|--------|--------|
| `/cmd` | Main menu |
| 📈 TRADE MENU | Select market session (NY/Tokyo/London) |
| 📊 POSITIONS | View open trades + manual close |
| 💸 PnL LEDGER | Live PnL (auto-refresh 3s) |
| 🚀 EXECUTE TRADE | Manual signal scan + entry |

---

## 🛡️ Security & Compliance

- **API keys** stored in `.env` (never committed)
- **IP whitelisting** supported on BingX
- **No private keys** or wallet connectivity
- **Read-only** market data access
- **User consent** required for all trades

---

## 📄 License

Proprietary — ClawForge empire codebase.

---

**Built with ❤️ by Open Claw  for @Rentardio .**  
*Protecting capital first, building the empire second.*
