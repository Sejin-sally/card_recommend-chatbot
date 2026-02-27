from __future__ import annotations
from pathlib import Path
import pandas as pd
from .constants import CATS


def load_cards_db(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    cards = pd.read_csv(path)

    num_cols = ["prev_month_spend", "annual_fee", "base_rate", "monthly_cap"] + CATS
    for c in num_cols:
        if c in cards.columns:
            cards[c] = pd.to_numeric(cards[c], errors="coerce").fillna(0)

    rate_cols = ["base_rate"] + CATS
    for c in rate_cols:
        if c in cards.columns:
            cards[c] = cards[c].apply(lambda x: x / 100 if float(x) > 1 else float(x))

    return cards




