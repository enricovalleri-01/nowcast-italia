"""Trasformazioni delle serie: date di periodo, stazionarietà, aggregazione."""

from __future__ import annotations

import numpy as np
import pandas as pd

_OFFSETS = {"M": pd.offsets.MonthEnd(0), "Q": pd.offsets.QuarterEnd(0)}


def period_end(label: str, frequency: str) -> pd.Timestamp:
    """Ultimo giorno del periodo: '2026-08' -> 2026-08-31, '2026-Q2' -> 2026-06-30."""
    period = pd.Period(label.replace("-Q", "Q"), freq=frequency)
    return period.end_time.normalize()


def to_period_end(dates: pd.DatetimeIndex, frequency: str) -> pd.DatetimeIndex:
    """Porta date qualsiasi interne al periodo all'ultimo giorno del periodo."""
    return pd.DatetimeIndex(dates + _OFFSETS[frequency]).normalize()


def apply_transform(series: pd.Series, kind: str) -> pd.Series:
    """Rende stazionaria una serie in livelli. Le variazioni sono in punti percentuali."""
    if kind == "none":
        return series
    if kind == "diff":
        return series.diff()
    if kind == "pct_change":
        return series.pct_change(fill_method=None) * 100
    if kind == "log_diff":
        return pd.Series(np.log(series), index=series.index).diff() * 100
    raise ValueError(f"trasformazione sconosciuta: {kind}")


def daily_to_monthly(series: pd.Series, last_complete: pd.Timestamp) -> pd.Series:
    """Media mensile di una serie giornaliera, solo per i mesi già conclusi."""
    monthly = series.resample("ME").mean()
    return monthly[monthly.index <= last_complete]


def monthly_to_quarterly(series: pd.Series) -> pd.Series:
    """Media trimestrale; un trimestre con meno di tre mesi osservati resta mancante."""
    grouped = series.resample("QE")
    return grouped.mean().where(grouped.count() == 3)


def standardize(frame: pd.DataFrame) -> pd.DataFrame:
    return (frame - frame.mean()) / frame.std(ddof=1)
