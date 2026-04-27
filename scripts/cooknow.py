import os, json, time, logging, ssl, urllib.request
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cooknow")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SSL_CTX = ssl.create_default_context()

RECIPE_ARCHETYPES = [
    {"name":"Bull Ignition","emoji":"🔥","conditions":["FOMC dovish surprise","ETF inflows > $500M","BTC breaks resistance","Fear/Greed rising","Whale accumulation"],"base_probability":0.25,"expected_move":"+8% to +15%","timeframe":"24-72h","pairs":["BTC","ETH","SOL"],"direction":"LONG","risk":"MEDIUM"},
    {"name":"Slow Grind Up","emoji":"📈","conditions":["FOMC holds as expected","ETF inflows $200-400M","BTC consolidating","Funding neutral","Low volatility"],"base_probability":0.30,"expected_move":"+2% to +5%","timeframe":"48-96h","pairs":["BTC","ETH"],"direction":"LONG","risk":"LOW"},
    {"name":"Liquidity Hunt","emoji":"🎯","conditions":["High funding (longs heavy)","Low volume consolidation","Options max pain below","Whale sell walls","CME gap below"],"base_probability":0.20,"expected_move":"-3% to -8% then reversal","timeframe":"12-24h","pairs":["BTC","ETH","SOL"],"direction":"SHORT then LONG","risk":"HIGH"},
    {"name":"Macro Shock","emoji":"⚡","conditions":["FOMC hawkish surprise","CPI higher than expected","ETF outflows > $200M","Risk-off all markets","Stablecoin dominance rising"],"base_probability":0.10,"expected_move":"-10% to -20%","timeframe":"24-48h","pairs":["ALL"],"direction":"SHORT or AVOID","risk":"VERY HIGH"},
    {"name":"Alt Season Rotation","emoji":"🌀","conditions":["BTC dominance < 55%","ETH/BTC rising","BTC stable alts pumping","Social volume spike","High alt funding"],"base_probability":0.15,"expected_move":"BTC flat, alts +15% to +40%","timeframe":"72-168h","pairs":["ETH","SOL","BNB"],"direction":"LONG ALTS","risk":"MEDIUM-HIGH"},
]

def fetch_current_conditions():
    c = {}
    try:
        req = urllib.request.Request("https://api.alternative.me/fng/?limit=1", headers={"User-Agent":"CookNow/1.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=8) as r:
            d = json.loads(r.read())
        c["fear_greed"] = int(d["data"][0]["value"])
        c["fear_greed_label"] = d["data"][0]["value_classification"]
    except: c["fear_greed"] = 50; c["fear_greed_label"] = "Neutral"
    try:
        req = urllib.request.Request("https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=8) as r:
            d = json.loads(r.read())
        t = d["result"]["list"][0]
        c["btc_price"] = float(t["lastPrice"])
        c["btc_change_24h"] = float(t.get("price24hPcnt",0))*100
        c["btc_funding"] = float(t.get("fundingRate",0))
    except: c["btc_price"] = 77000; c["btc_change_24h"] = 0; c["btc_funding"] = 0
    try:
        req = urllib.request.Request("https://api.coingecko.com/api/v3/global", headers={"User-Agent":"CookNow/1.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as r:
            d = json.loads(r.read())
        dom = d.get("data",{}).get("market_cap_percentage",{})
        c["btc_dominance"] = round(dom.get("btc",55),2)
        c["mcap_change"] = round(d.get("data",{}).get("market_cap_change_percentage_24h_usd",0),2)
    except: c["btc_dominance"] = 55; c["mcap_change"] = 0
    c["upcoming_events"] = [
        {"name":"FOMC Rate Decision","days":2,"impact":"HIGH"},
        {"name":"BTC Nashville Conference","days":2,"impact":"HIGH"},
        {"name":"NFP / May Day","days":3,"impact":"HIGH"},
        {"name":"CME Options Expiry","days":4,"impact":"MEDIUM"},
    ]
    return c

def calculate_recipe_probability(recipe, conditions):
    score = recipe["base_probability"]
    match_factors = []
    mismatch_factors = []
    fg = conditions.get("fear_greed", 50)
    btc_change = conditions.get("btc_change_24h", 0)
    btc_funding = conditions.get("btc_funding", 0)
    btc_dom = conditions.get("btc_dominance", 55)
    mcap_change = conditions.get("mcap_change", 0)
    name = recipe["name"]
    if name == "Bull Ignition":
        if fg > 60: score += 0.08; match_factors.append("F&G bullish")
        if btc_change > 2: score += 0.06; match_factors.append("BTC momentum")
        if btc_funding < 0: score += 0.04; match_factors.append("Shorts paying longs")
        if any(e["impact"]=="HIGH" and e["days"]<=2 for e in conditions.get("upcoming_events",[])): score += 0.05; match_factors.append("High-impact event soon")
        if fg < 40: score -= 0.08; mismatch_factors.append("Fear dominant")
    elif name == "Slow Grind Up":
        if 40<=fg<=65: score += 0.08; match_factors.append("Neutral sentiment")
        if -1<=btc_change<=3: score += 0.06; match_factors.append("Low volatility")
        if abs(btc_funding)<0.0002: score += 0.05; match_factors.append("Balanced funding")
        if btc_dom>57: score += 0.03; match_factors.append("BTC season")
    elif name == "Liquidity Hunt":
        if btc_funding>0.0005: score += 0.10; match_factors.append("Longs overleveraged")
        if fg>70: score += 0.07; match_factors.append("Extreme greed")
        if -1<=btc_change<=1: score += 0.05; match_factors.append("Consolidation")
        if btc_funding<0: score -= 0.05; mismatch_factors.append("Shorts heavy")
    elif name == "Macro Shock":
        if fg<30: score += 0.10; match_factors.append("Fear dominant")
        if btc_change<-3: score += 0.08; match_factors.append("Selling pressure")
        if mcap_change<-2: score += 0.06; match_factors.append("Market cap falling")
        if fg>50: score -= 0.05; mismatch_factors.append("Market not fearful")
    elif name == "Alt Season Rotation":
        if btc_dom<55: score += 0.10; match_factors.append("BTC dom falling")
        if fg>55: score += 0.05; match_factors.append("Risk appetite")
        if btc_dom>60: score -= 0.08; mismatch_factors.append("BTC dominant")
    score = max(0.02, min(0.95, score))
    return {**recipe, "probability": round(score,3), "probability_pct": round(score*100,1), "match_factors": match_factors, "mismatch_factors": mismatch_factors, "confidence": "HIGH" if score>0.40 else "MEDIUM" if score>0.20 else "LOW"}

def generate_ai_recipes(conditions, ranked):
    try:
        top3 = ranked[:3]
        recipes_text = "\n".join([f"{r['emoji']} {r['name']}: {r['probability_pct']}% — {r['expected_move']} ({r['timeframe']})" for r in top3])
        prompt = f"""You are COOKNOW, elite macro scenario simulator for crypto trading.
CURRENT: BTC ${conditions.get('btc_price',0):,.0f} ({conditions.get('btc_change_24h',0):+.1f}%), Dom {conditions.get('btc_dominance',0)}%, F&G {conditions.get('fear_greed',50)}/100, Funding {conditions.get('btc_funding',0):.4f}
CATALYSTS: FOMC in 2d (HIGH), BTC Conference in 2d (HIGH), NFP in 3d (HIGH)
TOP SCENARIOS:\n{recipes_text}
Give 4-sentence brief: 1) Most likely scenario & why 2) Key catalyst to watch 3) Entry strategy 4) Invalidation signal. Be quantitative like Goldman Sachs."""
        payload = json.dumps({"model":"llama-3.1-8b-instant","messages":[{"role":"user","content":prompt}],"temperature":0.4,"max_tokens":400}).encode()
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=payload, headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as r:
            d = json.loads(r.read())
        return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Top scenario: {ranked[0]['name']} at {ranked[0]['probability_pct']}% probability. Watch FOMC + BTC Conference this week."

def cook_now():
    logger.info("COOKNOW: Firing up the kitchen...")
    start = time.time()
    conditions = fetch_current_conditions()
    scored = [calculate_recipe_probability(r, conditions) for r in RECIPE_ARCHETYPES]
    total = sum(r["probability"] for r in scored)
    for r in scored:
        r["probability"] = round(r["probability"]/total, 3)
        r["probability_pct"] = round(r["probability"]*100, 1)
    ranked = sorted(scored, key=lambda x: x["probability"], reverse=True)
    ai_brief = generate_ai_recipes(conditions, ranked)
    top = ranked[0]
    long_prob = sum(r["probability"] for r in ranked if "LONG" in r["direction"])
    overall = "BULLISH" if long_prob > 0.5 else "BEARISH" if sum(r["probability"] for r in ranked if "SHORT" in r["direction"] and "LONG" not in r["direction"]) > 0.3 else "NEUTRAL"
    client_outlook = {"overall_bias": overall, "emoji": "🟢" if overall=="BULLISH" else "🔴" if overall=="BEARISH" else "🟡", "confidence": top["confidence"], "top_scenario": top["name"], "expected_move": top["expected_move"], "timeframe": top["timeframe"], "focus_pairs": top["pairs"], "risk_level": top["risk"], "key_message": f"Market leaning {overall.lower()} — {top['expected_move']} in {top['timeframe']}", "watch_for": [e["name"] for e in conditions.get("upcoming_events",[])[:2]]}
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "elapsed_sec": round(time.time()-start,1), "conditions": conditions, "recipes": ranked, "top_recipe": top, "ai_brief": ai_brief, "client_outlook": client_outlook}

def format_admin_report(result):
    recipes = result["recipes"]
    c = result["conditions"]
    recipe_lines = []
    for i, r in enumerate(recipes, 1):
        bar = "█" * int(r["probability_pct"]/5) + "░" * (20-int(r["probability_pct"]/5))
        match_str = " · ".join(r["match_factors"][:2]) if r["match_factors"] else "No matches"
        recipe_lines.append(f"{r['emoji']} *{i}. {r['name']}* — `{r['probability_pct']}%`\n   `{bar}`\n   Move: `{r['expected_move']}` | `{r['timeframe']}`\n   Dir: `{r['direction']}` | Risk: `{r['risk']}`\n   ✅ {match_str}")
    events = c.get("upcoming_events",[])
    event_lines = "\n".join([f"  {'🔴' if e['impact']=='HIGH' else '🟡'} {e['name']} (in {e['days']}d)" for e in events[:3]])
    return (f"👨‍🍳 *COOKNOW — Macro Scenario Simulator*\n━━━━━━━━━━━━━━━━━━━━\n\n*CONDITIONS*\n  BTC: `${c.get('btc_price',0):,.0f}` ({c.get('btc_change_24h',0):+.1f}%)\n  Dom: `{c.get('btc_dominance',0)}%` | F&G: `{c.get('fear_greed',50)}/100`\n  Funding: `{c.get('btc_funding',0):+.4f}`\n\n*MACRO CALENDAR*\n{event_lines}\n\n━━━━━━━━━━━━━━━━━━━━\n*RECIPES RANKED*\n\n" + "\n\n".join(recipe_lines) + f"\n\n━━━━━━━━━━━━━━━━━━━━\n*AI ANALYSIS*\n_{result['ai_brief']}_\n\n⚙️ _CookNow | {result['elapsed_sec']}s | Admin Only_")

def format_client_outlook(result):
    o = result["client_outlook"]
    watch = " · ".join(o["watch_for"]) if o["watch_for"] else "Standard sessions"
    pairs = " · ".join(o["focus_pairs"][:3]) if o["focus_pairs"] != ["ALL"] else "BTC · ETH · SOL"
    return (f"🌍 *MARKET OUTLOOK*\n━━━━━━━━━━━━━━━━━━━━\n\n{o['emoji']} *{o['overall_bias']}* — {o['confidence']} Confidence\n\n*Expected Move:* `{o['expected_move']}`\n*Timeframe:* `{o['timeframe']}`\n*Focus Pairs:* `{pairs}`\n*Risk Level:* `{o['risk_level']}`\n\n*Scenario:* {o['top_scenario']}\n_{o['key_message']}_\n\n*Watch This Week:*\n  {watch}\n\n━━━━━━━━━━━━━━━━━━━━\n_Powered by Clawtcher Sentinel_")

def send_telegram(chat_id, text):
    try:
        payload = json.dumps({"chat_id":chat_id,"text":text,"parse_mode":"Markdown","disable_web_page_preview":True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data=payload, headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        logger.error(f"Telegram failed: {e}"); return False

import sys
if __name__ == "__main__":
    chat_id = int(sys.argv[1]) if len(sys.argv)>1 else 7093901111
    mode = sys.argv[2] if len(sys.argv)>2 else "admin"
    print("CookNow firing up...")
    result = cook_now()
    text = format_admin_report(result) if mode=="admin" else format_client_outlook(result)
    print(text)
    send_telegram(chat_id, text)
    print(f"Done in {result['elapsed_sec']}s")