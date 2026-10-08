"""Intervalli di previsione calibrati sugli errori del backtest.

Gli intervalli non usano le deviazioni standard dei modelli: sono i quantili empirici
degli errori commessi nel backtest dallo stesso modello allo stesso orizzonte, esclusi
i trimestri del 2020-2021. Valgono quindi per periodi ordinari, non per shock di quella
portata.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nowcast.evaluation.backtest import HORIZONS, OK
from nowcast.evaluation.metrics import COVID_YEARS

LEVELS = (0.5, 0.8)
EXCLUDED = COVID_YEARS
EXCLUSION_NOTE = "Intervalli calcolati sugli errori del backtest, esclusi i trimestri 2020-2021."


def tail_probabilities(levels: tuple[float, ...] = LEVELS) -> list[float]:
    """Quantili che delimitano gli intervalli centrali: 0.8 -> 0.10 e 0.90."""
    tails = [(1 - level) / 2 for level in levels]
    return sorted({round(p, 4) for t in tails for p in (t, 1 - t)})


def calibration_errors(results: pd.DataFrame) -> pd.DataFrame:
    """Errori (previsione - realizzato) usati per la calibrazione."""
    rows = results[results["status"] == OK]
    outside = (rows["target"] < EXCLUDED[0]) | (rows["target"] > EXCLUDED[1])
    rows = rows[outside]
    return rows.assign(error=rows["forecast"] - rows["actual"])[["model", "horizon", "error"]]


def error_quantiles(results: pd.DataFrame) -> pd.DataFrame:
    """Quantili degli errori per (modello, orizzonte), con il numero di errori usati."""
    grouped = calibration_errors(results).groupby(["model", "horizon"])["error"]
    table = grouped.quantile(np.array(tail_probabilities())).unstack()
    table.columns = [f"q{round(float(p) * 100):02d}" for p in table.columns]
    return table.assign(n=grouped.size())


def applied_horizon(days_to_publication: int) -> int:
    """L'orizzonte del backtest da applicare a una stima fatta oggi.

    È il più vicino che non sia più corto dei giorni mancanti: tra due orizzonti adiacenti
    si usa quello più lontano dalla pubblicazione, che ha in genere errori più ampi. Oltre
    i 90 giorni si usa comunque 90, il più lontano valutato.
    """
    eligible = [h for h in HORIZONS if h >= days_to_publication]
    return min(eligible) if eligible else max(HORIZONS)


def interval(forecast: float, quantiles: pd.Series) -> dict[str, float]:
    """Estremi degli intervalli: realizzato = previsione - errore.

    Un modello che in media sovrastima (errori positivi) ha quindi un intervallo spostato
    verso il basso rispetto alla previsione.
    """
    bounds = {}
    for level in LEVELS:
        low_p, high_p = (1 - level) / 2, 1 - (1 - level) / 2
        label = round(level * 100)
        bounds[f"low{label}"] = forecast - float(quantiles[f"q{round(high_p * 100):02d}"])
        bounds[f"high{label}"] = forecast - float(quantiles[f"q{round(low_p * 100):02d}"])
    return bounds
