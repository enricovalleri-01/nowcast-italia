"""Bridge equation: indicatori mensili portati a trimestre e regressione sul PIL."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nowcast.models.ar import fit_ar, forecast_ar, select_order
from nowcast.models.base import (
    InfoSet,
    Nowcast,
    Window,
    in_window,
    mask_window,
    months_between,
    variant_name,
)
from nowcast.transforms import apply_transform, monthly_to_quarterly

# Scelti a priori, non sul periodo di valutazione: due indicatori quantitativi con la
# copertura più ampia (industria, consumi) e l'indicatore di fiducia sintetico.
DEFAULT_INDICATORS = ("ip", "retail", "esi")
MAX_AR_ORDER = 6


@dataclass(frozen=True)
class BridgeFit:
    coefs: pd.Series  # "const" più un coefficiente per indicatore
    sigma: float
    regressors: pd.DataFrame  # indicatori trimestrali, compreso il trimestre obiettivo


def rebuild_levels(last_level: float, changes: np.ndarray, kind: str) -> np.ndarray:
    """Inverte la trasformazione: dai valori stazionari previsti ai livelli."""
    if kind == "none":
        return changes
    if kind == "diff":
        return last_level + np.cumsum(changes)
    if kind == "pct_change":
        return last_level * np.cumprod(1 + changes / 100)
    if kind == "log_diff":
        return last_level * np.exp(np.cumsum(changes) / 100)
    raise ValueError(f"trasformazione sconosciuta: {kind}")


def complete_months(
    levels: pd.Series,
    kind: str,
    target: pd.Timestamp,
    exclude: Window | None = None,
) -> pd.Series:
    """Estende la serie in livelli fino alla fine del trimestre obiettivo con un AR."""
    observed = pd.Series(levels.loc[: levels.last_valid_index()].interpolate(limit_area="inside"))
    steps = months_between(observed.index[-1], target)
    if steps <= 0:
        return pd.Series(observed)
    stationary = apply_transform(observed, kind)
    estimation = mask_window(stationary, exclude)
    fit = fit_ar(estimation, select_order(estimation, MAX_AR_ORDER))
    changes, _ = forecast_ar(stationary.to_numpy(), fit, steps)
    future = pd.date_range(observed.index[-1], periods=steps + 1, freq="ME")[1:]
    extension = pd.Series(rebuild_levels(float(observed.iloc[-1]), changes, kind), index=future)
    return pd.Series(pd.concat([observed, extension]))


def quarterly_regressor(levels: pd.Series, kind: str) -> pd.Series:
    """Media trimestrale dei livelli, poi la stessa trasformazione a frequenza trimestrale."""
    return apply_transform(monthly_to_quarterly(levels), kind)


def ols(y: pd.Series, x: pd.DataFrame) -> tuple[pd.Series, float]:
    design = np.column_stack([np.ones(len(x)), x.to_numpy()])
    coefs, *_ = np.linalg.lstsq(design, y.to_numpy(), rcond=None)
    residuals = y.to_numpy() - design @ coefs
    sigma = float(np.sqrt(residuals @ residuals / (len(y) - design.shape[1])))
    return pd.Series(coefs, index=["const", *x.columns]), sigma


class Bridge:
    def __init__(
        self,
        indicators: tuple[str, ...] = DEFAULT_INDICATORS,
        exclude: Window | None = None,
    ) -> None:
        self.indicators = indicators
        self.exclude = exclude
        self.name = variant_name("bridge", exclude)

    def regressors(self, info: InfoSet, target: pd.Timestamp) -> pd.DataFrame:
        columns = {}
        for name in self.indicators:
            kind = info.transforms[name]
            completed = complete_months(info.monthly_levels[name], kind, target, self.exclude)
            columns[name] = quarterly_regressor(completed, kind)
        return pd.DataFrame(columns)

    def fit(self, info: InfoSet, target: pd.Timestamp) -> BridgeFit:
        regressors = self.regressors(info, target)
        sample = regressors.join(info.gdp_growth, how="inner").dropna()
        sample = sample[~in_window(sample.index, self.exclude).to_numpy()]
        coefs, sigma = ols(sample["gdp"], sample[list(self.indicators)])
        return BridgeFit(coefs, sigma, regressors)

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast:
        fit = self.fit(info, target)
        row = fit.regressors.loc[target, list(self.indicators)]
        mean = float(fit.coefs["const"] + (fit.coefs[list(self.indicators)] * row).sum())
        return Nowcast(self.name, target, mean, fit.sigma)
