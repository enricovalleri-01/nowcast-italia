"""Metriche di accuratezza e tabelle del protocollo, a partire dai risultati del backtest."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nowcast.evaluation.backtest import OK
from nowcast.evaluation.dm_test import dm_test

BENCHMARK = "ar1"
MAIN_MODELS = ["media_storica", "ar1", "ar2", "bridge", "dfm_k1", "dfm_k2"]
EX_POST_MODELS = [f"{name}_expost" for name in MAIN_MODELS]
CONFIRMATORY = ["bridge", "dfm_k1"]

Window = tuple[pd.Timestamp, pd.Timestamp]
COVID_YEARS: Window = (pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31"))
SUBPERIODS: dict[str, Window] = {
    "2012-2019": (pd.Timestamp("2012-01-01"), pd.Timestamp("2019-12-31")),
    "2020-2021": COVID_YEARS,
    "2022-2026": (pd.Timestamp("2022-01-01"), pd.Timestamp("2026-12-31")),
}


def rmse(errors: pd.Series) -> float:
    return float(np.sqrt(np.mean(np.square(errors))))


def mae(errors: pd.Series) -> float:
    return float(np.mean(np.abs(errors)))


def error_table(results: pd.DataFrame, horizon: int, models: list[str]) -> pd.DataFrame:
    """Errori (previsione - realizzato): una riga per trimestre, una colonna per modello.

    Restano solo i trimestri in cui tutti i modelli richiesti hanno una previsione.
    """
    rows = results[(results["horizon"] == horizon) & results["model"].isin(models)]
    rows = rows[rows["status"] == OK]
    errors = (rows["forecast"] - rows["actual"]).rename("error")
    wide = pd.concat([rows[["target", "model"]], errors], axis=1).pivot(
        index="target", columns="model", values="error"
    )
    return wide.reindex(columns=models).dropna()


def keep(
    errors: pd.DataFrame, window: Window | None = None, exclude: Window | None = None
) -> pd.DataFrame:
    """Limita i trimestri a una finestra e/o ne esclude una."""
    index = pd.DatetimeIndex(errors.index)
    mask = np.ones(len(index), dtype=bool)
    if window is not None:
        mask &= (index >= window[0]) & (index <= window[1])
    if exclude is not None:
        mask &= ~((index >= exclude[0]) & (index <= exclude[1]))
    return errors[mask]


def accuracy(errors: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """RMSE, MAE, errore medio e RMSE relativo al benchmark, per modello."""
    table = pd.DataFrame(
        {
            "trimestri": len(errors),
            "RMSE": errors.apply(rmse),
            "MAE": errors.apply(mae),
            "errore_medio": errors.mean(),
        }
    )
    table["RMSE_relativo"] = table["RMSE"] / rmse(errors[benchmark])
    return table


def failures(results: pd.DataFrame) -> pd.DataFrame:
    """Numero di previsioni mancanti per modello e orizzonte."""
    failed = results[results["status"] != OK]
    counts = failed.groupby(["model", "horizon"]).size().unstack(fill_value=0)
    models = sorted(results["model"].unique())
    horizons = sorted(results["horizon"].unique(), reverse=True)
    return counts.reindex(index=models, columns=horizons, fill_value=0).astype(int)


def max_steps(results: pd.DataFrame, horizon: int) -> int:
    """Massimo numero di trimestri tra l'ultimo PIL noto e quello previsto, a un orizzonte."""
    return int(results.loc[results["horizon"] == horizon, "steps"].max())


def dm_table(
    errors: pd.DataFrame, models: list[str], benchmark: str, steps: int, loss: str
) -> pd.DataFrame:
    """Test di Diebold-Mariano di ogni modello contro il benchmark, sugli stessi trimestri."""
    rows = {}
    for model in models:
        result = dm_test(errors[model].to_numpy(), errors[benchmark].to_numpy(), steps, loss)
        rows[model] = {"statistica": result.statistic, "p_value": result.p_value, "n": result.nobs}
    return pd.DataFrame(rows).T.astype({"n": int})


def largest_errors(
    results: pd.DataFrame, horizon: int, models: list[str], top: int
) -> pd.DataFrame:
    """I trimestri con il maggiore errore assoluto medio tra i modelli indicati."""
    errors = error_table(results, horizon, models)
    actual = results.drop_duplicates("target").set_index("target")["actual"]
    table = errors.assign(realizzato=actual.reindex(errors.index))
    order = errors.abs().mean(axis=1).sort_values(ascending=False).index[:top]
    return table.loc[order, ["realizzato", *models]]
