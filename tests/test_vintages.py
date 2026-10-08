import numpy as np
import pandas as pd
import pytest

from nowcast.config import SeriesSpec
from nowcast.data.vintages import (
    ALFRED,
    ESTIMATED,
    FIRST_SEEN,
    REVISION,
    assign_release_dates,
    publication_date,
    snapshot,
    to_panel,
)

TODAY = pd.Timestamp("2026-10-08")
WEEK = pd.Timedelta(days=7)


def spec(sid: str = "ip", lag: int = 40, frequency: str = "M", **kwargs: object) -> SeriesSpec:
    return SeriesSpec(sid, sid, "eurostat", frequency, "none", lag, "real", **kwargs)  # type: ignore[arg-type]


def monthly(values: list[float], end: str = "2026-08-31") -> pd.Series:
    return pd.Series(values, index=pd.date_range(end=end, periods=len(values), freq="ME"))


def values_seen(table: pd.DataFrame, as_of: pd.Timestamp) -> dict[pd.Timestamp, float]:
    return snapshot(table, as_of).set_index("ref_period")["value"].to_dict()


def test_estimated_release_is_period_end_plus_lag() -> None:
    table = assign_release_dates(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    assert table["release_date"].tolist() == [
        pd.Timestamp("2026-08-09"),
        pd.Timestamp("2026-09-09"),
    ]
    assert set(table["release_source"]) == {ESTIMATED}


def test_lag_regimes_apply_by_reference_period() -> None:
    history = ((pd.Timestamp("2017-12-31"), 46),)
    quarters = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2017-12-31", "2018-03-31"]))
    table = assign_release_dates(quarters, spec("gdp", 32, "Q", lag_history=history), TODAY)
    assert table["release_date"].tolist() == [
        pd.Timestamp("2018-02-15"),
        pd.Timestamp("2018-05-02"),
    ]


def test_release_date_never_after_download_day() -> None:
    table = assign_release_dates(monthly([1.0], end="2026-09-30"), spec(lag=40), TODAY)
    assert table["release_date"].iloc[0] == TODAY
    assert table["release_source"].iloc[0] == FIRST_SEEN


def test_missing_values_are_not_observations() -> None:
    table = assign_release_dates(monthly([1.0, np.nan, 3.0]), spec(), TODAY)
    assert len(table) == 2


def test_new_observation_gets_download_date() -> None:
    first = assign_release_dates(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    second = assign_release_dates(monthly([1.0, 2.0, 3.0]), spec(), TODAY + WEEK, first)
    newest = second[second["ref_period"] == pd.Timestamp("2026-08-31")].iloc[0]
    assert (newest["release_date"], newest["release_source"]) == (TODAY + WEEK, FIRST_SEEN)


def test_observed_release_date_survives_later_downloads() -> None:
    first = assign_release_dates(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    second = assign_release_dates(monthly([1.0, 2.0, 3.0]), spec(), TODAY + WEEK, first)
    third = assign_release_dates(monthly([1.0, 2.0, 3.0]), spec(), TODAY + 2 * WEEK, second)
    assert len(third) == 3
    assert third.iloc[-1]["release_date"] == TODAY + WEEK


def test_revision_is_appended_and_old_snapshots_do_not_change() -> None:
    first = assign_release_dates(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    july = pd.Timestamp("2026-07-31")
    before = values_seen(first, TODAY)
    second = assign_release_dates(
        monthly([1.0, 2.5], end="2026-07-31"), spec(), TODAY + WEEK, first
    )
    assert values_seen(second, TODAY) == before  # il passato non viene riscritto
    assert values_seen(second, TODAY + WEEK)[july] == 2.5
    revisions = second[second["release_source"] == REVISION]
    assert revisions[["ref_period", "value", "release_date"]].values.tolist() == [
        [july, 2.5, TODAY + WEEK]
    ]


def test_unchanged_values_do_not_create_revisions() -> None:
    first = assign_release_dates(monthly([1.0, 2.0]), spec(), TODAY)
    second = assign_release_dates(monthly([1.0, 2.0]), spec(), TODAY + WEEK, first)
    assert len(second) == 2


def test_estimated_dates_follow_a_changed_lag() -> None:
    first = assign_release_dates(monthly([1.0], end="2026-07-31"), spec(lag=40), TODAY)
    second = assign_release_dates(monthly([1.0], end="2026-07-31"), spec(lag=10), TODAY, first)
    assert second["release_date"].iloc[0] == pd.Timestamp("2026-08-10")


def test_older_history_added_later_keeps_an_estimated_date() -> None:
    first = assign_release_dates(monthly([2.0], end="2026-08-31"), spec(lag=0), TODAY)
    second = assign_release_dates(monthly([1.0, 2.0]), spec(lag=0), TODAY + WEEK, first)
    assert second.iloc[0]["release_source"] == ESTIMATED


def test_gap_filled_later_is_not_backdated() -> None:
    """Gennaio e marzo scaricati il 1° aprile; febbraio compare solo il 10 aprile."""
    index = pd.DatetimeIndex(["2026-01-31", "2026-03-31"])
    first_day, second_day = pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-10")
    first = assign_release_dates(pd.Series([1.0, 3.0], index=index), spec(lag=0), first_day)
    full = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2026-01-31", periods=3, freq="ME"))
    second = assign_release_dates(full, spec(lag=0), second_day, first)
    february = second[second["ref_period"] == pd.Timestamp("2026-02-28")].iloc[0]
    assert (february["release_date"], february["release_source"]) == (second_day, FIRST_SEEN)
    assert pd.Timestamp("2026-02-28") not in values_seen(second, first_day)


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


def test_publication_date_is_the_first_release() -> None:
    first = assign_release_dates(monthly([1.0], end="2026-07-31"), spec(), TODAY)
    second = assign_release_dates(monthly([1.5], end="2026-07-31"), spec(), TODAY + WEEK, first)
    assert publication_date(second, "ip", pd.Timestamp("2026-07-31")) == pd.Timestamp("2026-09-09")
    with pytest.raises(KeyError):
        publication_date(second, "ip", pd.Timestamp("2030-01-31"))


def test_derived_series_needs_both_components() -> None:
    derived = SeriesSpec(
        "d", "d", "derived", "M", "none", 1, "financial", params={"minus": ["a", "b"]}
    )
    specs = [spec("a", lag=1), spec("b", lag=20), derived]
    obs = pd.concat(
        [
            assign_release_dates(monthly([4.0, 5.0]), specs[0], TODAY),
            assign_release_dates(monthly([1.0, 1.5]), specs[1], TODAY),
        ]
    )
    early = to_panel(snapshot(obs, pd.Timestamp("2026-09-05")), specs, "M")
    late = to_panel(snapshot(obs, pd.Timestamp("2026-09-20")), specs, "M")
    assert early["d"].isna().tolist() == [False, True]
    assert late["d"].tolist() == [3.0, 3.5]


def test_panel_shows_ragged_edge_as_trailing_nan() -> None:
    specs = [spec("fast", lag=0), spec("slow", lag=40), spec("gdp", lag=30, frequency="Q")]
    obs = pd.concat([assign_release_dates(monthly([1.0, 2.0, 3.0]), s, TODAY) for s in specs[:2]])
    panel = to_panel(snapshot(obs, pd.Timestamp("2026-09-15")), specs, "M")
    assert list(panel.columns) == ["fast", "slow"]
    assert panel.index[-1] == pd.Timestamp("2026-08-31")
    assert panel["fast"].notna().all()
    assert panel["slow"].isna().tolist() == [False, False, True]
