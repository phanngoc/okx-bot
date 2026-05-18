"""Fetch crypto news from RSS feeds + CryptoCompare API and compute sentiment."""

import json
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BULLISH_WORDS = {
    "surge", "soar", "rally", "bull", "bullish", "breakout", "moon", "pump",
    "gain", "jump", "spike", "rise", "climb", "recover", "rebound", "high",
    "record", "milestone", "adoption", "approval", "etf", "institutional",
    "upgrade", "partnership", "launch", "growth", "positive", "optimistic",
    "buy", "accumulate", "inflow", "support", "strong", "momentum",
    "breakthrough", "innovation", "demand", "profit", "outperform",
}

BEARISH_WORDS = {
    "crash", "dump", "plunge", "bear", "bearish", "breakdown", "sell",
    "drop", "fall", "decline", "tank", "collapse", "fear", "panic",
    "hack", "scam", "fraud", "ban", "regulation", "restrict", "fine",
    "lawsuit", "sec", "warning", "risk", "bubble", "overvalued",
    "liquidation", "outflow", "resistance", "weak", "correction",
    "recession", "inflation", "crisis", "concern", "uncertain", "loss",
}

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://www.theblock.co/rss.xml",
    "https://bitcoinmagazine.com/feed",
    "https://cryptoslate.com/feed/",
    "https://news.bitcoin.com/feed/",
]


def _fetch_url(url: str, timeout: int = 8) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "*/*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def fetch_rss(symbol: str = "BTC") -> list[dict]:
    """Fetch headlines from multiple crypto RSS feeds."""
    coin_names = {
        "BTC": ["bitcoin", "btc"],
        "ETH": ["ethereum", "eth", "ether"],
        "SOL": ["solana", "sol"],
        "XRP": ["xrp", "ripple"],
        "BNB": ["bnb", "binance"],
    }
    keywords = coin_names.get(symbol.upper(), [symbol.lower()])

    headlines = []
    for feed_url in RSS_FEEDS:
        try:
            data = _fetch_url(feed_url, timeout=8)
            if not data:
                continue
            root = ET.fromstring(data)

            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item")
            if not items:
                items = root.findall(".//atom:entry", ns)

            for item in items[:30]:
                title = ""
                desc = ""
                pub_date = ""
                source = feed_url.split("/")[2]

                title_el = item.find("title")
                if title_el is None:
                    title_el = item.find("atom:title", ns)
                if title_el is not None and title_el.text:
                    title = title_el.text.strip()

                desc_el = item.find("description")
                if desc_el is None:
                    desc_el = item.find("atom:summary", ns)
                if desc_el is not None and desc_el.text:
                    desc = re.sub(r'<[^>]+>', '', desc_el.text)[:200].strip()

                date_el = item.find("pubDate")
                if date_el is None:
                    date_el = item.find("atom:updated", ns)
                if date_el is not None and date_el.text:
                    pub_date = date_el.text.strip()

                text_lower = (title + " " + desc).lower()
                is_relevant = any(kw in text_lower for kw in keywords)
                is_general_crypto = any(w in text_lower for w in ["crypto", "market", "trading", "defi"])

                if is_relevant or is_general_crypto:
                    headlines.append({
                        "title": title,
                        "body": desc,
                        "source": source,
                        "time": pub_date,
                    })
        except (ET.ParseError, Exception):
            continue

    return headlines


def fetch_api(symbol: str = "BTC") -> list[dict]:
    """Fetch from CryptoCompare API as backup."""
    coin_name = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    }.get(symbol.upper(), symbol.lower())

    headlines = []
    url = f"https://min-api.cryptocompare.com/data/v2/news/?categories={coin_name}&limit=20"
    try:
        data = _fetch_url(url)
        if data:
            parsed = json.loads(data)
            for item in parsed.get("Data", [])[:20]:
                headlines.append({
                    "title": item.get("title", ""),
                    "body": item.get("body", "")[:200],
                    "source": item.get("source", ""),
                    "time": datetime.fromtimestamp(
                        item.get("published_on", 0), tz=timezone.utc
                    ).isoformat(),
                })
    except Exception:
        pass
    return headlines


def score_text(text: str) -> tuple[int, int]:
    words = set(re.findall(r'[a-z]+', text.lower()))
    bull_count = len(words & BULLISH_WORDS)
    bear_count = len(words & BEARISH_WORDS)
    return bull_count, bear_count


def analyze_sentiment(symbol: str = "BTC") -> dict:
    """Fetch news from RSS + API and return sentiment analysis."""
    rss_headlines = fetch_rss(symbol)
    api_headlines = fetch_api(symbol)

    seen_titles = set()
    headlines = []
    for h in rss_headlines + api_headlines:
        title_key = h["title"][:50].lower()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            headlines.append(h)

    if not headlines:
        return {
            "score": 0,
            "label": "NEUTRAL (no data)",
            "bull_signals": 0,
            "bear_signals": 0,
            "headline_count": 0,
            "top_headlines": [],
            "details": [],
            "sources": [],
        }

    total_bull = 0
    total_bear = 0
    details = []
    sources = set()

    for h in headlines:
        text = f"{h['title']} {h['body']}"
        bull, bear = score_text(text)
        total_bull += bull
        total_bear += bear
        net = bull - bear
        sources.add(h["source"])
        details.append({
            "title": h["title"][:80],
            "source": h["source"],
            "bull": bull,
            "bear": bear,
            "net": net,
        })

    total = total_bull + total_bear
    if total == 0:
        score = 0
    else:
        score = round((total_bull - total_bear) / total * 100)

    if score > 30:
        label = "BULLISH"
    elif score > 10:
        label = "SLIGHTLY BULLISH"
    elif score < -30:
        label = "BEARISH"
    elif score < -10:
        label = "SLIGHTLY BEARISH"
    else:
        label = "NEUTRAL"

    details.sort(key=lambda x: abs(x["net"]), reverse=True)

    return {
        "score": score,
        "label": label,
        "bull_signals": total_bull,
        "bear_signals": total_bear,
        "headline_count": len(headlines),
        "top_headlines": [d["title"] for d in details[:5]],
        "details": details[:10],
        "sources": sorted(sources),
    }
