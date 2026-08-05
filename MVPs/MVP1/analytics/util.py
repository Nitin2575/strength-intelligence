"""Small shared numeric helpers."""
from __future__ import annotations

from typing import Sequence


def pct_change(start: float | None, end: float | None) -> float | None:
    if start in (None, 0) or end is None:
        return None
    return 100.0 * (end - start) / start


def round_or_none(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def mean_or_none(values: Sequence[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def pearson_r(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation. Returns None when undefined (n<3 or no spread)."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denom = (sum(a * a for a in dx) ** 0.5) * (sum(b * b for b in dy) ** 0.5)
    if denom == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


def ols_slope(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Least-squares fit; returns (slope, intercept). Flat line if x has no spread."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    return slope, mean_y - slope * mean_x
