"""Scelta del numero di fattori del DFM, usando solo dati precedenti alla valutazione.

Tre evidenze: criteri di Bai e Ng sul panel mensile, BIC del modello stimato, errore
pseudo fuori campione su una finestra di validazione che termina prima del 2012,
anno da cui parte il backtest della Fase 3.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nowcast.config import SeriesSpec
from nowcast.models.base import build_info, stationary_panel
from nowcast.models.dfm import DFM, bai_ng_ic

SELECTION_END = pd.Timestamp("2011-12-31")
VALIDATION_START = pd.Timestamp("2008-03-31")
GDP_LAG_DAYS = 30
MAX_FACTORS = 6


def selection_info_date() -> pd.Timestamp:
    """Giorno in cui è noto il PIL dell'ultimo trimestre della finestra di selezione."""
    return SELECTION_END + pd.Timedelta(days=GDP_LAG_DAYS)


def information_criteria(observations: pd.DataFrame, specs: list[SeriesSpec]) -> pd.DataFrame:
    info = build_info(observations, specs, selection_info_date())
    panel = stationary_panel(info, info.dfm_transforms)
    balanced = panel[panel.index <= SELECTION_END].dropna()
    return bai_ng_ic(balanced, MAX_FACTORS)


def model_bic(
    observations: pd.DataFrame, specs: list[SeriesSpec], grid: list[tuple[int, int]]
) -> pd.DataFrame:
    """BIC del DFM stimato sulla finestra di selezione, per (fattori, ordine del VAR)."""
    info = build_info(observations, specs, selection_info_date())
    rows = []
    for factors, order in grid:
        estimated = DFM(factors, order).estimate(info, SELECTION_END)
        rows.append(
            {"fattori": factors, "ordine": order, "parametri": len(estimated.params),
             "logL": float(estimated.llf), "BIC": float(estimated.bic)}
        )  # fmt: skip
    return pd.DataFrame(rows).set_index(["fattori", "ordine"])


def validation_errors(
    observations: pd.DataFrame, specs: list[SeriesSpec], factors: int, days_before: int
) -> pd.Series:
    """Errori di nowcast (previsto - realizzato) sui trimestri di validazione."""
    actual = build_info(observations, specs, selection_info_date()).gdp_growth
    quarters = actual[(actual.index >= VALIDATION_START) & (actual.index <= SELECTION_END)].index
    errors = {}
    for quarter in quarters:
        as_of = quarter + pd.Timedelta(days=GDP_LAG_DAYS - days_before)
        info = build_info(observations, specs, as_of)
        errors[quarter] = DFM(factors).nowcast(info, quarter).mean - float(actual[quarter])
    return pd.Series(errors)


def validation_rmse(
    observations: pd.DataFrame, specs: list[SeriesSpec], grid: list[int], horizons: list[int]
) -> pd.DataFrame:
    """RMSE di validazione per numero di fattori (righe) e giorni alla pubblicazione."""
    table = {
        h: {k: float(np.sqrt((validation_errors(observations, specs, k, h) ** 2).mean()))
            for k in grid}
        for h in horizons
    }  # fmt: skip
    return pd.DataFrame(table).rename_axis("fattori")
