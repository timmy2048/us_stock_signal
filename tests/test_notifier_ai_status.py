from us_stock_signal.models import Recommendation
from us_stock_signal.notifiers.dingtalk import format_markdown_message


def test_markdown_message_makes_missing_ai_analysis_explicit():
    rec = Recommendation(
        id="scan-1-XYZ",
        symbol="XYZ",
        rank=1,
        score=88.5,
        session="afterhours",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="2 个交易日",
        invalidation_price=9.9,
        reasons=["日线强势"],
        risk_flags=["未发现可用新闻，AI 评分按中性处理。"],
        data_quality="duckdb_daily",
        ai_status="neutral_or_missing",
        signal_status="WATCHLIST",
    )

    message = format_markdown_message([rec])

    assert "AI分析：未参与有效评分" in message.text
    assert "按中性 50 分处理" in message.text
    assert "最新日线收盘价" in message.text
    assert "不是盘中实时价" in message.text
