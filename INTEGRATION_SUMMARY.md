# 🏗️ Claw_Rise_bot — Integration & Architecture Summary

**Rebranded from:** @Clawmimoto_bot → **@Claw_Rise_bot**  
**Inspired by:** Freqtrade (https://github.com/freqtrade/freqtrade)  
**Stack:** Python 3.11+, SQLite, Docker, FastAPI, python‑telegram‑bot, DeepSeek Chat API

---

## 📐 High-Level Architecture

```
┌────────────────────┐
│   Telegram User    │◄──┐  Inline buttons only (0‑Type)
└─────────▲──────────┘   │
          │ commands       │ callbacks
          │                │
┌─────────▼──────────┐   │
│ Telegram Bot Layer │   │
│ (clawforge/        │   │
│  telegram_ui.py)   │   │
└─────────▲──────────┘   │
          │ calls         │
          │               │
┌─────────▼──────────────▼─────────────┐
│   Freqtrade Engine (docker)           │
│   ─ Scheduler: 3 trades/day          │
│   ─ Manual trigger via UI            │
│   ─ AI → Risk → Exchange pipeline    │
└─────────▲──────────────▲─────────────┘
          │              │
   fetch  │              │  execute
          │              │
┌─────────▼──────┐ ┌────▼─────────────┐
│ AI Engine      │ │ Grid Layer       │
│ (DeepSeek      │ │ (passivbot       │
│  sentiment)    │ │  integration)    │
│ • analyze_sent │ │ • grid trading   │
│ • get_sentiment│ │ • process mgmt   │
│ • get_trade_adv│ └──────────────────┘
└─────────▲──────┘
          │
          │
┌─────────▼────────────┐
│ Bybit API (v5)       │
│ • tickers, klines    │
│ • order book         │
│ • funding rate       │
│ • wallet balance     │
└──────────────────────┘
```

---

## 📦 Modules & File Map

| Module | Path | Purpose |
|--------|------|---------|
| **Config** | `config/config.yaml` | Exchange keys, risk params, session times, AI thresholds |
| **Telegram UI** | `clawforge/telegram_ui.py` | Inline keyboard menus, live PnL ticker, scan, positions |
| **AI Engine** | `clawforge/integrations/deepseek.py` | DeepSeek sentiment analysis + trade advice |
| **Strategy** | `clawforge/strategy.py` | Claw5MSniper — 5M strategy with AI sentiment gate |
| **Grid Layer** | `grid_layer/` | Passivbot grid-trading process manager |
| **Scripts** | `scripts/` | Maintenance, market snapshot, sentinel agent, TA cron |
| **Unified UI** | `unified_ui/` | Consolidated handler routing |
| **Web** | `web/` | Standalone web UI (Docker) |

---

## 🔌 External Integrations

| Service | Purpose | Credentials (`.env`) |
|---------|---------|----------------------|
| **Bybit** | Exchange API (perpetuals) | `BYBIT_API_KEY`, `BYBIT_API_SECRET` |
| **DeepSeek** | AI sentiment analysis | `DEEPSEEK_API_KEY` |
| **Telegram** | Bot control UI | `TELEGRAM_BOT_TOKEN` |
| **Supabase** | Trade history & stats | `SUPABASE_URL`, `SUPABASE_ANON_KEY` |
| **Groq** | Fallback AI scoring | `GROQ_API_KEY` |

---

## ⚙️ Configuration (`config/config.yaml`)

```yaml
exchange:
  bingx:
    api_key: ${BINGX_API_KEY}
    api_secret: ${BINGX_API_SECRET}
    test_mode: ${BINGX_TEST_MODE:false}
    margin_mode: isolated
    default_leverage: 50

risk:
  margin_percent: 1.5
  max_trades_per_day: 3
  sl_tolerance_min_pct: 10
  sl_tolerance_max_pct: 20
  default_rrr: 2.0
  max_leverage: 100
  leverage_warning_threshold_low: 50
  leverage_warning_threshold_high: 100

trading:
  timeframe: 5m
  session_times_sgt:
    NY_MORNING: "21:30"
    TOKYO_MORNING: "08:00"
    TOKYO_AFTERNOON: "11:30"
    LONDON_OPEN: "16:00"
  auto_enabled: true
  manual_anytime: true

ai:
  model: deepseek-chat
  confidence_threshold: 65
  min_rrr: 1.5
  deepseek_timeout: 15

database:
  url: sqlite:///data/claw_rise.db

logging:
  level: INFO
  dir: logs
  rotation: 10MB x 5

webui:
  host: 0.0.0.0
  port: 8000

health:
  host: 0.0.0.0
  port: 8080
  supervisor_restart_attempts: 3
  supervisor_alert_retry_delay: 300
```

---

## 🐳 Docker Quick Start

```bash
# 1. Clone / navigate
cd /docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot

# 2. Configure
cp .env.example .env
# edit .env with your keys

# 3. Build & run
docker-compose up -d --build

# 4. Verify
docker-compose logs -f bot

# 5. Open Telegram → @Claw_Rise_bot → press buttons
```

---

## 🔒 Security & Safety

- **Isolated margin only** — no cross/hedge
- **Max 3 auto trades/day** — enforced in scheduler
- **Hard SL** — 10–20% max loss per trade
- **Trailing SL** — activates at +50%, rides to +100%
- **0‑Type Telegram** — no free‑text input; all actions via buttons
- **Admin lock** — only your Telegram ID sees ADMIN panel
- **MOCK mode default** — switch to REAL only when ready

---

## 📈 Expected Behavior

| Component | Expected |
|-----------|----------|
| **AI Scan** | At `/scan` or via menu — analyzes top 20 Bybit pairs, returns top 4 setups |
| **Manual trade** | Anytime via Telegram → confirm → execute |
| **Sentiment gate** | `strategy.py` can optionally gate buy signals via DeepSeek sentiment score |
| **Position refresh** | Detail view auto-refreshes every 6 seconds |
| **Market snapshot** | Auto-posted to @RightclawTrade every 4 hours |
| **Dashboard** | Open `clawmimoto-backtests.vercel.app` for full history |

---

## 📞 Support

Problems? Check:
- `LAUNCH_CHECKLIST.md` — step‑by‑step verification
- `DELIVERABLES.md` — what's done vs remaining
- Logs: `logs/bot.log`, `logs/freqtrade.log`

**Ready to rise.** Let's print.
