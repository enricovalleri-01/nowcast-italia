"""Cache locale su disco: serie grezze, archivio delle osservazioni e sue versioni."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from pandas.api import types

from nowcast.config import DATA_DIR
from nowcast.data.vintages import COLUMNS, ORDER, empty_observations

RAW_DIR = DATA_DIR / "raw"
OBSERVATIONS_PATH = DATA_DIR / "observations.parquet"
VERSIONS_DIR = DATA_DIR / "versions"

_SCHEMA = {
    "series_id": types.is_string_dtype,
    "ref_period": types.is_datetime64_any_dtype,
    "value": types.is_float_dtype,
    "release_date": types.is_datetime64_any_dtype,
    "release_source": types.is_string_dtype,
    "acquired_date": types.is_datetime64_any_dtype,
    "seq": types.is_integer_dtype,
}


def save_raw(series: pd.Series, series_id: str, raw_dir: Path = RAW_DIR) -> Path:
    """Salva la serie così come scaricata, prima di ogni elaborazione."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{series_id}.parquet"
    series.rename("value").rename_axis("date").to_frame().to_parquet(path)
    return path


def load_raw(series_id: str, raw_dir: Path = RAW_DIR) -> pd.Series:
    frame = pd.read_parquet(raw_dir / f"{series_id}.parquet")
    return frame["value"]


def validate_schema(observations: pd.DataFrame) -> None:
    """Rifiuta una tabella con colonne o tipi diversi da quelli dell'archivio."""
    if list(observations.columns) != COLUMNS:
        raise ValueError(f"colonne inattese: {list(observations.columns)}")
    wrong = [c for c, check in _SCHEMA.items() if not check(observations[c])]
    if wrong:
        raise ValueError(f"tipi inattesi nelle colonne {wrong}")


def canonical_order(observations: pd.DataFrame) -> pd.DataFrame:
    return observations.sort_values(["series_id", "ref_period", *ORDER]).reset_index(drop=True)


def dataset_version(observations: pd.DataFrame) -> str:
    """Impronta di schema e contenuto: identifica il dataset usato da una valutazione.

    Non dipende dall'ordine delle righe. Lo schema viene prima validato, poi incluso nei
    byte da cui si calcola l'impronta insieme a una serializzazione testuale dei valori.
    """
    validate_schema(observations)
    schema = json.dumps({c: _SCHEMA[c].__name__ for c in COLUMNS})
    content = canonical_order(observations).to_csv(
        index=False, float_format="%.17g", date_format="%Y-%m-%d"
    )
    return hashlib.sha256((schema + "\n" + content).encode()).hexdigest()[:12]


def load_observations(path: Path = OBSERVATIONS_PATH) -> pd.DataFrame:
    if not path.exists():
        return empty_observations()
    return pd.read_parquet(path)


def save_observations(
    observations: pd.DataFrame, path: Path = OBSERVATIONS_PATH, versions_dir: Path = VERSIONS_DIR
) -> str:
    """Salva l'archivio corrente e una copia immutabile con l'impronta nel nome."""
    version = dataset_version(observations)
    ordered = canonical_order(observations)
    path.parent.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)
    ordered.to_parquet(path, index=False)
    frozen = versions_dir / f"{version}.parquet"
    if not frozen.exists():
        ordered.to_parquet(frozen, index=False)
    return version


def load_version(version: str, versions_dir: Path = VERSIONS_DIR) -> pd.DataFrame:
    """Carica una versione congelata e verifica che il contenuto corrisponda all'impronta."""
    observations = pd.read_parquet(versions_dir / f"{version}.parquet")
    if dataset_version(observations) != version:
        raise ValueError(f"il file della versione {version} non corrisponde alla sua impronta")
    return observations
