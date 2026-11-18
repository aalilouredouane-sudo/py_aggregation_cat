from __future__ import annotations

import numpy as np
import pandas as pd

from .config import TOTAL_LABEL
from .metrics import strip_stats


class GroupAggregation:
    """Strips du groupe : somme des strips des entités converties en euros, par risque et au total."""

    def __init__(self, risks: list[str], n_years: int):
        self.columns = list(risks) + [TOTAL_LABEL]  # tous les risques de toutes les entités, puis Total
        self.n_years = n_years
        self.losses = {col: np.zeros(n_years) for col in self.columns}

    def add(self, entity_strips: pd.DataFrame, fx_rate: float) -> None:
        """Ajoute les strips d'une entité (year, risques, Total) x taux de change ; risque absent = 0."""
        for col in self.columns:
            if col in entity_strips.columns:
                self.losses[col] = self.losses[col] + entity_strips[col].to_numpy() * fx_rate

    def build(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(feuille Gross_STEC : mean / AEP200 / STEC par colonne, feuille Local_AAL_strips)."""
        strips = pd.DataFrame({"year": np.arange(1, self.n_years + 1), **self.losses})
        figures = pd.DataFrame({col: strip_stats(strips[col]) for col in self.columns})
        return figures, strips
