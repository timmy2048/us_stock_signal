from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - fallback is for minimal environments.
    yaml = None

try:
    from dotenv import dotenv_values
except Exception:  # pragma: no cover
    dotenv_values = None


@dataclass(slots=True)
class AppSettings:
    timezone: str = "Asia/Shanghai"
    market_timezone: str = "America/New_York"
    data_dir: str = "data"
    database_path: str = "data/us_stock_signal.duckdb"


@dataclass(slots=True)
class Settings:
    app: AppSettings
    universe: dict[str, Any]
    scoring: dict[str, Any]
    pricing: dict[str, Any]
    backtest: dict[str, Any]
    schedule: dict[str, Any]
    dingtalk_webhook: str = ""
    dingtalk_secret: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"


def load_settings(
    config_path: str | Path = "configs/default.yaml",
    env_file: str | Path | None = ".env",
) -> Settings:
    env = _read_env(env_file)
    data = _read_yaml(Path(config_path))
    app_data = data.get("app", {})
    return Settings(
        app=AppSettings(**{**asdict(AppSettings()), **app_data}),
        universe=data.get("universe", {}),
        scoring=data.get("scoring", {}),
        pricing=data.get("pricing", {}),
        backtest=data.get("backtest", {}),
        schedule=data.get("schedule", {}),
        dingtalk_webhook=env.get("DINGTALK_WEBHOOK", ""),
        dingtalk_secret=env.get("DINGTALK_SECRET", ""),
        deepseek_api_key=env.get("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=env.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )


def _read_env(env_file: str | Path | None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if isinstance(value, str)}
    if env_file and dotenv_values:
        path = Path(env_file)
        if path.exists():
            for key, value in dotenv_values(path).items():
                if value is not None and key not in env:
                    env[key] = value
    return env


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if yaml:
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config root must be a mapping")
        return loaded
    return _minimal_yaml_mapping(text)


def _minimal_yaml_mapping(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        if not raw_line.startswith(" "):
            key = raw_line.rstrip(":").strip()
            root[key] = {}
            current = root[key]
        elif current is not None:
            key, value = raw_line.strip().split(":", 1)
            current[key.strip()] = _coerce_scalar(value.strip())
    return root


def _coerce_scalar(value: str) -> Any:
    if value == "":
        return ""
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip('"')
