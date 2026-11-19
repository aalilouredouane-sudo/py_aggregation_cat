"""Compare fichier par fichier les sorties du script R et du script Python, et écrit un rapport Excel.

Usage : renseigner la section CONFIGURATION ci-dessous (dossiers R / Python, rapport, tolérances), puis
    python tests/compare_outputs.py

Fichiers comparés : tous les .csv et .xlsx présents dans l'un ou l'autre dossier (même nom).
- CSV  : comparés comme une table.
- XLSX : chaque feuille est comparée (Gross_STEC, Local_AAL_strips, ...).
Pour chaque table : forme, noms de colonnes, puis cellule par cellule
(numérique avec tolérance, texte à l'identique ; NA == NA).

Rapport Excel (écrit dans REPORT_PATH) :
- Synthese : paramètres du test + une ligne par fichier / feuille avec son statut
- Colonnes : une ligne par colonne comparée (type, nb d'écarts, écarts max)
- Ecarts   : le détail des cellules différentes (limité à MAX_DETAILS par colonne)

Code de sortie : 0 si tout est identique, 1 sinon.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ================================================================ CONFIGURATION
R_DIR = Path("/Users/waelaalilou/Documents/work/axa/o_aggregation_cat_R")  # sorties du script R
PY_DIR = Path("/Users/waelaalilou/Documents/work/axa/o_aggregation_cat_PY")  # sorties du script Python
REPORT_PATH = Path("/Users/waelaalilou/Documents/work/axa/rapport_comparaison_R_Python.xlsx")  # rapport Excel
RTOL = 1e-9  # tolérance relative (R = référence)
ATOL = 1e-6  # tolérance absolue
MAX_DETAILS = 1000  # nb max de cellules détaillées par colonne dans l'onglet Ecarts
# ================================================================

EXTENSIONS = {".csv", ".xlsx"}
CONSOLE_EXAMPLES = 10  # nombre de cellules différentes affichées en console par colonne

OK, DIFF, MISSING = "OK", "ECART", "MANQUANT"


# ---------------------------------------------------------------- chargement

def load_tables(path: Path) -> dict[str, pd.DataFrame]:
    """Toutes les tables d'un fichier, lues en texte brut : {nom_feuille: table}."""
    if path.suffix == ".csv":
        return {"csv": pd.read_csv(path, dtype=str, keep_default_na=False)}
    return pd.read_excel(path, sheet_name=None, dtype=object, header=0)


def _is_unnamed(name) -> bool:
    """Colonne sans nom : 'Unnamed: 0' (pandas), '...1' (readxl), '' ou None."""
    s = "" if name is None else str(name).strip()
    return s == "" or s.startswith("Unnamed:") or (s.startswith("...") and s[3:].isdigit())


def _normalize_text(value) -> str | None:
    """Valeur -> texte comparable ; vide / NA / NaN -> None ; booléens -> TRUE / FALSE."""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return "TRUE" if value else "FALSE"
    s = str(value).strip()
    if s in ("", "NA", "NaN", "nan", "None", "<NA>"):
        return None
    if s.upper() in ("TRUE", "FALSE"):
        return s.upper()
    return s


def _as_numeric(col: pd.Series) -> pd.Series | None:
    """Colonne numérique si toutes ses valeurs non vides sont des nombres, sinon None."""
    text = col.map(_normalize_text)
    num = pd.to_numeric(text, errors="coerce")
    if (num.isna() & text.notna()).any():
        return None
    return num.astype(float)


# ---------------------------------------------------------------- résultats

@dataclass
class CellDiff:
    row: int  # numéro de ligne tel qu'affiché dans Excel / le CSV (en-tête = ligne 1)
    r_value: object
    py_value: object
    abs_diff: float | None = None
    rel_diff: float | None = None


@dataclass
class ColumnResult:
    name: str
    kind: str  # "numérique" ou "texte"
    n_cells: int
    n_diff: int = 0
    max_abs: float | None = None
    max_rel: float | None = None
    diffs: list[CellDiff] = field(default_factory=list)


@dataclass
class TableResult:
    file: str
    sheet: str
    shape_r: tuple[int, int] | None = None
    shape_py: tuple[int, int] | None = None
    problems: list[str] = field(default_factory=list)  # écarts de structure
    missing: bool = False  # fichier ou feuille absent d'un côté
    columns: list[ColumnResult] = field(default_factory=list)

    @property
    def n_cells(self) -> int:
        return sum(c.n_cells for c in self.columns)

    @property
    def n_diff(self) -> int:
        return sum(c.n_diff for c in self.columns)

    @property
    def max_abs(self) -> float | None:
        vals = [c.max_abs for c in self.columns if c.max_abs is not None]
        return max(vals) if vals else None

    @property
    def max_rel(self) -> float | None:
        vals = [c.max_rel for c in self.columns if c.max_rel is not None]
        return max(vals) if vals else None

    @property
    def status(self) -> str:
        if self.missing:
            return MISSING
        return OK if not self.problems and self.n_diff == 0 else DIFF


def _finite_max(values: pd.Series) -> float | None:
    values = values.replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.max()) if len(values) else None


# ---------------------------------------------------------------- comparaison

def compare_tables(file: str, sheet: str, r: pd.DataFrame, py: pd.DataFrame,
                   rtol: float, atol: float, max_details: int) -> TableResult:
    res = TableResult(file, sheet, r.shape, py.shape)

    if r.shape != py.shape:
        res.problems.append(f"forme différente : R {r.shape} vs Python {py.shape}")

    r_cols = ["" if _is_unnamed(c) else str(c) for c in r.columns]
    py_cols = ["" if _is_unnamed(c) else str(c) for c in py.columns]
    if r_cols != py_cols:
        res.problems.append(f"colonnes différentes : R {r_cols} vs Python {py_cols}")

    # comparaison cellule par cellule sur la partie commune (par position)
    n_rows = min(len(r), len(py))
    for j in range(min(r.shape[1], py.shape[1])):
        label = r_cols[j] or f"<col {j + 1}>"
        rc = r.iloc[:n_rows, j].reset_index(drop=True)
        pc = py.iloc[:n_rows, j].reset_index(drop=True)
        rn, pn = _as_numeric(rc), _as_numeric(pc)

        if rn is not None and pn is not None:
            col = ColumnResult(label, "numérique", n_rows)
            both_na = (rn.isna() & pn.isna()).to_numpy()
            close = np.isclose(pn.to_numpy(), rn.to_numpy(), rtol=rtol, atol=atol)  # R = référence
            diff = ~(close | both_na)
            abs_diff = (rn - pn).abs()
            rel_diff = abs_diff / rn.abs().where(rn != 0)
            col.max_abs = _finite_max(abs_diff)
            col.max_rel = _finite_max(rel_diff)
            idx = np.flatnonzero(diff)
            col.n_diff = len(idx)
            col.diffs = [CellDiff(i + 2, _num(rn[i]), _num(pn[i]), _num(abs_diff[i]), _num(rel_diff[i]))
                         for i in idx[:max_details]]
        else:
            col = ColumnResult(label, "texte", n_rows)
            rt, pt = rc.map(_normalize_text), pc.map(_normalize_text)
            diff = ~((rt == pt) | (rt.isna() & pt.isna())).to_numpy()
            idx = np.flatnonzero(diff)
            col.n_diff = len(idx)
            col.diffs = [CellDiff(i + 2, rt[i], pt[i]) for i in idx[:max_details]]
        res.columns.append(col)
    return res


def _num(x) -> float | None:
    x = float(x)
    return None if np.isnan(x) or np.isinf(x) else x


def compare_files(name: str, r_path: Path | None, py_path: Path | None,
                  rtol: float, atol: float, max_details: int) -> list[TableResult]:
    if py_path is None:
        return [TableResult(name, "", missing=True, problems=["fichier absent côté Python"])]
    if r_path is None:
        return [TableResult(name, "", missing=True, problems=["fichier absent côté R"])]

    r_tables, py_tables = load_tables(r_path), load_tables(py_path)
    results = []
    for sheet in dict.fromkeys([*r_tables, *py_tables]):
        if sheet not in py_tables:
            results.append(TableResult(name, sheet, shape_r=r_tables[sheet].shape, missing=True,
                                       problems=["feuille absente côté Python"]))
        elif sheet not in r_tables:
            results.append(TableResult(name, sheet, shape_py=py_tables[sheet].shape, missing=True,
                                       problems=["feuille absente côté R"]))
        else:
            results.append(compare_tables(name, sheet, r_tables[sheet], py_tables[sheet],
                                          rtol, atol, max_details))
    if list(r_tables) != list(py_tables) and set(r_tables) == set(py_tables) and results:
        results[0].problems.append(f"ordre des feuilles : R {list(r_tables)} vs Python {list(py_tables)}")
    return results


# ---------------------------------------------------------------- console

def print_results(results: list[TableResult]) -> None:
    by_file: dict[str, list[TableResult]] = {}
    for res in results:
        by_file.setdefault(res.file, []).append(res)
    for file, tables in by_file.items():
        statuses = {t.status for t in tables}
        status = MISSING if MISSING in statuses else DIFF if DIFF in statuses else OK
        print(f"[{status:<8}] {file}")
        for t in tables:
            prefix = f"    [{t.sheet}] " if t.sheet else "    "
            for p in t.problems:
                print(prefix + p)
            for c in t.columns:
                if c.n_diff:
                    extra = (f" (écart abs max {c.max_abs:.6g}, écart rel max {c.max_rel:.6g})"
                             if c.kind == "numérique" and c.max_abs is not None and c.max_rel is not None else "")
                    print(f"{prefix}colonne '{c.name}' ({c.kind}) : {c.n_diff} cellule(s) différente(s){extra}")
                    for d in c.diffs[:CONSOLE_EXAMPLES]:
                        print(f"          ligne {d.row}: R={d.r_value!r}  Python={d.py_value!r}")


# ---------------------------------------------------------------- rapport Excel

FILL = {OK: PatternFill("solid", fgColor="C6EFCE"),
        DIFF: PatternFill("solid", fgColor="FFC7CE"),
        MISSING: PatternFill("solid", fgColor="FFEB9C")}
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _write_table(ws, start_row: int, headers: list[str], rows: list[list], status_col: int | None = None,
                 number_formats: dict[int, str] | None = None) -> None:
    for j, h in enumerate(headers, 1):
        cell = ws.cell(start_row, j, h)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for i, row in enumerate(rows, start_row + 1):
        for j, v in enumerate(row, 1):
            cell = ws.cell(i, j, v)
            if number_formats and j in number_formats and isinstance(v, (int, float)):
                cell.number_format = number_formats[j]
        if status_col is not None:
            ws.cell(i, status_col).fill = FILL.get(row[status_col - 1], PatternFill())
    last = start_row + max(len(rows), 1)
    ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{last}"
    ws.freeze_panes = ws.cell(start_row + 1, 1)


def _autosize(ws, max_width: int = 60) -> None:
    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                widths[cell.column] = max(widths.get(cell.column, 0), len(str(cell.value)))
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = min(max(w + 2, 10), max_width)


def write_report(path: Path, results: list[TableResult], args: argparse.Namespace) -> None:
    wb = Workbook()

    # --- Synthese
    ws = wb.active
    ws.title = "Synthese"
    n_ok = sum(r.status == OK for r in results)
    params = [
        ("Rapport de comparaison R vs Python", None),
        ("Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Dossier R", str(args.r_dir.resolve())),
        ("Dossier Python", str(args.py_dir.resolve())),
        ("Tolérance relative (rtol)", args.rtol),
        ("Tolérance absolue (atol)", args.atol),
        ("Règle (R = référence)", "|Python - R| <= atol + rtol * |R|  ;  écart rel = |Python - R| / |R|"),
        ("Tables comparées", len(results)),
        ("Tables OK", n_ok),
        ("Tables en écart / manquantes", len(results) - n_ok),
        ("Résultat global", OK if n_ok == len(results) else DIFF),
    ]
    for i, (k, v) in enumerate(params, 1):
        ws.cell(i, 1, k).font = Font(bold=True)
        ws.cell(i, 2, v)
    ws.cell(1, 1).font = Font(bold=True, size=14)
    ws.cell(len(params), 2).fill = FILL[params[-1][1]]
    ws.cell(len(params), 2).font = Font(bold=True)

    start = len(params) + 2
    headers = ["Fichier", "Feuille", "Statut", "Lignes R", "Lignes Python", "Colonnes R", "Colonnes Python",
               "Cellules comparées", "Cellules en écart", "Écart abs max", "Écart rel max", "Commentaire"]
    rows = [[r.file, r.sheet, r.status,
             r.shape_r[0] if r.shape_r else None, r.shape_py[0] if r.shape_py else None,
             r.shape_r[1] if r.shape_r else None, r.shape_py[1] if r.shape_py else None,
             r.n_cells, r.n_diff, r.max_abs, r.max_rel, " | ".join(r.problems) or None]
            for r in results]
    _write_table(ws, start, headers, rows, status_col=3,
                 number_formats={10: "0.000E+00", 11: "0.000E+00"})
    _autosize(ws)
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = max(ws.column_dimensions["B"].width, 20)

    # --- Colonnes
    ws = wb.create_sheet("Colonnes")
    headers = ["Fichier", "Feuille", "Colonne", "Type", "Statut", "Cellules comparées",
               "Cellules en écart", "Écart abs max", "Écart rel max"]
    rows = [[r.file, r.sheet, c.name, c.kind, OK if c.n_diff == 0 else DIFF,
             c.n_cells, c.n_diff, c.max_abs, c.max_rel]
            for r in results for c in r.columns]
    _write_table(ws, 1, headers, rows, status_col=5, number_formats={8: "0.000E+00", 9: "0.000E+00"})
    _autosize(ws)

    # --- Ecarts
    ws = wb.create_sheet("Ecarts")
    headers = ["Fichier", "Feuille", "Colonne", "Ligne", "Valeur R", "Valeur Python",
               "Écart abs", "Écart rel"]
    rows = [[r.file, r.sheet, c.name, d.row, d.r_value, d.py_value, d.abs_diff, d.rel_diff]
            for r in results for c in r.columns for d in c.diffs]
    truncated = [(r, c) for r in results for c in r.columns if c.n_diff > len(c.diffs)]
    _write_table(ws, 1, headers, rows, number_formats={7: "0.000E+00", 8: "0.000E+00"})
    if truncated:
        note = len(rows) + 3
        ws.cell(note, 1, f"Détail limité à {args.max_details} cellules par colonne "
                         f"(MAX_DETAILS) ; colonnes tronquées :").font = Font(italic=True)
        for k, (r, c) in enumerate(truncated, 1):
            ws.cell(note + k, 1, f"{r.file} / {r.sheet} / {c.name} : {c.n_diff} écarts au total")
    _autosize(ws)

    wb.save(path)


# ---------------------------------------------------------------- main

def list_outputs(folder: Path) -> dict[str, Path]:
    return {p.name: p for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith("~$")}


def main(r_dir: Path = R_DIR, py_dir: Path = PY_DIR, report: Path = REPORT_PATH,
         rtol: float = RTOL, atol: float = ATOL, max_details: int = MAX_DETAILS) -> int:
    for label, folder in (("R", r_dir), ("Python", py_dir)):
        if not folder.is_dir():
            print(f"Dossier des sorties {label} introuvable : {folder}")
            return 2
    args = argparse.Namespace(r_dir=r_dir, py_dir=py_dir, rtol=rtol, atol=atol, max_details=max_details)

    r_files, py_files = list_outputs(args.r_dir), list_outputs(args.py_dir)
    results: list[TableResult] = []
    for name in sorted(set(r_files) | set(py_files)):
        results += compare_files(name, r_files.get(name), py_files.get(name),
                                 args.rtol, args.atol, args.max_details)

    print_results(results)
    write_report(report, results, args)

    n_ok = sum(r.status == OK for r in results)
    print(f"\n{n_ok}/{len(results)} table(s) identique(s) (rtol={args.rtol}, atol={args.atol})")
    print(f"Rapport Excel : {report}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
