from __future__ import annotations

import json
from typing import Any

import requests

from us_stock_signal.models import AIEventScore


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: int = 30) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def score_event(self, symbol: str, headlines: list[str]) -> AIEventScore:
        if not self.api_key:
            return AIEventScore(
                score=50,
                status="missing_key",
                summary="未配置 DeepSeek API key，AI 评分按中性处理。",
                risk_notes=["AI 缺失"],
            )
        if not headlines:
            return AIEventScore(score=50, status="no_news", summary="未发现可用新闻，AI 评分按中性处理。")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是股票新闻风险评估器。只返回 JSON："
                        '{"score":0-100,"summary":"中文一句话","risk_notes":["中文风险"]}。'
                    ),
                },
                {
                    "role": "user",
                    "content": f"股票 {symbol} 新闻标题：\n" + "\n".join(headlines[:8]),
                },
            ],
            "temperature": 0.1,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except Exception:
            return AIEventScore(
                score=50,
                status="request_failed",
                summary="DeepSeek 请求失败，AI 评分按中性处理。",
                risk_notes=["AI 请求失败"],
            )
        return self.parse_score_response(content)

    def parse_score_response(self, content: str) -> AIEventScore:
        try:
            data = self._extract_json(content)
            score = max(0.0, min(100.0, float(data.get("score", 50))))
            summary = str(data.get("summary", "")).strip() or "AI 未返回摘要。"
            raw_notes: Any = data.get("risk_notes", [])
            risk_notes = [str(note) for note in raw_notes if str(note).strip()][:5] if isinstance(raw_notes, list) else []
            return AIEventScore(score=score, status="available", summary=summary, risk_notes=risk_notes)
        except Exception:
            return AIEventScore(score=50, status="invalid_json", summary="AI 返回格式无效，按中性评分处理。")

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start : end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("AI response must be a JSON object")
        return parsed

