"""Test di Diebold-Mariano con la correzione di Harvey, Leybourne e Newbold (1997)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

LOSSES = {"squared": np.square, "absolute": np.abs}


@dataclass(frozen=True)
class DMResult:
    statistic: float  # negativa: il modello ha perdita media minore del benchmark
    p_value: float  # a due code
    nobs: int
    mean_loss_difference: float


def loss_differential(
    model_errors: np.ndarray, benchmark_errors: np.ndarray, loss: str
) -> np.ndarray:
    function = LOSSES[loss]
    return np.asarray(function(model_errors) - function(benchmark_errors), dtype=float)


def long_run_variance(d: np.ndarray, truncation: int) -> float:
    """Varianza di lungo periodo con nucleo rettangolare troncato a `truncation` ritardi."""
    centered = d - d.mean()
    n = len(d)
    variance = float(centered @ centered) / n
    for lag in range(1, truncation + 1):
        variance += 2 * float(centered[lag:] @ centered[:-lag]) / n
    return variance


def dm_test(
    model_errors: np.ndarray, benchmark_errors: np.ndarray, steps: int = 1, loss: str = "squared"
) -> DMResult:
    """Confronta due serie di errori di previsione sugli stessi periodi.

    `steps` è l'orizzonte in periodi: la varianza usa `steps - 1` autocovarianze. La
    statistica corretta si confronta con una t con n - 1 gradi di libertà. Se la varianza
    stimata non è positiva il test non è calcolabile e restituisce NaN.
    """
    d = loss_differential(np.asarray(model_errors), np.asarray(benchmark_errors), loss)
    n = len(d)
    variance = long_run_variance(d, steps - 1)
    if n < 2 or not variance > 0:
        return DMResult(float("nan"), float("nan"), n, float(d.mean()) if n else float("nan"))
    raw = d.mean() / np.sqrt(variance / n)
    correction = np.sqrt((n + 1 - 2 * steps + steps * (steps - 1) / n) / n)
    statistic = float(raw * correction)
    p_value = float(2 * stats.t.sf(abs(statistic), df=n - 1))
    return DMResult(statistic, p_value, n, float(d.mean()))
