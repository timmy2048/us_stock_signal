from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import requests


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
FALLBACK_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOGL",
    "COIN",
    "PLTR",
    "SMCI",
    "MARA",
    "RIOT",
    "SOFI",
    "HOOD",
]
LIQUID_STARTER_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMD",
    "META",
    "AMZN",
    "GOOGL",
    "AVGO",
    "NFLX",
    "COIN",
    "PLTR",
    "SMCI",
    "MARA",
    "RIOT",
    "SOFI",
    "HOOD",
    "RBLX",
    "SHOP",
    "CRWD",
]


@dataclass(slots=True)
class UniverseSymbol:
    symbol: str
    name: str
    exchange: str
    is_etf: bool = False


def load_us_stock_universe(timeout_seconds: int = 20) -> list[UniverseSymbol]:
    symbols: list[UniverseSymbol] = []
    try:
        symbols.extend(_load_nasdaq_listed(timeout_seconds))
        symbols.extend(_load_other_listed(timeout_seconds))
    except Exception:
        return prioritize_symbols([UniverseSymbol(symbol=s, name=s, exchange="FALLBACK") for s in FALLBACK_SYMBOLS])
    seen: set[str] = set()
    filtered: list[UniverseSymbol] = []
    for item in symbols:
        if item.symbol in seen or not _looks_like_common_stock(item):
            continue
        seen.add(item.symbol)
        filtered.append(item)
    if not filtered:
        filtered = [UniverseSymbol(symbol=s, name=s, exchange="FALLBACK") for s in FALLBACK_SYMBOLS]
    return prioritize_symbols(filtered)


def prioritize_symbols(symbols: list[UniverseSymbol]) -> list[UniverseSymbol]:
    by_symbol = {item.symbol.upper(): item for item in symbols}
    ordered: list[UniverseSymbol] = []
    seen: set[str] = set()
    for symbol in LIQUID_STARTER_SYMBOLS:
        if symbol in by_symbol:
            ordered.append(by_symbol[symbol])
        else:
            ordered.append(UniverseSymbol(symbol=symbol, name=symbol, exchange="PRIORITY"))
        seen.add(symbol)
    for item in symbols:
        normalized = item.symbol.upper()
        if normalized not in seen:
            ordered.append(item)
            seen.add(normalized)
    return ordered


def _load_nasdaq_listed(timeout_seconds: int) -> list[UniverseSymbol]:
    response = requests.get(NASDAQ_LISTED_URL, timeout=timeout_seconds)
    response.raise_for_status()
    rows = _parse_pipe_file(response.text)
    result = []
    for row in rows:
        symbol = row.get("Symbol", "").strip()
        if not symbol or symbol == "File Creation Time":
            continue
        result.append(
            UniverseSymbol(
                symbol=symbol,
                name=row.get("Security Name", symbol),
                exchange="NASDAQ",
                is_etf=row.get("ETF", "N").upper() == "Y",
            )
        )
    return result


def _load_other_listed(timeout_seconds: int) -> list[UniverseSymbol]:
    response = requests.get(OTHER_LISTED_URL, timeout=timeout_seconds)
    response.raise_for_status()
    rows = _parse_pipe_file(response.text)
    result = []
    for row in rows:
        symbol = row.get("ACT Symbol", "").strip()
        if not symbol or symbol == "File Creation Time":
            continue
        result.append(
            UniverseSymbol(
                symbol=symbol,
                name=row.get("Security Name", symbol),
                exchange=row.get("Exchange", "OTHER"),
                is_etf=row.get("ETF", "N").upper() == "Y",
            )
        )
    return result


def _parse_pipe_file(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if "|" in line and not line.startswith("File Creation Time")]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|"))


def _looks_like_common_stock(item: UniverseSymbol) -> bool:
    if item.is_etf:
        return False
    symbol = item.symbol.upper()
    name = item.name.upper()
    if any(mark in symbol for mark in ["$", "^", "/"]):
        return False
    blocked_terms = [
        "ETF",
        "ETN",
        "FUND",
        "WARRANT",
        "RIGHT",
        "UNIT",
        "PREFERRED",
        "PFD",
        "NOTE DUE",
        "NOTES DUE",
        "SENIOR NOTES",
        "DEBENTURE",
        "WHEN-ISSUED",
        "TEST",
        "TICK PILOT",
        "LISTING MARKET",
    ]
    return not any(term in name for term in blocked_terms)
