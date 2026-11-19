from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import NON_LOB_COLS, POOL_TAG, TOTAL_LABEL
from .rcompat import group_sums, has_tag, list_files, row_sums

_SEPARATORS = (",", ";", "\t", "|")


def _detect_sep(path: Path) -> str:
    """Séparateur le plus fréquent de la ligne d'en-tête (fread le détecte automatiquement)."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        header = f.readline()
    counts = {sep: header.count(sep) for sep in _SEPARATORS}
    sep = max(counts, key=counts.get)
    return sep if counts[sep] else ","


def read_csv(path: Path) -> pd.DataFrame:
    """fread(path) puis noms de colonnes en minuscules."""
    df = pd.read_csv(path, sep=_detect_sep(path), encoding="utf-8-sig",
                     float_precision="round_trip")
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _is_character(col: pd.Series) -> bool:
    return col.dtype == object or pd.api.types.is_string_dtype(col)


def read_catfile(path: Path) -> pd.DataFrame:
    """read_classic_Man_Made_catfile : year, eventid, une colonne par LoB et total (somme des LoB)."""
    df = read_csv(path)
    yearid = [c for c in df.columns if "yearid" in c]
    if len(yearid) == 1:
        df = df.rename(columns={yearid[0]: "year"})
    lobs = [c for c in dict.fromkeys(df.columns) if c not in NON_LOB_COLS]
    if lobs and _is_character(df[lobs[0]]):  # décimales avec virgule : "1,5" -> 1.5
        for c in lobs:
            text = df[c].astype("string").str.replace(",", ".", regex=False).str.strip()
            df[c] = pd.to_numeric(text, errors="coerce")
    df["total"] = row_sums(df[lobs].to_numpy(dtype=float))  # NA si une LoB est NA
    return df.drop(columns=[c for c in ("model_id", "modelid") if c in df.columns])


def read_pool_file(path: Path) -> pd.DataFrame:
    return read_csv(path)


def single_catfile(directory: Path) -> Path:
    """Unique fichier non pool_property du dossier (le script R plante s'il n'y en a pas exactement un)."""
    files = [f for f in list_files(directory) if not has_tag(f, POOL_TAG)]
    if len(files) != 1:
        raise ValueError(f"{directory} : {len(files)} fichier(s) hors {POOL_TAG}, "
                         f"1 attendu (le script R plante aussi dans ce cas)")
    return files[0]


def combine_segments(segment_events: list[pd.DataFrame]) -> pd.DataFrame:
    """get_one_run_catfile : fusion complète des segments par (year, eventid), NA -> 0, total = somme des LoB."""
    if len(segment_events) == 1:  # un seul segment : rien à fusionner (le script R plantait dans ce cas)
        return segment_events[0]
    merged = None
    for k, events in enumerate(segment_events):
        events = events.drop(columns="total")
        # noms de LoB rendus uniques (R suffixe .x/.y) : seule leur somme est utilisée
        events = events.rename(columns={c: f"{k}|{c}" for c in events.columns
                                        if c not in ("year", "eventid")})
        if merged is None:
            merged = events
        else:
            merged = (merged.merge(events, on=["year", "eventid"], how="outer")
                      .sort_values(["year", "eventid"], kind="stable")  # merge de data.table trie par clé
                      .fillna(0))
    lobs = [c for c in merged.columns if c not in NON_LOB_COLS]
    merged["total"] = row_sums(merged[lobs].to_numpy(dtype=float))
    return merged


# ---------------------------------------------------------------- stripfiles annuels

def _years(n_years: int) -> pd.RangeIndex:
    return pd.RangeIndex(1, n_years + 1, name="year")


def _check_years(df: pd.DataFrame, n_years: int, source: str) -> pd.DataFrame:
    """Années hors 1..n_years : le script R plante (longueurs incompatibles), on lève une erreur claire."""
    years = pd.to_numeric(df["year"], errors="coerce")
    bad = years.isna() | (years < 1) | (years > n_years)
    if bad.any():
        raise ValueError(f"{source} : {int(bad.sum())} ligne(s) avec une année hors de 1..{n_years}")
    return df.assign(year=years.astype("int64"))


def _group_sum_max(values: pd.Series, keys) -> tuple[pd.Series, pd.Series]:
    """sum() et max() par groupe (clés triées), NA si le groupe contient un NA (comme en R)."""
    grouped = values.groupby(keys, dropna=False, sort=True)
    peak = grouped.max()
    total = pd.Series(group_sums(values.to_numpy(dtype=float), grouped.ngroup().to_numpy(),
                                 grouped.ngroups), index=peak.index)
    has_na = values.isna().groupby(keys, dropna=False, sort=True).any()
    total[has_na] = np.nan
    peak[has_na] = np.nan
    return total, peak


def _strip(values: pd.Series, years_col: pd.Series, unit: float, n_years: int) -> pd.DataFrame:
    loss, max_loss = _group_sum_max(values, years_col)
    years = _years(n_years)
    return pd.DataFrame({
        "year": years.to_numpy(),
        "loss": loss.reindex(years, fill_value=0.0).to_numpy() * unit,
        "max_loss": max_loss.reindex(years, fill_value=0.0).to_numpy() * unit,
    })


def yearly_strip(events: pd.DataFrame, unit: float, n_years: int, source: str = "") -> pd.DataFrame:
    """get_yearly_catfile : par année, loss = somme et max_loss = plus gros événement, x unité."""
    events = _check_years(events, n_years, source)
    return _strip(events["total"], events["year"], unit, n_years)


# ---------------------------------------------------------------- stripfiles par LoB (option by_lob)

def lob_columns(events: pd.DataFrame) -> list[str]:
    return [c for c in events.columns if c not in NON_LOB_COLS and c != "total"]


def combine_segments_by_lob(segment_events: list[pd.DataFrame]) -> pd.DataFrame:
    """Comme combine_segments, mais en gardant les LoB : une même LoB est sommée entre segments
    pour un même (year, eventid) ; événement ou LoB absent d'un segment = 0."""
    if len(segment_events) == 1:
        return segment_events[0]
    stacked = pd.concat([e.drop(columns="total") for e in segment_events],
                        ignore_index=True, sort=False)
    merged = stacked.groupby(["year", "eventid"], sort=True).sum().reset_index()
    lobs = lob_columns(merged)
    merged["total"] = row_sums(merged[lobs].to_numpy(dtype=float))
    return merged


def yearly_lob_strips(events: pd.DataFrame, unit: float, n_years: int,
                      source: str = "") -> dict[str, pd.DataFrame]:
    """Un strip (year, loss, max_loss) par LoB, plus TOTAL_LABEL calculé sur le total par événement
    (son max_loss est donc le plus gros événement toutes LoB confondues)."""
    events = _check_years(events, n_years, source)
    strips = {lob: _strip(events[lob], events["year"], unit, n_years) for lob in lob_columns(events)}
    strips[TOTAL_LABEL] = _strip(events["total"], events["year"], unit, n_years)
    return strips


def add_lob_strips(acc: dict[str, pd.DataFrame], other: dict[str, pd.DataFrame],
                   n_years: int) -> dict[str, pd.DataFrame]:
    """add_strip LoB par LoB ; une LoB absente d'un côté vaut 0."""
    acc = dict(acc)
    for lob, strip in other.items():
        acc[lob] = add_strip(acc[lob] if lob in acc else zero_strip(n_years), strip)
    return acc


def pool_yearly_strip(pool_files: list[pd.DataFrame], unit: float, n_years: int,
                      source: str = "") -> pd.DataFrame:
    """get_pool_tmp_risk_file : pertes annuelles cumulées et max annuel des pool files, x unité."""
    years = _years(n_years)
    loss, max_loss = np.zeros(n_years), np.zeros(n_years)
    for pool in pool_files:
        pool = _check_years(pool, n_years, source)
        event_loss, _ = _group_sum_max(pool["loss"], [pool["year"], pool["eventid"]])
        annual, peak = _group_sum_max(event_loss, event_loss.index.get_level_values("year"))
        loss = loss + annual.reindex(years, fill_value=0.0).to_numpy()
        max_loss = np.maximum(max_loss, peak.reindex(years, fill_value=0.0).to_numpy())
    return pd.DataFrame({"year": years.to_numpy(), "loss": loss * unit, "max_loss": max_loss * unit})


def zero_strip(n_years: int) -> pd.DataFrame:
    years = _years(n_years)
    return pd.DataFrame({"year": years.to_numpy(), "loss": np.zeros(n_years),
                         "max_loss": np.zeros(n_years)})


def add_strip(strip: pd.DataFrame, other: pd.DataFrame) -> pd.DataFrame:
    """loss additionnées, max_loss = pmax des deux."""
    return strip.assign(loss=strip["loss"].to_numpy() + other["loss"].to_numpy(),
                        max_loss=np.maximum(strip["max_loss"].to_numpy(),
                                            other["max_loss"].to_numpy()))
