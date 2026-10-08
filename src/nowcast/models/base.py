"""Set informativo e interfaccia comune dei modelli di nowcasting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from nowcast.config import DFM_EXCLUDE, SeriesSpec
from nowcast.data.vintages import snapshot, to_panel
from nowcast.transforms import apply_transform

SAMPLE_START = pd.Timestamp("2000-01-01")

Window = tuple[pd.Timestamp, pd.Timestamp]

# Crollo e rimbalzo del 2020. Escluderli dalla stima è una scelta fatta col senno di poi:
# i modelli principali non la applicano, serve solo alle varianti ex post.
COVID_WINDOW: Window = (pd.Timestamp("2020-03-01"), pd.Timestamp("2020-09-30"))


@dataclass(frozen=True)
class InfoSet:
    """Ciò che era noto alla data `as_of`: livelli mensili e crescita t/t del PIL."""

    as_of: pd.Timestamp
    monthly_levels: pd.DataFrame
    gdp_growth: pd.Series
    transforms: dict[str, str]
    dfm_transforms: dict[str, str]  # solo le serie che entrano nel DFM


@dataclass(frozen=True)
class Nowcast:
    model: str
    target: pd.Timestamp
    mean: float
    std: float


class Model(Protocol):
    name: str

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast: ...


def build_info(observations: pd.DataFrame, specs: list[SeriesSpec], as_of: pd.Timestamp) -> InfoSet:
    """Ricostruisce il set informativo di una data dalla tabella delle osservazioni."""
    known = snapshot(observations, as_of)
    monthly = to_panel(known, specs, "M")
    gdp_level = to_panel(known, specs, "Q")["gdp"]
    growth = apply_transform(gdp_level, "pct_change").dropna()
    monthly_specs = [s for s in specs if s.frequency == "M"]
    transforms = {s.id: s.transform for s in monthly_specs}
    dfm = {s.id: s.params.get("dfm", s.transform) for s in monthly_specs}
    return InfoSet(
        as_of=as_of,
        monthly_levels=monthly[monthly.index >= SAMPLE_START],
        gdp_growth=growth[growth.index >= SAMPLE_START].rename("gdp"),
        transforms=transforms,
        dfm_transforms={k: v for k, v in dfm.items() if v != DFM_EXCLUDE},
    )


def next_unpublished_quarter(info: InfoSet) -> pd.Timestamp:
    """Il primo trimestre il cui PIL non è ancora noto: l'oggetto del nowcast."""
    last = pd.Timestamp(info.gdp_growth.index[-1])
    return pd.Timestamp(last + pd.offsets.QuarterEnd(1)).normalize()


def quarters_between(last: pd.Timestamp, target: pd.Timestamp) -> int:
    return int(target.to_period("Q").ordinal - last.to_period("Q").ordinal)


def months_between(last: pd.Timestamp, target: pd.Timestamp) -> int:
    return int(target.to_period("M").ordinal - last.to_period("M").ordinal)


def in_window(index: pd.Index, window: Window | None) -> pd.Series:
    """True per i periodi che cadono nella finestra; tutto False se la finestra è None."""
    dates = pd.DatetimeIndex(index)
    if window is None:
        return pd.Series(False, index=index)
    return pd.Series((dates >= window[0]) & (dates <= window[1]), index=index)


def mask_window(data: pd.Series, window: Window | None) -> pd.Series:
    """Sostituisce con NaN i periodi della finestra: restano fuori dalla stima dei parametri."""
    return data.mask(in_window(data.index, window))


def variant_name(name: str, window: Window | None) -> str:
    """Le varianti stimate con una finestra esclusa sono riconoscibili dal nome."""
    return name if window is None else f"{name}_expost"


def stationary_panel(info: InfoSet, transforms: dict[str, str] | None = None) -> pd.DataFrame:
    """Applica a ogni indicatore mensile la sua trasformazione (di default quella del registro)."""
    kinds = transforms if transforms is not None else info.transforms
    return pd.DataFrame({c: apply_transform(info.monthly_levels[c], kinds[c]) for c in kinds})
