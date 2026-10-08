"""Cache locale su disco: serie grezze per fonte e tabella delle osservazioni."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from nowcast.config import DATA_DIR
from nowcast.data.vintages import empty_observations

RAW_DIR = DATA_DIR / "raw"
OBSERVATIONS_PATH = DATA_DIR / "observations.parquet"


def save_raw(series: pd.Series, series_id: str, raw_dir: Path = RAW_DIR) -> Path:
    """Salva la serie così come scaricata, prima di ogni elaborazione."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{series_id}.parquet"
    series.rename("value").rename_axis("date").to_frame().to_parquet(path)
    return path


def load_raw(series_id: str, raw_dir: Path = RAW_DIR) -> pd.Series:
    frame = pd.read_parquet(raw_dir / f"{series_id}.parquet")
    return frame["value"]


def load_observations(path: Path = OBSERVATIONS_PATH) -> pd.DataFrame:
    if not path.exists():
        return empty_observations()
    return pd.read_parquet(path)


def save_observations(observations: pd.DataFrame, path: Path = OBSERVATIONS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = observations.sort_values(["series_id", "ref_period", "release_date"])
    ordered.reset_index(drop=True).to_parquet(path, index=False)


def dataset_version(observations: pd.DataFrame) -> str:
    """Impronta del contenuto della tabella: identifica il dataset usato da una valutazione."""
    ordered = observations.sort_values(["series_id", "ref_period", "release_date"])
    digest = hashlib.sha256(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes())
    return digest.hexdigest()[:12]
