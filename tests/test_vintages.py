import numpy as np
import pandas as pd
import pytest

from nowcast.config import SeriesSpec
from nowcast.data.vintages import (
    ALFRED,
    ESTIMATED,
    FIRST_SEEN,
    assign_release_dates,
    derive_difference,
    snapshot,
    to_panel,
)

TODAY = pd.Timestamp("2026-10-08")


def spec(sid: str = "ip", lag: int = 40, frequency: str = "M", **params: object) -> SeriesSpec:
    return SeriesSpec(sid, sid, "eurostat", frequency, "none", lag, "real", params=dict(params))


def monthly(values: list[float], end: str = "2026-08-31") -> pd.Series:
    return pd.Series(values, index=pd.date_range(end=end, periods=len(values), freq="ME"))


def test_estimated_release_is_period_end_plus_lag() -> None:
    table = assign_release_dates(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    assert table["release_date"].tolist() == [
        pd.Timestamp("2026-08-09"),
        pd.Timestamp("2026-09-09"),
    ]
    assert set(table["release_source"]) == {ESTIMATED}


def test_release_date_never_after_download_day() -> None:
    table = assign_release_dates(monthly([1.0], end="2026-09-30"), spec(lag=40), TODAY)
    assert table["release_date"].iloc[0] == TODAY
    assert table["release_source"].iloc[0] == FIRST_SEEN


def test_missing_values_are_not_observations() -> None:
    table = assign_release_dates(monthly([1.0, np.nan, 3.0]), spec(), TODAY)
    assert len(table) == 2


def test_new_observation_gets_download_date_and_old_ones_keep_theirs() -> None:
    first = assign_release_dates(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    later = pd.Timestamp("2026-10-15")
    second = assign_release_dates(monthly([1.0, 2.5, 3.0]), spec(), later, previous=first)
    assert second["release_date"].tolist()[:2] == first["release_date"].tolist()
    assert second["value"].tolist() == [1.0, 2.5, 3.0]  # il valore rivisto sostituisce il vecchio
    assert second.iloc[-1]["release_date"] == later
    assert second.iloc[-1]["release_source"] == FIRST_SEEN


def test_observed_release_date_survives_later_downloads() -> None:
    first = assign_release_dates(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    second = assign_release_dates(
        monthly([1.0, 2.0, 3.0]), spec(), TODAY + pd.Timedelta(days=7), first
    )
    third = assign_release_dates(
        monthly([1.0, 2.0, 3.0]), spec(), TODAY + pd.Timedelta(days=14), second
    )
    assert third.iloc[-1]["release_date"] == TODAY + pd.Timedelta(days=7)
    assert third.iloc[-1]["release_source"] == FIRST_SEEN


def test_estimated_dates_follow_a_changed_lag() -> None:
    first = assign_release_dates(monthly([1.0], end="2026-07-31"), spec(lag=40), TODAY)
    second = assign_release_dates(monthly([1.0], end="2026-07-31"), spec(lag=10), TODAY, first)
    assert second["release_date"].iloc[0] == pd.Timestamp("2026-08-10")


def test_backfilled_history_is_not_marked_as_newly_released() -> None:
    first = assign_release_dates(monthly([2.0], end="2026-08-31"), spec(), TODAY)
    second = assign_release_dates(monthly([1.0, 2.0]), spec(), TODAY, previous=first)
    assert second.iloc[0]["release_source"] == ESTIMATED


def test_real_release_dates_override_estimates() -> None:
    real = pd.Series({pd.Timestamp("2026-08-31"): pd.Timestamp("2026-09-03")})
    table = assign_release_dates(monthly([1.0, 2.0]), spec(), TODAY, real=real)
    assert table["release_source"].tolist() == [ESTIMATED, ALFRED]
    assert table.iloc[-1]["release_date"] == pd.Timestamp("2026-09-03")


@pytest.mark.parametrize("as_of", ["2026-08-09", "2026-09-08", "2026-09-09", "2026-10-08"])
def test_snapshot_has_no_look_ahead(as_of: str) -> None:
    table = assign_release_dates(monthly([1.0, 2.0, 3.0]), spec(), TODAY)
    seen = snapshot(table, pd.Timestamp(as_of))
    assert (seen["release_date"] <= pd.Timestamp(as_of)).all()
    hidden = table[~table["ref_period"].isin(seen["ref_period"])]
    assert (hidden["release_date"] > pd.Timestamp(as_of)).all()


def test_snapshot_grows_with_time() -> None:
    table = assign_release_dates(monthly([1.0, 2.0, 3.0]), spec(), TODAY)
    counts = [
        len(snapshot(table, pd.Timestamp(d))) for d in ("2026-08-08", "2026-08-09", "2026-09-09")
    ]
    assert counts == [0, 1, 2]


def test_derived_series_waits_for_slowest_component() -> None:
    fast = assign_release_dates(monthly([4.0, 5.0]), spec("a", lag=1), TODAY)
    slow = assign_release_dates(monthly([1.0, 1.5]), spec("b", lag=20), TODAY)
    derived = derive_difference(pd.concat([fast, slow]), spec("d", minus=["a", "b"]))
    assert derived["value"].tolist() == [3.0, 3.5]
    assert derived["release_date"].tolist() == slow["release_date"].tolist()


def test_panel_shows_ragged_edge_as_trailing_nan() -> None:
    specs = [spec("fast", lag=0), spec("slow", lag=40), spec("gdp", lag=30, frequency="Q")]
    obs = pd.concat([assign_release_dates(monthly([1.0, 2.0, 3.0]), s, TODAY) for s in specs[:2]])
    panel = to_panel(snapshot(obs, pd.Timestamp("2026-09-15")), specs, "M")
    assert list(panel.columns) == ["fast", "slow"]
    assert panel.index[-1] == pd.Timestamp("2026-08-31")
    assert panel["fast"].notna().all()
    assert panel["slow"].isna().tolist() == [False, False, True]
