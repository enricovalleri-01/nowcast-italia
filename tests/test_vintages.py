import numpy as np
import pandas as pd
import pytest

from nowcast.config import SeriesSpec
from nowcast.data.vintages import (
    ALFRED,
    ESTIMATED,
    FIRST_SEEN,
    REVISION,
    import_history,
    publication_date,
    redate,
    snapshot,
    to_panel,
    update,
)

TODAY = pd.Timestamp("2026-10-08")
WEEK = pd.Timedelta(days=7)
JAN, FEB, MAR = (pd.Timestamp(d) for d in ("2026-01-31", "2026-02-28", "2026-03-31"))


def spec(sid: str = "ip", lag: int = 40, frequency: str = "M", **kwargs: object) -> SeriesSpec:
    return SeriesSpec(sid, sid, "eurostat", frequency, "none", lag, "real", **kwargs)  # type: ignore[arg-type]


def monthly(values: list[float], end: str = "2026-08-31") -> pd.Series:
    return pd.Series(values, index=pd.date_range(end=end, periods=len(values), freq="ME"))


def values_seen(table: pd.DataFrame, as_of: pd.Timestamp) -> dict[pd.Timestamp, float]:
    return snapshot(table, as_of).set_index("ref_period")["value"].to_dict()


def all_snapshots(table: pd.DataFrame, until: pd.Timestamp) -> list[dict[pd.Timestamp, float]]:
    return [values_seen(table, day) for day in pd.date_range("2026-01-01", until, freq="D")]


# --- importazione iniziale


def test_import_dates_history_with_the_estimated_lag() -> None:
    table = import_history(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    assert table["release_date"].tolist() == [
        pd.Timestamp("2026-08-09"),
        pd.Timestamp("2026-09-09"),
    ]
    assert set(table["release_source"]) == {ESTIMATED}
    assert (table["seq"] == 0).all() and (table["acquired_date"] == TODAY).all()


def test_lag_regimes_apply_by_reference_period() -> None:
    history = ((pd.Timestamp("2017-12-31"), 46),)
    quarters = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2017-12-31", "2018-03-31"]))
    table = import_history(quarters, spec("gdp", 32, "Q", lag_history=history), TODAY)
    assert table["release_date"].tolist() == [
        pd.Timestamp("2018-02-15"),
        pd.Timestamp("2018-05-02"),
    ]


def test_release_date_never_after_acquisition() -> None:
    table = import_history(monthly([1.0], end="2026-09-30"), spec(lag=40), TODAY)
    assert table["release_date"].iloc[0] == TODAY
    assert table["release_source"].iloc[0] == FIRST_SEEN


def test_missing_values_are_not_observations() -> None:
    assert len(import_history(monthly([1.0, np.nan, 3.0]), spec(), TODAY)) == 2


def test_real_release_dates_override_estimates() -> None:
    real = pd.Series({pd.Timestamp("2026-08-31"): pd.Timestamp("2026-09-03")})
    table = import_history(monthly([1.0, 2.0]), spec(), TODAY, real=real)
    assert table["release_source"].tolist() == [ESTIMATED, ALFRED]
    assert table.iloc[-1]["release_date"] == pd.Timestamp("2026-09-03")


def test_real_release_date_after_acquisition_is_capped() -> None:
    real = pd.Series({pd.Timestamp("2026-08-31"): TODAY + WEEK})
    table = import_history(monthly([1.0]), spec(), TODAY, real=real)
    assert table.iloc[0]["release_date"] == TODAY
    assert table.iloc[0]["release_source"] == FIRST_SEEN


# --- aggiornamento ordinario: solo righe aggiunte


def test_update_requires_an_imported_series() -> None:
    empty = import_history(monthly([1.0]), spec(), TODAY).iloc[:0]
    with pytest.raises(ValueError, match="import_history"):
        update(monthly([1.0]), spec(), TODAY, empty)


def test_new_period_gets_the_download_date() -> None:
    first = import_history(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    second = update(monthly([1.0, 2.0, 3.0]), spec(), TODAY + WEEK, first)
    newest = second[second["ref_period"] == pd.Timestamp("2026-08-31")].iloc[0]
    assert (newest["release_date"], newest["release_source"]) == (TODAY + WEEK, FIRST_SEEN)


def test_update_never_changes_existing_rows() -> None:
    first = import_history(monthly([1.0, 2.0], end="2026-07-31"), spec(lag=40), TODAY)
    # valore rivisto, periodo nuovo e ritardo del registro cambiato nel frattempo
    second = update(monthly([1.0, 2.5, 3.0]), spec(lag=5), TODAY + WEEK, first)
    pd.testing.assert_frame_equal(second.iloc[: len(first)], first)


def test_revision_is_appended_and_past_snapshots_do_not_change() -> None:
    first = import_history(monthly([1.0, 2.0], end="2026-07-31"), spec(), TODAY)
    july = pd.Timestamp("2026-07-31")
    second = update(monthly([1.0, 2.5], end="2026-07-31"), spec(), TODAY + WEEK, first)
    assert all_snapshots(second, TODAY) == all_snapshots(first, TODAY)
    assert values_seen(second, TODAY + WEEK)[july] == 2.5
    revision = second[second["release_source"] == REVISION].iloc[0]
    assert (revision["value"], revision["release_date"], revision["seq"]) == (2.5, TODAY + WEEK, 1)


def test_unchanged_values_do_not_create_revisions() -> None:
    first = import_history(monthly([1.0, 2.0]), spec(), TODAY)
    assert len(update(monthly([1.0, 2.0]), spec(), TODAY + WEEK, first)) == 2


def test_changed_lag_does_not_move_recorded_dates() -> None:
    """Gennaio registrato con ritardo zero; un ritardo diverso non svuota lo snapshot."""
    first_day, second_day = pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-10")
    first = import_history(pd.Series([1.0], index=[JAN]), spec(lag=0), first_day)
    second = update(pd.Series([1.0], index=[JAN]), spec(lag=30), second_day, first)
    assert values_seen(second, pd.Timestamp("2026-02-01")) == {JAN: 1.0}


def test_gap_filled_later_is_not_backdated() -> None:
    """Gennaio e marzo scaricati il 1° aprile; febbraio compare solo il 10 aprile."""
    first_day, second_day = pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-10")
    first = import_history(pd.Series([1.0, 3.0], index=[JAN, MAR]), spec(lag=0), first_day)
    second = update(
        pd.Series([1.0, 2.0, 3.0], index=[JAN, FEB, MAR]), spec(lag=0), second_day, first
    )
    february = second[second["ref_period"] == FEB].iloc[0]
    assert (february["release_date"], february["release_source"]) == (second_day, FIRST_SEEN)
    assert all_snapshots(second, first_day) == all_snapshots(first, first_day)


def test_older_history_added_later_is_not_backdated() -> None:
    """Solo marzo scaricato il 1° aprile; febbraio, più vecchio, arriva il 10 aprile."""
    first_day, second_day = pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-10")
    first = import_history(pd.Series([3.0], index=[MAR]), spec(lag=0), first_day)
    second = update(pd.Series([2.0, 3.0], index=[FEB, MAR]), spec(lag=0), second_day, first)
    assert FEB not in values_seen(second, pd.Timestamp("2026-03-01"))
    assert all_snapshots(second, first_day) == all_snapshots(first, first_day)


def test_period_dropped_by_the_source_is_kept() -> None:
    first = import_history(monthly([1.0, 2.0]), spec(), TODAY)
    second = update(monthly([2.0]), spec(), TODAY + WEEK, first)
    assert len(second) == 2


def test_update_cannot_be_dated_before_the_last_acquisition() -> None:
    first = import_history(monthly([1.0]), spec(), TODAY)
    with pytest.raises(ValueError, match="prima dell'ultima acquisizione"):
        update(monthly([1.0]), spec(), TODAY - WEEK, first)


# --- ordine delle versioni


def revised_twice_same_day() -> pd.DataFrame:
    first = import_history(pd.Series([1.0], index=[JAN]), spec(lag=0), pd.Timestamp("2026-04-01"))
    day = pd.Timestamp("2026-04-10")
    second = update(pd.Series([2.0], index=[JAN]), spec(lag=0), day, first)
    return update(pd.Series([3.0], index=[JAN]), spec(lag=0), day, second)


def test_snapshot_does_not_depend_on_row_order() -> None:
    table = revised_twice_same_day()
    day = pd.Timestamp("2026-04-10")
    for seed in range(5):
        shuffled = table.sample(frac=1, random_state=seed)
        assert values_seen(shuffled, day) == {JAN: 3.0}
    assert values_seen(table.iloc[::-1], day) == {JAN: 3.0}


def test_revision_prevails_over_base_on_the_same_day() -> None:
    """Una correzione del calendario porta la base alla data della revisione."""
    day = pd.Timestamp("2026-04-10")
    first = import_history(pd.Series([1.0], index=[JAN]), spec(lag=0), day)
    second = update(pd.Series([2.0], index=[JAN]), spec(lag=0), day, first)
    moved = redate(second, spec(lag=400))
    assert (moved["release_date"] == day).all()
    assert values_seen(moved, day) == {JAN: 2.0}
    assert values_seen(moved.iloc[::-1], day) == {JAN: 2.0}


def test_revisions_are_compared_with_the_latest_version_regardless_of_order() -> None:
    table = revised_twice_same_day().iloc[::-1]
    unchanged = update(
        pd.Series([3.0], index=[JAN]), spec(lag=0), pd.Timestamp("2026-04-20"), table
    )
    assert len(unchanged) == 3


# --- correzione esplicita del calendario


def test_redate_applies_the_new_calendar_to_estimated_rows_only() -> None:
    first = import_history(monthly([1.0, 2.0], end="2026-07-31"), spec(lag=40), TODAY)
    second = update(monthly([1.0, 2.5, 3.0]), spec(lag=40), TODAY + WEEK, first)
    moved = redate(second, spec(lag=10))
    base = moved[moved["release_source"] == ESTIMATED]
    assert base["release_date"].tolist() == [pd.Timestamp("2026-07-10"), pd.Timestamp("2026-08-10")]
    observed = moved[moved["release_source"].isin([FIRST_SEEN, REVISION])]
    assert (observed["release_date"] == TODAY + WEEK).all()
    assert moved["value"].tolist() == second["value"].tolist()


def test_redate_never_moves_a_base_row_after_its_revision() -> None:
    """Una data reale incoerente non fa tornare lo snapshot dal valore rivisto a quello di base."""
    first = import_history(pd.Series([1.0], index=[JAN]), spec(lag=0), pd.Timestamp("2026-04-01"))
    second = update(pd.Series([2.0], index=[JAN]), spec(lag=0), pd.Timestamp("2026-04-10"), first)
    real = pd.Series({JAN: pd.Timestamp("2026-04-15")})
    moved = redate(second, spec(lag=0), real)
    assert values_seen(moved, pd.Timestamp("2026-04-10")) == {JAN: 2.0}
    assert values_seen(moved, pd.Timestamp("2026-04-15")) == {JAN: 2.0}


# --- snapshot e panel


@pytest.mark.parametrize("as_of", ["2026-08-09", "2026-09-08", "2026-09-09", "2026-10-08"])
def test_snapshot_has_no_look_ahead(as_of: str) -> None:
    table = import_history(monthly([1.0, 2.0, 3.0]), spec(), TODAY)
    seen = snapshot(table, pd.Timestamp(as_of))
    assert (seen["release_date"] <= pd.Timestamp(as_of)).all()
    hidden = table[~table["ref_period"].isin(seen["ref_period"])]
    assert (hidden["release_date"] > pd.Timestamp(as_of)).all()


def test_snapshot_grows_with_time() -> None:
    table = import_history(monthly([1.0, 2.0, 3.0]), spec(), TODAY)
    counts = [
        len(snapshot(table, pd.Timestamp(d))) for d in ("2026-08-08", "2026-08-09", "2026-09-09")
    ]
    assert counts == [0, 1, 2]


def test_publication_date_is_the_first_release() -> None:
    first = import_history(monthly([1.0], end="2026-07-31"), spec(), TODAY)
    second = update(monthly([1.5], end="2026-07-31"), spec(), TODAY + WEEK, first)
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
            import_history(monthly([4.0, 5.0]), specs[0], TODAY),
            import_history(monthly([1.0, 1.5]), specs[1], TODAY),
        ]
    )
    early = to_panel(snapshot(obs, pd.Timestamp("2026-09-05")), specs, "M")
    late = to_panel(snapshot(obs, pd.Timestamp("2026-09-20")), specs, "M")
    assert early["d"].isna().tolist() == [False, True]
    assert late["d"].tolist() == [3.0, 3.5]


def test_panel_shows_ragged_edge_as_trailing_nan() -> None:
    specs = [spec("fast", lag=0), spec("slow", lag=40), spec("gdp", lag=30, frequency="Q")]
    obs = pd.concat([import_history(monthly([1.0, 2.0, 3.0]), s, TODAY) for s in specs[:2]])
    panel = to_panel(snapshot(obs, pd.Timestamp("2026-09-15")), specs, "M")
    assert list(panel.columns) == ["fast", "slow"]
    assert panel.index[-1] == pd.Timestamp("2026-08-31")
    assert panel["fast"].notna().all()
    assert panel["slow"].isna().tolist() == [False, False, True]
