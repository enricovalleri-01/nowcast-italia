import pandas as pd
import pytest

from nowcast.config import load_series, parse_spec

BASE = {
    "id": "x",
    "name": "X",
    "source": "fred",
    "fred_id": "ABC",
    "frequency": "M",
    "transform": "none",
    "release_lag_days": 5,
    "block": "energy",
}


def test_registry_is_valid_and_has_one_quarterly_target() -> None:
    specs = load_series()
    targets = [s for s in specs if s.role == "target"]
    assert [(t.id, t.frequency) for t in targets] == [("gdp", "Q")]
    assert all(s.release_lag_days >= 0 for s in specs)


def test_source_parameters_go_to_params() -> None:
    spec = parse_spec(BASE)
    assert spec.params == {"fred_id": "ABC"} and spec.role == "indicator"


@pytest.mark.parametrize(
    "change",
    [{"source": "bloomberg"}, {"frequency": "D"}, {"transform": "sqrt"}, {"fred_id": None}],
)
def test_invalid_spec_is_rejected(change: dict) -> None:
    raw = {k: v for k, v in {**BASE, **change}.items() if v is not None}
    with pytest.raises(ValueError):
        parse_spec(raw)


def test_lag_history_selects_the_regime_of_each_period() -> None:
    raw = {**BASE, "release_lag_days": 38, "release_lag_history": [
        {"until": "2016-12-31", "days": 56}, {"until": "2017-12-31", "days": 43}]}  # fmt: skip
    spec = parse_spec(raw)
    periods = pd.DatetimeIndex(["2016-12-31", "2017-01-31", "2017-12-31", "2018-01-31"])
    assert spec.lag_days(periods).tolist() == [56, 43, 43, 38]
    assert "release_lag_history" not in spec.params


def test_lag_history_must_be_chronological() -> None:
    raw = {**BASE, "release_lag_history": [
        {"until": "2017-12-31", "days": 43}, {"until": "2016-12-31", "days": 56}]}  # fmt: skip
    with pytest.raises(ValueError, match="ordine"):
        parse_spec(raw)
