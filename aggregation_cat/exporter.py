from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from .rcompat import fwrite


def _cell(value):
    """Valeur Python pour openpyxl ; NA -> cellule vide."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


class ExcelExporter:
    """Écrit Gross_MM_reconciliation_<entité>.xlsx : feuilles Gross_STEC et Local_AAL_strips."""

    def __init__(self, output_path: Path):
        self.output_path = output_path

    def export(self, figures: pd.DataFrame, strips: pd.DataFrame) -> None:
        wb = Workbook(write_only=True)

        ws = wb.create_sheet("Gross_STEC")
        ws.append([None] + list(figures.columns))
        for name, row in figures.iterrows():
            ws.append([name] + [_cell(v) for v in row])

        ws = wb.create_sheet("Local_AAL_strips")
        ws.append(list(strips.columns))
        for row in strips.itertuples(index=False, name=None):
            ws.append([_cell(v) for v in row])

        wb.save(self.output_path)


class CsvExporter:
    """Écrit un CSV au format de fwrite."""

    def __init__(self, output_path: Path):
        self.output_path = output_path

    def export(self, table: pd.DataFrame) -> None:
        fwrite(table, self.output_path)
