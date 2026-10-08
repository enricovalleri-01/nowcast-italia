"""Comandi del progetto. Uso: python -m nowcast.pipeline <comando>

init-data       importa lo storico delle serie non ancora in archivio (nuova versione)
update-data     aggiornamento ordinario: solo righe aggiunte
redate-data     riapplica il calendario di series.yaml (nuova versione)
backtest        backtest del protocollo sulla versione congelata del dataset
evaluate        tabelle dei risultati del backtest
nowcast         stima del trimestre in corso
select-factors  evidenze sulla finestra di sviluppo
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from collections.abc import Callable

import pandas as pd
from dotenv import load_dotenv

from nowcast.config import DATA_DIR, ROOT, SeriesSpec, load_series
from nowcast.data import cache
from nowcast.data.sources import ecb, eurostat, fred
from nowcast.data.vintages import import_history, redate, update
from nowcast.evaluation import backtest
from nowcast.evaluation.report import build_report
from nowcast.live.intervals import EXCLUSION_NOTE
from nowcast.live.nowcast import append_to_log, current_nowcasts
from nowcast.models import selection
from nowcast.transforms import daily_to_monthly

log = logging.getLogger("nowcast")


RESULTS_DIR = ROOT / "results"
BACKTEST_PATH = RESULTS_DIR / "backtest.csv"
REPORT_PATH = RESULTS_DIR / "report.md"
DATE_COLUMNS = ["target", "as_of", "publication_date"]
NOWCAST_LOG_PATH = DATA_DIR / "nowcast_log.csv"


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


def code_commit() -> str:
    """Commit del codice in esecuzione, con un segno se ci sono modifiche non committate."""
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    dirty = (
        subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=ROOT, check=False).returncode != 0
    )
    return f"{head}-modificato" if dirty else head


def run_nowcast(as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Stima corrente di tutti i modelli del protocollo, aggiunta al registro."""
    as_of = (as_of or pd.Timestamp.today()).normalize()
    observations = cache.load_observations()
    rows = current_nowcasts(
        observations,
        load_series(),
        backtest.protocol_models(),
        load_backtest(),
        as_of,
        cache.dataset_version(observations),
        code_commit(),
    )
    append_to_log(rows, NOWCAST_LOG_PATH)
    first = rows.iloc[0]
    log.info(
        "PIL t/t del trimestre che termina il %s, dati al %s (dataset %s)",
        first["target"].date(), as_of.date(), first["dataset_version"],
    )  # fmt: skip
    log.info(
        "pubblicazione attesa tra %d giorni: intervalli dall'orizzonte a %d giorni. %s",
        first["days_to_publication"], first["horizon_applied"], EXCLUSION_NOTE,
    )  # fmt: skip
    for row in rows.itertuples():
        log.info(
            "%-22s %+.2f%%   80%%: [%+.2f, %+.2f]   50%%: [%+.2f, %+.2f]",
            row.model, row.forecast, row.low80, row.high80, row.low50, row.high50,
        )  # fmt: skip
    return rows


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


def run_backtest(workers: int = 6) -> pd.DataFrame:
    """Backtest del protocollo sulla versione congelata del dataset."""
    version = backtest.DATASET_VERSION
    observations = cache.load_version(version)  # verifica anche l'impronta
    commit = backtest.specification_commit()
    log.info("backtest su dataset %s, specificazione %s", version, commit)
    results = backtest.run_backtest(
        observations,
        load_series(),
        backtest.protocol_models(),
        backtest.protocol_quarters(),
        version,
        commit,
        workers=workers,
    )
    RESULTS_DIR.mkdir(exist_ok=True)
    results.to_csv(BACKTEST_PATH, index=False, float_format="%.10g")
    failed = int((results["status"] != backtest.OK).sum())
    log.info("%d previsioni, %d mancanti -> %s", len(results), failed, BACKTEST_PATH)
    return results


def load_backtest() -> pd.DataFrame:
    return pd.read_csv(BACKTEST_PATH, parse_dates=DATE_COLUMNS, keep_default_na=False,
                       na_values={"forecast": [""], "std": [""], "actual": [""]})  # fmt: skip


def run_evaluation() -> str:
    """Scrive il rapporto con tutte le tabelle del protocollo."""
    report = build_report(load_backtest())
    REPORT_PATH.write_text(report, encoding="utf-8")
    log.info("rapporto scritto in %s", REPORT_PATH)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands: dict[str, Callable[[], object]] = {
        "init-data": init_data,
        "update-data": update_data,
        "redate-data": redate_data,
        "backtest": run_backtest,
        "evaluate": run_evaluation,
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
