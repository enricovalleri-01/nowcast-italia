"""Lettura e validazione del registro delle serie (config/series.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SERIES_PATH = ROOT / "config" / "series.yaml"
DATA_DIR = ROOT / "data"

SOURCES = {"eurostat", "ecb", "fred", "derived"}
FREQUENCIES = {"M", "Q"}
TRANSFORMS = {"none", "diff", "pct_change", "log_diff"}
DFM_EXCLUDE = "exclude"
_COMMON = {"id", "name", "source", "frequency", "transform", "release_lag_days", "block", "role"}
_REQUIRED_PARAMS = {
    "eurostat": {"dataset", "filters"},
    "ecb": {"flow", "key"},
    "fred": {"fred_id"},
    "derived": {"minus"},
}


@dataclass(frozen=True)
class SeriesSpec:
    id: str
    name: str
    source: str
    frequency: str
    transform: str
    release_lag_days: int
    block: str
    role: str = "indicator"
    params: dict[str, Any] = field(default_factory=dict)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def parse_spec(raw: dict[str, Any]) -> SeriesSpec:
    sid = raw.get("id", "<senza id>")
    missing = (_COMMON - {"role"}) - raw.keys()
    _check(not missing, f"{sid}: campi mancanti {sorted(missing)}")
    _check(raw["source"] in SOURCES, f"{sid}: fonte sconosciuta {raw['source']}")
    _check(raw["frequency"] in FREQUENCIES, f"{sid}: frequenza non valida {raw['frequency']}")
    _check(raw["transform"] in TRANSFORMS, f"{sid}: trasformazione non valida {raw['transform']}")
    params = {k: v for k, v in raw.items() if k not in _COMMON}
    dfm = params.get("dfm", raw["transform"])
    _check(dfm in TRANSFORMS | {DFM_EXCLUDE}, f"{sid}: valore di dfm non valido {dfm}")
    absent = _REQUIRED_PARAMS[raw["source"]] - params.keys()
    _check(not absent, f"{sid}: parametri mancanti per {raw['source']}: {sorted(absent)}")
    common = {k: raw[k] for k in _COMMON if k in raw}
    return SeriesSpec(**common, params=params)


def load_series(path: Path = SERIES_PATH) -> list[SeriesSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs = [parse_spec(item) for item in raw["series"]]
    ids = [s.id for s in specs]
    _check(len(ids) == len(set(ids)), "id duplicati in series.yaml")
    for spec in specs:
        if spec.source == "derived":
            unknown = set(spec.params["minus"]) - set(ids)
            _check(not unknown, f"{spec.id}: componenti sconosciute {sorted(unknown)}")
    return specs
