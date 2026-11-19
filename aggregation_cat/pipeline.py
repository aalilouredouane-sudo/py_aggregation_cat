from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import GROUP_LABEL, N_YEARS, XL_ENTITY
from .entity import LOB_COLUMNS, SUMMARY_COLUMNS, TABLE_COLUMNS, EntityAggregation
from .exporter import CsvExporter, ExcelExporter
from .group import GroupAggregation
from .rcompat import list_dirs


class AggregationCatPipeline:
    def __init__(self, folder: Path, units: dict[str, float], is_xl_pool_format: bool = False,
                 group: bool = False, fx_rates: dict[str, float] | None = None,
                 n_years: int = N_YEARS, output_dir: Path | None = None, by_lob: bool = False):
        self.folder = folder
        self.units = units  # unité des catfiles par entité ; ses clés sont les entités possibles
        self.is_xl_pool_format = is_xl_pool_format  # True : XL déjà au format pool, exclu du calcul
        self.group = group  # True : ajoute Gross_MM_reconciliation_Group.xlsx (toutes entités, en euros)
        self.fx_rates = fx_rates or {}  # taux de change vers l'euro par entité (utilisé si group)
        self.n_years = n_years
        self.output_dir = output_dir or folder  # le script R écrit dans le dossier d'entrée
        self.by_lob = by_lob  # True : ajoute <entité>_summary_by_lob.csv et All_entities_summary_by_lob.csv

    def entity_folders(self) -> dict[str, Path]:
        """Dossiers (à toute profondeur) nommés comme une entité et contenant au moins un sous-dossier."""
        dirs = list_dirs(self.folder, recursive=True)
        paths = [d.as_posix() for d in dirs]
        folders = {}
        for d, path in zip(dirs, paths):
            if d.name in self.units and sum(path in other for other in paths) > 1:
                folders.setdefault(d.name, d)
        return folders

    def _group_aggregation(self, folders: dict[str, Path], entities: list[str]) -> GroupAggregation:
        missing = [e for e in entities if e not in self.fx_rates]
        if missing:
            raise ValueError(f"group = True mais pas de taux de change (fx_rates) pour : {', '.join(missing)}")
        # colonnes du groupe : risques de toutes les entités trouvées, dans l'ordre de première apparition
        risks = [d.name for folder in folders.values() for d in list_dirs(folder)]
        return GroupAggregation(list(dict.fromkeys(risks)), self.n_years)

    def run(self) -> None:
        folders = self.entity_folders()
        entities = [e for e in folders if not (self.is_xl_pool_format and e == XL_ENTITY)]
        group = self._group_aggregation(folders, entities) if self.group else None

        tables, summary_rows, lob_tables = [], [], []
        for entity in entities:
            print("------------------------------------------------------")
            print(entity)
            result = EntityAggregation(entity, folders[entity], self.units[entity],
                                       self.n_years, self.by_lob).build()
            ExcelExporter(self.output_dir / f"Gross_MM_reconciliation_{entity}.xlsx").export(
                result.figures, result.strips)
            CsvExporter(self.output_dir / f"{entity}_summary.csv").export(result.table)
            tables.append(result.table)
            if self.by_lob:
                CsvExporter(self.output_dir / f"{entity}_summary_by_lob.csv").export(result.lob_table)
                lob_tables.append(result.lob_table)
            summary_rows += result.summary_rows
            print("------------------------------------------------------")
            if group:
                print(f"Taux de change {entity} : {self.fx_rates[entity]}")
                group.add(result.strips, self.fx_rates[entity])

        if group:
            ExcelExporter(self.output_dir / f"Gross_MM_reconciliation_{GROUP_LABEL}.xlsx").export(
                *group.build())
        CsvExporter(self.output_dir / "summary_all_subrisks.csv").export(
            pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS))
        all_entities = pd.concat(tables) if tables else pd.DataFrame(columns=TABLE_COLUMNS)
        CsvExporter(self.output_dir / "All_entities_summary.csv").export(all_entities)
        if self.by_lob:
            all_lobs = pd.concat(lob_tables) if lob_tables else pd.DataFrame(columns=LOB_COLUMNS)
            CsvExporter(self.output_dir / "All_entities_summary_by_lob.csv").export(all_lobs)
        print(f"Fichiers écrits dans : {self.output_dir}")
