#!/usr/bin/env python3
"""
4-Hour Technical Analysis Cron Job
Fetches Binance 4H klines for BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT
Generates support/resistance levels and sends formatted updates to Telegram.

NEWS: Aggregates from CryptoPanic API, CoinTelegraph RSS, Decrypt RSS.
"""

import os
import sys
import json
import logging
import re
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# ── Logging Setup ──
LOG_DIR = Path("/data/.openclaw/workspace/clawmimoto-bot/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "ta_cron.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ── Load Config ──
ENV_PATH = Path(__file__).parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7093901111")
RIGHTCLAW_CHANNEL = os.getenv("RIGHTCLAW_CHANNEL", "@RightclawTrade")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not set in .env — aborting")
    sys.exit(1)

# Binance public endpoint (no key needed)
BINANCE_BASE = "https://api.binance.com/api/v3"
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVAL = "4h"
LIMIT = 50

# Relevant crypto tickers for news filtering
RELEVANT_TICKERS = {"btc", "eth", "sol", "bnb", "bitcoin", "ethereum", "solana", "binance"}

# ── News Fetchers ──
def fetch_cryptopanic_news() -> list[dict]:
    """Fetch top important posts from CryptoPanic (free tier)."""
    try:
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": "free",
            "kind": "news",
            "currencies": "BTC,ETH,SOL,BNB",
            "filter": "important",
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = []
            for item in data.get("results", [])[:10]:
                title = item.get("title", "")
                title_lower = title.lower()
                if not any(t in title_lower for t in RELEVANT_TICKERS):
                    continue
                source = item.get("source", {}).get("title", "CryptoPanic")
                published = item.get("published_at", "")
                url = item.get("url", "")
                results.append({"title": title, "source": source, "published": published, "url": url})
            return results
    except Exception as e:
        logger.debug(f"CryptoPanic fetch error: {e}")
    return []


def parse_rss_feed(url: str, source_name: str) -> list[dict]:
    """Generic RSS parser. Returns list of {title, source, published, url}."""
    try:
        feed = feedparser.parse(url)
        entries = []
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            title_lower = title.lower()
            if not any(t in title_lower for t in RELEVANT_TICKERS):
                continue
            source = source_name
            published = entry.get("published", "")
            link = entry.get("link", "")
            entries.append({"title": title, "source": source, "published": published, "url": link})
        return entries
    except Exception as e:
        logger.debug(f"RSS fetch error {source_name}: {e}")
    return []


def fetch_news() -> list[dict]:
    """Aggregate news from all sources, sort by recency, return top 3."""
    all_items: list[dict] = []
    all_items.extend(fetch_cryptopanic_news())
    all_items.extend(parse_rss_feed("https://cointelegraph.com/rss", "CoinTelegraph"))
    all_items.extend(parse_rss_feed("https://decrypt.co/feed", "Decrypt"))
    # Deduplicate by title (simple)
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"][:100].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    # Sort by published
    def parse_time(item):
        try:
            return datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc) - timedelta(days=1)
    unique.sort(key=parse_time, reverse=True)
    return unique[:3]


def format_time_ago(published_str: str) -> str:
    """Convert published timestamp to '2h ago', '30m ago', etc."""
    try:
        dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        minutes = int(diff.total_seconds() / 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        # Fallback: assume ~1 hour ago
        return "1h ago"


# ── Binance Kline Fetchers ──
def fetch_klines(symbol: str) -> list | None:
    """Fetch OHLCV klines from Binance. Returns list of [open, high, low, close, ...]"""
    url = f"{BINANCE_BASE}/klines"
    params = {"symbol": symbol, "interval": INTERVAL, "limit": LIMIT}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [[float(c[1]), float(c[2]), float(c[3]), float(c[4])] for c in data]
    except Exception as e:
        logger.warning(f"Binance fetch failed for {symbol}: {e}")
        return None


def calculate_sr(klines: list) -> tuple[float, float, float]:
    """Return (current_close, resistance, support) based on last 10 candles."""
    recent = klines[-10:]
    closes = [k[3] for k in klines]
    current_price = closes[-1]
    resistance = max(k[1] for k in recent)
    support = min(k[2] for k in recent)
    return current_price, resistance, support


def generate_narrative(symbol: str, klines: list, current: float, res: float, sup: float) -> str:
    """Create 2-3 sentence TA narrative."""
    avg_close = sum(k[3] for k in klines[-10:]) / 10
    if current > avg_close * 1.005:
        trend = "trending up"
    elif current < avg_close * 0.995:
        trend = "trending down"
    else:
        trend = "ranging"
    distance_res = (res - current) / current * 100
    distance_sup = (current - sup) / current * 100
    narrative = (
        f"{symbol.replace('USDT', '/USDT')} is {trend} on the 4H timeframe. "
        f"Price ${current:,.2f} is {distance_res:.1f}% below resistance (${res:,.2f}) "
        f"and {distance_sup:.1f}% above support (${sup:,.2f})."
    )
    return narrative


def format_ta_message(symbol: str, klines: list, current: float, res: float, sup: float) -> str:
    """Format TA block for a single symbol."""
    narrative = generate_narrative(symbol, klines, current, res, sup)
    return (
        f"🔵 {symbol.replace('USDT', '/USDT')}\n"
        f"{narrative}\n"
        f"💰 Price: ${current:,.2f}\n"
        f"🔴 Resistance: ${res:,.2f}\n"
        f"🟢 Support: ${sup:,.2f}\n"
    )


def send_telegram_message(token: str, chat_id: str, text: str, log_type: str = "ta_update") -> int | None:
    """Send formatted message via Telegram Bot API. Returns message_id or None."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        result = r.json()
        msg_id = result.get("result", {}).get("message_id")
        if msg_id:
            log_path = Path(__file__).parent.parent / "user_data" / "channel_message_log.json"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            delete_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
            entry = {
                "message_id": msg_id,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "chat_id": chat_id,
                "type": log_type,
                "delete_at": delete_at,
            }
            logs = []
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8") as lf:
                        logs = json.load(lf)
                except Exception:
                    logs = []
            logs.append(entry)
            with open(log_path, "w", encoding="utf-8") as lf:
                json.dump(logs, lf, indent=2, ensure_ascii=False)
            logger.info(f"Logged {log_type} message ID {msg_id} (delete_at={delete_at})")
        return msg_id
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return None


def calculate_next_session_countdown() -> str:
    """Return formatted countdown to next trading session."""
    now_utc = datetime.now(timezone.utc)
    sessions = [
        ("Pre-London", 21, 45),
        ("London", 7, 45),
        ("NY", 12, 45),
    ]
    next_deltas = []
    for name, hour, minute in sessions:
        candidate = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_utc:
            candidate += timedelta(days=1)
        delta = candidate - now_utc
        next_deltas.append((name, delta))
    name, delta = min(next_deltas, key=lambda x: x[1])
    total_minutes = int(delta.total_seconds() // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"⏰ Next: {name} in {hours}h {minutes}min"


def main():
    logger.info("Starting 4H TA update run")
    now_utc = datetime.now(timezone.utc)
    time_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    # ── Build message ──
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 4H TA UPDATE — {time_str}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # TA for each pair
    for symbol in PAIRS:
        klines = fetch_klines(symbol)
        if not klines or len(klines) < 10:
            logger.warning(f"Skipping {symbol}: insufficient data")
            lines.append(f"❌ {symbol.replace('USDT', '/USDT')} — data unavailable")
            continue
        current, resistance, support = calculate_sr(klines)
        lines.append(format_ta_message(symbol, klines, current, resistance, support))

    # News section
    lines.append("📰 NEWS")
    news_items = fetch_news()
    if news_items:
        for item in news_items:
            time_ago = format_time_ago(item["published"])
            url = item.get("url", "")
            if url:
                # Title plain, source as clickable link on separate line
                lines.append(f"• {item['title']}")
                lines.append(f" 🔗 [{item['source']}]({url}) · {time_ago}")
            else:
                lines.append(f"• {item['title']} — {item['source']} ({time_ago})")
    else:
        lines.append("• No major crypto news in the last 4 hours.")

    # Countdown
    lines.append("")
    lines.append(calculate_next_session_countdown())

    # Footer
    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "⚡ ClawForge Market Intelligence",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ])

    message = "\n".join(lines)
    logger.info(f"Sending TA update to admin chat {TELEGRAM_CHAT_ID} and channel {RIGHTCLAW_CHANNEL}")

    # Send to admin chat
    admin_msg_id = send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message, log_type="ta_update")
    logger.info(f"Admin chat message_id={admin_msg_id}")

    # Forward to channel
    channel_msg_id = send_telegram_message(TELEGRAM_BOT_TOKEN, RIGHTCLAW_CHANNEL, message, log_type="ta_update")
    logger.info(f"Channel message_id={channel_msg_id}")

    # Send top headline as separate message for link preview card
    if news_items:
        top = news_items[0]
        url = top.get("url", "")
        if url:
            headline_text = f"📰 {top['title']}\n🔗 [{top['source']}]({url})"
            send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, headline_text, log_type="headline_preview")
            send_telegram_message(TELEGRAM_BOT_TOKEN, RIGHTCLAW_CHANNEL, headline_text, log_type="headline_preview")
            logger.info(f"Sent headline preview for: {top['title'][:60]}...")

    return True


if __name__ == "__main__":
    main()
