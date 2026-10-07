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
