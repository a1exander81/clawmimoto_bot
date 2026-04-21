"""StepFun API integration for market sentiment analysis."""
import os
import requests
from typing import Optional

STEPFUN_API_KEY = os.getenv("STEPFUN_API_KEY", "")
STEPFUN_URL = "https://api.stepfun.ai/v1/chat/completions"

def get_sentiment_score(pair: str, context: str = "") -> float:
    """Query StepFun for market sentiment. Returns score 0.0-1.0."""
    if not STEPFUN_API_KEY:
        return 0.5
    try:
        headers = {
            "Authorization": f"Bearer {STEPFUN_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "step-3.5-flash",
            "messages": [
                {"role": "system", "content": "You are a crypto market sentiment analyzer. Reply with only a number between 0.0 (very bearish) and 1.0 (very bullish)."},
                {"role": "user", "content": f"Sentiment for {pair}? {context}"}
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        r = requests.post(STEPFUN_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return max(0.0, min(1.0, float(text)))
    except Exception as e:
        print(f"StepFun error: {e}")
        return 0.5
