# clawforge/integrations/deepseek.py
"""AI market analysis – powered by DeepSeek Chat API (OpenAI-compatible).

Provides sentiment analysis and trade advice using DeepSeek Chat API.
All risk-level values should be overridden via config.yaml (ai.risk_pct_*).
Uses plain HTTP requests (no openai SDK dependency).
"""

import json
import logging
import os
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ── Defaults (override via config.yaml) ──
DEFAULT_TIMEOUT: float = 15.0
DEFAULT_RETRIES: int = 3
DEFAULT_BACKOFF: float = 1.0

# Risk percentages (config-driven in production — see config.yaml ai section)
RISK_PCT_BULLISH: float = 0.8
RISK_PCT_BEARISH: float = 0.3
RISK_PCT_NEUTRAL: float = 0.5

# ── Typed return schemas ──

SentimentResult = dict[str, Any]
"""Expected keys: bias (str), confidence (float 0-1), summary (str)."""

TradeAdvice = dict[str, Any]
"""Expected keys: risk_pct (float), timeframe (str)."""

# ── Internal helpers ──


def _get_env_config() -> tuple[str, str, float]:
    """Return (api_key, base_url, timeout) from environment."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    try:
        timeout = float(os.getenv("DEEPSEEK_TIMEOUT", str(DEFAULT_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return api_key, base_url, timeout


def _call_deepseek(
    messages: list[dict[str, str]],
    model: str = "deepseek-v4-pro",
    retries: int = DEFAULT_RETRIES,
) -> Optional[str]:
    """Call DeepSeek Chat via REST API with exponential-backoff retry.

    Returns the response content string, or None on repeated failure.
    """
    api_key, base_url, timeout = _get_env_config()
    if not api_key:
        logger.error("DEEPSEEK_API_KEY not set")
        return None

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=timeout
            )
            if response.status_code != 200:
                logger.warning(
                    "DeepSeek HTTP %d (attempt %d/%d): %s",
                    response.status_code, attempt, retries,
                    response.text[:200],
                )
                if attempt < retries:
                    time.sleep(DEFAULT_BACKOFF * (2 ** (attempt - 1)))
                    continue
                return None

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                return content.strip()
            logger.warning(f"DeepSeek returned empty content (attempt {attempt})")
        except requests.exceptions.Timeout:
            logger.warning(
                "DeepSeek timeout (attempt %d/%d)", attempt, retries
            )
        except Exception as exc:
            logger.warning(
                "DeepSeek API attempt %d/%d failed: %s",
                attempt, retries, exc,
            )
        if attempt < retries:
            time.sleep(DEFAULT_BACKOFF * (2 ** (attempt - 1)))
    return None


# ── Response validation ──


def _validate_sentiment(raw: dict[str, Any]) -> SentimentResult:
    """Coerce and sanitise a raw sentiment dict into a safe result."""
    bias = str(raw.get("bias", "neutral")).lower().strip()
    if bias not in ("bullish", "bearish", "neutral"):
        bias = "neutral"

    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    summary = str(raw.get("summary", ""))[:300]
    return SentimentResult(
        bias=bias,
        confidence=confidence,
        summary=summary or "No summary provided.",
    )


# ── Public API ──


def analyze_sentiment(pair: str) -> SentimentResult:
    """Return sentiment analysis for a given trading pair.

    Result keys:
        bias       – "bullish" | "bearish" | "neutral"
        confidence – float 0.0–1.0
        summary    – short text summary
    """
    if not os.getenv("DEEPSEEK_API_KEY"):
        logger.warning("No DeepSeek API key – returning neutral sentiment.")
        return SentimentResult(
            bias="neutral",
            confidence=0.5,
            summary="AI disabled (no API key)",
        )

    system_prompt = (
        "You are a crypto market analyst. Respond in JSON only. "
        "Do not include markdown fences or extra commentary."
    )
    user_prompt = (
        f"Analyze the current market sentiment for {pair}. "
        "Consider price action, recent news, and volatility. "
        "Return JSON with keys: bias (bullish/bearish/neutral), "
        "confidence (0-1), summary (short text)."
    )

    try:
        content = _call_deepseek([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        if not content:
            return SentimentResult(
                bias="neutral",
                confidence=0.5,
                summary="AI returned no response after retries",
            )

        # Strip potential markdown fences
        cleaned = content.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline:]
            cleaned = cleaned.replace("```", "").strip()

        result = json.loads(cleaned)
        return _validate_sentiment(result)

    except json.JSONDecodeError:
        logger.error("DeepSeek returned invalid JSON: %s", content)
        return SentimentResult(
            bias="neutral",
            confidence=0.5,
            summary="AI response parse error",
        )
    except Exception as exc:
        logger.error("DeepSeek sentiment analysis failed: %s", exc)
        return SentimentResult(
            bias="neutral",
            confidence=0.5,
            summary=f"AI error: {exc}",
        )


def get_sentiment_score(pair: str) -> float:
    """Return a numeric sentiment score in [0.0, 1.0].

    0.0 = max bearish, 0.5 = neutral, 1.0 = max bullish.
    Used by strategy.py to gate buy signals.
    """
    result = analyze_sentiment(pair)
    bias = result.get("bias", "neutral")
    confidence = result.get("confidence", 0.5)

    if bias == "bullish":
        return 0.5 + confidence * 0.5   # → [0.5, 1.0]
    elif bias == "bearish":
        return 0.5 - confidence * 0.5   # → [0.0, 0.5]
    return 0.5


def get_trade_advice(pair: str, strategy: str = "claw") -> TradeAdvice:
    """Get AI-generated trade parameters for a strategy.

    Returns dict with:
        risk_pct  – suggested risk allocation (0.0–1.0)
        timeframe – "short" | "medium" | "long"

    Risk values can be overridden via config.yaml > ai.risk_pct_* .
    """
    sentiment = analyze_sentiment(pair)
    bias = sentiment.get("bias", "neutral")

    if bias == "bearish":
        return TradeAdvice(risk_pct=RISK_PCT_BEARISH, timeframe="short")
    elif bias == "bullish":
        return TradeAdvice(risk_pct=RISK_PCT_BULLISH, timeframe="long")
    return TradeAdvice(risk_pct=RISK_PCT_NEUTRAL, timeframe="medium")
