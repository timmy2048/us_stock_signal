from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_USER_AGENT = "us-stock-signal/0.1 research-tool"


@dataclass(slots=True)
class FundamentalSnapshot:
    symbol: str
    cik: str
    revenue_growth: float | None = None
    net_income: float | None = None
    risk_flags: list[str] | None = None


def load_cik_map(timeout_seconds: int = 20) -> dict[str, str]:
    response = requests.get(SEC_TICKERS_URL, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    result = {}
    for item in data.values():
        ticker = str(item.get("ticker", "")).upper()
        cik = str(item.get("cik_str", "")).zfill(10)
        if ticker and cik:
            result[ticker] = cik
    return result


def fetch_company_facts(symbol: str, cik: str, timeout_seconds: int = 20) -> FundamentalSnapshot:
    try:
        response = requests.get(
            SEC_COMPANY_FACTS_URL.format(cik=cik),
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        facts = response.json().get("facts", {}).get("us-gaap", {})
        revenue = _latest_value(facts.get("Revenues") or facts.get("RevenueFromContractWithCustomerExcludingAssessedTax"))
        net_income = _latest_value(facts.get("NetIncomeLoss"))
        return FundamentalSnapshot(symbol=symbol, cik=cik, net_income=net_income, risk_flags=[])
    except Exception:
        return FundamentalSnapshot(symbol=symbol, cik=cik, risk_flags=["SEC 基本面不可用"])


def _latest_value(fact: dict[str, Any] | None) -> float | None:
    if not fact:
        return None
    units = fact.get("units", {})
    values = []
    for unit_values in units.values():
        if isinstance(unit_values, list):
            values.extend(unit_values)
    values = [item for item in values if item.get("val") is not None and item.get("end")]
    if not values:
        return None
    values.sort(key=lambda item: item.get("end", ""))
    return float(values[-1]["val"])

