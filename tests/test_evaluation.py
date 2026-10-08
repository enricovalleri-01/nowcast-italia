import numpy as np
import pandas as pd
import pytest
from scipy import stats

from nowcast.config import SeriesSpec
from nowcast.data.vintages import import_history
from nowcast.evaluation import backtest
from nowcast.evaluation.dm_test import dm_test, long_run_variance, loss_differential
from nowcast.evaluation.metrics import (
    accuracy,
    dm_table,
    error_table,
    failures,
    keep,
    largest_errors,
    mae,
    rmse,
)
from nowcast.evaluation.report import build_report, markdown_table
from nowcast.models.base import InfoSet, Nowcast

TODAY = pd.Timestamp("2026-10-08")
GDP = SeriesSpec("gdp", "PIL", "eurostat", "Q", "pct_change", 30, "target", role="target")
IP = SeriesSpec("ip", "IP", "eurostat", "M", "pct_change", 40, "real")
SPECS = [GDP, IP]


def observations() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    quarters = pd.date_range("2018-03-31", "2026-06-30", freq="QE")
    months = pd.date_range("2018-01-31", "2026-08-31", freq="ME")
    gdp = pd.Series(100 * np.cumprod(1 + rng.normal(0.002, 0.004, len(quarters))), index=quarters)
    ip = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.01, len(months))), index=months)
    return pd.concat([import_history(gdp, GDP, TODAY), import_history(ip, IP, TODAY)])


class LastValue:
    """Prevede l'ultimo valore noto del PIL e registra cosa gli viene mostrato."""

    name = "ultimo"

    def __init__(self) -> None:
        self.seen: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast:
        self.seen.append((info.as_of, target, info.gdp_growth.index[-1]))
        return Nowcast(self.name, target, float(info.gdp_growth.iloc[-1]), 1.0)


class AlwaysFails:
    name = "rotto"

    def nowcast(self, info: InfoSet, target: pd.Timestamp) -> Nowcast:
        raise ValueError("stima rifiutata")


QUARTERS = pd.date_range("2024-03-31", "2025-12-31", freq="QE")


def run(models: list) -> pd.DataFrame:  # type: ignore[type-arg]
    return backtest.run_backtest(observations(), SPECS, models, QUARTERS, "abc123", "deadbee")


# --- backtest


def test_origins_are_counted_back_from_the_publication_date() -> None:
    made = backtest.origins(observations(), QUARTERS[:1])
    assert [o.horizon for o in made] == [90, 60, 30]
    assert all(o.publication == pd.Timestamp("2024-04-30") for o in made)
    assert [o.as_of for o in made] == [
        pd.Timestamp(d) for d in ("2024-01-31", "2024-03-01", "2024-03-31")
    ]


def test_every_result_row_carries_provenance() -> None:
    results = run([LastValue()])
    assert list(results.columns) == backtest.RESULT_COLUMNS
    assert len(results) == len(QUARTERS) * 3
    required = ["as_of", "publication_date", "actual", "dataset_version", "specification_commit"]
    assert results[required].notna().all().all()
    assert set(results["dataset_version"]) == {"abc123"}
    assert set(results["specification_commit"]) == {"deadbee"}
    assert (
        results["as_of"] == results["publication_date"] - pd.to_timedelta(results["horizon"], "D")
    ).all()


def test_models_never_see_the_quarter_they_forecast() -> None:
    model = LastValue()
    results = run([model])
    assert all(last_known < target for _, target, last_known in model.seen)
    assert sorted(a for a, _, _ in model.seen) == sorted(results["as_of"])
    assert results["steps"].between(1, 2).all()


def test_actual_is_the_latest_value_in_the_dataset() -> None:
    results = run([LastValue()])
    growth = backtest.realized_growth(observations(), SPECS)
    assert (results["actual"].to_numpy() == growth.reindex(results["target"]).to_numpy()).all()


def test_failure_is_recorded_and_not_replaced() -> None:
    results = run([LastValue(), AlwaysFails()])
    broken = results[results["model"] == "rotto"]
    assert (broken["status"] == backtest.FAILED).all()
    assert broken["forecast"].isna().all()
    assert set(broken["reason"]) == {"stima rifiutata"}
    assert (results[results["model"] == "ultimo"]["status"] == backtest.OK).all()
    assert failures(results).loc["rotto"].tolist() == [len(QUARTERS)] * 3
    assert failures(results).loc["ultimo"].tolist() == [0, 0, 0]
    assert list(failures(results).columns) == [90, 60, 30]


def test_backtest_refuses_an_origin_where_the_target_is_already_known() -> None:
    origin = backtest.Origin(QUARTERS[0], 0, pd.Timestamp("2024-04-30"), pd.Timestamp("2024-05-15"))
    with pytest.raises(RuntimeError, match="già noto"):
        backtest.run_origin(origin, observations(), SPECS, [LastValue()])


def test_parallel_run_gives_the_same_results() -> None:
    serial = run([backtest.HistoricalMean(), backtest.ARBenchmark(1)])
    parallel = backtest.run_backtest(
        observations(), SPECS, [backtest.HistoricalMean(), backtest.ARBenchmark(1)],
        QUARTERS, "abc123", "deadbee", workers=2,
    )  # fmt: skip
    pd.testing.assert_frame_equal(serial, parallel)


def test_protocol_constants() -> None:
    assert len(backtest.protocol_quarters()) == 58
    names = [m.name for m in backtest.protocol_models()]
    assert names[:6] == ["media_storica", "ar1", "ar2", "bridge", "dfm_k1", "dfm_k2"]
    assert names[6:] == [f"{n}_expost" for n in names[:6]]
    assert backtest.HORIZONS == (90, 60, 30)


# --- metriche


def fake_results() -> pd.DataFrame:
    rows = []
    quarters = pd.date_range("2019-03-31", periods=4, freq="QE")
    forecasts = {"a": [1.0, 1.0, 1.0, 1.0], "b": [0.0, 2.0, 0.0, 4.0]}
    for model, values in forecasts.items():
        for quarter, value in zip(quarters, values, strict=True):
            rows.append({"model": model, "target": quarter, "horizon": 30, "forecast": value,
                         "actual": 0.0, "status": "ok", "steps": 1})  # fmt: skip
    return pd.DataFrame(rows)


def test_rmse_and_mae_known_values() -> None:
    errors = pd.Series([3.0, -4.0])
    assert rmse(errors) == pytest.approx(np.sqrt(12.5))
    assert mae(errors) == pytest.approx(3.5)


def test_accuracy_table_and_relative_rmse() -> None:
    table = accuracy(error_table(fake_results(), 30, ["a", "b"]), "a")
    assert table.loc["a", ["RMSE", "MAE", "errore_medio", "RMSE_relativo"]].tolist() == [1, 1, 1, 1]
    assert table.loc["b", "RMSE"] == pytest.approx(np.sqrt(5))
    assert table.loc["b", "RMSE_relativo"] == pytest.approx(np.sqrt(5))
    assert table.loc["b", "errore_medio"] == pytest.approx(1.5)


def test_models_are_compared_on_common_quarters_only() -> None:
    results = fake_results()
    results.loc[(results["model"] == "b") & (results["target"] == "2019-12-31"), "status"] = (
        "failed"
    )
    errors = error_table(results, 30, ["a", "b"])
    assert len(errors) == 3 and pd.Timestamp("2019-12-31") not in errors.index


def test_keep_selects_and_excludes_windows() -> None:
    errors = pd.DataFrame({"a": 1.0}, index=pd.date_range("2019-03-31", "2022-12-31", freq="QE"))
    covid = (pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31"))
    assert len(keep(errors, exclude=covid)) == 8
    assert len(keep(errors, window=covid)) == 8
    assert len(keep(errors)) == 16


def test_largest_errors_are_sorted_by_mean_absolute_error() -> None:
    table = largest_errors(fake_results(), 30, ["a", "b"], 2)
    assert list(table.index) == [pd.Timestamp("2019-12-31"), pd.Timestamp("2019-06-30")]
    assert list(table.columns) == ["realizzato", "a", "b"]


# --- Diebold-Mariano


def test_dm_matches_a_hand_computed_case() -> None:
    model, benchmark = np.array([1.0, 2.0, 0.0, 1.0]), np.array([2.0, 2.0, 2.0, 1.0])
    d = np.array([-3.0, 0.0, -4.0, 0.0])  # errori quadratici: [1,4,0,1] - [4,4,4,1]
    assert loss_differential(model, benchmark, "squared").tolist() == d.tolist()
    n = 4
    raw = d.mean() / np.sqrt(d.var() / n)
    expected = raw * np.sqrt((n - 1) / n)  # correzione HLN con un passo
    result = dm_test(model, benchmark)
    assert result.statistic == pytest.approx(expected)
    assert result.p_value == pytest.approx(2 * stats.t.sf(abs(expected), df=3))
    assert result.statistic < 0 and result.nobs == 4


def test_dm_is_antisymmetric_and_undefined_for_identical_forecasts() -> None:
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=60), 1.5 * rng.normal(size=60)
    assert dm_test(a, b).statistic == pytest.approx(-dm_test(b, a).statistic)
    assert dm_test(a, b).p_value == pytest.approx(dm_test(b, a).p_value)
    assert np.isnan(dm_test(a, a).statistic)


def test_dm_absolute_loss_differs_from_squared() -> None:
    a, b = np.array([0.1, 0.1, 0.1, 3.0, 0.2]), np.array([1.0, 1.1, 0.9, 1.0, 1.2])
    assert dm_test(a, b, loss="absolute").statistic < 0 < dm_test(a, b, loss="squared").statistic


def test_long_run_variance_adds_autocovariances() -> None:
    d = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    assert long_run_variance(d, 0) == pytest.approx(1.0)
    assert long_run_variance(d, 1) == pytest.approx(
        1.0 + 2 * (-5 / 6)
    )  # negativa: test non calcolabile
    assert np.isnan(dm_test(d + 2, np.zeros(6), steps=2, loss="absolute").statistic)


def test_dm_rejects_when_one_forecast_is_clearly_better() -> None:
    rng = np.random.default_rng(1)
    result = dm_test(0.2 * rng.normal(size=80), rng.normal(size=80))
    assert result.statistic < 0 and result.p_value < 0.01


def test_dm_table_has_one_row_per_model() -> None:
    errors = error_table(fake_results(), 30, ["a", "b"])
    table = dm_table(errors, ["b"], "a", 1, "squared")
    assert list(table.index) == ["b"] and table.loc["b", "n"] == 4


# --- rapporto


def test_markdown_table_formats_quarters_missing_values_and_integers() -> None:
    index = pd.DatetimeIndex(["2020-06-30", "2020-09-30"])
    table = pd.DataFrame({"x": [1.23456, float("nan")], "n": [57, 58]}, index=index)
    text = markdown_table(table.rename_axis("trimestre"))
    assert "| 2020-Q2 | 1.235 | 57 |" in text and "| 2020-Q3 | n.d. | 58 |" in text


def test_report_contains_every_protocol_table() -> None:
    quarters = pd.date_range("2012-03-31", "2026-06-30", freq="QE")
    rng = np.random.default_rng(0)
    rows = []
    for model in [m.name for m in backtest.protocol_models()]:
        for horizon in backtest.HORIZONS:
            for quarter in quarters:
                rows.append({"model": model, "target": quarter, "horizon": horizon, "steps": 1,
                             "forecast": rng.normal(), "actual": rng.normal(), "status": "ok",
                             "dataset_version": "abc123", "specification_commit": "deadbee"})  # fmt: skip
    report = build_report(pd.DataFrame(rows))
    for expected in ("Finestra: Completa", "Finestra: Senza 2020-2021", "Diebold-Mariano, errore quadratico",
                     "Varianti ex post", "RMSE per sottoperiodo", "errori più grandi, a 30 giorni",
                     "Previsioni mancanti", "abc123", "deadbee"):  # fmt: skip
        assert expected in report
