# clawmimoto_bot

A self-hosted crypto futures trading system built on Freqtrade, running on Bybit with a Telegram-native interface. Designed around session-based automation, AI-assisted signal filtering, and strict capital protection logic.

## Overview

This project started as a personal trading automation tool and evolved into a structured system with three core components: a strategy engine, a signal scanner, and a Telegram UI layer. The goal was to remove emotional decision-making from the trading loop without giving up control entirely.

The bot runs three sessions per day — Pre-London, London, and NY — each with pre-calculated entry levels, adaptive stop losses, and session-specific take profit targets. Outside of sessions, a manual scan mode lets you drop any exchange link or pair directly into Telegram and get an AI-ranked setup back within 30 seconds.

## Architecture

Two containers run in production:
- `clawforge-freqtrade` — Freqtrade engine, REST API on 127.0.0.1:8080
- `clawforge-telegram` — Telegram UI, manages session state

Key directories:
- strategies/     — Freqtrade strategy (Claw5MHybrid)
- clawforge/      — Telegram UI and StepFun integration
- scripts/        — Cron jobs (sessions, TA, cleanup, auto-rebuild)
- configs/        — Freqtrade config

## Strategy

Claw5MHybrid is a multi-timeframe strategy using 5M entries filtered by 1H and 4H trend confirmation.

Entry filters:
- ADX threshold (session-aware, 22-40)
- EMA8/20/50 alignment across timeframes
- Volume ratio greater than 1.3x 20-period average
- ATR filter to skip low-volatility setups
- Weekend position size reduction

Leverage: Dynamic 5x-100x based on AI confidence and trend strength. Base 50x.

Stop loss: Adaptive — reads last 10 closed trades, adjusts margin stop based on win/loss ratio. Session multipliers apply on top. Tightens after consecutive losses.

Take profit: Tiered ROI (20% to 15% to 10% to 5% to 2%) with session-aware custom exits. Capital recovery at 10% profit moves SL to breakeven.

## Sessions

Three automated sessions run via cron. Each fires a prescan 15 minutes before open, sends a setup to Telegram with Approve/Skip buttons, and auto-skips if no response within 10 minutes.

| Session    | UTC Time | Pairs              | Min RRR |
|------------|----------|--------------------|---------|
| Pre-London | 21:45    | BTC, ETH, SOL      | 2.5     |
| London     | 07:45    | BTC, ETH, SOL, BNB | 3.0     |
| NY         | 12:45    | BTC, ETH           | 2.5     |

## Scan Mode

/scan fetches top movers from Bybit linear futures, filters for minimum $50M 24H volume, price above $0.10, and 4H moves between 2-15%. Candidates get scored by StepFun in parallel and ranked by AI score. Results come back with Execute/Skip buttons.

Supported link inputs:
- Bybit, Binance, BingX trade URLs
- TradingView chart links
- Twitter/X posts (StepFun extracts pair from context)

## Cron Jobs

- Every 5min: watchdog, session autoskip, auto-rebuild
- 0,4,8,12,16,18 UTC: 4H market snapshots
- 21:45 UTC: Pre-London prescan
- 07:45 UTC: London prescan
- 12:45 UTC: NY prescan
- 00:00 UTC: Channel cleanup
- 20:00 UTC: Daily maintenance

## Setup

Requirements: Docker, Docker Compose, Bybit account with futures API, Telegram bot token, StepFun API key.

```bash
cp .env.example .env
# Fill in credentials
docker compose up -d --build
curl -u admin:admin http://127.0.0.1:8080/api/v1/ping
```

## Environment Variables

| Variable             | Description                        |
|----------------------|------------------------------------|
| BYBIT_API_KEY        | Bybit API key (trade + read)       |
| BYBIT_API_SECRET     | Bybit API secret                   |
| TELEGRAM_BOT_TOKEN   | Bot token from BotFather           |
| TELEGRAM_CHAT_ID     | Your Telegram user ID              |
| RIGHTCLAW_CHANNEL    | Signal channel (e.g. @channel)     |
| STEPFUN_API_KEY      | StepFun API key (step-3.5-flash)   |
| FREQTRADE_API_USER   | Freqtrade REST API username        |
| FREQTRADE_API_PASS   | Freqtrade REST API password        |

## Safety

- Dry run enabled by default. Set dry_run false in configs/config.json to go live.
- Circuit breaker stops trading at +150% daily PnL or -30% loss.
- Max 7 trades per day (3 session + 4 manual).
- Micro-cap guard blocks pairs priced below $0.10.
- Session mode restricts execution to whitelisted pairs only.
- Auto-skip prevents stale session caches from executing late.

## License

Private. Not for redistribution.
