"""Comportements de R reproduits à l'identique : sommes et moyennes, tri des dossiers, list.files,
as.character, all.equal, fwrite."""
from __future__ import annotations

import math
import os
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

# Ordre des espaces et de la ponctuation dans la collation ICU, utilisée par R pour trier les fichiers
_PUNCTUATION_ORDER = "\t\n\r _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
ALL_EQUAL_TOLERANCE = math.sqrt(np.finfo(float).eps)  # sqrt(.Machine$double.eps)


# ---------------------------------------------------------------- sommes et moyennes de R
# R accumule sum(), rowSums() et mean() en long double : 80 bits sous Windows (résultat quasi exact,
# reproduit ici par une somme compensée), 64 bits sur Mac Apple Silicon (somme séquentielle).

def _two_sum(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Somme a + b et son erreur d'arrondi exacte (algorithme TwoSum de Knuth)."""
    s = a + b
    bb = s - a
    return s, (a - (s - bb)) + (b - bb)


def _finish(acc: np.ndarray, comp: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.where(np.isfinite(acc), acc + comp, acc)


def row_sums(matrix: np.ndarray) -> np.ndarray:
    """rowSums() : somme de chaque ligne, colonnes prises dans l'ordre."""
    acc = np.zeros(matrix.shape[0])
    comp = np.zeros(matrix.shape[0])
    for j in range(matrix.shape[1]):
        if config.R_LONG_DOUBLE:
            acc, err = _two_sum(acc, matrix[:, j])
            comp += err
        else:
            acc = acc + matrix[:, j]
    return _finish(acc, comp) if config.R_LONG_DOUBLE else acc


def group_sums(values: np.ndarray, codes: np.ndarray, n_groups: int) -> np.ndarray:
    """sum() par groupe (codes 0..n_groups-1), valeurs additionnées dans l'ordre des lignes."""
    order = np.argsort(codes, kind="stable")
    values = values[order]
    counts = np.bincount(codes, minlength=n_groups)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    by_size = np.argsort(-counts, kind="stable")  # groupes du plus grand au plus petit
    neg_sizes = -counts[by_size]
    acc, comp = np.zeros(n_groups), np.zeros(n_groups)
    for k in range(counts.max() if n_groups else 0):  # k-ième valeur de chaque groupe
        groups = by_size[:np.searchsorted(neg_sizes, -k, side="left")]
        x = values[starts[groups] + k]
        if config.R_LONG_DOUBLE:
            acc[groups], err = _two_sum(acc[groups], x)
            comp[groups] += err
        else:
            acc[groups] += x
    return _finish(acc, comp) if config.R_LONG_DOUBLE else acc


def r_sum(values) -> float:
    """sum() d'un vecteur."""
    x = np.asarray(values, dtype=float)
    if len(x) == 0:
        return 0.0
    if config.R_LONG_DOUBLE and np.isfinite(x).all():
        return math.fsum(x)
    return float(np.cumsum(x)[-1])


def _exact_mean(x: np.ndarray) -> float:
    """Moyenne exacte arrondie au double le plus proche."""
    mantissa, exponent = np.frexp(x)
    ints = (mantissa * 2.0 ** 53).astype(np.int64)
    exponent = exponent.astype(np.int64) - 53
    e_min = int(exponent.min())
    total = sum(int(m) << int(e - e_min) for m, e in zip(ints, exponent) if m)
    n = len(x)
    return total / (n << -e_min) if e_min < 0 else (total << e_min) / n


def r_mean(values) -> float:
    """mean() : somme / n puis correction par un second passage sur les écarts."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n == 0:
        return math.nan
    if config.R_LONG_DOUBLE and np.isfinite(x).all():
        return _exact_mean(x)
    mean = np.cumsum(x)[-1] / n
    if math.isfinite(mean):
        mean += np.cumsum(x - mean)[-1] / n
    return float(mean)


# ---------------------------------------------------------------- tri et listing des fichiers

def _primary_weight(ch: str) -> int:
    i = _PUNCTUATION_ORDER.find(ch)
    if i >= 0:
        return i
    base = unicodedata.normalize("NFD", ch)[0]
    if base.isdigit():
        return 1000 + ord(base)
    if base.isalpha():
        return 2000 + ord(base.lower())
    return 100000 + ord(ch)


def sort_key(path: Path | str) -> tuple:
    """Ordre alphabétique de R (sans casse, ponctuation avant chiffres et lettres, minuscule avant majuscule)."""
    s = path if isinstance(path, str) else path.as_posix()
    return tuple(_primary_weight(c) for c in s), tuple(c.isupper() for c in s)


def list_dirs(path: Path, recursive: bool = False) -> list[Path]:
    """list.dirs(path, recursive) sans le dossier lui-même ; vide si le dossier n'existe pas."""
    if not path.is_dir():
        return []
    candidates = path.rglob("*") if recursive else path.iterdir()
    return sorted((p for p in candidates if p.is_dir()), key=sort_key)


def list_files(paths: Path | list[Path], pattern: str | None = None) -> list[Path]:
    """list.files(paths, pattern, full.names = T) : fichiers et dossiers non cachés, triés sur le chemin complet."""
    if isinstance(paths, Path):
        paths = [paths]
    found = []
    for path in paths:
        if not path.is_dir():
            continue
        found += [p for p in path.iterdir()
                  if not p.name.startswith(".")
                  and (pattern is None or re.search(pattern, p.name))]
    return sorted(found, key=sort_key)


def has_tag(path: Path, tag: str) -> bool:
    """grep(path, pattern = tag) : le motif est cherché dans le chemin complet."""
    return tag in path.as_posix()


# ---------------------------------------------------------------- format des nombres

def _significant_digits(x: float, digits: int) -> tuple[int, int]:
    """(nombre de chiffres significatifs utiles, exposant décimal) de x arrondi à `digits` chiffres."""
    if config.R_LONG_DOUBLE:  # arrondi décimal exact (R en long double 80 bits)
        mantissa, exponent = f"{abs(x):.{digits - 1}e}".split("e")
        return len(mantissa.replace(".", "").rstrip("0")) or 1, int(exponent)
    # R en double 64 bits : x est ramené à un entier de `digits` chiffres par une multiplication en double
    r = abs(x)
    kp = math.floor(math.log10(r)) - digits + 1
    if abs(kp) < 23:
        r_prec = r / 10.0 ** kp if kp > 0 else r * 10.0 ** -kp
    else:
        r_prec = r / 10.0 ** kp
    if r_prec < 10.0 ** (digits - 1):
        r_prec *= 10.0
        kp -= 1
    alpha = float(round(r_prec))  # arrondi au pair le plus proche, comme nearbyint
    nsig = digits
    for _ in range(digits):
        alpha /= 10.0
        if alpha != math.floor(alpha):
            break
        nsig -= 1
    if nsig == 0:
        nsig, kp = 1, kp + 1
    return nsig, kp + digits - 1


def format_number(x: float, digits: int = 15) -> str | None:
    """as.character(x) (digits = 15) ou format(x) (digits = 7) ; None pour NA."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, (bool, np.bool_)):
        return "TRUE" if x else "FALSE"
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    x = float(x)
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "0"
    nsig, exponent = _significant_digits(x, digits)
    mantissa, _ = f"{x:.{nsig - 1}e}".split("e")
    scientific = f"{mantissa}e{'-' if exponent < 0 else '+'}{abs(exponent):02d}"
    fixed = f"{x:.{max(0, nsig - 1 - exponent)}f}"
    return fixed if len(fixed) <= len(scientific) else scientific


# ---------------------------------------------------------------- all.equal

def _all_equal_numeric(target: np.ndarray, current: np.ndarray) -> str | None:
    """all.equal.numeric de R : None si égal, sinon le message de différence."""
    if len(target) != len(current):
        return f"Lengths ({len(target)}, {len(current)}) differ"
    na_target, na_current = np.isnan(target), np.isnan(current)
    if (na_target != na_current).any():
        return (f"'is.NA' value mismatch: {int(na_current.sum())} in current "
                f"{int(na_target.sum())} in target")
    same = na_target | (target == current)
    if same.all():
        return None
    target, current = target[~same], current[~same]
    n = len(target)
    scale = r_sum(np.abs(target) / n)
    if math.isfinite(scale) and scale > ALL_EQUAL_TOLERANCE:
        what = "relative"
    else:
        scale, what = 1.0, "absolute"
    xy = r_sum(np.abs(target - current) / (n * scale))
    if math.isnan(xy) or xy > ALL_EQUAL_TOLERANCE:
        return f"Mean {what} difference: {format_number(xy, digits=7)}"
    return None


def all_equal(target: pd.DataFrame, current: pd.DataFrame) -> str:
    """as.character(all.equal(target, current)) pour deux data.table numériques : "TRUE" ou le 1er écart."""
    if len(target) != len(current):
        return "Different number of rows"
    if sorted(target.columns) != sorted(current.columns):
        return "Different column names"
    if list(target.columns) != list(current.columns):
        return "Different column order"
    for col in target.columns:
        msg = _all_equal_numeric(target[col].to_numpy(dtype=float),
                                 current[col].to_numpy(dtype=float))
        if msg is not None:
            return f"Column '{col}': {msg}"
    return "TRUE"


# ---------------------------------------------------------------- fwrite

def _csv_field(value) -> str:
    if isinstance(value, str):
        if value == "":
            return '""'  # fwrite met les chaînes vides entre guillemets pour les distinguer de NA
        if any(c in value for c in ',"\n\r'):
            return '"' + value.replace('"', '""') + '"'
        return value
    text = format_number(value)
    return "" if text is None else text


def fwrite(table: pd.DataFrame, path: Path) -> None:
    """fwrite(table, path) : séparateur virgule, nombres sur 15 chiffres significatifs, NA vide."""
    lines = [",".join(_csv_field(str(c)) for c in table.columns)]
    lines += [",".join(_csv_field(v) for v in row)
              for row in table.itertuples(index=False, name=None)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(os.linesep.join(lines) + os.linesep)
