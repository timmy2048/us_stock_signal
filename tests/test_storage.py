from pathlib import Path

import us_stock_signal.storage as storage
from us_stock_signal.storage import load_latest_scan_session, save_latest_recommendations


def test_save_duckdb_recommendations_is_best_effort(monkeypatch):
    class BrokenDuckDB:
        @staticmethod
        def connect(path):
            raise OSError("database wal is locked")

    monkeypatch.setitem(__import__("sys").modules, "duckdb", BrokenDuckDB)

    storage._save_duckdb_recommendations([], Path("ignored.duckdb"))


def test_save_latest_recommendations_persists_scan_session_for_empty_results(tmp_path):
    save_latest_recommendations([], tmp_path, session="afterhours")

    assert load_latest_scan_session(tmp_path) == "afterhours"
