from us_stock_signal.data_providers.universe import UniverseSymbol, _looks_like_common_stock, prioritize_symbols


def test_prioritize_symbols_places_liquid_starter_names_first_without_duplicates():
    symbols = [
        UniverseSymbol(symbol="ZZZ", name="ZZZ Corp", exchange="NASDAQ"),
        UniverseSymbol(symbol="AAPL", name="Apple Inc", exchange="NASDAQ"),
    ]

    prioritized = prioritize_symbols(symbols)

    assert prioritized[0].symbol == "AAPL"
    assert len([item for item in prioritized if item.symbol == "AAPL"]) == 1


def test_universe_filter_rejects_test_issues_notes_and_when_issued_symbols():
    blocked = [
        UniverseSymbol(symbol="ZVZZT", name="NASDAQ TEST STOCK", exchange="NASDAQ"),
        UniverseSymbol(symbol="FDX.V", name="FedEx Corporation Common Stock When-Issued", exchange="NYSE"),
        UniverseSymbol(symbol="ABC", name="Example 8.00% Senior Notes due 2031", exchange="NASDAQ"),
        UniverseSymbol(symbol="NTEST.A", name="NYSE Tick Pilot Test Sym-G1", exchange="NYSE"),
    ]

    assert [_looks_like_common_stock(item) for item in blocked] == [False, False, False, False]


def test_universe_filter_allows_regular_common_stock():
    assert _looks_like_common_stock(UniverseSymbol(symbol="AAPL", name="Apple Inc. Common Stock", exchange="NASDAQ"))
