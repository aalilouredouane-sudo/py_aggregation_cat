from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import (AEP, ALL_LABEL, CATFILE_PATTERN, NO_POOL, NO_POOL_FILE, OEP,
                     POOL_TAG, TOTAL_LABEL, XL_ENTITY)
from .metrics import strip_stats
from .reader import (add_lob_strips, add_strip, combine_segments, combine_segments_by_lob,
                     pool_yearly_strip, read_catfile, read_pool_file, single_catfile,
                     yearly_lob_strips, yearly_strip, zero_strip)
from .rcompat import all_equal, has_tag, list_dirs, list_files

TABLE_COLUMNS = ["Entity", "risk", "mean", AEP, "STEC", OEP, "Checkpool"]
SUMMARY_COLUMNS = ["Entity", "Risk", "segment", "file", "mean", AEP, "STEC", OEP]
LOB_COLUMNS = ["Entity", "risk", "LoB", "mean", AEP, "STEC", OEP]


@dataclass
class EntityResult:
    table: pd.DataFrame                # <entité> _summary.csv
    strips: pd.DataFrame               # feuille Local_AAL_strips : year, une colonne par risque, Total
    figures: pd.DataFrame              # feuille Gross_STEC : mean / AEP200 / STEC par colonne de strips
    summary_rows: list[dict] = field(default_factory=list)  # lignes de summary_all_subrisks.csv
    lob_table: pd.DataFrame | None = None  # <entité> _summary_by_lob.csv (option by_lob)


class EntityAggregation:
    """Agrège les catfiles de tous les risques d'une entité et calcule mean / AEP200 / STEC / OEP200."""

    def __init__(self, code: str, folder: Path, unit: float, n_years: int, by_lob: bool = False):
        self.code = code
        self.folder = folder
        self.unit = unit
        self.n_years = n_years
        self.by_lob = by_lob  # True : calcule aussi les métriques par LoB (catfiles uniquement)
        self._summary_rows: list[dict] = []
        self._run_rows: list[dict] = []
        self._lob_strips: dict[str, dict[str, pd.DataFrame]] = {}  # risque -> LoB -> strip

    @property
    def risks(self) -> list[str]:
        return [d.name for d in list_dirs(self.folder)]

    # ------------------------------------------------------------ lignes de tableaux

    def _table_row(self, risk: str, stats: dict, checkpool: str) -> dict:
        return {"Entity": self.code, "risk": risk, **stats, "Checkpool": checkpool}

    def _add_summary(self, risk: str, segment: str, file: str, strip: pd.DataFrame) -> None:
        stats = strip_stats(strip["loss"], strip["max_loss"])
        self._summary_rows.append({"Entity": self.code, "Risk": risk, "segment": segment,
                                   "file": file, **stats})

    def _yearly(self, events: pd.DataFrame, source) -> pd.DataFrame:
        return yearly_strip(events, self.unit, self.n_years, str(source))

    def _add_lobs(self, risk: str, events: pd.DataFrame, source) -> None:
        """Option by_lob : ajoute les strips par LoB de ces événements à ceux du risque."""
        if self.by_lob:
            strips = yearly_lob_strips(events, self.unit, self.n_years, str(source))
            self._lob_strips[risk] = add_lob_strips(self._lob_strips.get(risk, {}), strips,
                                                    self.n_years)

    def _pool(self, pool_paths: list[Path]) -> pd.DataFrame:
        return pool_yearly_strip([read_pool_file(p) for p in pool_paths], self.unit,
                                 self.n_years, ", ".join(map(str, pool_paths)))

    # ------------------------------------------------------------ risque sans segment

    def _flat_risk(self, risk: str, risk_dir: Path) -> tuple[pd.DataFrame, str]:
        """Somme des catfiles du dossier ; remplacée par le pool file s'il existe."""
        print("No sub folder")
        files = list_files(risk_dir, CATFILE_PATTERN)
        strip = zero_strip(self.n_years)
        for path in (f for f in files if not has_tag(f, POOL_TAG)):
            print(path.as_posix())
            events = read_catfile(path)
            yearly = self._yearly(events, path)
            self._add_lobs(risk, events, path)
            strip = add_strip(strip, yearly)
            self._add_summary(risk, ALL_LABEL, path.name, yearly)

        pool_paths = [f for f in files if has_tag(f, POOL_TAG)]
        if not pool_paths:
            print(NO_POOL_FILE)
            return strip, NO_POOL_FILE
        print("POOL FILE")
        pool = self._pool(pool_paths)
        return pool, all_equal(pool, strip)  # le pool file sert au reporting

    # ------------------------------------------------------------ risque avec segments

    def _segmented_risk(self, risk: str, risk_dir: Path) -> pd.DataFrame:
        """Pour chaque run : fusion des segments ; on retient les pool files s'il y en a, sinon la fusion."""
        print("Sub folder")
        segment_dirs = list_dirs(risk_dir)
        strip = zero_strip(self.n_years)
        for run in [d.name for d in list_dirs(segment_dirs[0])]:
            print(run)
            label = f"{risk} run : {run}"

            segment_events = []
            for segment in segment_dirs:
                path = single_catfile(segment / run)
                events = read_catfile(path)
                segment_events.append(events)
                self._add_summary(label, segment.name, path.name, self._yearly(events, path))

            yearly = self._yearly(combine_segments(segment_events), f"{risk_dir}/*/{run}")
            if self.by_lob:  # les runs s'additionnent comme dans le strip du risque
                self._add_lobs(risk, combine_segments_by_lob(segment_events), f"{risk_dir}/*/{run}")
            self._add_summary(label, ALL_LABEL, "", yearly)

            # XL : pool files de tous les segments ; autres entités : seulement du 1er segment
            run_dirs = [s / run for s in segment_dirs] if self.code == XL_ENTITY else segment_dirs[0] / run
            pool_paths = [f for f in list_files(run_dirs) if has_tag(f, POOL_TAG)]

            if pool_paths:
                print("POOL FILE")
                for pool_path in pool_paths:
                    pool = self._pool([pool_path])
                    strip = add_strip(strip, pool)
                    stats = strip_stats(pool["loss"], pool["max_loss"])
                    self._run_rows.append(self._table_row(label, stats, all_equal(pool, yearly)))
            else:
                print(NO_POOL_FILE)
                stats = strip_stats(yearly["loss"], yearly["max_loss"])
                self._run_rows.append(self._table_row(label, stats, NO_POOL))
                strip = add_strip(strip, yearly)
        return strip

    # ------------------------------------------------------------ par LoB

    def _lob_table(self, risks: list[str]) -> pd.DataFrame:
        """Une ligne par (risque, LoB) puis par risque au total, et un bloc Total entité par LoB.
        Calculé sur les catfiles seulement : les pool files n'ont pas de détail par LoB."""
        rows = []
        entity: dict[str, pd.DataFrame] = {}

        def add_rows(risk: str, strips: dict[str, pd.DataFrame]) -> None:
            names = [k for k in strips if k != TOTAL_LABEL] + [TOTAL_LABEL]
            for lob in names:
                strip = strips.get(lob, zero_strip(self.n_years))
                rows.append({"Entity": self.code, "risk": risk, "LoB": lob,
                             **strip_stats(strip["loss"], strip["max_loss"])})

        for risk in risks:
            strips = self._lob_strips.get(risk, {})
            add_rows(risk, strips)
            entity = add_lob_strips(entity, strips, self.n_years)
        add_rows(TOTAL_LABEL, entity)
        return pd.DataFrame(rows, columns=LOB_COLUMNS)

    # ------------------------------------------------------------ entité

    def build(self) -> EntityResult:
        zero_stats = {"mean": 0.0, AEP: 0.0, "STEC": 0.0, OEP: 0.0}
        risks = self.risks
        base_rows = {name: self._table_row(name, zero_stats, NO_POOL_FILE)
                     for name in risks + [TOTAL_LABEL]}
        strips = {"year": zero_strip(self.n_years)["year"].to_numpy()}
        total = zero_strip(self.n_years)

        for risk in risks:
            print("****************")
            print(risk)
            risk_dir = self.folder / risk
            if list_dirs(risk_dir):
                strip = self._segmented_risk(risk, risk_dir)
            else:
                strip, checkpool = self._flat_risk(risk, risk_dir)
                base_rows[risk]["Checkpool"] = checkpool
            strips[risk] = strip["loss"].to_numpy()
            total = add_strip(total, strip)  # OEP Total : plus gros événement tous risques
            base_rows[risk].update(strip_stats(strip["loss"], strip["max_loss"]))
            print("****************")

        strips[TOTAL_LABEL] = total["loss"].to_numpy()
        strips = pd.DataFrame(strips)
        figures = pd.DataFrame({col: strip_stats(strips[col]) for col in strips.columns[1:]})
        base_rows[TOTAL_LABEL].update(strip_stats(total["loss"], total["max_loss"]))

        table = pd.DataFrame(list(base_rows.values()) + self._run_rows, columns=TABLE_COLUMNS)
        return EntityResult(table=table, strips=strips, figures=figures,
                            summary_rows=self._summary_rows,
                            lob_table=self._lob_table(risks) if self.by_lob else None)
