"""Comandi del progetto. Uso: python -m nowcast.pipeline <comando>

init-data       importa lo storico delle serie non ancora in archivio (nuova versione)
update-data     aggiornamento ordinario: solo righe aggiunte
redate-data     riapplica il calendario di series.yaml (nuova versione)
nowcast         stima del trimestre in corso
select-factors  evidenze sulla finestra di sviluppo
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable

import pandas as pd
from dotenv import load_dotenv

from nowcast.config import ROOT, SeriesSpec, load_series
from nowcast.data import cache
from nowcast.data.sources import ecb, eurostat, fred
from nowcast.data.vintages import import_history, redate, update
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


def stored_specs() -> list[SeriesSpec]:
    """Le serie del registro che hanno righe proprie in archivio (non le derivate)."""
    return [s for s in load_series() if s.source != "derived"]


def _rows_of(archive: pd.DataFrame, spec: SeriesSpec) -> pd.DataFrame:
    return archive[archive["series_id"] == spec.id]


def _save(tables: list[pd.DataFrame], action: str) -> pd.DataFrame:
    observations = pd.concat(tables, ignore_index=True)
    version = cache.save_observations(observations)
    log.info("%s: dataset %s (%d righe)", action, version, len(observations))
    return observations


def init_data(today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Importa lo storico delle serie del registro non ancora in archivio.

    Crea una nuova versione del dataset: lo storico importato riceve date stimate e
    compare anche negli snapshot delle date passate.
    """
    today = (today or pd.Timestamp.today()).normalize()
    archive = cache.load_observations()
    missing = [s for s in stored_specs() if _rows_of(archive, s).empty]
    tables = [archive] if not archive.empty else []
    for spec in missing:
        series = download(spec, today)
        cache.save_raw(series, spec.id)
        tables.append(import_history(series, spec, today, real_release_dates(spec)))
        log.info("%-16s importati %4d periodi", spec.id, series.count())
    if not missing:
        log.info("nessuna serie da importare")
        return archive
    return _save(tables, "importazione")


def update_data(today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Aggiornamento ordinario: aggiunge nuovi periodi e revisioni, senza toccare il resto."""
    today = (today or pd.Timestamp.today()).normalize()
    archive = cache.load_observations()
    absent = [s.id for s in stored_specs() if _rows_of(archive, s).empty]
    if absent:
        raise ValueError(f"serie assenti dall'archivio {absent}: eseguire prima init-data")
    tables = []
    for spec in stored_specs():
        series = download(spec, today)
        cache.save_raw(series, spec.id)
        table = update(series, spec, today, _rows_of(archive, spec))
        added = len(table) - len(_rows_of(archive, spec))
        log.info("%-16s %3d righe aggiunte  ultimo %s", spec.id, added, series.index.max().date())
        tables.append(table)
    return _save(tables, "aggiornamento")


def redate_data() -> pd.DataFrame:
    """Riapplica il calendario di series.yaml alle date stimate: nuova versione del dataset."""
    archive = cache.load_observations()
    tables = [redate(_rows_of(archive, s), s, real_release_dates(s)) for s in stored_specs()]
    return _save(tables, "correzione del calendario")


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
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands: dict[str, Callable[[], object]] = {
        "init-data": init_data,
        "update-data": update_data,
        "redate-data": redate_data,
        "nowcast": run_nowcast,
        "select-factors": run_factor_selection,
    }
    parser.add_argument("command", choices=list(commands))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(ROOT / ".env")
    commands[args.command]()


if __name__ == "__main__":
    main()
