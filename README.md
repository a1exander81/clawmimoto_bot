```

░█████╗░██╗░░░░░░█████╗░░██╗░░░░░░░██╗███╗░░░███╗██╗███╗░░░███╗░█████╗░████████╗░█████╗░
██╔══██╗██║░░░░░██╔══██╗░██║░░██╗░░██║████╗░████║██║████╗░████║██╔══██╗╚══██╔══╝██╔══██╗
██║░░╚═╝██║░░░░░███████║░╚██╗████╗██╔╝██╔████╔██║██║██╔████╔██║██║░░██║░░░██║░░░██║░░██║
██║░░██╗██║░░░░░██╔══██║░░████╔═████║░██║╚██╔╝██║██║██║╚██╔╝██║██║░░██║░░░██║░░░██║░░██║
╚█████╔╝███████╗██║░░██║░░╚██╔╝░╚██╔╝░██║░╚═╝░██║██║██║░╚═╝░██║╚█████╔╝░░░██║░░░╚█████╔╝
░╚════╝░╚══════╝╚═╝░░╚═╝░░░╚═╝░░░╚═╝░░╚═╝░░░░░╚═╝╚═╝╚═╝░░░░░╚═╝░╚════╝░░░░╚═╝░░░░╚════╝░
                           🦞 AI-Powered Crypto Scalping Engine 🦞
              
```

> **Institutional 5-minute crypto scalping bot on Bybit Perpetuals**  
> Built on the **OpenClaw Foundation** · Watched by **Clawtcher** · Managed via **Telegram**  
> *"Every trade decision must be defensible."*

---

## 📡 Architecture Overview

```
                              ┌─────────────────────────────────────┐
                              │         TELEGRAM USER              │
                              │  @Clawmimoto_bot (0-Type UI)       │
                              └──────────────┬──────────────────────┘
                                             │ Inline Keyboard Callbacks
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                           TELEGRAM UI LAYER                                    │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  unified_ui/main_menu.py    ·    unified_ui/handlers.py                  │   │
│  │  clawforge/telegram_ui.py   ·    clawforge/telegram_bot.py              │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│  Features: Main Menu · Session Select · Position View · PnL Cards · AI Scan    │
└────────────────────────────────────────────────────────────────────────────────┘
                                    │
                  ┌─────────────────┼────────────────────┐
                  ▼                 ▼                     ▼
┌─────────────────────────────┐  ┌─────────────────┐  ┌──────────────────────────┐
│     🔥 CLAW LAYER           │  │  🕸️ GRID LAYER  │  │     AI ENGINE            │
│     (Directional)           │  │  (Contrarian)   │  │                          │
│                             │  │                  │  │  ┌──────────────────┐   │
│  ┌───────────────────────┐  │  │  ┌────────────┐  │  │  │ DeepSeek Chat    │   │
│  │ Claw5MSniper Strategy │  │  │  │ Passivbot  │  │  │  │ (Sentiment)      │   │
│  │                       │  │  │  │ Process    │  │  │  └──────────────────┘   │
│  │ • RSI (10-30)         │  │  │  │ Manager    │  │  │                        │
│  │ • MACD (12/26/9)      │  │  │  └────────────┘  │  │  ┌──────────────────┐   │
│  │ • EMA Cross (10/30)   │  │  │                  │  │  │ Groq (Fallback)  │   │
│  │ • Session Filters     │  │  │  Weekend: Conserv │  │  │ llama-3.1-8b     │   │
│  │ • AI Sentiment Gate   │  │  │  Weekday: Aggress │  │  └──────────────────┘   │
│  └───────────────────────┘  │  └──────────────────┘  └──────────────────────────┘
└─────────────────────────────┘
                  │                          │                     │
                  └──────────────────────────┼─────────────────────┘
                                             ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                               LIQUIDITY GATE                                      │
│  ┌────────────────────────────────────────────────────────────────────────────┐   │
│  │  Real-time market checks: 24h Volume ≥ $5M  ·  Spread ≤ 0.15%             │   │
│  │  Weekend Volume Multiplier: 0.5x  ·  15-second TTL Cache                  │   │
│  └────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                               BYBIT EXCHANGE (v5 API)                            │
│  ┌────────────────────────────────────────────────────────────────────────────┐   │
│  │  Linear Perpetuals · ISOLATED Margin · 5–100x Leverage                    │   │
│  │  Endpoints: tickers · klines · orderbook · funding rate · wallet          │   │
│  └────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────┘
                                                                                     
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                DATA & INFRA                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  ┌────────────────────┐  │
│  │   Supabase   │  │   SQLite     │  │    Docker      │  │  GitHub Actions    │  │
│  │  (Cloud DB)  │  │ (Local Cache)│  │  Orchestration │  │  CI/CD Pipeline    │  │
│  └──────────────┘  └──────────────┘  └────────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧩 Two-Layer Trading System

### 🔥 CLAW LAYER — Directional Sniper
The primary strategy, **Claw5MSniper**, is a Freqtrade-based 5-minute scalping system:

| Parameter | Value | Description |
|-----------|-------|-------------|
| Timeframe | `5m` | 5-minute candles |
| Max Open Trades | `3` | Session cap |
| Stoploss | `-25%` (of position) | Hard floor |
| Trailing Stop | `+50%` → locks in gains | Ride the wave |
| RSI Period | `14` (10–30 range) | Oversold/overbought |
| MACD | `12/26/9` | Momentum confirmation |
| EMA Cross | `10/30` | Trend filter |
| Sessions | `Pre-London` · `London` · `NY` | Time-gated |
| AI Sentiment Gate | Optional (DeepSeek) | Extra confirmation |

### 🕸️ GRID LAYER — Contrarian Engine
Passivbot-powered grid trading with session-aware aggressiveness:

| Session | Spacing | TP Markup | Max Exposure | Label |
|---------|---------|-----------|-------------|-------|
| Pre-London | 0.8x | 0.08% | 10% | 🌅 Moderate |
| London | 1.2x | 0.15% | 20% | 🇪🇺 Aggressive |
| EU-US Overlap | 1.5x | 0.20% | 25% | 💥 Extreme |
| New York | 1.3x | 0.18% | 22% | 🇺🇸 Aggressive |
| Weekend | 0.6x | 0.06% | 8% | 🛡️ Conservative |

---

## ⏰ Trading Sessions

```
 UTC    0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23
        ├──┤──├──┤──├──┤──├──┤──├──┤──├──┤──├──┤──├──┤──├──┤──├──┤──├──┤──├──┤
NY      ████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░
TOKYO   ░░░░░░░░░░░░░░░░░░░████████████████████████████████░░░░░░░░░░░░░░░░░░░░
LONDON  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░████████████████████████████████████

SGT+8   8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23  0  1  2  3  4  5  6  7
```

### Risk-Weighted Sessions (SGT / UTC+8)
| Session | SGT Window | Volatility | Max Trades | Risk/Trade | Volume Req |
|---------|-----------|------------|------------|------------|------------|
| 🌅 Pre-London | 14:00–16:00 | Rising | 1 | 0.5% | 0.5x |
| 🇪🇺 London Open | 16:00–00:00 | Very High | 3 | 1.0% | 0.7x |
| 💥 EU-US Overlap | 21:00–00:00 | Extreme | 4 | 1.5% | 0.8x |
| 🇺🇸 New York | 21:00–06:00 | High | 4 | 1.0% | 0.8x |
| 🛡️ Weekend | All day | Low | 1 | 0.5% | 0.4x |

### Day-of-Week Volatility Profiles
| Day | Tendency | Avg Return | Volatility |
|-----|----------|------------|------------|
| Monday | 📈 Trending | +1.55% | High |
| Tuesday | 🌪️ Volatile | +0.80% | High |
| Wednesday | ➡️ Normal | +0.50% | Moderate |
| Thursday | ➡️ Normal | +0.40% | Moderate |
| Friday | 📈 Trending | +0.90% | High |
| Saturday | 🔄 Mean-Reversion | +0.30% | Low |
| Sunday | 🔄 Mean-Reversion | +0.25% | Low |

---

## 🏗️ Project Map

```
clawmimoto_bot/
├── clawforge/                          # Core trading engine
│   ├── bot.py                          # Entry point — wraps Freqtrade
│   ├── strategy.py                     # Claw5MSniper — RSI/MACD/EMA + AI gate
│   ├── telegram_ui.py                  # 4492-line Telegram UI (menus, positions, scan)
│   ├── telegram_bot.py                 # Telegram bot instance
│   ├── liquidity_gate.py               # Real-time volume/spread checks
│   ├── mock_engine.py                  # CLUSDT virtual balance (Supabase-backed)
│   ├── subscription.py                 # Web3 Solana Pay gating
│   └── integrations/
│       ├── deepseek.py                 # AI sentiment via DeepSeek Chat API
│       ├── meme.py                     # PnL meme card generator (Pillow)
│       └── stepfun.py                  # StepFun scoring adapter
├── config/
│   ├── config.yaml                     # Central config (risk, AI, sessions)
│   └── sessions.py                     # Session definitions + DOW profiles
├── configs/
│   └── config.json                     # Freqtrade runtime config
├── grid_layer/                         # Passivbot grid trading
│   ├── __init__.py
│   ├── db_reader.py                    # Grid trade DB reader
│   └── process_manager.py             # Launch/stop/monitor grid instances
├── strategies/
│   ├── claw5m_hybrid.py               # Hybrid strategy variant
│   └── claw5m_sniper.py               # Standalone sniper strategy
├── unified_ui/                         # Consolidated handler routing
│   ├── __init__.py
│   ├── handlers.py                     # Claw & Grid session handlers
│   └── main_menu.py                    # Inline keyboard layout
├── scripts/                            # Operational tooling
│   ├── boot_recovery.sh               # Startup recovery
│   ├── channel_cleanup.py             # Telegram channel maintenance
│   ├── clawstrike_scan.py             # Auto-scanner (cron)
│   ├── market_snapshot.py             # 4-hour market broadcast
│   ├── sentinel_agent.py              # AI monitoring agent
│   ├── ta_cron.py                     # Technical analysis cron
│   ├── supabase_sync.py              # DB sync
│   └── ... (more)
├── web/                                # Web dashboard
│   └── Dockerfile
├── tests/
│   └── test_strategy.py               # Strategy unit tests
├── .github/workflows/
│   ├── ci.yml                         # Test · Lint · Type-check · Security
│   ├── deploy.yml                      # Build · Push · Deploy to VPS
│   └── coderabbit.yml                  # AI PR review
├── Dockerfile                          # Multi-stage build
├── docker-compose.yml                  # freqtrade + telegram-ui services
├── docker-compose.local.yml            # Local dev variant
├── pyproject.toml                      # Project metadata
├── requirements.txt                    # Python deps
└── .env.example                        # Environment template
```

---

## ⚙️ Quick Start

### Prerequisites
- Docker & Docker Compose
- Bybit API Key (perpetuals trading)
- Telegram Bot Token (from @BotFather)
- DeepSeek API Key (optional, for AI scoring)
- Supabase Project (optional, for cloud stats)

### 1. Configure
```bash
cp .env.example .env
# Fill in your keys:
#   BYBIT_API_KEY / BYBIT_API_SECRET
#   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
#   GROQ_API_KEY / DEEPSEEK_API_KEY (optional)
#   SUPABASE_URL / SUPABASE_ANON_KEY (optional)
```

### 2. Launch
```bash
docker-compose up -d --build
```

### 3. Verify
```bash
docker-compose logs -f freqtrade    # Trading engine
docker-compose logs -f telegram-ui  # Telegram interface
```

### 4. Trade
Open Telegram → `@Clawmimoto_bot` → Press buttons.

---

## 🔒 Security Model

| Guard | Implementation |
|-------|---------------|
| **Isolated Margin** | No cross/hedge — each position isolated |
| **Max Trades** | 3 auto/day (configurable via sessions) |
| **Hard Stoploss** | -25% max loss per position |
| **Trailing Stop** | Activates at +50%, locks gains |
| **Liquidity Gate** | Blocks trading if volume < $5M or spread > 0.15% |
| **0-Type UI** | No free-text input — all actions via inline buttons |
| **Access Control** | Admin · Whitelisted · Public tiers |
| **Channel Gating** | Optional channel membership requirement |
| **MOCK Mode** | Default — switch to REAL explicitly |
| **Weekend Mode** | Reduced risk, mean-reversion only |

---

## 🧠 AI Integration

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  User asks  │────>│  Telegram UI    │────>│  DeepSeek/Groq   │
│  for scan   │     │  /scan command  │     │  API Call        │
└─────────────┘     └─────────────────┘     └──────────────────┘
                                                    │
                                                    ▼
┌─────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  Top 4      │<────│  Ranked by      │<────│  Analyze Top 20  │
│  Setups     │     │  Win Probability│     │  Bybit Movers    │
└─────────────┘     └─────────────────┘     └──────────────────┘
```

The AI engine:
- 🎯 **DeepSeek Chat** — Primary: sentiment analysis & trade advice (JSON output)
- 🔄 **Groq (llama-3.1-8b)** — Fallback: scoring & signal generation
- 📊 **StepFun** — Legacy adapter (AI TA signals)

Sentiment scores gate strategy buy signals when `use_sentiment=True`:
- Bearish → `0.0–0.5` (block buy)
- Neutral → `0.5` (pass-through)
- Bullish → `0.5–1.0` (allow buy)

---

## 💎 Mock Engine (CLUSDT)

The virtual paper-trading system uses **CLUSDT** — a simulated stablecoin backed by Supabase:

- **Initial Balance**: 10,000 CLUSDT per user
- **Fee Rate**: 0.1% per trade
- **Engine**: `MockEngine` in `clawforge/mock_engine.py`
- **Storage**: Supabase tables — `mock_accounts`, `mock_positions`, `mock_trades`
- **Order Types**: Limit orders that fill at market price if conditions met

---

## 🔄 CI/CD Pipeline

```
PR → [CodeRabbit AI Review] → [Ruff Lint] → [Mypy Type Check]
     → [Pytest + Coverage] → [Safety Scan] → [Bandit Security]
     → [Docker Build] → [Human Review] → Merge

Main Push → [Docker Build + Push] → [SSH Deploy to VPS]
          → [docker-compose pull + up -d]
```

---

## 📊 Key Metrics

| Metric | Target |
|--------|--------|
| Win Rate | ≥ 60% |
| Risk/Reward | ≥ 2.0 |
| Max Drawdown | ≤ 15% |
| Trades/Day | 3–4 |
| Sharpe Ratio | ≥ 1.5 |
| Avg Hold Time | 15–45 min |

---

## 🤝 Contributing

See `CONTRIBUTING.md` and `CLAUDE.md` for code review guidelines.

**Critical rules:**
- No API keys/secrets in code
- No hardcoded amounts
- No auto-trading without explicit permission
- All PRs need CodeRabbit + 1 human approval
- Strategy changes must include backtest results

---

## 🛟 Support & Resources

| Resource | Link |
|----------|------|
| Dashboard | `clawmimoto-backtests.vercel.app` |
| Telegram | `@Clawmimoto_bot` |
| Channel | `@RightclawTrade` |
| Setup Guide | `SETUP_GUIDE.md` |
| Launch Checklist | `LAUNCH_CHECKLIST.md` |
| Deliverables | `DELIVERABLES.md` |
| Docker Deploy | `DEPLOY_DOCKER.md` |

---

## 🧪 SUTAMM — Shut Up And Take My Money

Auto-executes session trades when enabled. **Defaulted OFF** — manual approval required for every trade.

---

## 🦞 The ClawForge Stack

```
┌───────────────────────────────────────┐
│         🔝  CLAWFORGE                 │
│    AI-Powered Trading Engine          │
├───────────────────────────────────────┤
│  ┌──────────┐  ┌──────────────────┐   │
│  │ Freqtrade│  │  Telegram UI     │   │
│  │ Strategy │  │  @Clawmimoto_bot │   │
│  │ Engine   │  │  0-Type Menus    │   │
│  └──────────┘  └──────────────────┘   │
├───────────────────────────────────────┤
│  ┌──────────┐  ┌──────────────────┐   │
│  │ Clawtcher│  │  Supabase        │   │
│  │ Watchdog │  │  Cloud Database  │   │
│  └──────────┘  └──────────────────┘   │
├───────────────────────────────────────┤
│  ┌──────────┐  ┌──────────────────┐   │
│  │ OpenClaw │  │  Dashboard       │   │
│  │ AI Dev   │  │  Vercel App      │   │
│  └──────────┘  └──────────────────┘   │
└───────────────────────────────────────┘
```

---

```
  ╔═══════════════════════════════════════════════════════════════════╗
  ║                                                                   ║
  ║   Built with 🦞 by the RIGHTCLAW                           ║
  ║   Powered by OpenClaw Foundation                                  ║
  ║   © 2026 ClawForge — Proprietary. All rights reserved.      ║
  ║                                                                   ║
  ║   "We're building an institutional tool.                         ║
  ║    Every trade decision must be defensible."                      ║
  ║                                                                   ║
  ╚═══════════════════════════════════════════════════════════════════╝
```
