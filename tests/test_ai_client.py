from us_stock_signal.ai.deepseek import DeepSeekClient


def test_ai_client_returns_fallback_when_key_missing():
    client = DeepSeekClient(api_key="", base_url="https://api.deepseek.com", model="deepseek-chat")

    result = client.score_event(symbol="XYZ", headlines=["great news"])

    assert result.score == 50
    assert result.status == "missing_key"
    assert result.summary


def test_ai_json_parser_falls_back_on_invalid_json():
    client = DeepSeekClient(api_key="key", base_url="https://api.deepseek.com", model="deepseek-chat")

    result = client.parse_score_response("not-json")

    assert result.score == 50
    assert result.status == "invalid_json"

