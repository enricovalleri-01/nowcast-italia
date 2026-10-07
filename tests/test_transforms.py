import numpy as np
import pandas as pd
import pytest

from nowcast.transforms import (
    apply_transform,
    daily_to_monthly,
    monthly_to_quarterly,
    period_end,
    standardize,
    to_period_end,
)


def test_period_end_monthly_and_quarterly() -> None:
    assert period_end("2026-08", "M") == pd.Timestamp("2026-08-31")
    assert period_end("2024-02", "M") == pd.Timestamp("2024-02-29")
    assert period_end("2026-Q2", "Q") == pd.Timestamp("2026-06-30")


def test_to_period_end_moves_period_start_to_end() -> None:
    dates = pd.DatetimeIndex(["2026-04-01", "2026-06-30"])
    assert list(to_period_end(dates, "Q")) == [pd.Timestamp("2026-06-30")] * 2
    assert list(to_period_end(dates, "M")) == [
        pd.Timestamp("2026-04-30"),
        pd.Timestamp("2026-06-30"),
    ]


def test_apply_transform_values() -> None:
    s = pd.Series([100.0, 110.0, 99.0])
    assert apply_transform(s, "none").equals(s)
    assert apply_transform(s, "diff").tolist()[1:] == [10.0, -11.0]
    assert apply_transform(s, "pct_change").tolist()[1:] == pytest.approx([10.0, -10.0])
    assert apply_transform(s, "log_diff")[1] == pytest.approx(100 * np.log(1.1))


def test_pct_change_does_not_bridge_missing_values() -> None:
    s = pd.Series([100.0, np.nan, 121.0])
    assert apply_transform(s, "pct_change").isna().all()


def test_apply_transform_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        apply_transform(pd.Series([1.0]), "boh")


def test_daily_to_monthly_drops_month_in_progress() -> None:
    days = pd.date_range("2026-08-01", "2026-10-06", freq="D")
    daily = pd.Series(np.where(days.month == 8, 2.0, 4.0), index=days)
    monthly = daily_to_monthly(daily, pd.Timestamp("2026-09-30"))
    assert monthly.to_dict() == {pd.Timestamp("2026-08-31"): 2.0, pd.Timestamp("2026-09-30"): 4.0}


def test_monthly_to_quarterly_requires_three_months() -> None:
    idx = pd.date_range("2026-01-31", periods=5, freq="ME")
    q = monthly_to_quarterly(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx))
    assert q[pd.Timestamp("2026-03-31")] == 2.0
    assert np.isnan(q[pd.Timestamp("2026-06-30")])


def test_standardize_gives_zero_mean_unit_variance() -> None:
    z = standardize(pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [10.0, 30.0, 20.0]}))
    assert z.mean().abs().max() == pytest.approx(0.0)
    assert z.std(ddof=1).tolist() == pytest.approx([1.0, 1.0])
