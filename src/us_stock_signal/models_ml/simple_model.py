from __future__ import annotations


def heuristic_ml_score(rule_score: float, atr_pct: float, volume_ratio: float) -> float:
    score = rule_score * 0.75 + 50 * 0.15
    if 0.02 <= atr_pct <= 0.08:
        score += 7
    elif 0.01 <= atr_pct < 0.02:
        score += 3
    elif 0.08 < atr_pct <= 0.12:
        score += 2
    elif atr_pct > 0.12:
        score -= min(12, (atr_pct - 0.12) * 100)
    else:
        score -= 4
    score += max(-4, min(8, (volume_ratio - 1.0) * 4.0))
    return round(max(0, min(100, score)), 2)
