"""StepFun API integration for market sentiment analysis."""

import os
from typing import Optional
from stepfun import StepFunClient
from dotenv import load_dotenv

load_dotenv()

_client: Optional[StepFunClient] = None

def get_client() -> StepFunClient:
    global _client
    if _client is None:
        api_key = os.getenv("STEPFUN_API_KEY")
        if not api_key:
            raise ValueError("STEPFUN_API_KEY not set")
        _client = StepFunClient(api_key=api_key)
    return _client

def get_sentiment_score(symbol: str, timeframe: str = "5m") -> float:
    """
    Query StepFun 3.5 Flash for market sentiment.
    Returns: 0.0 (bearish) to 1.0 (bullish)
    """
    prompt = f"""
    Analyze current market sentiment for {symbol} on {timeframe} timeframe.
    Consider: recent price action, news flow, social buzz, on-chain flows.
    Respond with JSON: {{"sentiment": float(0-1), "confidence": float(0-1), "reason": "brief"}}
    """
    try:
        client = get_client()
        resp = client.chat.completions.create(
            model="stepfun-3.5-flash",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        data = resp.choices[0].message.content
        import json
        parsed = json.loads(data)
        return parsed.get("sentiment", 0.5)
    except Exception as e:
        print(f"StepFun error: {e}")
        return 0.5  # neutral on error
