"""Benchmark univariati: usano solo la storia del PIL."""

from __future__ import annotations

import pandas as pd

from nowcast.models.ar import fit_ar, forecast_ar
from nowcast.models.base import (
    InfoSet,
    Nowcast,
    Window,
    mask_window,
    quarters_between,
    variant_name,
)


class HistoricalMean:
    """Media storica della crescita t/t."""

    def __init__(self, exclude: Window | None = None) -> None:
        self.exclude = exclude
        self.name = variant_name("media_storica", exclude)

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast:
        sample = mask_window(info.gdp_growth, self.exclude).dropna()
        return Nowcast(self.name, target, float(sample.mean()), float(sample.std(ddof=1)))


class ARBenchmark:
    """AR(p) sul PIL; se manca anche il trimestre precedente prevede più passi avanti."""

    def __init__(self, order: int, exclude: Window | None = None) -> None:
        self.order = order
        self.exclude = exclude
        self.name = variant_name(f"ar{order}", exclude)

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast:
        growth = info.gdp_growth
        fit = fit_ar(mask_window(growth, self.exclude), self.order)
        steps = quarters_between(growth.index[-1], target)
        means, stds = forecast_ar(growth.to_numpy(), fit, steps)
        return Nowcast(self.name, target, float(means[-1]), float(stds[-1]))
