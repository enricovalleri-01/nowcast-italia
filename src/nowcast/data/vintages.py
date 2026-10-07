"""Tabella delle osservazioni con data di rilascio e ricostruzione del set informativo.

Ogni riga è (series_id, ref_period, value, release_date, release_source). Il valore è
quello dell'ultimo download: la tabella dice *quando* un dato è diventato noto, non
com'era prima delle revisioni. Per questo il backtest è pseudo real-time.
"""

from __future__ import annotations

import pandas as pd

from nowcast.config import SeriesSpec

COLUMNS = ["series_id", "ref_period", "value", "release_date", "release_source"]

# Affidabilità decrescente della data di rilascio.
ALFRED = "alfred"  # prima pubblicazione dallo storico dei vintage ALFRED
FIRST_SEEN = "first_seen"  # osservazione comparsa tra due download: data del download
ESTIMATED = "estimated_lag"  # fine periodo + ritardo tipico della serie


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


def _estimated(series: pd.Series, spec: SeriesSpec, today: pd.Timestamp) -> pd.DataFrame:
    """Fine periodo + ritardo tipico.

    Se il ritardo stimato cadrebbe dopo oggi il dato è comunque già in mano: la data
    diventa quella del download, che è un'osservazione diretta.
    """
    expected = series.index + pd.Timedelta(days=spec.release_lag_days)
    early = expected > today
    return pd.DataFrame(
        {
            "series_id": spec.id,
            "ref_period": series.index,
            "value": series.to_numpy(),
            "release_date": expected.where(~early, today),
            "release_source": pd.Series(early).map({True: FIRST_SEEN, False: ESTIMATED}).to_numpy(),
        }
    )


def _mark_first_seen(table: pd.DataFrame, previous: pd.DataFrame, today: pd.Timestamp) -> None:
    """Le osservazioni più recenti di tutte quelle già note sono uscite dopo l'ultimo download."""
    if previous.empty:
        return
    is_new = table["ref_period"] > previous["ref_period"].max()
    table.loc[is_new, "release_date"] = today
    table.loc[is_new, "release_source"] = FIRST_SEEN


def _keep_previous(table: pd.DataFrame, previous: pd.DataFrame) -> None:
    """Una data osservata a un download precedente non viene riscritta.

    Le date stimate invece si ricalcolano sempre, così seguono le modifiche ai ritardi
    in series.yaml.
    """
    known = previous[previous["release_source"] == FIRST_SEEN].set_index("ref_period")
    seen = table["ref_period"].isin(known.index)
    periods = table.loc[seen, "ref_period"]
    table.loc[seen, "release_date"] = known.loc[periods, "release_date"].to_numpy()
    table.loc[seen, "release_source"] = FIRST_SEEN


def _apply_real(table: pd.DataFrame, real: pd.Series) -> None:
    has_real = table["ref_period"].isin(real.index)
    table.loc[has_real, "release_date"] = real.loc[table.loc[has_real, "ref_period"]].to_numpy()
    table.loc[has_real, "release_source"] = ALFRED


def assign_release_dates(
    series: pd.Series,
    spec: SeriesSpec,
    today: pd.Timestamp,
    previous: pd.DataFrame | None = None,
    real: pd.Series | None = None,
) -> pd.DataFrame:
    """Costruisce le righe di una serie scegliendo la data di rilascio più affidabile."""
    table = _estimated(series.dropna(), spec, today)
    if previous is not None:
        _mark_first_seen(table, previous, today)
        _keep_previous(table, previous)
    if real is not None:
        _apply_real(table, real)
    return table[COLUMNS]


def derive_difference(observations: pd.DataFrame, spec: SeriesSpec) -> pd.DataFrame:
    """Serie derivata a - b: nota solo quando lo sono entrambe le componenti."""
    first, second = spec.params["minus"]
    a = observations[observations["series_id"] == first].set_index("ref_period")
    b = observations[observations["series_id"] == second].set_index("ref_period")
    common = a.index.intersection(b.index)
    a, b = a.loc[common], b.loc[common]
    b_later = b["release_date"] > a["release_date"]
    return pd.DataFrame(
        {
            "series_id": spec.id,
            "ref_period": common,
            "value": (a["value"] - b["value"]).to_numpy(),
            "release_date": b["release_date"].where(b_later, a["release_date"]).to_numpy(),
            "release_source": b["release_source"].where(b_later, a["release_source"]).to_numpy(),
        }
    )[COLUMNS]


def snapshot(observations: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Le osservazioni già pubblicate alla data `as_of` (inclusa)."""
    return observations[observations["release_date"] <= as_of].reset_index(drop=True)


def to_panel(observations: pd.DataFrame, specs: list[SeriesSpec], frequency: str) -> pd.DataFrame:
    """Panel largo (periodi x serie) in livelli per le serie di una frequenza.

    L'indice copre tutti i periodi fino all'ultimo osservato: i NaN in coda sono il
    ragged edge.
    """
    ids = [s.id for s in specs if s.frequency == frequency]
    subset = observations[observations["series_id"].isin(ids)]
    wide = subset.pivot(index="ref_period", columns="series_id", values="value")
    if wide.empty:
        return wide.reindex(columns=ids)
    alias = {"M": "ME", "Q": "QE"}[frequency]
    full_index = pd.date_range(wide.index.min(), wide.index.max(), freq=alias)
    return wide.reindex(index=full_index, columns=ids)
