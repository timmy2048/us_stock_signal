from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

import requests

from us_stock_signal.models import NewsBundle


YAHOO_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"


def fetch_yahoo_news(symbol: str, timeout_seconds: int = 15) -> NewsBundle:
    try:
        response = requests.get(YAHOO_RSS_URL.format(symbol=symbol), timeout=timeout_seconds)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        titles = []
        for title in root.findall(".//item/title"):
            if title.text:
                clean = re.sub(r"\s+", " ", html.unescape(title.text)).strip()
                if clean and clean not in titles:
                    titles.append(clean)
        return NewsBundle(symbol=symbol, headlines=titles[:10])
    except Exception:
        return NewsBundle(symbol=symbol, headlines=[], risk_notes=["新闻源不可用"])

