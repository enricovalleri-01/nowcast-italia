"""Dynamic factor model a frequenza mista (statsmodels DynamicFactorMQ)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

from nowcast.models.base import (
    InfoSet,
    Nowcast,
    Window,
    mask_window,
    stationary_panel,
    variant_name,
)

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


@dataclass(frozen=True)
class DFMEstimate:
    """Parametri stimati, con la data e le serie del set informativo che li ha prodotti."""

    results: Any  # DynamicFactorMQResults
    as_of: pd.Timestamp
    columns: tuple[str, ...]


def masked(data: pd.DataFrame, window: Window | None) -> pd.DataFrame:
    return data.apply(lambda column: mask_window(column, window))


def max_root(results: Any) -> float:
    """Modulo massimo degli autovalori della transizione: sotto 1 il modello è stazionario."""
    return float(np.abs(np.linalg.eigvals(results.filter_results.transition[:, :, 0])).max())


class DFM:
    """Fattori comuni mensili; il PIL trimestrale entra con l'aggregazione di Mariano-Murasawa.

    I parametri sono stimati con l'algoritmo EM, poi il filtro di Kalman viene applicato ai
    dati di `info`. Con `exclude` i periodi della finestra restano fuori dalla stima dei
    parametri ma non dai dati su cui si calcola il nowcast (variante ex post).
    """

    def __init__(
        self,
        factors: int = DEFAULT_FACTORS,
        factor_order: int = DEFAULT_FACTOR_ORDER,
        maxiter: int = 1000,
        transforms: dict[str, str] | None = None,
        exclude: Window | None = None,
    ) -> None:
        self.transforms = transforms  # None: quelle indicate dal registro
        self.factors = factors
        self.factor_order = factor_order
        self.maxiter = maxiter
        self.exclude = exclude
        self.name = variant_name(f"dfm_k{factors}", exclude)

    def _model(self, monthly: pd.DataFrame, quarterly: pd.DataFrame) -> DynamicFactorMQ:
        return DynamicFactorMQ(
            with_period_index(monthly, "M"),
            endog_quarterly=with_period_index(quarterly, "Q"),
            factors=self.factors,
            factor_orders=self.factor_order,
            idiosyncratic_ar1=True,
            standardize=True,
        )

    def _check(self, results: Any) -> None:
        """Rifiuta una stima che non è arrivata a convergenza o non è stazionaria."""
        if results.mle_retvals["iter"] >= self.maxiter:
            raise ValueError(f"{self.name}: EM non convergente in {self.maxiter} iterazioni")
        if max_root(results) >= 1:
            raise ValueError(f"{self.name}: stima non stazionaria (radice {max_root(results):.3f})")

    def estimate(self, info: InfoSet, target: pd.Timestamp) -> DFMEstimate:
        """Stima i parametri sui dati di `info`."""
        monthly = masked(monthly_endog(info, target, self.transforms), self.exclude)
        quarterly = masked(info.gdp_growth.to_frame(), self.exclude)
        results = self._model(monthly, quarterly).fit(disp=False, maxiter=self.maxiter)
        self._check(results)
        return DFMEstimate(results, info.as_of, tuple(monthly.columns))

    def fit(self, info: InfoSet, target: pd.Timestamp, estimate: DFMEstimate | None = None) -> Any:
        """Applica i parametri stimati ai dati completi di `info`.

        Si può riusare una stima precedente, mai una successiva alla data di `info`:
        parametri e standardizzazione porterebbero nel passato informazione futura.
        """
        estimate = estimate if estimate is not None else self.estimate(info, target)
        monthly = monthly_endog(info, target, self.transforms)
        if estimate.as_of > info.as_of:
            raise ValueError(
                f"{self.name}: stima del {estimate.as_of.date()} successiva al set informativo "
                f"del {info.as_of.date()}"
            )
        if estimate.columns != tuple(monthly.columns):
            raise ValueError(
                f"{self.name}: la stima usa serie diverse da quelle del set informativo"
            )
        return estimate.results.apply(
            with_period_index(monthly, "M"),
            endog_quarterly=with_period_index(info.gdp_growth.to_frame(), "Q"),
            retain_standardization=True,
        )

    def nowcast(
        self, info: InfoSet, target: pd.Timestamp, estimate: DFMEstimate | None = None
    ) -> Nowcast:
        results = self.fit(info, target, estimate)
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
