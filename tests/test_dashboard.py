import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from nowcast.config import ROOT
from nowcast.dashboard import charts
from nowcast.dashboard.data import (
    BENCHMARK_WARNING,
    DISPLAY_ORDER,
    backtest_history,
    ex_post_estimates,
    label,
    latest_run,
    main_estimates,
    quarter_label,
    readme_section,
    without_covid_years,
)

APP = str(ROOT / "app" / "streamlit_app.py")


def log() -> pd.DataFrame:
    rows = []
    for run_date in ("2026-10-01", "2026-10-08"):
        for i, model in enumerate(
            ["dfm_k1", "ar1", "bridge", "ar1_expost", "media_storica", "ar2", "dfm_k2"]
        ):
            rows.append({"run_date": pd.Timestamp(run_date), "model": model, "forecast": 0.1 * i,
                         "low80": -0.3, "low50": -0.1, "high50": 0.3, "high80": 0.5,
                         "target": pd.Timestamp("2026-09-30")})  # fmt: skip
    return pd.DataFrame(rows)


def test_labels_distinguish_benchmark_and_ex_post() -> None:
    assert label("ar1") == "AR(1), benchmark"
    assert label("dfm_k1_expost") == "DFM, 1 fattore (ex post)"
    assert label("sconosciuto") == "sconosciuto"


def test_latest_run_keeps_only_the_most_recent_date() -> None:
    latest = latest_run(log())
    assert set(latest["run_date"]) == {pd.Timestamp("2026-10-08")} and len(latest) == 7
    assert latest_run(log().iloc[:0]).empty


def test_benchmark_is_always_first_and_flagged() -> None:
    main = main_estimates(latest_run(log()))
    assert main["model"].tolist() == DISPLAY_ORDER
    assert main["benchmark"].tolist() == [True] + [False] * 5
    assert main.iloc[0]["label"] == "AR(1), benchmark"


def test_ex_post_estimates_are_kept_separate() -> None:
    ex_post = ex_post_estimates(latest_run(log()))
    assert ex_post["model"].tolist() == ["ar1_expost"]
    assert not main_estimates(latest_run(log()))["model"].str.endswith("_expost").any()


def test_warning_says_no_model_beat_the_benchmark() -> None:
    assert "nessun modello ha battuto l'AR(1)" in BENCHMARK_WARNING


def results() -> pd.DataFrame:
    quarters = pd.date_range("2019-03-31", "2022-12-31", freq="QE")
    frame = pd.DataFrame({"target": quarters, "forecast": 1.0, "actual": 0.5, "status": "ok"})
    frame.loc[3, "status"] = "failed"
    return frame.assign(model="ar1", horizon=30, as_of=quarters - pd.Timedelta(days=28))


def test_backtest_history_has_errors_and_skips_failures() -> None:
    history = backtest_history(results(), "ar1", 30)
    assert len(history) == 15 and (history["error"] == 0.5).all()
    assert backtest_history(results(), "ar1", 60).empty


def test_without_covid_years_drops_2020_and_2021() -> None:
    kept = without_covid_years(backtest_history(results(), "ar1", 30))
    assert sorted(set(kept["target"].dt.year)) == [2019, 2022]


def test_quarter_label() -> None:
    assert quarter_label(pd.Timestamp("2026-09-30")) == "2026-Q3"


def test_readme_section_extracts_one_section() -> None:
    text = "# T\n\n## A\n\nuno\n\n### sotto\n\ndue\n\n## B\n\ntre\n"
    assert readme_section(text, "A") == "uno\n\n### sotto\n\ndue"
    assert readme_section(text, "B") == "tre"


def test_readme_has_the_sections_the_dashboard_shows() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "nessun modello batte l'AR(1)" in readme_section(readme, "Conclusioni")
    assert "Pseudo real-time" in readme_section(readme, "Limiti")


def test_charts_build_valid_specifications() -> None:
    main = main_estimates(latest_run(log()))
    history = backtest_history(results(), "ar1", 30)
    history = history.assign(quarter=history["target"].map(quarter_label))
    for chart in (
        charts.interval_chart(main),
        charts.history_chart(history),
        charts.error_chart(history),
    ):
        assert chart.to_dict()["$schema"].startswith("https://vega.github.io/schema/vega-lite")


def render(page: str) -> None:
    from nowcast.dashboard import pages

    getattr(pages, page)()


@pytest.mark.parametrize("page", ["page_current", "page_history", "page_comparison", "page_method"])
def test_every_page_renders_without_errors(page: str) -> None:
    app = AppTest.from_function(render, kwargs={"page": page}, default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.title) == 1


def test_current_page_shows_the_benchmark_warning_and_the_applied_horizon() -> None:
    app = AppTest.from_function(render, kwargs={"page": "page_current"}, default_timeout=60).run()
    assert [w.value for w in app.warning] == [BENCHMARK_WARNING]
    assert app.metric[0].label == "AR(1), benchmark"
    captions = " ".join(c.value for c in app.caption)
    assert "esclusi i trimestri 2020-2021" in captions and "orizzonte a" in captions


def test_app_entry_point_runs() -> None:
    app = AppTest.from_file(APP, default_timeout=60).run()
    assert not app.exception


def test_line_is_broken_where_quarters_are_hidden() -> None:
    history = backtest_history(results(), "ar1", 30)
    full = charts.segments(history["target"])
    assert set(full.values()) == {0, 1}  # il trimestre fallito (2019-Q4) apre un secondo tratto
    hidden = charts.segments(without_covid_years(history)["target"])
    assert hidden[pd.Timestamp("2019-09-30")] == 0 and hidden[pd.Timestamp("2022-03-31")] == 1
    continuous = pd.Series(pd.date_range("2019-03-31", periods=8, freq="QE"))
    assert set(charts.segments(continuous).values()) == {0}
