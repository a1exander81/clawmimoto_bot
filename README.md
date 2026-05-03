# 🦞 Clawmimoto Bot

> **ClawForge Trading Platform** — AI-powered crypto scalping bot on Bybit Perpetuals  
> Built on OpenClaw Foundation · Watched by Clawtcher · Managed via Telegram


## 🏗️ Architecture

CLAWFORGE STACK:
- Freqtrade     → Strategy engine (Claw5MHybrid)
- Telegram UI   → @Clawmimoto_bot (user interface)
- Clawtcher     → Omnipresent watchdog / chairman of sub-agents
- Supabase      → Trade database (cloud backup)
- OpenClaw      → AI dev assistant (@Clawtardio_bot)
- Dashboard     → clawmimoto-backtests.vercel.app

## AI Scan
- Fetches top 20 movers by volume from Bybit
- Sends to your preferred AI for analysis
- Returns top 4 ranked by highest win probability

## Strategy: Claw5MHybrid
- Max Open Trades: 3 (session) / Unlimited (manual)
- Stoploss: -2% | Trailing Stop: enabled
- Sessions: Pre-London, London, NY
- 30-minute approval window

## SUTAMM (Shut Up and Take My Money)
- Auto-executes session trades when enabled
- Defaulted OFF — manual approval required

## Beta
- First 200 beta testers receive CLUSDT airdrops

---
Built with 🦞 by the RightClaw team · Powered by OpenClaw Foundation
