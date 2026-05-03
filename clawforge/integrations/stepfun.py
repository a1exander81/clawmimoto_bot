# clawforge/integrations/stepfun.py
"""AI market analysis – powered by DeepSeek (OpenAI‑compatible)."""
import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE)

def analyze_sentiment(pair: str) -> dict:
    """
    Return sentiment analysis for a given trading pair.
    Expected return: { "bias": "bullish"|"bearish"|"neutral", "confidence": 0.0-1.0, "summary": "..." }
    """
    if not DEEPSEEK_KEY:
        logger.warning("No DeepSeek API key – returning neutral sentiment.")
        return {"bias": "neutral", "confidence": 0.5, "summary": "AI disabled (no API key)"}

    try:
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            messages=[
                {"role": "system", "content": "You are a crypto market analyst. Respond in JSON only."},
                {"role": "user", "content": (
                    f"Analyze the current market sentiment for {pair}. "
                    "Consider price action, recent news, and volatility. "
                    "Return JSON with keys: bias (bullish/bearish/neutral), confidence (0-1), summary (short text)."
                )}
            ],
            temperature=0.3
        )
        content = response.choices[0].message.content
        result = json.loads(content)
        return result
    except Exception as e:
        logger.error(f"DeepSeek sentiment analysis failed: {e}")
        return {"bias": "neutral", "confidence": 0.5, "summary": f"AI error: {str(e)}"}

def get_trade_advice(pair: str, strategy: str = "claw") -> dict:
    """
    Get AI-generated trade parameters for a specific strategy.
    Returns a dict with risk_pct and timeframe.
    """
    sentiment = analyze_sentiment(pair)
    if sentiment["bias"] == "bearish":
        return {"risk_pct": 0.3, "timeframe": "short"}
    elif sentiment["bias"] == "bullish":
        return {"risk_pct": 0.8, "timeframe": "long"}
    else:
        return {"risk_pct": 0.5, "timeframe": "medium"}
