"""Comandi del progetto. Uso: python -m nowcast.pipeline {update-data,nowcast,select-factors}"""

from __future__ import annotations

import argparse
import logging

import pandas as pd
from dotenv import load_dotenv

from nowcast.config import ROOT, SeriesSpec, load_series
from nowcast.data import cache
from nowcast.data.sources import ecb, eurostat, fred
from nowcast.data.vintages import assign_release_dates
from nowcast.models import selection
from nowcast.models.base import Model, Nowcast, build_info, next_unpublished_quarter
from nowcast.models.benchmark import ARBenchmark, HistoricalMean
from nowcast.models.bridge import Bridge
from nowcast.models.dfm import DFM
from nowcast.transforms import daily_to_monthly

log = logging.getLogger("nowcast")


def last_complete_month(today: pd.Timestamp) -> pd.Timestamp:
    return (today.normalize() - pd.offsets.MonthEnd(1)).normalize()


def download(spec: SeriesSpec, today: pd.Timestamp) -> pd.Series:
    """Scarica una serie e la riporta alla frequenza dichiarata, indicizzata a fine periodo."""
    if spec.source == "eurostat":
        return eurostat.fetch(spec.params["dataset"], spec.params["filters"], spec.frequency)
    if spec.source == "ecb":
        daily = ecb.fetch(spec.params["flow"], spec.params["key"])
        return daily_to_monthly(daily, last_complete_month(today))
    if spec.source == "fred":
        return fred.fetch(spec.params["fred_id"], spec.frequency)
    raise ValueError(f"{spec.id}: fonte non scaricabile {spec.source}")


def real_release_dates(spec: SeriesSpec) -> pd.Series | None:
    if spec.source != "fred":
        return None
    return fred.fetch_first_releases(spec.params["fred_id"], spec.frequency)


def update_series(spec: SeriesSpec, previous: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    series = download(spec, today)
    cache.save_raw(series, spec.id)
    known = previous[previous["series_id"] == spec.id]
    table = assign_release_dates(series, spec, today, known, real_release_dates(spec))
    revised = int((table["release_source"] == "revision").sum())
    last = table["ref_period"].max().date()
    log.info("%-16s %4d periodi  %4d revisioni  ultimo %s", spec.id, series.count(), revised, last)
    return table


def update_data(today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Aggiorna tutte le serie e riscrive la tabella delle osservazioni."""
    today = (today or pd.Timestamp.today()).normalize()
    specs = load_series()
    previous = cache.load_observations()
    tables = [update_series(s, previous, today) for s in specs if s.source != "derived"]
    observations = pd.concat(tables, ignore_index=True)
    cache.save_observations(observations)
    log.info("dataset %s (%d righe)", cache.dataset_version(observations), len(observations))
    return observations


def default_models() -> list[Model]:
    return [HistoricalMean(), ARBenchmark(1), ARBenchmark(2), Bridge(), DFM(1), DFM(2)]


def run_nowcast(as_of: pd.Timestamp | None = None) -> list[Nowcast]:
    """Nowcast di tutti i modelli per il primo trimestre non ancora pubblicato."""
    as_of = (as_of or pd.Timestamp.today()).normalize()
    observations = cache.load_observations()
    info = build_info(observations, load_series(), as_of)
    target = next_unpublished_quarter(info)
    log.info("dataset %s", cache.dataset_version(observations))
    results = [model.nowcast(info, target) for model in default_models()]
    log.info(
        "Nowcast del PIL t/t, trimestre che termina il %s (dati al %s)", target.date(), as_of.date()
    )
    for r in results:
        log.info("%-14s %+.2f%%  (dev. std. %.2f)", r.model, r.mean, r.std)
    return results


def run_factor_selection() -> None:
    """Stampa le evidenze sulla scelta del numero di fattori (solo dati fino al 2011)."""
    observations, specs = cache.load_observations(), load_series()
    log.info(
        "Criteri di Bai e Ng\n%s\n", selection.information_criteria(observations, specs).round(3)
    )
    grid = [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1)]
    log.info("BIC del modello\n%s\n", selection.model_bic(observations, specs, grid).round(1))
    rmse = selection.development_rmse(observations, specs, [1, 2, 3], [90, 60, 30])
    log.info(
        "RMSE sulla finestra di sviluppo 2008-2011, per giorni alla pubblicazione\n%s",
        rmse.round(3),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["update-data", "nowcast", "select-factors"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(ROOT / ".env")
    if args.command == "update-data":
        update_data()
    elif args.command == "nowcast":
        run_nowcast()
    else:
        run_factor_selection()


if __name__ == "__main__":
    main()
