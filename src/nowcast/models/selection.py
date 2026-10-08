"""Scelta della specificazione del DFM sulla finestra di sviluppo.

I dati fino al 2011 sono serviti a sviluppare il modello: su di essi sono stati scelti
il numero di fattori e la trasformazione delle fiducie. Gli errori calcolati qui non
sono quindi una verifica indipendente; quella è il backtest dal 2012 in poi.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nowcast.config import SeriesSpec
from nowcast.data.vintages import publication_date
from nowcast.models.base import build_info, stationary_panel
from nowcast.models.dfm import DFM, bai_ng_ic

DEVELOPMENT_END = pd.Timestamp("2011-12-31")
DEVELOPMENT_ERRORS_START = pd.Timestamp("2008-03-31")
MAX_FACTORS = 6


def development_info_date(observations: pd.DataFrame) -> pd.Timestamp:
    """Giorno di pubblicazione del PIL dell'ultimo trimestre della finestra di sviluppo."""
    return publication_date(observations, "gdp", DEVELOPMENT_END)


def information_criteria(observations: pd.DataFrame, specs: list[SeriesSpec]) -> pd.DataFrame:
    info = build_info(observations, specs, development_info_date(observations))
    panel = stationary_panel(info, info.dfm_transforms)
    balanced = panel[panel.index <= DEVELOPMENT_END].dropna()
    return bai_ng_ic(balanced, MAX_FACTORS)


def model_bic(
    observations: pd.DataFrame, specs: list[SeriesSpec], grid: list[tuple[int, int]]
) -> pd.DataFrame:
    """BIC del DFM stimato sulla finestra di sviluppo, per (fattori, ordine del VAR)."""
    info = build_info(observations, specs, development_info_date(observations))
    rows = []
    for factors, order in grid:
        results = DFM(factors, order).estimate(info, DEVELOPMENT_END).results
        rows.append(
            {"fattori": factors, "ordine": order, "parametri": len(results.params),
             "logL": float(results.llf), "BIC": float(results.bic)}
        )  # fmt: skip
    return pd.DataFrame(rows).set_index(["fattori", "ordine"])


def development_errors(
    observations: pd.DataFrame, specs: list[SeriesSpec], factors: int, days_before: int
) -> pd.Series:
    """Errori di nowcast (previsto - realizzato) a `days_before` giorni dalla pubblicazione."""
    actual = build_info(observations, specs, development_info_date(observations)).gdp_growth
    window = (actual.index >= DEVELOPMENT_ERRORS_START) & (actual.index <= DEVELOPMENT_END)
    errors = {}
    for quarter in actual[window].index:
        as_of = publication_date(observations, "gdp", quarter) - pd.Timedelta(days=days_before)
        info = build_info(observations, specs, as_of)
        errors[quarter] = DFM(factors).nowcast(info, quarter).mean - float(actual[quarter])
    return pd.Series(errors)


def development_rmse(
    observations: pd.DataFrame, specs: list[SeriesSpec], grid: list[int], horizons: list[int]
) -> pd.DataFrame:
    """RMSE sulla finestra di sviluppo per numero di fattori (righe) e orizzonte (colonne)."""
    table = {
        h: {k: float(np.sqrt((development_errors(observations, specs, k, h) ** 2).mean()))
            for k in grid}
        for h in horizons
    }  # fmt: skip
    return pd.DataFrame(table).rename_axis("fattori")
