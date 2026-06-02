from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_settings
from .data_providers.market_data import fetch_latest_prices
from .data_providers.yahoo_chart import fetch_yahoo_chart_daily_bars
from .models import MarkdownMessage, SignalEvent
from .notifiers.dingtalk import DingTalkNotifier, format_markdown_message
from .pipeline import run_scan
from .pipeline import build_recommendations_from_snapshots, collect_snapshots
from .repository import MarketRepository
from .runtime_lock import runtime_lock
from .scoring_validation import validate_scoring_from_daily_bars
from .strategy_search import search_high_yield_strategies_from_daily_bars
from .storage import (
    load_latest_recommendations,
    load_latest_scan_meta,
    load_latest_scan_session,
    load_signal_events,
    save_backtest_report,
    save_latest_recommendations,
    save_signal_events,
    save_strategy_search_report,
    save_top1_signal,
    save_top1_signal_events,
)
from .sync_guard import daily_sync_window_decision
from .time_utils import infer_us_session, validate_session
from .tracker import evaluate_tracked_signal
from .sync import fetch_yfinance_daily_bars, sync_daily_bars_from_provider, sync_universe_from_provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="us-stock-signal")
    parser.add_argument("--config", default="configs/default.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("--session", choices=["premarket", "regular", "afterhours"], default=None)
    scan_parser.add_argument("--max-symbols", type=int, default=None)
    scan_parser.add_argument("--demo", action="store_true", help="Use deterministic demo data when market data is unavailable.")
    scan_parser.add_argument("--notify", action="store_true", help="Send DingTalk notification after scan completes.")
    scan_parser.add_argument("--live", action="store_true", help="Force live market-data fetch outside regular session.")

    backtest_parser = subparsers.add_parser("backtest")
    backtest_parser.add_argument("--lookback-days", type=int, default=365)
    backtest_parser.add_argument("--sample-days", type=int, default=40)
    backtest_parser.add_argument("--top-n", type=int, default=None)
    backtest_parser.add_argument("--max-symbols", type=int, default=None)
    backtest_parser.add_argument("--max-holding-days", type=int, default=None)

    validate_parser = subparsers.add_parser("validate-scoring")
    validate_parser.add_argument("--lookback-days", type=int, default=365)
    validate_parser.add_argument("--sample-days", type=int, default=40)
    validate_parser.add_argument("--top-n", type=int, default=None)
    validate_parser.add_argument("--max-symbols", type=int, default=None)
    validate_parser.add_argument("--max-holding-days", type=int, default=None)

    strategy_search_parser = subparsers.add_parser("strategy-search")
    strategy_search_parser.add_argument("--lookback-days", type=int, default=365)
    strategy_search_parser.add_argument("--sample-days", type=int, default=40)
    strategy_search_parser.add_argument("--max-symbols", type=int, default=None)
    strategy_search_parser.add_argument("--max-holding-days", type=int, default=None)
    strategy_search_parser.add_argument("--objective", choices=["compound", "avg_all", "avg_entered", "profit_factor"], default="compound")
    strategy_search_parser.add_argument("--min-signals", type=int, default=30)
    strategy_search_parser.add_argument("--top-results", type=int, default=10)

    sync_universe_parser = subparsers.add_parser("sync-universe")
    sync_universe_parser.add_argument("--notify", action="store_true")

    sync_daily_parser = subparsers.add_parser("sync-daily")
    sync_daily_parser.add_argument("--max-symbols", type=int, default=None)
    sync_daily_parser.add_argument("--period", default="1y")
    sync_daily_parser.add_argument("--batch-size", type=int, default=50)
    sync_daily_parser.add_argument("--batch-delay-seconds", type=float, default=None)
    sync_daily_parser.add_argument("--source", choices=["yahoo-chart", "yfinance", "auto"], default="yahoo-chart")
    sync_daily_parser.add_argument("--force", action="store_true", help="Bypass the US daily-bar sync time guard.")

    sync_all_parser = subparsers.add_parser("sync-all")
    sync_all_parser.add_argument("--max-symbols", type=int, default=None)
    sync_all_parser.add_argument("--period", default="1y")
    sync_all_parser.add_argument("--batch-size", type=int, default=50)
    sync_all_parser.add_argument("--batch-delay-seconds", type=float, default=None)
    sync_all_parser.add_argument("--source", choices=["yahoo-chart", "yfinance", "auto"], default="yahoo-chart")
    sync_all_parser.add_argument("--force", action="store_true", help="Bypass the US daily-bar sync time guard.")

    prepare_parser = subparsers.add_parser("prepare-market")
    prepare_parser.add_argument("--session", choices=["premarket", "regular", "afterhours"], default="premarket")
    prepare_parser.add_argument("--period", default="1y")
    prepare_parser.add_argument("--batch-size", type=int, default=100)
    prepare_parser.add_argument("--batch-delay-seconds", type=float, default=None)
    prepare_parser.add_argument("--source", choices=["yahoo-chart", "yfinance", "auto"], default="yahoo-chart")
    prepare_parser.add_argument("--notify", action="store_true")
    prepare_parser.add_argument("--force", action="store_true", help="Bypass the US daily-bar sync time guard.")

    status_parser = subparsers.add_parser("market-status")
    status_parser.add_argument("--min-daily-bars", type=int, default=25)

    subparsers.add_parser("notify").add_argument("--latest", action="store_true")
    track_parser = subparsers.add_parser("track")
    track_parser.add_argument("--notify", action="store_true", help="Send DingTalk only for first-time significant tracking events.")

    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    if args.command == "scan":
        session = validate_session(args.session or infer_us_session())
        return _run_scan_from_repository(
            settings=settings,
            session=session,
            max_symbols=args.max_symbols,
            demo=args.demo,
            notify=args.notify,
            live=args.live,
        )
    if args.command == "sync-universe":
        count = sync_universe_from_provider(_repo(settings))
        print(f"股票池同步完成：{count} 个普通股票/优先标的已写入数据库")
        if args.notify:
            message = format_markdown_message([], session="afterhours", scan_summary={"scanned_count": count})
            sent = _send_dingtalk(settings, message)
            print("钉钉发送成功" if sent else "钉钉未发送：未配置 webhook 或请求失败")
        return 0
    if args.command == "sync-daily":
        return _run_sync_daily(settings, args)
    if args.command == "sync-all":
        return _run_sync_all(settings, args)
    if args.command == "prepare-market":
        return _run_prepare_market(settings, args)
    if args.command == "market-status":
        return _run_market_status(settings, args)
    if args.command == "notify":
        recommendations = load_latest_recommendations(settings.app.data_dir)
        meta = load_latest_scan_meta(settings.app.data_dir)
        session = load_latest_scan_session(settings.app.data_dir)
        message = format_markdown_message(recommendations, session=session, scan_summary=meta.get("scan_summary"))
        sent = _send_dingtalk(settings, message)
        print(message.text)
        print("\n钉钉发送成功" if sent else "\n钉钉未发送：未配置 webhook 或请求失败")
        return 0
    if args.command == "track":
        recommendations = load_latest_recommendations(settings.app.data_dir)
        prices = fetch_latest_prices([rec.symbol for rec in recommendations])
        previous_events = load_signal_events(settings.app.data_dir)
        previously_notified = _previously_notified_track_events(previous_events)
        events = []
        now = datetime.now(timezone.utc)
        for rec in recommendations:
            if rec.symbol not in prices:
                continue
            events.append(
                evaluate_tracked_signal(
                    rec,
                    prices[rec.symbol],
                    now,
                    rec.created_at,
                    max_tracking_days=_configured_max_holding_days(settings, None),
                )
            )
        save_signal_events(events, settings.app.data_dir)
        save_top1_signal_events(events, settings.app.data_dir)
        for event in events:
            print(f"{event.symbol} {event.event_type}: {event.message} 当前价 {event.price:.2f}")
        if not events:
            print("没有可跟踪事件。")
        notify_events = [event for event in events if _should_notify_track_event(event, previously_notified)]
        if args.notify and notify_events:
            sent = _send_dingtalk(settings, _format_track_events_message(notify_events))
            print("钉钉跟踪提醒发送成功" if sent else "钉钉跟踪提醒未发送")
        return 0
    if args.command in {"backtest", "validate-scoring"}:
        return _run_scoring_validation(settings, args)
    if args.command == "strategy-search":
        return _run_strategy_search(settings, args)
    return 1


def _run_scan_from_repository(
    settings,
    session: str,
    max_symbols: int | None,
    demo: bool,
    notify: bool,
    live: bool,
) -> int:
    with runtime_lock(_runtime_lock_path(settings)) as acquired:
        if not acquired:
            print("已有同步或扫描任务正在运行，本次任务跳过。")
            return 0
        return _run_scan_from_repository_unlocked(settings, session, max_symbols, demo, notify, live)


def _run_scan_from_repository_unlocked(
    settings,
    session: str,
    max_symbols: int | None,
    demo: bool,
    notify: bool,
    live: bool,
) -> int:
    scan_limit = _scan_limit_for_command(max_symbols, settings, live)
    repo = _repo(settings, read_only=not live)
    snapshots = []
    if live:
        snapshots = collect_snapshots(settings, scan_limit, demo)
        repo.upsert_market_snapshots(snapshots)
    if not snapshots and not live:
        snapshots = repo.load_market_snapshots_from_daily_bars(limit=scan_limit)
    if not snapshots:
        snapshots = repo.load_latest_market_snapshots(limit=scan_limit)
    if not snapshots:
        snapshots = repo.load_market_snapshots_from_daily_bars(limit=scan_limit)

    recommendations = build_recommendations_from_snapshots(settings, session, snapshots)
    scanned_count = len(snapshots) if scan_limit is None else int(scan_limit)
    scan_summary = {
        "scanned_count": scanned_count,
        "candidate_count": len(recommendations),
        "min_score": _score_gate_for_session(settings, session),
        "top_n": int(settings.scoring.get("top_n", 10)),
        "trigger_mode": settings.scoring.get("trigger_mode", "standard"),
        "primary_take_profit": settings.scoring.get("high_yield", {}).get("primary_take_profit", "tp1"),
    }
    path = save_latest_recommendations(
        recommendations,
        settings.app.data_dir,
        session=session,
        scan_summary=scan_summary,
    )
    save_top1_signal(
        recommendations[0] if recommendations else None,
        settings.app.data_dir,
        session=session,
        scan_summary=scan_summary,
    )
    message = format_markdown_message(recommendations, session=session, scan_summary=scan_summary)
    print(message.text)
    print(f"\n已保存推荐结果：{path}")
    if notify:
        sent = _send_dingtalk(settings, message)
        print("钉钉发送成功" if sent else "钉钉未发送：未配置 webhook 或请求失败")
    return 0


def _run_sync_daily(settings, args) -> int:
    with runtime_lock(_runtime_lock_path(settings)) as acquired:
        if not acquired:
            print("已有同步或扫描任务正在运行，本次任务跳过。")
            return 0
        if not _daily_sync_allowed(settings, args):
            return 0
        repo = _repo(settings)
        symbols = repo.load_symbols(limit=args.max_symbols)
        if not symbols:
            print("数据库股票池为空，请先运行：python -m us_stock_signal sync-universe")
            return 1
        provider, fallback_provider = _daily_sync_providers(args.source)
        count = sync_daily_bars_from_provider(
            repo,
            symbols,
            provider=provider,
            fallback_provider=fallback_provider,
            period=args.period,
            batch_size=args.batch_size,
            batch_delay_seconds=_daily_sync_batch_delay_seconds(settings, args),
            progress_callback=_print_daily_sync_progress,
        )
        print(f"日线同步完成：{count} 条日线记录已写入数据库，股票数：{len(symbols)}")
        return 0


def _run_sync_all(settings, args) -> int:
    with runtime_lock(_runtime_lock_path(settings)) as acquired:
        if not acquired:
            print("已有同步或扫描任务正在运行，本次任务跳过。")
            return 0
        if not _daily_sync_allowed(settings, args):
            return 0
        repo = _repo(settings)
        universe_count = sync_universe_from_provider(repo)
        symbols = repo.load_symbols(limit=args.max_symbols)
        provider, fallback_provider = _daily_sync_providers(args.source)
        daily_count = sync_daily_bars_from_provider(
            repo,
            symbols,
            provider=provider,
            fallback_provider=fallback_provider,
            period=args.period,
            batch_size=args.batch_size,
            batch_delay_seconds=_daily_sync_batch_delay_seconds(settings, args),
            progress_callback=_print_daily_sync_progress,
        )
        print(
            f"全量同步完成：股票池 {universe_count} 个；"
            f"日线记录 {daily_count} 条；本次日线股票数 {len(symbols)}"
        )
        return 0


def _run_prepare_market(settings, args) -> int:
    with runtime_lock(_runtime_lock_path(settings)) as acquired:
        if not acquired:
            print("已有同步或扫描任务正在运行，本次任务跳过。")
            return 0
        if not _daily_sync_allowed(settings, args):
            return 0
        repo = _repo(settings)
        universe_count = sync_universe_from_provider(repo)
        symbols = repo.load_symbols(limit=None)
        provider, fallback_provider = _daily_sync_providers(args.source)
        daily_count = sync_daily_bars_from_provider(
            repo,
            symbols,
            provider=provider,
            fallback_provider=fallback_provider,
            period=args.period,
            batch_size=args.batch_size,
            batch_delay_seconds=_daily_sync_batch_delay_seconds(settings, args),
            progress_callback=_print_daily_sync_progress,
        )
        print(
            f"盘前全量准备完成：股票池 {universe_count} 个；"
            f"日线记录 {daily_count} 条；本次日线股票数 {len(symbols)}"
        )
        return _run_scan_from_repository_unlocked(
            settings=settings,
            session=validate_session(args.session),
            max_symbols=None,
            demo=False,
            notify=args.notify,
            live=False,
        )


def _run_market_status(settings, args) -> int:
    with runtime_lock(_runtime_lock_path(settings)) as acquired:
        if not acquired:
            print("已有同步或扫描任务正在运行，本次任务跳过。")
            return 0
        coverage = _repo(settings, read_only=True).market_data_coverage(min_daily_bars=args.min_daily_bars)
        print(f"股票池总数：{coverage['active_symbols']}")
        print(f"已有日线股票：{coverage['symbols_with_daily_bars']}")
        print(f"可参与扫描：{coverage['symbols_ready_for_scan']}")
        print(f"日线记录数：{coverage['daily_bar_rows']}")
        print(f"最新日线日期：{coverage['latest_daily_bar_date']}")
        print(f"覆盖率：{coverage['coverage_pct']}%")
        return 0


def _run_scoring_validation(settings, args) -> int:
    with runtime_lock(_runtime_lock_path(settings)) as acquired:
        if not acquired:
            print("已有同步或扫描任务正在运行，本次任务跳过。")
            return 0
        daily_bars = _repo(settings, read_only=True).load_daily_bars_for_validation(max_symbols=args.max_symbols)
        report = validate_scoring_from_daily_bars(
            daily_bars,
            {
                "universe": settings.universe,
                "scoring": settings.scoring,
                "pricing": settings.pricing,
                "backtest": settings.backtest,
            },
            lookback_days=args.lookback_days,
            top_n=_validation_top_n(settings, args.top_n),
            sample_days=args.sample_days,
            max_holding_days=_configured_max_holding_days(settings, args.max_holding_days),
        )
        path = save_backtest_report(report, settings.app.data_dir)
        _print_scoring_validation_report(report, path)
        return 0


def _run_strategy_search(settings, args) -> int:
    with runtime_lock(_runtime_lock_path(settings)) as acquired:
        if not acquired:
            print("已有同步、扫描或验证任务正在运行，本次策略搜索跳过。")
            return 0
        daily_bars = _repo(settings, read_only=True).load_daily_bars_for_validation(max_symbols=args.max_symbols)
        report = search_high_yield_strategies_from_daily_bars(
            daily_bars,
            {
                "universe": settings.universe,
                "scoring": settings.scoring,
                "pricing": settings.pricing,
                "backtest": settings.backtest,
            },
            lookback_days=args.lookback_days,
            sample_days=args.sample_days,
            max_holding_days=_configured_max_holding_days(settings, args.max_holding_days),
            objective=args.objective,
            min_signal_count=args.min_signals,
            top_results=args.top_results,
        )
        path = save_strategy_search_report(report, settings.app.data_dir)
        _print_strategy_search_report(report, path)
        return 0


def _print_scoring_validation_report(report: dict[str, Any], path: Path) -> None:
    summary = report.get("summary", {})
    print("评分效果验证完成")
    print(f"报告已保存：{path}")
    print(f"样本交易日：{report.get('sample_days_evaluated', 0)} / 请求 {report.get('sample_days_requested', 0)}")
    if report.get("first_signal_date") and report.get("last_signal_date"):
        print(f"验证区间：{report['first_signal_date']} 至 {report['last_signal_date']}")
    print(f"信号数量：{summary.get('signal_count', 0)}")
    print(f"入场率：{float(summary.get('entry_rate', 0)) * 100:.2f}%")
    print(f"胜率：{float(summary.get('win_rate', 0)) * 100:.2f}%")
    print(f"平均收益：{float(summary.get('avg_return_pct', 0)):.2f}%")
    print(f"Profit Factor：{summary.get('profit_factor', 0)}")
    print(f"最大回撤：{float(summary.get('max_drawdown_pct', 0)):.2f}%")
    print(f"退出分布：{summary.get('exit_reason_counts', {})}")


def _print_strategy_search_report(report: dict[str, Any], path: Path) -> None:
    print("策略搜索完成")
    print(f"报告已保存：{path}")
    print(f"样本交易日：{report.get('sample_days_evaluated', 0)} / 请求 {report.get('sample_days_requested', 0)}")
    print(f"目标排序：{report.get('objective')}；最小信号数：{report.get('min_signal_count')}")
    print(f"已评估参数组合：{report.get('evaluated_variants', 0)}")
    if report.get("reason"):
        print(f"无法完成搜索：{report['reason']}")
        return
    results = report.get("results", [])
    if not results:
        print("没有满足最小信号数的策略组合。")
        return
    for idx, item in enumerate(results, start=1):
        variant = item.get("variant", {})
        summary = item.get("summary", {})
        print(
            f"{idx}. {variant.get('name')} | "
            f"信号 {summary.get('signal_count', 0)} | "
            f"入场率 {float(summary.get('entry_rate', 0)) * 100:.2f}% | "
            f"胜率 {float(summary.get('win_rate', 0)) * 100:.2f}% | "
            f"平均收益 {float(summary.get('avg_return_pct', 0)):.2f}% | "
            f"全信号平均 {float(summary.get('avg_return_pct_all_signals', 0)):.2f}% | "
            f"单仓复利 {float(summary.get('single_position_total_return_pct', 0)):.2f}% | "
            f"单仓交易 {summary.get('single_position_trade_count', 0)} | "
            f"PF {summary.get('profit_factor', 0)} | "
            f"最大回撤 {float(summary.get('max_drawdown_pct', 0)):.2f}% | "
            f"Top{variant.get('top_n')} TP2={variant.get('take_profit_2_atr_multiple')}ATR | "
            f"entryBuf={variant.get('entry_buffer_pct') if variant.get('entry_buffer_pct') is not None else 'default'} | "
            f"pending={variant.get('pending_entry_days') if variant.get('pending_entry_days') is not None else 'default'} | "
            f"stopATR={variant.get('stop_atr_multiple') or 'default'} | "
            f"maxStop={variant.get('max_stop_pct') or 'default'}"
        )


def _print_scoring_validation_report(report: dict[str, Any], path: Path) -> None:
    summary = report.get("summary", {})
    print("评分效果验证完成")
    print(f"报告已保存：{path}")
    print(f"样本交易日：{report.get('sample_days_evaluated', 0)} / 请求 {report.get('sample_days_requested', 0)}")
    if report.get("first_signal_date") and report.get("last_signal_date"):
        print(f"验证区间：{report['first_signal_date']} 至 {report['last_signal_date']}")
    print(f"信号数量：{summary.get('signal_count', 0)}")
    print(f"入场率：{float(summary.get('entry_rate', 0)) * 100:.2f}%")
    print(f"胜率：{float(summary.get('win_rate', 0)) * 100:.2f}%")
    print(f"平均收益：{float(summary.get('avg_return_pct', 0)):.2f}%")
    print(f"全信号平均收益：{float(summary.get('avg_return_pct_all_signals', 0)):.2f}%")
    print(f"单仓复利收益：{float(summary.get('single_position_total_return_pct', 0)):.2f}%")
    print(f"单仓最终权益倍数：{float(summary.get('single_position_final_equity', 0)):.4f}x")
    print(f"单仓交易次数：{summary.get('single_position_trade_count', 0)}")
    print(f"单仓最大回撤：{float(summary.get('single_position_max_drawdown_pct', 0)):.2f}%")
    print(f"Profit Factor：{summary.get('profit_factor', 0)}")
    print(f"最大回撤：{float(summary.get('max_drawdown_pct', 0)):.2f}%")
    print(f"退出分布：{summary.get('exit_reason_counts', {})}")


def _send_dingtalk(settings: Any, message) -> bool:
    notifier = DingTalkNotifier(settings.dingtalk_webhook, settings.dingtalk_secret)
    return notifier.send_markdown(message)


_TRACK_NOTIFY_EVENT_TYPES = {
    "ENTRY_TRIGGERED",
    "STOP_LOSS",
    "TAKE_PROFIT_1",
    "TAKE_PROFIT_2",
    "INVALIDATED",
    "EXPIRED",
}


def _previously_notified_track_events(events: list[SignalEvent]) -> set[tuple[str, str]]:
    return {
        (event.recommendation_id, event.event_type)
        for event in events
        if event.event_type in _TRACK_NOTIFY_EVENT_TYPES
    }


def _should_notify_track_event(event: SignalEvent, previously_notified: set[tuple[str, str]]) -> bool:
    if event.event_type not in _TRACK_NOTIFY_EVENT_TYPES:
        return False
    return (event.recommendation_id, event.event_type) not in previously_notified


def _format_track_events_message(events: list[SignalEvent]) -> MarkdownMessage:
    title = "美股信号跟踪提醒"
    lines = [
        f"### {title}",
        "",
        "以下为首次触发的跟踪事件，价格来自实时/近实时行情接口：",
        "",
    ]
    for event in events:
        lines.append(f"- {event.symbol} {_track_event_label(event.event_type)}：当前价 {event.price:.2f}；{event.message}")
    lines.extend(["", "> 仅为研究提醒，不自动交易，不构成投资建议。"])
    return MarkdownMessage(title=title, text="\n".join(lines))


def _track_event_label(event_type: str) -> str:
    labels = {
        "ENTRY_TRIGGERED": "触发入场",
        "STOP_LOSS": "触发止损",
        "TAKE_PROFIT_1": "触发第一止盈",
        "TAKE_PROFIT_2": "触发第二止盈",
        "INVALIDATED": "信号失效",
        "EXPIRED": "跟踪超期",
    }
    return labels.get(event_type, event_type)


def _runtime_lock_path(settings) -> Path:
    return Path(settings.app.data_dir) / "us_stock_signal.lock"


def _print_daily_sync_progress(done: int, total: int, rows: int) -> None:
    print(f"日线同步进度：{done}/{total} 股票，累计 {rows} 条记录", flush=True)


def _daily_sync_allowed(settings, args) -> bool:
    decision = daily_sync_window_decision(
        settings.schedule,
        market_timezone=settings.app.market_timezone,
        force=bool(getattr(args, "force", False)),
    )
    if decision.allowed:
        print(f"日线同步窗口：{decision.window}，美东时间 {decision.market_time:%Y-%m-%d %H:%M}")
        return True
    print(f"跳过日线同步：{decision.message}")
    print("如需手动修复或补历史数据，可追加 --force。")
    return False


def _daily_sync_batch_delay_seconds(settings, args) -> float:
    override = getattr(args, "batch_delay_seconds", None)
    if override is not None:
        return float(override)
    return float(settings.schedule.get("daily_sync_batch_delay_seconds", 0.0))


def _repo(settings, read_only: bool = False) -> MarketRepository:
    return MarketRepository(settings.app.database_path, read_only=read_only)


def _daily_sync_providers(source: str):
    if source == "yahoo-chart":
        return fetch_yahoo_chart_daily_bars, None
    if source == "yfinance":
        return fetch_yfinance_daily_bars, None
    return fetch_yfinance_daily_bars, fetch_yahoo_chart_daily_bars


def _score_gate_for_session(settings, session: str) -> float:
    scoring = settings.scoring
    if scoring.get("trigger_mode") == "high_yield_breakout":
        high_yield = scoring.get("high_yield", {})
        if session in {"premarket", "afterhours"}:
            return float(high_yield.get("watchlist_min_score", high_yield.get("min_score", 60)))
        return float(high_yield.get("min_score", 60))
    if session in {"premarket", "afterhours"}:
        return float(scoring.get("watchlist_min_score", scoring.get("min_score", 60)))
    return float(scoring.get("min_score", 60))


def _validation_top_n(settings, override: int | None) -> int:
    if override is not None:
        return int(override)
    scoring = settings.scoring
    if scoring.get("trigger_mode") == "high_yield_breakout":
        return int(scoring.get("high_yield", {}).get("top_n", scoring.get("top_n", 10)))
    return int(scoring.get("top_n", 10))


def _configured_max_holding_days(settings, override: int | None) -> int:
    if override is not None:
        return int(override)
    return int(settings.pricing.get("max_tracking_trading_days", 10))


def _scan_limit_for_command(max_symbols: int | None, settings, use_live_scan: bool) -> int | None:
    if max_symbols is not None:
        return max_symbols
    if use_live_scan:
        return int(settings.universe.get("max_symbols_per_scan", 300))
    return None


if __name__ == "__main__":
    raise SystemExit(main())
