from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nowcast.config import SeriesSpec
from nowcast.data.vintages import import_history
from nowcast.live.intervals import (
    EXCLUSION_NOTE,
    applied_horizon,
    calibration_errors,
    error_quantiles,
    interval,
    tail_probabilities,
)
from nowcast.live.nowcast import (
    LOG_COLUMNS,
    append_to_log,
    current_nowcasts,
    expected_publication,
    read_log,
)
from nowcast.models.benchmark import ARBenchmark, HistoricalMean

QUARTERS = pd.date_range("2012-03-31", "2026-06-30", freq="QE")


def backtest_results(
    bias: float = 0.0, models: tuple[str, ...] = ("ar1", "media_storica")
) -> pd.DataFrame:
    """Errori noti: per ogni cella i valori 1..n (più `bias`), 100 nel 2020-2021."""
    rows = []
    for model in models:
        for horizon in (90, 60, 30):
            ordinary = iter(np.arange(1.0, 51.0))
            for quarter in QUARTERS:
                covid = quarter.year in (2020, 2021)
                error = 100.0 if covid else next(ordinary) + bias
                rows.append({"model": model, "horizon": horizon, "target": quarter,
                             "forecast": error, "actual": 0.0, "status": "ok"})  # fmt: skip
    return pd.DataFrame(rows)


# --- intervalli


def test_tail_probabilities_for_50_and_80_percent() -> None:
    assert tail_probabilities() == [0.1, 0.25, 0.75, 0.9]


def test_calibration_excludes_2020_2021_and_failed_forecasts() -> None:
    results = backtest_results()
    results.loc[0, "status"] = "failed"
    errors = calibration_errors(results)
    assert errors["error"].max() == 50.0  # nessun errore del 2020-2021
    assert len(errors) == 2 * 3 * 50 - 1
    assert "2020-2021" in EXCLUSION_NOTE


def test_error_quantiles_known_values() -> None:
    table = error_quantiles(backtest_results())
    row = table.loc[("ar1", 30)]
    expected = np.quantile(np.arange(1.0, 51.0), [0.1, 0.25, 0.75, 0.9])
    assert row[["q10", "q25", "q75", "q90"]].tolist() == pytest.approx(expected.tolist())
    assert row["n"] == 50


def test_interval_is_forecast_minus_error_quantiles() -> None:
    quantiles = pd.Series({"q10": -0.4, "q25": -0.2, "q75": 0.1, "q90": 0.3})
    bounds = interval(1.0, quantiles)
    assert bounds == pytest.approx({"low50": 0.9, "high50": 1.2, "low80": 0.7, "high80": 1.4})
    assert bounds["low80"] < bounds["low50"] < bounds["high50"] < bounds["high80"]


def test_interval_corrects_for_a_model_that_overestimates() -> None:
    """Errori tutti positivi (previsione sopra il realizzato): l'intervallo sta sotto la previsione."""
    quantiles = error_quantiles(backtest_results(bias=10.0)).loc[("ar1", 30)]
    bounds = interval(0.0, quantiles)
    assert bounds["high80"] < 0


def test_intervals_cover_the_calibration_errors_at_the_nominal_rate() -> None:
    rng = np.random.default_rng(0)
    results = backtest_results()
    results["forecast"] = rng.normal(0.1, 0.4, len(results))
    quantiles = error_quantiles(results).loc[("ar1", 60)]
    errors = calibration_errors(results)
    cell = errors[(errors["model"] == "ar1") & (errors["horizon"] == 60)]["error"]
    inside80 = ((cell >= quantiles["q10"]) & (cell <= quantiles["q90"])).mean()
    inside50 = ((cell >= quantiles["q25"]) & (cell <= quantiles["q75"])).mean()
    assert inside80 == pytest.approx(0.8, abs=0.05) and inside50 == pytest.approx(0.5, abs=0.05)


@pytest.mark.parametrize(
    ("days", "horizon"),
    [
        (120, 90),
        (91, 90),
        (90, 90),
        (61, 90),
        (60, 60),
        (31, 60),
        (30, 30),
        (5, 30),
        (0, 30),
        (-3, 30),
    ],
)
def test_applied_horizon_never_uses_a_shorter_one_than_the_days_left(
    days: int, horizon: int
) -> None:
    assert applied_horizon(days) == horizon


# --- stima corrente e registro

GDP = SeriesSpec("gdp", "PIL", "eurostat", "Q", "pct_change", 32, "target", role="target")
IP = SeriesSpec("ip", "IP", "eurostat", "M", "pct_change", 43, "real")
TODAY = pd.Timestamp("2026-10-08")


def observations() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    quarters = pd.date_range("2005-03-31", "2026-06-30", freq="QE")
    months = pd.date_range("2005-01-31", "2026-08-31", freq="ME")
    gdp = pd.Series(100 * np.cumprod(1 + rng.normal(0.002, 0.004, len(quarters))), index=quarters)
    ip = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.01, len(months))), index=months)
    return pd.concat([import_history(gdp, GDP, TODAY), import_history(ip, IP, TODAY)])


def rows(as_of: pd.Timestamp = TODAY, version: str = "abc123") -> pd.DataFrame:
    models = [ARBenchmark(1), HistoricalMean()]
    return current_nowcasts(
        observations(), [GDP, IP], models, backtest_results(), as_of, version, "deadbee"
    )


def test_expected_publication_uses_the_registry_calendar() -> None:
    assert expected_publication(pd.Timestamp("2026-09-30"), [GDP, IP]) == pd.Timestamp("2026-11-01")


def test_current_nowcasts_have_intervals_and_provenance() -> None:
    table = rows()
    assert list(table.columns) == LOG_COLUMNS
    assert table["model"].tolist() == ["ar1", "media_storica"]
    assert set(table["target"]) == {pd.Timestamp("2026-09-30")}
    assert set(table["days_to_publication"]) == {24} and set(table["horizon_applied"]) == {30}
    assert (table["low80"] < table["low50"]).all() and (table["high50"] < table["high80"]).all()
    assert table[["dataset_version", "code_commit", "run_date"]].notna().all().all()
    quantiles = error_quantiles(backtest_results()).loc[("ar1", 30)]
    assert table.loc[0, "high80"] == pytest.approx(table.loc[0, "forecast"] - quantiles["q10"])


def test_horizon_applied_follows_the_days_left() -> None:
    table = rows(as_of=pd.Timestamp("2026-08-20"))  # il PIL del 2026-Q2 è già noto
    assert set(table["days_to_publication"]) == {73} and set(table["horizon_applied"]) == {90}


def test_log_is_append_only_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "nowcast_log.csv"
    first = append_to_log(rows(), path)
    again = append_to_log(rows(), path)
    assert len(first) == len(again) == 2  # stessa esecuzione: nessun duplicato
    later = append_to_log(rows(as_of=TODAY + pd.Timedelta(days=7)), path)
    assert len(later) == 4
    pd.testing.assert_frame_equal(later.iloc[:2].reset_index(drop=True), read_log(path).iloc[:2])
    other_data = append_to_log(rows(version="zzz999"), path)
    assert len(other_data) == 6  # stesso giorno, dataset diverso: nuova riga, la vecchia resta


def test_log_round_trips_through_disk(tmp_path: Path) -> None:
    path = tmp_path / "nowcast_log.csv"
    written = append_to_log(rows(), path)
    reloaded = read_log(path)
    assert reloaded["forecast"].tolist() == pytest.approx(written["forecast"].tolist())
    assert reloaded["run_date"].tolist() == written["run_date"].tolist()
    assert reloaded["reason"].tolist() == ["", ""]
