from pathlib import Path

from us_stock_signal.config import load_settings


def test_load_settings_reads_yaml_and_env_without_requiring_secrets(tmp_path: Path):
    config_path = tmp_path / "default.yaml"
    config_path.write_text(
        """
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: data
  database_path: data/test.duckdb
scoring:
  top_n: 10
""",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path, env_file=None)

    assert settings.app.timezone == "Asia/Shanghai"
    assert settings.scoring["top_n"] == 10
    assert settings.deepseek_api_key == ""


def test_default_config_uses_aggressive_150_60_signal_profile():
    settings = load_settings("configs/default.yaml", env_file=None)

    high_yield = settings.scoring["high_yield"]

    assert settings.scoring["trigger_mode"] == "high_yield_breakout"
    assert high_yield["profile_name"] == "aggressive_150_60"
    assert high_yield["top_n"] == 2
    assert high_yield["min_momentum_20_pct"] == 150
    assert high_yield["min_momentum_5_pct"] == 60
    assert high_yield["max_gap_pct"] == 80
    assert high_yield["max_price"] == 100
    assert settings.schedule["daily_sync_batch_delay_seconds"] == 1.0
