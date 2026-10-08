"""Archivio delle osservazioni con data di rilascio e ricostruzione del set informativo.

Ogni riga è una versione di un'osservazione: (series_id, ref_period, value, release_date,
release_source, acquired_date, seq). Un periodo ha una riga di base (seq 0) e una riga
in più per ogni revisione rilevata ai download successivi.

L'archivio cresce solo per aggiunta. Tre operazioni distinte lo modificano:

- `import_history`: importazione iniziale dello storico di una serie, con date stimate;
- `update`: aggiornamento ordinario, che aggiunge righe e non tocca quelle esistenti;
- `redate`: correzione esplicita del calendario, che produce una nuova versione del dataset.

Solo `update` garantisce che gli snapshot delle date passate restino identici. Le altre
due creano deliberatamente un dataset diverso, riconoscibile dall'impronta.

Limite: nell'importazione iniziale il valore di base è quello già rivisto disponibile
quel giorno. Per quel tratto di storia il backtest è pseudo real-time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nowcast.config import SeriesSpec

COLUMNS = [
    "series_id",
    "ref_period",
    "value",
    "release_date",
    "release_source",
    "acquired_date",
    "seq",
]
KEY = ["series_id", "ref_period"]
# Ordine totale delle versioni di un periodo: a parità di data prevale la più recente.
ORDER = ["release_date", "seq"]

# Origine della data di rilascio.
ALFRED = "alfred"  # prima pubblicazione dallo storico dei vintage ALFRED
FIRST_SEEN = "first_seen"  # data del download in cui il periodo è comparso
ESTIMATED = "estimated_lag"  # fine periodo + ritardo di pubblicazione dell'epoca
REVISION = "revision"  # valore rivisto: data del download che l'ha rilevato


def empty_observations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": pd.Series(dtype="str"),
            "ref_period": pd.Series(dtype="datetime64[ns]"),
            "value": pd.Series(dtype="float"),
            "release_date": pd.Series(dtype="datetime64[ns]"),
            "release_source": pd.Series(dtype="str"),
            "acquired_date": pd.Series(dtype="datetime64[ns]"),
            "seq": pd.Series(dtype="int64"),
        }
    )


def estimated_release(periods: pd.DatetimeIndex, spec: SeriesSpec) -> pd.DatetimeIndex:
    """Fine periodo più il ritardo di pubblicazione in vigore per quel periodo."""
    return pd.DatetimeIndex(periods + pd.to_timedelta(spec.lag_days(periods), unit="D"))


def _rows(
    series: pd.Series,
    spec: SeriesSpec,
    release: object,
    source: object,
    acquired: pd.Timestamp,
    seq: object,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "series_id": spec.id,
            "ref_period": series.index,
            "value": series.to_numpy(dtype=float),
            "release_date": release,
            "release_source": source,
            "acquired_date": acquired,
            "seq": seq,
        }
    )
    return frame.astype({"seq": "int64"})[COLUMNS]


def base_dates(
    periods: pd.DatetimeIndex,
    spec: SeriesSpec,
    acquired: pd.DatetimeIndex,
    real: pd.Series | None,
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Data di rilascio e origine delle righe di base.

    Nell'ordine: data reale ALFRED se nota, altrimenti data stimata dal calendario. Nessuna
    delle due può superare la data di acquisizione: un dato già in archivio era pubblico.
    """
    release = estimated_release(periods, spec)
    source = np.full(len(periods), ESTIMATED, dtype=object)
    if real is not None:
        known = periods.isin(real.index)
        release = release.where(~known, pd.DatetimeIndex(real.reindex(periods)))
        source[known] = ALFRED
    late = release > acquired
    source[late] = FIRST_SEEN
    return release.where(~late, acquired), source


def import_history(
    series: pd.Series, spec: SeriesSpec, today: pd.Timestamp, real: pd.Series | None = None
) -> pd.DataFrame:
    """Importazione iniziale dello storico di una serie non ancora in archivio."""
    current = series.dropna()
    periods = pd.DatetimeIndex(current.index)
    acquired = pd.DatetimeIndex([today] * len(periods))
    release, source = base_dates(periods, spec, acquired, real)
    return _rows(current, spec, release, source, today, 0)


def latest_versions(rows: pd.DataFrame) -> pd.DataFrame:
    """Per ogni (serie, periodo) la versione più recente secondo l'ordine totale."""
    return rows.sort_values(ORDER).drop_duplicates(KEY, keep="last")


def _revision_rows(
    series: pd.Series, spec: SeriesSpec, today: pd.Timestamp, previous: pd.DataFrame
) -> pd.DataFrame:
    """Una riga nuova per ogni periodo il cui valore è cambiato rispetto all'ultimo noto."""
    latest = latest_versions(previous).set_index("ref_period").reindex(series.index)
    changed = ~np.isclose(series.to_numpy(), latest["value"].to_numpy(), rtol=1e-9, atol=1e-12)
    next_seq = latest.loc[changed, "seq"].to_numpy() + 1
    return _rows(series[changed], spec, today, REVISION, today, next_seq)


def update(
    series: pd.Series, spec: SeriesSpec, today: pd.Timestamp, previous: pd.DataFrame
) -> pd.DataFrame:
    """Aggiornamento ordinario: aggiunge righe, non modifica né rimuove quelle esistenti.

    Ogni periodo mai visto prende la data di oggi, anche se è più vecchio della copertura
    già in archivio: non c'è prova che fosse pubblico prima. Un valore cambiato diventa
    una revisione datata oggi.
    """
    if previous.empty:
        raise ValueError(f"{spec.id}: serie assente dall'archivio, serve import_history")
    if today < previous["acquired_date"].max():
        raise ValueError(f"{spec.id}: aggiornamento datato prima dell'ultima acquisizione")
    current = series.dropna()
    seen = current.index.isin(previous["ref_period"])
    new = _rows(current[~seen], spec, today, FIRST_SEEN, today, 0)
    revisions = _revision_rows(current[seen], spec, today, previous)
    parts = [p for p in (previous[COLUMNS], new, revisions) if not p.empty]
    return pd.concat(parts, ignore_index=True)


def redate(previous: pd.DataFrame, spec: SeriesSpec, real: pd.Series | None = None) -> pd.DataFrame:
    """Riapplica il calendario alle righe di base con data stimata o ALFRED.

    Cambia il contenuto degli snapshot passati: va usata solo come correzione esplicita,
    che genera una nuova versione del dataset. Le date osservate (first_seen, revision)
    non vengono toccate.
    """
    table = previous[COLUMNS].copy()
    base = (table["seq"] == 0) & table["release_source"].isin([ESTIMATED, ALFRED])
    periods = pd.DatetimeIndex(table.loc[base, "ref_period"])
    acquired = pd.DatetimeIndex(table.loc[base, "acquired_date"])
    release, source = base_dates(periods, spec, acquired, real)
    table.loc[base, "release_date"] = release.to_numpy()
    table.loc[base, "release_source"] = source
    return table


def snapshot(observations: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Per ogni periodo, l'ultima versione pubblicata entro la data `as_of` (inclusa)."""
    known = observations[observations["release_date"] <= as_of]
    return latest_versions(known).sort_values(KEY).reset_index(drop=True)


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
