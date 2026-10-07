import pandas as pd
import pytest

from nowcast.data.sources import ecb, eurostat, fred


def _jsonstat(sizes: list[int]) -> dict:
    return {
        "id": ["freq", "geo", "time"],
        "size": sizes,
        "dimension": {"time": {"category": {"index": {"2026-06": 0, "2026-07": 1, "2026-08": 2}}}},
        "value": {"0": 94.0, "2": 95.5},
    }


def test_eurostat_parser_keeps_gaps_out_and_uses_period_end() -> None:
    series = eurostat.parse_jsonstat(_jsonstat([1, 1, 3]), "M")
    assert series.to_dict() == {pd.Timestamp("2026-06-30"): 94.0, pd.Timestamp("2026-08-31"): 95.5}


def test_eurostat_parser_rejects_multiple_series() -> None:
    with pytest.raises(ValueError, match="una sola serie"):
        eurostat.parse_jsonstat(_jsonstat([1, 2, 3]), "M")


def test_eurostat_parser_raises_on_api_error() -> None:
    with pytest.raises(ValueError, match="errore Eurostat"):
        eurostat.parse_jsonstat({"error": [{"status": 404}]}, "M")


def test_ecb_parser_reads_dates_and_values() -> None:
    text = "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS\nk,2026-10-06,2.5,A\nk,2026-10-05,2.5,A\n"
    series = ecb.parse_csv(text)
    assert list(series.index) == [pd.Timestamp("2026-10-05"), pd.Timestamp("2026-10-06")]
    assert series.iloc[-1] == 2.5


FRED_ROWS = [
    {"date": "2026-01-01", "realtime_start": "2016-04-04", "value": "100.0"},
    {"date": "2026-04-01", "realtime_start": "2026-08-10", "value": "101.0"},
    {"date": "2026-04-01", "realtime_start": "2026-09-07", "value": "101.5"},
    {"date": "2026-07-01", "realtime_start": "2026-09-07", "value": "."},
]


def test_fred_observations_skip_missing_marker() -> None:
    rows = [{"date": "2026-08-01", "value": "91.08"}, {"date": "2026-09-01", "value": "."}]
    assert fred.parse_observations(rows, "M").to_dict() == {pd.Timestamp("2026-08-31"): 91.08}


def test_fred_first_release_is_earliest_vintage_and_skips_archive_start() -> None:
    first = fred.parse_first_releases(FRED_ROWS, "Q")
    assert first.to_dict() == {pd.Timestamp("2026-06-30"): pd.Timestamp("2026-08-10")}


def test_fred_key_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        fred.api_key()
