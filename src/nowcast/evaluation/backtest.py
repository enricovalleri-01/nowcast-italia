"""Backtest pseudo real-time secondo il protocollo di valutazione del README.

Per ogni trimestre e orizzonte ricostruisce il set informativo alla data dell'orizzonte,
ristima ogni modello e ne registra la previsione. Legge solo una versione congelata del
dataset e scrive, con ogni riga, l'impronta dei dati e il commit della specificazione.
"""

from __future__ import annotations

import subprocess
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import pandas as pd

from nowcast.config import ROOT, SeriesSpec
from nowcast.data.vintages import publication_date
from nowcast.models.base import COVID_WINDOW, InfoSet, Model, build_info, quarters_between
from nowcast.models.benchmark import ARBenchmark, HistoricalMean
from nowcast.models.bridge import Bridge
from nowcast.models.dfm import DFM

# Valori fissati dal protocollo.
PROTOCOL_TAG = "protocollo-v1.1"
DATASET_VERSION = "ef2b22705503"
HORIZONS = (90, 60, 30)
FIRST_QUARTER = pd.Timestamp("2012-03-31")
LAST_QUARTER = pd.Timestamp("2026-06-30")
SPECIFICATION_PATHS = (
    "config",
    "src/nowcast/config.py",
    "src/nowcast/transforms.py",
    "src/nowcast/data",
    "src/nowcast/models",
)

OK = "ok"
FAILED = "failed"
RESULT_COLUMNS = [
    "model",
    "target",
    "horizon",
    "as_of",
    "publication_date",
    "steps",
    "forecast",
    "std",
    "actual",
    "status",
    "reason",
    "warnings",
    "dataset_version",
    "specification_commit",
]


@dataclass(frozen=True)
class Origin:
    """Un punto del backtest: trimestre previsto e data da cui lo si prevede."""

    target: pd.Timestamp
    horizon: int
    publication: pd.Timestamp
    as_of: pd.Timestamp


def protocol_models() -> list[Model]:
    """I modelli del protocollo: principali e varianti ex post."""
    main: list[Model] = [
        HistoricalMean(),
        ARBenchmark(1),
        ARBenchmark(2),
        Bridge(),
        DFM(1),
        DFM(2),
    ]
    ex_post: list[Model] = [
        HistoricalMean(COVID_WINDOW),
        ARBenchmark(1, COVID_WINDOW),
        ARBenchmark(2, COVID_WINDOW),
        Bridge(exclude=COVID_WINDOW),
        DFM(1, exclude=COVID_WINDOW),
        DFM(2, exclude=COVID_WINDOW),
    ]
    return main + ex_post


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def specification_commit(tag: str = PROTOCOL_TAG) -> str:
    """Commit del tag del protocollo, dopo aver verificato che la specificazione non è cambiata.

    Dati, modelli e registro delle serie devono coincidere con quelli del tag, comprese le
    modifiche non committate: altrimenti i risultati non sarebbero quelli del protocollo.
    """
    if _git("diff", "--quiet", tag, "--", *SPECIFICATION_PATHS).returncode != 0:
        raise RuntimeError(f"la specificazione è diversa da quella del tag {tag}")
    return _git("rev-parse", "--short", f"{tag}^{{commit}}").stdout.strip()


def realized_growth(observations: pd.DataFrame, specs: list[SeriesSpec]) -> pd.Series:
    """Crescita t/t del PIL nell'ultima versione presente nel dataset."""
    last_day = pd.Timestamp(observations["release_date"].max())
    return build_info(observations, specs, last_day).gdp_growth


def origins(
    observations: pd.DataFrame, quarters: pd.DatetimeIndex, horizons: tuple[int, ...] = HORIZONS
) -> list[Origin]:
    """Per ogni trimestre, le date a `horizon` giorni dalla pubblicazione del suo PIL."""
    result = []
    for quarter in quarters:
        publication = publication_date(observations, "gdp", quarter)
        for horizon in horizons:
            as_of = publication - pd.Timedelta(days=horizon)
            result.append(Origin(quarter, horizon, publication, as_of))
    return result


def forecast(model: Model, info: InfoSet, target: pd.Timestamp) -> dict[str, object]:
    """Previsione di un modello; un rifiuto della stima diventa un fallimento registrato."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = model.nowcast(info, target)
            outcome = {"forecast": result.mean, "std": result.std, "status": OK, "reason": ""}
        except ValueError as error:
            outcome = {
                "forecast": float("nan"),
                "std": float("nan"),
                "status": FAILED,
                "reason": str(error),
            }
    messages = sorted({f"{w.category.__name__}: {w.message}" for w in caught})
    return {**outcome, "warnings": " | ".join(messages)}


def run_origin(
    origin: Origin, observations: pd.DataFrame, specs: list[SeriesSpec], models: list[Model]
) -> list[dict[str, object]]:
    """Tutti i modelli su un'origine, a partire dallo snapshot alla sua data."""
    info = build_info(observations, specs, origin.as_of)
    if origin.target in info.gdp_growth.index:
        raise RuntimeError(f"il PIL di {origin.target.date()} è già noto il {origin.as_of.date()}")
    rows = []
    for model in models:
        row = {
            "model": model.name,
            "target": origin.target,
            "horizon": origin.horizon,
            "as_of": origin.as_of,
            "publication_date": origin.publication,
            "steps": quarters_between(info.gdp_growth.index[-1], origin.target),
        }
        rows.append({**row, **forecast(model, info, origin.target)})
    return rows


def run_backtest(
    observations: pd.DataFrame,
    specs: list[SeriesSpec],
    models: list[Model],
    quarters: pd.DatetimeIndex,
    dataset_version: str,
    commit: str,
    horizons: tuple[int, ...] = HORIZONS,
    workers: int = 1,
) -> pd.DataFrame:
    """Esegue il backtest e restituisce una riga per modello, trimestre e orizzonte."""
    todo = origins(observations, quarters, horizons)
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            n = len(todo)
            batches = list(
                pool.map(run_origin, todo, [observations] * n, [specs] * n, [models] * n)
            )
    else:
        batches = [run_origin(origin, observations, specs, models) for origin in todo]
    results = pd.DataFrame([row for batch in batches for row in batch])
    results["actual"] = results["target"].map(realized_growth(observations, specs))
    results["dataset_version"] = dataset_version
    results["specification_commit"] = commit
    return results[RESULT_COLUMNS]


def protocol_quarters() -> pd.DatetimeIndex:
    return pd.date_range(FIRST_QUARTER, LAST_QUARTER, freq="QE")
