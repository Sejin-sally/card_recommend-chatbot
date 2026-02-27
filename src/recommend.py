from __future__ import annotations
import pandas as pd
from .constants import CATS

def summarize_spend(df2:pd.DataFrame) -> dict:
    spend = df2.groupby("category_final")["amount"].sum().to_dict()
    return {k: float(v) for k, v in spend.items()}

def compute_recommendation(df2: pd.DataFrame, cards: pd.DataFrame, topn: int = 30):
    spend = summarize_spend(df2)
    total_spend = float(sum(spend.values()))

    cards_scored = cards.copy()

    def score_row(r: pd.Series) -> float:
        base = float(r.get("base_rate", 0) or 0) * total_spend
        bonus = 0.0
        for cat in CATS:
            bonus += float(r.get(cat, 0) or 0) * float(spend.get(cat, 0) or 0)
        return base + bonus
    
    cards_scored["score_raw"] = cards_scored.apply(score_row, axis=1)

    def cap_score(r: pd.Series) -> float:
        cap = float(r.get("monthly_cap", 0) or 0)
        return min(float(r["score_raw"]), cap) if cap > 0 else float(r["score_raw"])
    
    cards_scored["score_capped"] = cards_scored.apply(cap_score, axis = 1)
    cards_scored["score_adj"] = cards_scored["score_capped"]

    top = cards_scored.sort_values("score_adj", ascending=False).head(topn).copy()
    return cards_scored, top, spend, total_spend

