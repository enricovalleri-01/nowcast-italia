"""Comandi del progetto. Uso: python -m nowcast.pipeline update-data"""

from __future__ import annotations

import argparse
import logging

import pandas as pd
from dotenv import load_dotenv

from nowcast.config import ROOT, SeriesSpec, load_series
from nowcast.data import cache
from nowcast.data.sources import ecb, eurostat, fred
from nowcast.data.vintages import assign_release_dates, derive_difference
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
    log.info("%-16s %4d oss.  ultimo %s", spec.id, len(table), table["ref_period"].max().date())
    return table


def update_data(today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Aggiorna tutte le serie e riscrive la tabella delle osservazioni."""
    today = (today or pd.Timestamp.today()).normalize()
    specs = load_series()
    previous = cache.load_observations()
    tables = [update_series(s, previous, today) for s in specs if s.source != "derived"]
    observations = pd.concat(tables, ignore_index=True)
    derived = [derive_difference(observations, s) for s in specs if s.source == "derived"]
    observations = pd.concat([observations, *derived], ignore_index=True)
    cache.save_observations(observations)
    return observations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["update-data"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(ROOT / ".env")
    if args.command == "update-data":
        update_data()


if __name__ == "__main__":
    main()
