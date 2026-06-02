import pandas as pd

from us_stock_signal.data_providers import yahoo_chart
from us_stock_signal.data_providers.yahoo_chart import (
    fetch_yahoo_chart_daily_bars,
    frame_from_yahoo_chart_payload,
    yahoo_chart_symbol,
)


def test_yahoo_chart_symbol_converts_share_class_separator():
    assert yahoo_chart_symbol("brk.b") == "BRK-B"
    assert yahoo_chart_symbol("AAPL") == "AAPL"


def test_frame_from_yahoo_chart_payload_parses_daily_bars():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1767225600, 1767312000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0, 10.5],
                                "high": [11.0, 11.5],
                                "low": [9.5, 10.0],
                                "close": [10.5, 11.0],
                                "volume": [1000, 2000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }

    frame = frame_from_yahoo_chart_payload(payload)

    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert frame["Close"].tolist() == [10.5, 11.0]
    assert frame["Volume"].tolist() == [1000, 2000]
    assert isinstance(frame.index, pd.DatetimeIndex)


def test_frame_from_yahoo_chart_payload_skips_rows_without_close():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1767225600, 1767312000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0, 10.5],
                                "high": [11.0, 11.5],
                                "low": [9.5, 10.0],
                                "close": [None, 11.0],
                                "volume": [1000, None],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }

    frame = frame_from_yahoo_chart_payload(payload)

    assert len(frame) == 1
    assert frame.iloc[0]["Close"] == 11.0
    assert frame.iloc[0]["Volume"] == 0


def test_frame_from_yahoo_chart_payload_returns_empty_on_chart_error():
    payload = {"chart": {"result": None, "error": {"code": "Not Found"}}}

    assert frame_from_yahoo_chart_payload(payload).empty


def test_fetch_yahoo_chart_daily_bars_fetches_symbols_concurrently(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1767225600],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [10.0],
                                        "high": [11.0],
                                        "low": [9.5],
                                        "close": [10.5],
                                        "volume": [1000],
                                    }
                                ]
                            },
                        }
                    ],
                    "error": None,
                }
            }

    def fake_get(url, params, headers, timeout):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(yahoo_chart.requests, "get", fake_get)

    frames = fetch_yahoo_chart_daily_bars(["AAPL", "MSFT"], period="1mo", max_workers=2)

    assert set(frames) == {"AAPL", "MSFT"}
    assert len(calls) == 2
