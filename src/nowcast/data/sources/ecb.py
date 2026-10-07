"""Client per l'ECB Data Portal (SDMX REST, risposta CSV, senza chiave)."""

from __future__ import annotations

import io

import pandas as pd
import requests

BASE_URL = "https://data-api.ecb.europa.eu/service/data"
TIMEOUT = 90


def parse_csv(text: str) -> pd.Series:
    """Estrae la serie (data, valore) dal CSV SDMX dell'ECB."""
    frame = pd.read_csv(io.StringIO(text), usecols=["TIME_PERIOD", "OBS_VALUE"])
    index = pd.DatetimeIndex(pd.to_datetime(frame["TIME_PERIOD"]))
    return pd.Series(frame["OBS_VALUE"].to_numpy(dtype=float), index=index).dropna().sort_index()


def fetch(flow: str, key: str) -> pd.Series:
    """Scarica una serie; le date restano quelle della fonte (giornaliere o di inizio periodo)."""
    response = requests.get(
        f"{BASE_URL}/{flow}/{key}", headers={"Accept": "text/csv"}, timeout=TIMEOUT
    )
    if response.status_code != 200:
        raise ValueError(f"ECB {flow}/{key}: HTTP {response.status_code}")
    return parse_csv(response.text)
