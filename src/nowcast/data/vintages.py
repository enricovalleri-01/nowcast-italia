"""Tabella delle osservazioni con data di rilascio e ricostruzione del set informativo.

Ogni riga è (series_id, ref_period, value, release_date, release_source). Un periodo può
avere più righe: quella di base e una per ogni revisione vista ai download successivi.
Un valore già registrato non viene mai riscritto, così lo snapshot di una data passata
resta identico dopo ogni aggiornamento.

Limite: per lo storico precedente al primo download il valore di base è quello già
rivisto disponibile quel giorno. Per quel tratto il backtest è pseudo real-time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nowcast.config import SeriesSpec

COLUMNS = ["series_id", "ref_period", "value", "release_date", "release_source"]
KEY = ["series_id", "ref_period"]

# Origine della data di rilascio.
ALFRED = "alfred"  # prima pubblicazione dallo storico dei vintage ALFRED
FIRST_SEEN = "first_seen"  # osservazione comparsa tra due download: data del download
ESTIMATED = "estimated_lag"  # fine periodo + ritardo tipico della serie
REVISION = "revision"  # valore rivisto: data del download che l'ha rilevato


def empty_observations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": pd.Series(dtype="str"),
            "ref_period": pd.Series(dtype="datetime64[ns]"),
            "value": pd.Series(dtype="float"),
            "release_date": pd.Series(dtype="datetime64[ns]"),
            "release_source": pd.Series(dtype="str"),
        }
    )


def estimated_release(periods: pd.DatetimeIndex, spec: SeriesSpec) -> pd.DatetimeIndex:
    """Fine periodo più il ritardo di pubblicazione in vigore per quel periodo."""
    return pd.DatetimeIndex(periods + pd.to_timedelta(spec.lag_days(periods), unit="D"))


def _rows(series: pd.Series, spec: SeriesSpec, release: object, source: object) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": spec.id,
            "ref_period": series.index,
            "value": series.to_numpy(),
            "release_date": release,
            "release_source": source,
        }
    )


def _new_rows(
    series: pd.Series, spec: SeriesSpec, today: pd.Timestamp, previous: pd.DataFrame
) -> pd.DataFrame:
    """Righe di base per i periodi mai visti prima.

    Un periodo che compare dentro o dopo la copertura già scaricata è uscito dopo l'ultimo
    download, quindi prende la data di oggi. Lo stesso vale se la data stimata cadrebbe
    nel futuro. Solo lo storico più vecchio di quello già noto riceve una data stimata.
    """
    expected = estimated_release(pd.DatetimeIndex(series.index), spec)
    observed_now = expected > today
    if not previous.empty:
        observed_now = observed_now | (series.index > previous["ref_period"].min())
    release = expected.where(~observed_now, today)
    source = np.where(observed_now, FIRST_SEEN, ESTIMATED)
    return _rows(series, spec, release, source)


def _refresh_estimates(previous: pd.DataFrame, spec: SeriesSpec, today: pd.Timestamp) -> None:
    """Le date stimate seguono i ritardi di series.yaml; quelle osservate non cambiano.

    Una data stimata non può superare quella della prima revisione dello stesso periodo.
    """
    estimated = previous["release_source"] == ESTIMATED
    periods = pd.DatetimeIndex(previous.loc[estimated, "ref_period"])
    limit = previous[previous["release_source"] == REVISION].groupby("ref_period")
    first_revision = limit["release_date"].min().reindex(periods).fillna(today).to_numpy()
    expected = estimated_release(periods, spec).to_numpy()
    previous.loc[estimated, "release_date"] = np.minimum(expected, first_revision)


def _revision_rows(
    series: pd.Series, spec: SeriesSpec, today: pd.Timestamp, previous: pd.DataFrame
) -> pd.DataFrame:
    """Una riga nuova per ogni periodo il cui valore è cambiato rispetto all'ultimo noto."""
    latest = previous.sort_values("release_date").drop_duplicates("ref_period", keep="last")
    last_known = latest.set_index("ref_period")["value"].reindex(series.index)
    changed = ~np.isclose(series.to_numpy(), last_known.to_numpy(), rtol=1e-9, atol=1e-12)
    return _rows(series[changed], spec, today, REVISION)


def _apply_real(table: pd.DataFrame, real: pd.Series) -> None:
    """La data reale di prima pubblicazione sostituisce quella delle righe di base."""
    base = (table["release_source"] != REVISION) & table["ref_period"].isin(real.index)
    table.loc[base, "release_date"] = real.loc[table.loc[base, "ref_period"]].to_numpy()
    table.loc[base, "release_source"] = ALFRED


def assign_release_dates(
    series: pd.Series,
    spec: SeriesSpec,
    today: pd.Timestamp,
    previous: pd.DataFrame | None = None,
    real: pd.Series | None = None,
) -> pd.DataFrame:
    """Aggiorna le righe di una serie con un nuovo download, senza riscrivere il passato."""
    current = series.dropna()
    kept = (previous if previous is not None else empty_observations()).copy()
    seen = current.index.isin(kept["ref_period"])
    _refresh_estimates(kept, spec, today)
    parts = [
        kept,
        _new_rows(current[~seen], spec, today, kept),
        _revision_rows(current[seen], spec, today, kept),
    ]
    table = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    if real is not None:
        _apply_real(table, real)
    return table.sort_values(["ref_period", "release_date"]).reset_index(drop=True)[COLUMNS]


def snapshot(observations: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Per ogni periodo, l'ultimo valore pubblicato entro la data `as_of` (inclusa)."""
    known = observations[observations["release_date"] <= as_of]
    latest = known.sort_values("release_date").drop_duplicates(KEY, keep="last")
    return latest.sort_values(KEY).reset_index(drop=True)


def publication_date(
    observations: pd.DataFrame, series_id: str, period: pd.Timestamp
) -> pd.Timestamp:
    """Data della prima pubblicazione di un'osservazione."""
    rows = observations[
        (observations["series_id"] == series_id) & (observations["ref_period"] == period)
    ]
    if rows.empty:
        raise KeyError(f"{series_id}: nessuna osservazione per {period.date()}")
    return pd.Timestamp(rows["release_date"].min())


def _add_derived(panel: pd.DataFrame, specs: list[SeriesSpec]) -> pd.DataFrame:
    """Serie derivate a - b: calcolate sullo snapshot, note solo se lo sono entrambe."""
    for spec in specs:
        if spec.source == "derived":
            first, second = spec.params["minus"]
            panel[spec.id] = panel[first] - panel[second]
    return panel


def to_panel(snapshot_rows: pd.DataFrame, specs: list[SeriesSpec], frequency: str) -> pd.DataFrame:
    """Panel largo (periodi x serie) in livelli, da uno snapshot, per una frequenza.

    L'indice copre tutti i periodi fino all'ultimo osservato: i NaN in coda sono il
    ragged edge.
    """
    wanted = [s for s in specs if s.frequency == frequency]
    stored = [s.id for s in wanted if s.source != "derived"]
    subset = snapshot_rows[snapshot_rows["series_id"].isin(stored)]
    wide = subset.pivot(index="ref_period", columns="series_id", values="value")
    if not wide.empty:
        alias = {"M": "ME", "Q": "QE"}[frequency]
        wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max(), freq=alias))
    wide = _add_derived(wide.reindex(columns=stored), wanted)
    return wide[[s.id for s in wanted]]
