from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from dataclasses import asdict
from typing import Any

import requests

from us_stock_signal.execution_policy import (
    recommendation_primary_take_profit_price,
    recommendation_primary_take_profit_target,
    recommendation_secondary_take_profit_price,
    take_profit_label,
)
from us_stock_signal.models import MarkdownMessage, Recommendation


def build_signed_url(webhook: str, secret: str = "", timestamp_ms: int | None = None) -> str:
    if not secret:
        return webhook
    timestamp = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"


def format_markdown_message(
    recommendations: list[Recommendation],
    session: str | None = None,
    scan_summary: dict[str, Any] | None = None,
) -> MarkdownMessage:
    title = _message_title(recommendations, session, scan_summary)
    if not recommendations:
        prefix = (
            "非交易时段，暂无达到预备观察阈值的做多候选。"
            if _session_is_watchlist(session)
            else "今日没有达到阈值的做多信号。"
        )
        lines = [f"### {title}", "", prefix, "", *_summary_lines(0, scan_summary)]
        return MarkdownMessage(title=title, text="\n".join(line for line in lines if line != ""))

    top = recommendations[0]
    is_watchlist = top.signal_status in {"WATCHLIST", "CONFIRMING"}
    top_heading = "Top1 预备观察" if is_watchlist else "Top1 重点信号"
    price_label = _price_label(top.data_quality)
    primary_target = _primary_take_profit_target(top, scan_summary)
    primary_label = take_profit_label(primary_target)
    primary_take_profit = recommendation_primary_take_profit_price(top, primary_target)
    secondary_label = "TP1" if primary_label == "TP2" else "TP2"
    secondary_take_profit = recommendation_secondary_take_profit_price(top, primary_target)

    lines = [
        f"### {title}",
        "",
        _status_line(top.signal_status),
        "",
        f"**{top_heading}**",
        f"- 股票：{top.symbol}",
        f"- 方向：{top.direction}",
        f"- 信号状态：{top.signal_status}",
        f"- 综合分：{top.score:.1f}/100",
        f"- {price_label}：{top.current_price:.2f}",
        f"- 观察区间：{top.entry_price_low:.2f} - {top.entry_price_high:.2f}",
        f"- 回测触发价：突破 {top.entry_price_high:.2f}",
        f"- 允许追价上限：{_max_chase_price(top):.2f}",
        f"- 回测止损价：{top.stop_loss:.2f}",
        f"- 回测主止盈：{primary_label} {primary_take_profit:.2f}",
        f"- 参考止盈：{secondary_label} {secondary_take_profit:.2f}",
        f"- 信号有效期：{top.expiry}",
        f"- 失效价格：{top.invalidation_price:.2f}",
        f"- 推荐原因：{'; '.join(top.reasons) or '无'}",
        f"- 风险提示：{'; '.join(top.risk_flags) or '无'}",
        f"- 数据质量：{top.data_quality}",
        _price_source_line(top.data_quality),
        _ai_status_line(top.ai_status),
        f"- 执行口径：按回测主目标 {primary_label} 跟踪，不按参考止盈分批落袋",
        "",
        *_summary_lines(len(recommendations), scan_summary),
        "",
        "**候选简表**",
    ]
    for rec in recommendations[:10]:
        rec_target = _primary_take_profit_target(rec, scan_summary)
        rec_primary_label = take_profit_label(rec_target)
        rec_primary_take_profit = recommendation_primary_take_profit_price(rec, rec_target)
        lines.append(
            f"{rec.rank}. {rec.symbol} | 分数 {rec.score:.1f} | 触发 >= {rec.entry_price_high:.2f} | "
            f"追价 <= {_max_chase_price(rec):.2f} | 止损 {rec.stop_loss:.2f} | "
            f"主止盈 {rec_primary_label} {rec_primary_take_profit:.2f}"
        )
    lines.extend(["", "> 仅为研究提醒，不自动交易，不构成投资建议。"])
    return MarkdownMessage(title=title, text="\n".join(lines))


def _summary_lines(candidate_count: int, scan_summary: dict[str, Any] | None) -> list[str]:
    scanned_count = None
    min_score = None
    top_n = None
    trigger_mode = None
    primary_take_profit = None
    if scan_summary:
        scanned_count = scan_summary.get("scanned_count")
        min_score = scan_summary.get("min_score")
        top_n = scan_summary.get("top_n")
        trigger_mode = scan_summary.get("trigger_mode")
        primary_take_profit = scan_summary.get("primary_take_profit")

    lines = [f"本次入选候选：{candidate_count} 个"]
    if trigger_mode == "high_yield_breakout":
        target_text = take_profit_label(primary_take_profit)
        lines.append(f"触发模式：高收益突破；验证主目标：{target_text}")
    if scanned_count is not None:
        lines.append(f"本次扫描范围：{scanned_count} 个")
    if min_score is not None:
        score_value = float(min_score)
        score_text = f"{score_value:.0f}" if score_value.is_integer() else f"{score_value:.1f}"
        limit_text = f"，最多推送 Top{top_n}" if top_n is not None else ""
        lines.append(f"入选门槛：综合分 >= {score_text}，且通过价格/流动性/止损止盈硬过滤{limit_text}")
    return lines


def _message_title(
    recommendations: list[Recommendation],
    session: str | None = None,
    scan_summary: dict[str, Any] | None = None,
) -> str:
    if scan_summary and scan_summary.get("trigger_mode") == "high_yield_breakout":
        if recommendations and recommendations[0].signal_status in {"WATCHLIST", "CONFIRMING"}:
            return "美股短线高收益突破预备观察"
        if not recommendations and _session_is_watchlist(session):
            return "美股短线高收益突破预备观察"
        return "美股短线高收益突破推荐"
    if recommendations and recommendations[0].signal_status in {"WATCHLIST", "CONFIRMING"}:
        return "美股短线 Top10 预备观察名单"
    if not recommendations and _session_is_watchlist(session):
        return "美股短线 Top10 预备观察名单"
    return "美股短线 Top10 推荐"


def _session_is_watchlist(session: str | None) -> bool:
    return session in {"premarket", "afterhours"}


def _status_line(signal_status: str) -> str:
    if signal_status == "WATCHLIST":
        return "**状态：非交易时段预备观察，等待开盘确认，不是立即买入信号。**"
    if signal_status == "CONFIRMING":
        return "**状态：盘前/盘后确认中，等待常规交易时段价格和成交量确认。**"
    return "**状态：交易时段可执行信号，请结合实时价格自行决策。**"


def _ai_status_line(ai_status: str) -> str:
    if ai_status == "available":
        return "- AI分析：已参与事件/新闻评分"
    if ai_status == "neutral_or_missing":
        return "- AI分析：未参与有效评分，新闻缺失或 AI 请求不可用，本次按中性 50 分处理"
    return f"- AI分析：状态 {ai_status}"


def _price_label(data_quality: str) -> str:
    if data_quality == "duckdb_daily":
        return "最新日线收盘价"
    return "当前价"


def _price_source_line(data_quality: str) -> str:
    if data_quality == "duckdb_daily":
        return "- 价格来源：日线数据库，不是盘中实时价"
    return "- 价格来源：实时/近实时行情"


def _primary_take_profit_target(
    recommendation: Recommendation,
    scan_summary: dict[str, Any] | None,
) -> str:
    fallback = None
    if scan_summary:
        fallback = scan_summary.get("primary_take_profit")
    return recommendation_primary_take_profit_target(recommendation, fallback)


def _max_chase_price(recommendation: Recommendation) -> float:
    if recommendation.max_chase_price and recommendation.max_chase_price >= recommendation.entry_price_high:
        return recommendation.max_chase_price
    return recommendation.entry_price_high


class DingTalkNotifier:
    def __init__(self, webhook: str, secret: str = "", timeout_seconds: int = 15) -> None:
        self.webhook = webhook.strip()
        self.secret = secret.strip()
        self.timeout_seconds = timeout_seconds

    def send_markdown(self, message: MarkdownMessage) -> bool:
        if not self.webhook:
            return False
        payload = {"msgtype": "markdown", "markdown": asdict(message)}
        url = build_signed_url(self.webhook, self.secret)
        try:
            response = requests.post(url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            data = response.json()
            return data.get("errcode", 0) == 0
        except Exception:
            return False
