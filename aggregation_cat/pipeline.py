from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import N_YEARS, XL_ENTITY
from .entity import SUMMARY_COLUMNS, TABLE_COLUMNS, EntityAggregation
from .exporter import CsvExporter, ExcelExporter
from .rcompat import list_dirs


class AggregationCatPipeline:
    def __init__(self, folder: Path, units: dict[str, float], is_xl_pool_format: bool = False,
                 n_years: int = N_YEARS, output_dir: Path | None = None):
        self.folder = folder
        self.units = units  # unité des catfiles par entité ; ses clés sont les entités possibles
        self.is_xl_pool_format = is_xl_pool_format  # True : XL déjà au format pool, exclu du calcul
        self.n_years = n_years
        self.output_dir = output_dir or folder  # le script R écrit dans le dossier d'entrée

    def entity_folders(self) -> dict[str, Path]:
        """Dossiers (à toute profondeur) nommés comme une entité et contenant au moins un sous-dossier."""
        dirs = list_dirs(self.folder, recursive=True)
        paths = [d.as_posix() for d in dirs]
        folders = {}
        for d, path in zip(dirs, paths):
            if d.name in self.units and sum(path in other for other in paths) > 1:
                folders.setdefault(d.name, d)
        return folders

    def run(self) -> None:
        folders = self.entity_folders()
        entities = [e for e in folders if not (self.is_xl_pool_format and e == XL_ENTITY)]

        tables, summary_rows = [], []
        for entity in entities:
            print("------------------------------------------------------")
            print(entity)
            result = EntityAggregation(entity, folders[entity], self.units[entity],
                                       self.n_years).build()
            ExcelExporter(self.output_dir / f"Gross_MM_reconciliation_{entity}.xlsx").export(
                result.figures, result.strips)
            CsvExporter(self.output_dir / f"{entity}_summary.csv").export(result.table)
            tables.append(result.table)
            summary_rows += result.summary_rows
            print("------------------------------------------------------")

        CsvExporter(self.output_dir / "summary_all_subrisks.csv").export(
            pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS))
        all_entities = pd.concat(tables) if tables else pd.DataFrame(columns=TABLE_COLUMNS)
        CsvExporter(self.output_dir / "All_entities_summary.csv").export(all_entities)
        print(f"Fichiers écrits dans : {self.output_dir}")
