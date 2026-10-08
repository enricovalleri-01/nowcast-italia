"""Benchmark univariati: usano solo la storia del PIL."""

from __future__ import annotations

import pandas as pd

from nowcast.models.ar import fit_ar, forecast_ar
from nowcast.models.base import InfoSet, Nowcast, mask_covid, quarters_between


class HistoricalMean:
    """Media storica della crescita t/t."""

    name = "media_storica"

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast:
        sample = mask_covid(info.gdp_growth).dropna()
        return Nowcast(self.name, target, float(sample.mean()), float(sample.std(ddof=1)))


class ARBenchmark:
    """AR(p) sul PIL; se manca anche il trimestre precedente prevede più passi avanti."""

    def __init__(self, order: int) -> None:
        self.order = order
        self.name = f"ar{order}"

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast:
        growth = info.gdp_growth
        fit = fit_ar(mask_covid(growth), self.order)
        steps = quarters_between(growth.index[-1], target)
        means, stds = forecast_ar(growth.to_numpy(), fit, steps)
        return Nowcast(self.name, target, float(means[-1]), float(stds[-1]))
