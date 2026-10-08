"""Dynamic factor model a frequenza mista (statsmodels DynamicFactorMQ)."""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

from nowcast.models.base import InfoSet, Nowcast, mask_covid, stationary_panel

# Scelta motivata nel README (sezione Modelli) e riproducibile con `select-factors`.
DEFAULT_FACTORS = 1
DEFAULT_FACTOR_ORDER = 1


def monthly_endog(
    info: InfoSet, target: pd.Timestamp, transforms: dict[str, str] | None = None
) -> pd.DataFrame:
    """Panel stazionario esteso fino al mese finale del trimestre obiettivo."""
    kinds = transforms if transforms is not None else info.dfm_transforms
    panel = stationary_panel(info, kinds).dropna(how="all")
    index = pd.date_range(panel.index[0], max(panel.index[-1], target), freq="ME")
    return panel.reindex(index)


def with_period_index(data: pd.DataFrame, frequency: str) -> pd.DataFrame:
    return data.set_axis(pd.DatetimeIndex(data.index).to_period(frequency), axis=0)


def masked(data: pd.DataFrame) -> pd.DataFrame:
    return data.apply(mask_covid)


def max_root(results: Any) -> float:
    """Modulo massimo degli autovalori della transizione: sotto 1 il modello è stazionario."""
    return float(np.abs(np.linalg.eigvals(results.filter_results.transition[:, :, 0])).max())


class DFM:
    """Fattori comuni mensili; il PIL trimestrale entra con l'aggregazione di Mariano-Murasawa.

    I parametri sono stimati (EM) con la finestra Covid oscurata, poi il filtro di Kalman
    viene applicato ai dati completi: il 2020 non distorce i parametri ma resta nei dati
    su cui si calcola il nowcast.
    """

    def __init__(
        self,
        factors: int = DEFAULT_FACTORS,
        factor_order: int = DEFAULT_FACTOR_ORDER,
        maxiter: int = 300,
        transforms: dict[str, str] | None = None,
    ) -> None:
        self.transforms = transforms  # None: quelle indicate dal registro
        self.factors = factors
        self.factor_order = factor_order
        self.maxiter = maxiter
        self.name = f"dfm_k{factors}"

    def _model(self, monthly: pd.DataFrame, quarterly: pd.DataFrame) -> DynamicFactorMQ:
        return DynamicFactorMQ(
            with_period_index(monthly, "M"),
            endog_quarterly=with_period_index(quarterly, "Q"),
            factors=self.factors,
            factor_orders=self.factor_order,
            idiosyncratic_ar1=True,
            standardize=True,
        )

    def estimate(self, info: InfoSet, target: pd.Timestamp) -> Any:
        """Stima i parametri sui dati oscurati (risultato statsmodels)."""
        monthly = monthly_endog(info, target, self.transforms)
        quarterly = info.gdp_growth.to_frame()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = self._model(masked(monthly), masked(quarterly)).fit(
                disp=False, maxiter=self.maxiter
            )
        if max_root(results) >= 1:
            raise ValueError(f"{self.name}: stima non stazionaria (radice {max_root(results):.3f})")
        return results

    def fit(self, info: InfoSet, target: pd.Timestamp, estimated: Any | None = None) -> Any:
        """Applica i parametri stimati ai dati completi di `info`.

        `estimated` permette di riusare parametri stimati su un set informativo precedente.
        """
        estimated = estimated if estimated is not None else self.estimate(info, target)
        monthly = with_period_index(monthly_endog(info, target, self.transforms), "M")
        quarterly = with_period_index(info.gdp_growth.to_frame(), "Q")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return estimated.apply(monthly, endog_quarterly=quarterly, retain_standardization=True)

    def nowcast(self, info: InfoSet, target: pd.Timestamp, estimated: Any | None = None) -> Nowcast:
        results = self.fit(info, target, estimated)
        month = target.to_period("M")
        prediction = results.get_prediction(start=month, end=month, information_set="smoothed")
        mean = float(prediction.predicted_mean["gdp"].iloc[0])
        std = float(prediction.se_mean["gdp"].iloc[0])
        return Nowcast(self.name, target, mean, std)


def bai_ng_ic(panel: pd.DataFrame, max_factors: int) -> pd.DataFrame:
    """Criteri di Bai e Ng (2002) e varianza spiegata, su un panel bilanciato.

    Il minimo di ICp1/ICp2 indica il numero di fattori. Con poche serie i criteri tendono
    a sovrastimarlo: vanno letti insieme alla varianza spiegata.
    """
    z = ((panel - panel.mean()) / panel.std(ddof=1)).to_numpy()
    t, n = z.shape
    _, singular, _ = np.linalg.svd(z, full_matrices=False)
    eigen = singular**2 / (t * n)
    scale = (n + t) / (n * t)
    rows = []
    for k in range(1, max_factors + 1):
        residual = float(eigen[k:].sum())
        rows.append(
            {
                "fattori": k,
                "varianza_spiegata": float(eigen[:k].sum() / eigen.sum()),
                "ICp1": np.log(residual) + k * scale * np.log(1 / scale),
                "ICp2": np.log(residual) + k * scale * np.log(min(n, t)),
            }
        )
    return pd.DataFrame(rows).set_index("fattori")
