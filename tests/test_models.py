import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

from nowcast.config import SeriesSpec
from nowcast.data.vintages import import_history
from nowcast.models.ar import _design, fit_ar, forecast_ar, select_order
from nowcast.models.base import (
    COVID_WINDOW,
    InfoSet,
    build_info,
    in_window,
    next_unpublished_quarter,
    quarters_between,
)
from nowcast.models.benchmark import ARBenchmark, HistoricalMean
from nowcast.models.bridge import Bridge, complete_months, quarterly_regressor, rebuild_levels
from nowcast.models.dfm import DFM, bai_ng_ic, em_convergence, max_root, monthly_endog
from nowcast.transforms import apply_transform, monthly_to_quarterly


def simulate_ar(phi: list[float], n: int, seed: int = 0, const: float = 0.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    y = np.zeros(n)
    for t in range(len(phi), n):
        y[t] = const + sum(p * y[t - 1 - j] for j, p in enumerate(phi)) + rng.normal()
    return pd.Series(y)


def synthetic_info(seed: int = 0, months: int = 240, last_gdp: str = "2019-09-30") -> InfoSet:
    """Un fattore AR(1) mensile guida tre indicatori e, via media trimestrale, il PIL."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2000-01-31", periods=months, freq="ME")
    factor = simulate_ar([0.5], months, seed).to_numpy()
    growth = {f"x{i}": factor + 0.3 * rng.normal(size=months) for i in range(3)}
    levels = pd.DataFrame(
        {k: 100 * np.cumprod(1 + v / 100) for k, v in growth.items()}, index=index
    )
    gdp = 0.2 + 0.5 * monthly_to_quarterly(pd.Series(factor, index=index))
    gdp = (gdp + 0.05 * rng.normal(size=len(gdp))).rename("gdp")
    kinds = {k: "pct_change" for k in growth}
    return InfoSet(index[-1], levels, gdp[gdp.index <= last_gdp], kinds, kinds)


# --- AR


def test_fit_ar_recovers_coefficient_and_sigma() -> None:
    fit = fit_ar(simulate_ar([0.6], 5000, const=1.0), 1)
    assert fit.coefs == pytest.approx([1.0, 0.6], abs=0.05)
    assert fit.sigma == pytest.approx(1.0, abs=0.05)


def test_fit_ar_drops_rows_touching_missing_values() -> None:
    y = simulate_ar([0.5], 50)
    y.iloc[20] = np.nan
    assert fit_ar(y, 2).nobs == 50 - 2 - 3  # la riga mancante e le due che la usano come ritardo


def test_select_order_finds_ar2() -> None:
    assert select_order(simulate_ar([0.5, -0.4], 3000), 6) == 2


def test_orders_are_compared_on_identical_rows_even_with_gaps() -> None:
    y = simulate_ar([0.5], 100)
    y.iloc[40:43] = np.nan
    samples = [fit_ar(y, p, sample_order=6).nobs for p in range(1, 7)]
    assert len(set(samples)) == 1
    assert samples[0] == 100 - 6 - (3 + 6)  # inizio campione, buco e righe che lo usano


def test_gap_does_not_join_distant_periods() -> None:
    y = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0, 6.0])
    x, target = _design(y, 1, 1)
    assert target.tolist() == [2.0, 5.0, 6.0]  # 4.0 non ha un ritardo valido
    assert x[:, 1].tolist() == [1.0, 4.0, 5.0]


def test_forecast_ar_one_step_and_long_run() -> None:
    fit = fit_ar(simulate_ar([0.6], 5000, const=1.0), 1)
    means, stds = forecast_ar(np.array([2.0]), fit, 60)
    assert means[0] == pytest.approx(fit.coefs[0] + fit.coefs[1] * 2.0)
    assert stds[0] == pytest.approx(fit.sigma)
    assert (np.diff(stds) >= 0).all() and stds[1] > stds[0]
    assert means[-1] == pytest.approx(fit.coefs[0] / (1 - fit.coefs[1]), abs=1e-6)
    assert stds[-1] == pytest.approx(fit.sigma / np.sqrt(1 - fit.coefs[1] ** 2), abs=1e-6)


# --- set informativo


def test_in_window_flags_only_the_given_period() -> None:
    index = pd.DatetimeIndex(["2020-02-29", "2020-03-31", "2020-09-30", "2020-12-31"])
    assert in_window(index, COVID_WINDOW).tolist() == [False, True, True, False]
    assert not in_window(index, None).any()


def test_build_info_hides_gdp_not_yet_published() -> None:
    gdp = SeriesSpec("gdp", "PIL", "eurostat", "Q", "pct_change", 30, "target", role="target")
    ip = SeriesSpec("ip", "IP", "eurostat", "M", "pct_change", 40, "real")
    today = pd.Timestamp("2026-10-08")
    quarters = pd.Series(
        np.linspace(100, 110, 20), index=pd.date_range("2021-09-30", periods=20, freq="QE")
    )
    months = pd.Series(
        np.linspace(100, 105, 60), index=pd.date_range("2021-09-30", periods=60, freq="ME")
    )
    obs = pd.concat([import_history(quarters, gdp, today), import_history(months, ip, today)])
    before = build_info(obs, [gdp, ip], pd.Timestamp("2026-07-29"))
    after = build_info(obs, [gdp, ip], pd.Timestamp("2026-07-30"))
    assert before.gdp_growth.index[-1] == pd.Timestamp("2026-03-31")
    assert after.gdp_growth.index[-1] == pd.Timestamp("2026-06-30")
    assert next_unpublished_quarter(before) == pd.Timestamp("2026-06-30")
    assert before.monthly_levels["ip"].last_valid_index() == pd.Timestamp("2026-05-31")


def test_quarters_between() -> None:
    assert quarters_between(pd.Timestamp("2025-12-31"), pd.Timestamp("2026-06-30")) == 2


# --- benchmark


def covid_info() -> InfoSet:
    info = synthetic_info(months=264, last_gdp="2021-12-31")
    shocked = info.gdp_growth.copy()
    shocked[pd.Timestamp("2020-06-30")] = -12.0
    return InfoSet(info.as_of, info.monthly_levels, shocked, info.transforms, info.dfm_transforms)


def test_models_use_all_data_by_default() -> None:
    info, target = covid_info(), pd.Timestamp("2022-03-31")
    assert HistoricalMean().nowcast(info, target).mean == pytest.approx(info.gdp_growth.mean())


def test_ex_post_variant_excludes_the_window_and_is_named_differently() -> None:
    info, target = covid_info(), pd.Timestamp("2022-03-31")
    ex_post = HistoricalMean(exclude=COVID_WINDOW).nowcast(info, target)
    quarters = pd.DatetimeIndex(["2020-03-31", "2020-06-30", "2020-09-30"])
    expected = info.gdp_growth.drop(quarters).mean()
    assert ex_post.mean == pytest.approx(expected)
    assert ex_post.model == "media_storica_expost"
    assert ARBenchmark(1, exclude=COVID_WINDOW).name == "ar1_expost"
    assert Bridge(exclude=COVID_WINDOW).name == "bridge_expost"
    assert DFM(1, exclude=COVID_WINDOW).name == "dfm_k1_expost"


def test_ar_benchmark_uncertainty_grows_when_previous_quarter_is_missing() -> None:
    info = synthetic_info()
    one = ARBenchmark(1).nowcast(info, pd.Timestamp("2019-12-31"))
    two = ARBenchmark(1).nowcast(info, pd.Timestamp("2020-03-31"))
    assert one.model == "ar1" and two.std > one.std


# --- bridge


@pytest.mark.parametrize("kind", ["none", "diff", "pct_change", "log_diff"])
def test_rebuild_levels_inverts_the_transform(kind: str) -> None:
    levels = pd.Series([100.0, 103.0, 101.0, 106.0])
    changes = apply_transform(levels, kind).to_numpy()[1:]
    assert rebuild_levels(100.0, changes, kind) == pytest.approx(levels.to_numpy()[1:])


def test_complete_months_extends_to_target_and_keeps_observed_values() -> None:
    info = synthetic_info()
    observed = info.monthly_levels["x0"].iloc[:-2]
    completed = complete_months(
        observed.reindex(info.monthly_levels.index), "pct_change", pd.Timestamp("2019-12-31")
    )
    assert completed.index[-1] == pd.Timestamp("2019-12-31")
    assert completed.loc[observed.index].equals(observed)
    assert completed.notna().all()


def test_quarterly_regressor_is_growth_of_the_quarterly_average() -> None:
    index = pd.date_range("2026-01-31", periods=6, freq="ME")
    levels = pd.Series([100.0, 100.0, 100.0, 110.0, 110.0, 110.0], index=index)
    assert quarterly_regressor(levels, "pct_change").iloc[-1] == pytest.approx(10.0)


def test_bridge_recovers_a_known_relationship() -> None:
    info = synthetic_info(last_gdp="2019-09-30")
    truth = synthetic_info(last_gdp="2019-12-31").gdp_growth
    target = pd.Timestamp("2019-12-31")
    model = Bridge(indicators=("x0", "x1"))
    result = model.nowcast(info, target)
    assert result.mean == pytest.approx(truth[target], abs=3 * result.std)
    assert result.std < 0.5 * info.gdp_growth.std()


def test_bridge_fills_the_ragged_edge_before_aggregating() -> None:
    info = synthetic_info()
    ragged = info.monthly_levels.copy()
    ragged.iloc[-2:, 0] = np.nan
    info = InfoSet(info.as_of, ragged, info.gdp_growth, info.transforms, info.dfm_transforms)
    regressors = Bridge(indicators=("x0", "x1")).regressors(info, pd.Timestamp("2019-12-31"))
    assert regressors.loc[pd.Timestamp("2019-12-31")].notna().all()


# --- DFM


def test_bai_ng_finds_the_true_number_of_factors() -> None:
    rng = np.random.default_rng(1)
    factors = rng.normal(size=(300, 2))
    loadings = rng.uniform(0.5, 1.5, size=(2, 60)) * rng.choice([-1, 1], size=(2, 60))
    panel = pd.DataFrame(factors @ loadings + 0.5 * rng.normal(size=(300, 60)))
    table = bai_ng_ic(panel, 6)
    assert table["ICp1"].idxmin() == 2 and table["ICp2"].idxmin() == 2
    assert table["varianza_spiegata"].is_monotonic_increasing


def test_monthly_endog_uses_dfm_series_and_reaches_the_target_month() -> None:
    info = synthetic_info()
    info = InfoSet(
        info.as_of,
        info.monthly_levels,
        info.gdp_growth,
        info.transforms,
        {"x0": "pct_change", "x2": "diff"},
    )
    panel = monthly_endog(info, pd.Timestamp("2020-03-31"))
    assert list(panel.columns) == ["x0", "x2"]
    assert panel.index[-1] == pd.Timestamp("2020-03-31")
    assert panel.iloc[-1].isna().all()


def test_dfm_nowcast_tracks_the_common_factor() -> None:
    info = synthetic_info(last_gdp="2019-09-30")
    truth = synthetic_info(last_gdp="2019-12-31").gdp_growth
    target = pd.Timestamp("2019-12-31")
    model = DFM(factors=1, maxiter=1000)
    estimate = model.estimate(info, target)
    result = model.nowcast(info, target, estimate)
    assert max_root(estimate.results) < 1
    assert estimate.as_of == info.as_of
    assert result.mean == pytest.approx(truth[target], abs=3 * result.std)
    assert result.std < 0.6 * info.gdp_growth.std()


def earlier(info: InfoSet, months: int) -> InfoSet:
    """Lo stesso set informativo come sarebbe stato `months` mesi prima."""
    levels = info.monthly_levels.iloc[:-months]
    gdp = info.gdp_growth[info.gdp_growth.index <= levels.index[-1] - pd.Timedelta(days=45)]
    return InfoSet(levels.index[-1], levels, gdp, info.transforms, info.dfm_transforms)


def test_dfm_rejects_parameters_estimated_in_the_future() -> None:
    info = synthetic_info()
    past = earlier(info, 12)
    model = DFM(factors=1, maxiter=1000)
    future_estimate = model.estimate(info, pd.Timestamp("2019-12-31"))
    with pytest.raises(ValueError, match="successiva al set informativo"):
        model.nowcast(past, pd.Timestamp("2018-12-31"), future_estimate)


def test_dfm_accepts_parameters_estimated_in_the_past() -> None:
    info = synthetic_info()
    model = DFM(factors=1, maxiter=1000)
    past_estimate = model.estimate(earlier(info, 12), pd.Timestamp("2018-12-31"))
    result = model.nowcast(info, pd.Timestamp("2019-12-31"), past_estimate)
    assert np.isfinite(result.mean)


def test_dfm_rejects_an_estimate_from_a_different_specification() -> None:
    info = covid_info()
    target = pd.Timestamp("2022-03-31")
    ex_post = DFM(1, exclude=COVID_WINDOW).estimate(info, target)
    with pytest.raises(ValueError, match="specificazione diversa"):
        DFM(1).nowcast(info, target, ex_post)
    other_transforms = {**info.dfm_transforms, "x0": "diff"}
    with pytest.raises(ValueError, match="specificazione diversa"):
        DFM(1, exclude=COVID_WINDOW, transforms=other_transforms).nowcast(info, target, ex_post)
    with pytest.raises(ValueError, match="specificazione diversa"):
        DFM(2, exclude=COVID_WINDOW).nowcast(info, target, ex_post)


def test_dfm_rejects_an_estimate_that_exhausted_its_iterations() -> None:
    info = synthetic_info()
    with pytest.warns(Warning), pytest.raises(ValueError, match="iterazioni esaurite"):
        DFM(factors=1, maxiter=3).estimate(info, pd.Timestamp("2019-12-31"))


def test_dfm_accepts_convergence_reached_on_the_last_allowed_iteration() -> None:
    info, target = synthetic_info(), pd.Timestamp("2019-12-31")
    needed = int(DFM(factors=1).estimate(info, target).results.mle_retvals["iter"])
    exact = DFM(factors=1, maxiter=needed).estimate(info, target)
    assert em_convergence(exact.results)[0]


def test_dfm_rejects_an_estimate_stopped_by_a_likelihood_decrease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alla seconda iterazione la verosimiglianza cala: statsmodels torna alla prima e si ferma."""
    original = DynamicFactorMQ._em_iteration
    calls = {"n": 0}

    class Worse:
        llf_obs = np.array([-1e12])

    def failing(self: DynamicFactorMQ, *args: object, **kwargs: object) -> tuple[object, ...]:
        calls["n"] += 1
        out = original(self, *args, **kwargs)
        return (Worse(), *out[1:]) if calls["n"] == 2 else out

    monkeypatch.setattr(DynamicFactorMQ, "_em_iteration", failing)
    with pytest.warns(Warning), pytest.raises(ValueError, match="calo della verosimiglianza"):
        DFM(factors=1).estimate(synthetic_info(), pd.Timestamp("2019-12-31"))
