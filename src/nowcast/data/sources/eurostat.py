"""Client per l'API Statistics di Eurostat (JSON-stat 2.0, senza chiave)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from nowcast.transforms import period_end

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
TIMEOUT = 90


def parse_jsonstat(payload: dict[str, Any], frequency: str) -> pd.Series:
    """Converte una risposta JSON-stat che contiene una sola serie storica."""
    if "error" in payload:
        raise ValueError(f"errore Eurostat: {payload['error']}")
    sizes = dict(zip(payload["id"], payload["size"], strict=True))
    extra = {dim: n for dim, n in sizes.items() if dim != "time" and n != 1}
    if extra:
        raise ValueError(f"i filtri non identificano una sola serie: {extra}")
    positions = payload["dimension"]["time"]["category"]["index"]
    labels = {pos: label for label, pos in positions.items()}
    values = {period_end(labels[int(k)], frequency): float(v) for k, v in payload["value"].items()}
    return pd.Series(values, dtype=float).sort_index()


def fetch(dataset: str, filters: dict[str, str], frequency: str) -> pd.Series:
    params = {**filters, "format": "JSON"}
    response = requests.get(f"{BASE_URL}/{dataset}", params=params, timeout=TIMEOUT)
    if response.status_code != 200:
        raise ValueError(f"Eurostat {dataset}: HTTP {response.status_code}")
    return parse_jsonstat(response.json(), frequency)
