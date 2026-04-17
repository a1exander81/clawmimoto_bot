#!/usr/bin/env python3
"""
Market Snapshot Broadcaster — Runs via cron every 4 hours
Sends MARKET NOW snapshot + breaking news + TA to @RightclawTrade
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import hashlib, hmac
import feedparser

# ── Load config ──
ENV_PATH = Path(__file__).parent.parent / "clawmimoto-bot" / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7093901111")
RIGHTCLAW_CHANNEL = os.getenv("RIGHTCLAW_CHANNEL", "@RightclawTrade")
STEPFUN_API_KEY = os.getenv("STEPFUN_API_KEY")
BINGX_API_KEY = os.getenv("BINGX_API_KEY")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Helpers ──
def bingx_signed_request(method, endpoint, params=None):
    if not BINGX_API_KEY or not BINGX_API_SECRET:
        return None
    base_url = "https://openapi.bingx.com"
    url = f"{base_url}{endpoint}"
    if params:
        sorted_params = sorted(params.items())
        query = '&'.join([f"{k}={v}" for k, v in sorted_params])
        signature = hmac.new(BINGX_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
        url += f"?{query}&signature={signature}"
    headers = {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}
    try:
        r = requests.request(method, url, headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.debug(f"BingX error: {e}")
        return None

def get_binance_ticker(symbol):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            d = r.json()
            return float(d.get("lastPrice", 0)), float(d.get("priceChangePercent", 0))
    except Exception as e:
        logger.debug(f"Binance error {symbol}: {e}")
    return None, None

def get_okx_ticker(symbol):
    try:
        r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={symbol}", timeout=5)
        if r.status_code == 200:
            d = r.json()
            if d.get("code") == "0" and d.get("data"):
                data = d["data"][0]
                return float(data.get("last", 0)), float(data.get("change24h", 0))
    except Exception as e:
        logger.debug(f"OKX error {symbol}: {e}")
    return None, None

def get_coingecko_ticker(cg_id):
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        if r.status_code == 200:
            d = r.json().get(cg_id, {})
            return d.get("usd", 0), d.get("usd_24h_change", 0)
    except Exception as e:
        logger.debug(f"CoinGecko error {cg_id}: {e}")
    return None, None

# ── Market Data ──
def fetch_market_data():
    pairs = [
        ("BTC", "BTCUSDT", "BTCUSDT", "BTC-USDT", "bitcoin"),
        ("ETH", "ETHUSDT", "ETHUSDT", "ETH-USDT", "ethereum"),
        ("SOL", "SOLUSDT", "SOLUSDT", "SOL-USDT", "solana"),
        ("BNB", "BNBUSDT", "BNBUSDT", "BNB-USDT", "binancecoin"),
    ]
    lines = []
    sources = []
    for label, bingx_sym, binance_sym, okx_sym, cg_id in pairs:
        price, change, source = None, None, None
        # BingX
        try:
            ticker = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": bingx_sym})
            if ticker and "data" in ticker:
                d = ticker["data"]
                price, change = float(d["lastPrice"]), float(d["priceChangePercent"])
                source = "BingX"
        except Exception:
            pass
        # Binance
        if price is None:
            price, change = get_binance_ticker(binance_sym)
            if price:
                source = "Binance"
        # OKX
        if price is None:
            price, change = get_okx_ticker(okx_sym)
            if price:
                source = "OKX"
        # CoinGecko
        if price is None:
            price, change = get_coingecko_ticker(cg_id)
            if price:
                source = "CoinGecko"
        # Format
        if price is not None:
            lines.append(f"{label}: ${price:,.2f} ({change:+.2f}%)")
            sources.append(source)
        else:
            lines.append(f"{label}: ERROR")
    return "\n".join(lines), ", ".join(set(sources)) if sources else "None"

# ── Market News (placeholder — replace with real RSS/API) ──
def get_market_news():
    """Fetch real crypto news from RSS feeds (no caching, no storage)."""
    feeds = [
        "https://cointelegraph.com/rss",
        "https://feeds.coindesk.com/coindesk/bitcoin",
        "https://decrypt.co/feed",
        "https://theblock.co/feed",
    ]
    articles = []
    for url in feeds:
        try:
            d = feedparser.parse(url)
            if d.entries:
                entry = d.entries[0]  # most recent from this feed
                title = entry.get('title', '').strip()
                link = entry.get('link', '').strip()
                # Strip UTM tracking params from URL
                if '?' in link and 'utm_' in link:
                    link = link.split('?')[0]
                if title and link:
                    articles.append((title, link))
        except Exception as e:
            logger.debug(f"RSS fetch error from {url}: {e}")
    # Deduplicate by title and limit to 4
    seen = set()
    uniq = []
    for title, link in articles:
        key = title.lower()
        if key not in seen:
            seen.add(key)
            uniq.append((title, link))
    uniq = uniq[:4]
    
    if not uniq:
        return (
            "📢 *Market Pulse — " + datetime.now(timezone.utc).strftime("%b %d, %Y") + "*\n\n"
            "• (News feeds temporarily unavailable — RSS error)\n"
        )
    
    lines = [f"• {title} [Source]({link})" for title, link in uniq]
    header = "📢 *Market Pulse — " + datetime.now(timezone.utc).strftime("%b %d, %Y") + "*"
    return f"{header}\n\n" + "\n".join(lines)

# ── TA: Support/Resistance (simple 24h hi/lo) ──
def generate_ta():
    """Get 24h high/low as support/resistance proxies."""
    lines = []
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
            if r.status_code == 200:
                d = r.json()
                high = float(d.get("highPrice", 0))
                low = float(d.get("lowPrice", 0))
                current = float(d.get("lastPrice", 0))
                lines.append(f"{symbol.replace('USDT','')}: S${low:,.0f} | R${high:,.0f}")
        except Exception:
            pass
    return "\n".join(lines) if lines else "TA unavailable"

# ── Telegram Sender ──
def send_telegram_message(text, parse_mode="Markdown"):
    if not TELEGRAM_BOT_TOKEN:
        logger.error("No TELEGRAM_BOT_TOKEN set")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Try channel first, fallback to DM
    targets = [RIGHTCLAW_CHANNEL, TELEGRAM_CHAT_ID]
    for chat_id in targets:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                logger.info(f"✅ Message sent to {chat_id}")
                return True
            else:
                logger.warning(f"Failed to send to {chat_id}: {r.status_code} {r.text[:100]}")
        except Exception as e:
            logger.debug(f"Send error to {chat_id}: {e}")
    logger.error("❌ Failed to send message to all targets")
    return False

# ── Main ──
def main():
    logger.info("📡 Generating Market Snapshot...")
    market_prices, sources_used = fetch_market_data()
    news = get_market_news()
    ta = generate_ta()

    utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = (
        f"🚨 *BREAKING MARKET SNAPSHOT*\n"
        f"📅 {utc_time}\n"
        f"📊 Powered by: {sources_used}\n\n"
        f"{news}\n\n"
        f"📈 *Live Prices*\n{market_prices}\n\n"
        f"📉 *Technical Levels*\n{ta}\n\n"
        f"_Data sources: Multi-exchange fallback chain (BingX → Binance → OKX → CoinGecko)_"
    )

    success = send_telegram_message(message)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
