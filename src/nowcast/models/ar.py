"""Autoregressione stimata con OLS: usata dai benchmark e per completare i mesi mancanti."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ARFit:
    coefs: np.ndarray  # costante, poi phi_1 ... phi_p
    sigma: float
    nobs: int

    @property
    def order(self) -> int:
        return len(self.coefs) - 1


def _design(y: pd.Series, order: int) -> tuple[np.ndarray, np.ndarray]:
    """Regressori ritardati; le righe con un mancante (anche tra i ritardi) sono scartate."""
    lags = pd.concat([y.shift(k) for k in range(1, order + 1)], axis=1)
    rows = (y.notna() & lags.notna().all(axis=1)).to_numpy()
    x = np.column_stack([np.ones(int(rows.sum())), lags.to_numpy()[rows]])
    return x, y.to_numpy()[rows]


def fit_ar(y: pd.Series, order: int) -> ARFit:
    """Stima AR(order). I NaN in `y` escludono dalla stima le righe che li coinvolgono."""
    x, target = _design(y, order)
    if len(target) <= order + 1:
        raise ValueError("osservazioni insufficienti per stimare l'AR")
    coefs, *_ = np.linalg.lstsq(x, target, rcond=None)
    residuals = target - x @ coefs
    sigma = float(np.sqrt(residuals @ residuals / (len(target) - order - 1)))
    return ARFit(coefs=coefs, sigma=sigma, nobs=len(target))


def bic(fit: ARFit) -> float:
    return fit.nobs * float(np.log(fit.sigma**2)) + (fit.order + 1) * float(np.log(fit.nobs))


def select_order(y: pd.Series, max_order: int) -> int:
    """Ordine con BIC minimo, a parità di campione di stima."""
    trimmed = y.copy()
    trimmed.iloc[:max_order] = np.nan  # stesso campione effettivo per tutti gli ordini
    scores = {p: bic(fit_ar(trimmed, p)) for p in range(1, max_order + 1)}
    return min(scores, key=lambda p: scores[p])


def forecast_ar(history: np.ndarray, fit: ARFit, steps: int) -> tuple[np.ndarray, np.ndarray]:
    """Previsioni iterate e loro deviazione standard (solo incertezza degli shock futuri)."""
    values = list(history[-fit.order :])
    phi = fit.coefs[1:]
    psi = [1.0]
    means = []
    for _ in range(steps):
        recent = values[::-1][: fit.order]
        means.append(float(fit.coefs[0] + phi @ np.array(recent)))
        values.append(means[-1])
        psi.append(float(sum(phi[j] * psi[-1 - j] for j in range(min(fit.order, len(psi))))))
    variances = fit.sigma**2 * np.cumsum(np.square(psi[:steps]))
    return np.array(means), np.sqrt(variances)
