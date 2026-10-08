"""Stima corrente di tutti i modelli, con intervalli, e registro a sole aggiunte."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nowcast.config import SeriesSpec
from nowcast.data.vintages import estimated_release
from nowcast.evaluation.backtest import forecast
from nowcast.live.intervals import applied_horizon, error_quantiles, interval
from nowcast.models.base import Model, build_info, next_unpublished_quarter

LOG_COLUMNS = [
    "run_date",
    "target",
    "model",
    "forecast",
    "model_std",
    "low80",
    "low50",
    "high50",
    "high80",
    "expected_publication",
    "days_to_publication",
    "horizon_applied",
    "status",
    "reason",
    "dataset_version",
    "code_commit",
]
LOG_KEY = ["run_date", "target", "model", "dataset_version", "code_commit"]
LOG_DATES = ["run_date", "target", "expected_publication"]


def expected_publication(target: pd.Timestamp, specs: list[SeriesSpec]) -> pd.Timestamp:
    """Data attesa di pubblicazione del PIL del trimestre, dal calendario del registro."""
    gdp = next(s for s in specs if s.role == "target")
    return pd.Timestamp(estimated_release(pd.DatetimeIndex([target]), gdp)[0])


def current_nowcasts(
    observations: pd.DataFrame,
    specs: list[SeriesSpec],
    models: list[Model],
    backtest_results: pd.DataFrame,
    as_of: pd.Timestamp,
    dataset_version: str,
    code_commit: str,
) -> pd.DataFrame:
    """Una riga per modello: stima del primo trimestre non pubblicato e suoi intervalli."""
    info = build_info(observations, specs, as_of)
    target = next_unpublished_quarter(info)
    publication = expected_publication(target, specs)
    days = int((publication - as_of).days)
    horizon = applied_horizon(days)
    quantiles = error_quantiles(backtest_results)
    rows = []
    for model in models:
        outcome = forecast(model, info, target)
        bounds = {}
        if outcome["status"] == "ok":
            bounds = interval(float(outcome["forecast"]), quantiles.loc[(model.name, horizon)])  # type: ignore[arg-type]
        rows.append(
            {
                "run_date": as_of,
                "target": target,
                "model": model.name,
                "forecast": outcome["forecast"],
                "model_std": outcome["std"],
                **bounds,
                "expected_publication": publication,
                "days_to_publication": days,
                "horizon_applied": horizon,
                "status": outcome["status"],
                "reason": outcome["reason"],
                "dataset_version": dataset_version,
                "code_commit": code_commit,
            }
        )
    return pd.DataFrame(rows).reindex(columns=LOG_COLUMNS)


def read_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.read_csv(
        path,
        parse_dates=LOG_DATES,
        dtype={"reason": "str", "dataset_version": "str", "code_commit": "str"},
        keep_default_na=False,
        na_values={
            c: [""] for c in ("forecast", "model_std", "low80", "low50", "high50", "high80")
        },
    )


def append_to_log(new_rows: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Aggiunge le stime al registro senza toccare le righe esistenti.

    Una stima già registrata (stessa data, modello, dataset e codice) non viene duplicata
    né sovrascritta.
    """
    existing = read_log(path)
    known = set(map(tuple, existing[LOG_KEY].astype(str).to_numpy()))
    is_new = [tuple(row) not in known for row in new_rows[LOG_KEY].astype(str).to_numpy()]
    combined = pd.concat([existing, new_rows[is_new]], ignore_index=True)[LOG_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False, float_format="%.10g", date_format="%Y-%m-%d")
    return combined
