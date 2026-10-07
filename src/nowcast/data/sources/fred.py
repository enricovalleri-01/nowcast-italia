"""Client per FRED/ALFRED. La chiave arriva dalla variabile d'ambiente FRED_API_KEY."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests

from nowcast.transforms import to_period_end

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
TIMEOUT = 90
ALL_VINTAGES = {"realtime_start": "1776-07-04", "realtime_end": "9999-12-31"}


def api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise RuntimeError("FRED_API_KEY non impostata: aggiungila al file .env")
    return key


def _get(series_id: str, extra: dict[str, str]) -> list[dict[str, Any]]:
    params = {"series_id": series_id, "api_key": api_key(), "file_type": "json", **extra}
    response = requests.get(BASE_URL, params=params, timeout=TIMEOUT)
    if response.status_code != 200:
        # Il testo dell'errore non viene riportato: l'URL contiene la chiave.
        raise ValueError(f"FRED {series_id}: HTTP {response.status_code}")
    observations: list[dict[str, Any]] = response.json()["observations"]
    return observations


def parse_observations(rows: list[dict[str, Any]], frequency: str) -> pd.Series:
    """Ultimo valore disponibile per ogni periodo; FRED indica i mancanti con '.'."""
    frame = pd.DataFrame(rows)
    frame = frame[frame["value"] != "."]
    index = to_period_end(pd.DatetimeIndex(pd.to_datetime(frame["date"])), frequency)
    return pd.Series(frame["value"].astype(float).to_numpy(), index=index).sort_index()


def parse_first_releases(rows: list[dict[str, Any]], frequency: str) -> pd.Series:
    """Data della prima pubblicazione di ogni periodo, dallo storico dei vintage.

    I periodi già presenti nel primo vintage archiviato sono esclusi: per loro la data
    indica l'inizio dell'archivio, non la pubblicazione.
    """
    frame = pd.DataFrame(rows)
    frame = frame[frame["value"] != "."]
    frame["realtime_start"] = pd.to_datetime(frame["realtime_start"])
    first = frame.groupby("date")["realtime_start"].min()
    first = first[first > first.min()]
    index = to_period_end(pd.DatetimeIndex(pd.to_datetime(first.index)), frequency)
    return pd.Series(first.to_numpy(), index=index).sort_index()


def fetch(series_id: str, frequency: str) -> pd.Series:
    return parse_observations(_get(series_id, {}), frequency)


def fetch_first_releases(series_id: str, frequency: str) -> pd.Series:
    return parse_first_releases(_get(series_id, ALL_VINTAGES), frequency)
