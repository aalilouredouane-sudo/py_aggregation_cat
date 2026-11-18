from __future__ import annotations

import math

import numpy as np

from .config import AEP, OEP, RANK
from .rcompat import r_mean


def xth_largest(values, rank: int = RANK) -> float:
    """sort(values, decreasing = T)[rank] : les NA sont écartés, NA s'il y a moins de rank valeurs."""
    x = np.asarray(values, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < rank:
        return math.nan
    return float(np.partition(x, len(x) - rank)[len(x) - rank])


def strip_stats(annual, max_event=None) -> dict[str, float]:
    """Moyenne, AEP200, STEC (= AEP200 - moyenne) et, si max_event est fourni, OEP200."""
    mean = r_mean(annual)
    aep = xth_largest(annual)
    stats = {"mean": mean, AEP: aep, "STEC": aep - mean}
    if max_event is not None:
        stats[OEP] = xth_largest(max_event)
    return stats
