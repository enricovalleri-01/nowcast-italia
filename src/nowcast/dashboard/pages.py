"""Pagine della dashboard. Non stimano nulla: leggono registro delle stime e backtest."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

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
from nowcast.evaluation.backtest import HORIZONS
from nowcast.evaluation.metrics import BENCHMARK, COVID_YEARS, EX_POST_MODELS, MAIN_MODELS, failures
from nowcast.evaluation.report import accuracy_by_horizon, dm_by_horizon, subperiod_rmse
from nowcast.live.intervals import EXCLUSION_NOTE
from nowcast.live.nowcast import read_log
from nowcast.pipeline import BACKTEST_PATH, NOWCAST_LOG_PATH, load_backtest

WINDOWS = {"Senza 2020-2021 (50 trimestri)": COVID_YEARS, "Completa (58 trimestri)": None}
ESTIMATE_COLUMNS = {
    "label": "Modello",
    "forecast": "Stima",
    "low80": "80%, da",
    "high80": "80%, a",
    "low50": "50%, da",
    "high50": "50%, a",
}


@st.cache_data
def backtest_results(modified: float) -> pd.DataFrame:
    return load_backtest()


@st.cache_data
def nowcast_log(modified: float) -> pd.DataFrame:
    return read_log(NOWCAST_LOG_PATH)


def results() -> pd.DataFrame:
    return backtest_results(BACKTEST_PATH.stat().st_mtime)


def estimates() -> pd.DataFrame:
    modified = NOWCAST_LOG_PATH.stat().st_mtime if NOWCAST_LOG_PATH.exists() else 0.0
    return nowcast_log(modified)


def estimate_table(rows: pd.DataFrame) -> None:
    table = rows[list(ESTIMATE_COLUMNS)].rename(columns=ESTIMATE_COLUMNS).set_index("Modello")
    st.dataframe(table.style.format("{:+.2f}"), width="stretch")


def page_current() -> None:
    st.title("Stima corrente del PIL")
    latest = latest_run(estimates())
    if latest.empty:
        st.info("Nessuna stima nel registro. Esegui `python -m nowcast.pipeline nowcast`.")
        return
    first = latest.iloc[0]
    main = main_estimates(latest)
    benchmark = main[main["benchmark"]].iloc[0]
    st.warning(BENCHMARK_WARNING)
    st.subheader(f"Crescita t/t del {quarter_label(first['target'])}")
    left, right = st.columns([1, 2])
    left.metric("AR(1), benchmark", f"{benchmark['forecast']:+.2f}%")
    left.caption(
        f"Intervallo 80%: da {benchmark['low80']:+.2f} a {benchmark['high80']:+.2f}  \n"
        f"Intervallo 50%: da {benchmark['low50']:+.2f} a {benchmark['high50']:+.2f}"
    )
    right.altair_chart(charts.interval_chart(main), width="stretch")
    st.caption(
        f"Tratto spesso: intervallo al 50%. Tratto sottile: intervallo all'80%. {EXCLUSION_NOTE} "
        f"Mancano {int(first['days_to_publication'])} giorni alla pubblicazione attesa "
        f"({first['expected_publication']:%d/%m/%Y}): è applicato l'orizzonte a "
        f"**{int(first['horizon_applied'])} giorni**."
    )
    estimate_table(main)
    with st.expander("Varianti ex post (analisi secondaria)"):
        st.caption(
            "Stimate senza marzo-settembre 2020: usano un'informazione che nel 2020 non "
            "esisteva. Servono a misurare quanto pesa il trattamento del Covid."
        )
        estimate_table(ex_post_estimates(latest))
    st.caption(
        f"Stime del {first['run_date']:%d/%m/%Y} · dataset `{first['dataset_version']}` · "
        f"codice `{first['code_commit']}`"
    )


def page_history() -> None:
    st.title("Storico: stime contro dato realizzato")
    st.caption(
        "Previsioni del backtest pseudo real-time: ogni punto è stato calcolato con i soli dati "
        "pubblicati a quella data. Il dato realizzato è l'ultima versione disponibile."
    )
    left, middle, right = st.columns(3)
    model = left.selectbox("Modello", DISPLAY_ORDER + EX_POST_MODELS, format_func=label)
    horizon = middle.selectbox("Giorni alla pubblicazione", HORIZONS, index=len(HORIZONS) - 1)
    period = right.segmented_control("Periodo", ["Tutto", "Senza 2020-2021"], default="Tutto")
    history = backtest_history(results(), model, horizon)
    if period == "Senza 2020-2021":
        history = without_covid_years(history)
        st.caption("I trimestri 2020-2021 sono nascosti: nel grafico completo dominano la scala.")
    history = history.assign(quarter=history["target"].map(quarter_label))
    st.altair_chart(charts.history_chart(history), width="stretch")
    st.subheader("Errori di previsione")
    st.altair_chart(charts.error_chart(history), width="stretch")
    rmse = float((history["error"] ** 2).mean() ** 0.5)
    st.caption(
        f"{len(history)} trimestri · RMSE {rmse:.3f} · errore medio {history['error'].mean():+.3f}"
    )
    table = history[["quarter", "as_of", "forecast", "actual", "error"]].set_index("quarter")
    table.columns = ["Dati al", "Previsione", "Realizzato", "Errore"]
    formats: dict[Any, Any] = {
        "Previsione": "{:+.2f}",
        "Realizzato": "{:+.2f}",
        "Errore": "{:+.2f}",
        "Dati al": "{:%d/%m/%Y}",
    }
    with st.expander("Tabella dei dati"):
        st.dataframe(table.style.format(formats), width="stretch")
    st.subheader("Stime dal vivo")
    log = estimates()
    live = log[log["model"] == model][
        ["run_date", "target", "forecast", "low80", "high80", "dataset_version"]
    ]
    if live.empty:
        st.info("Nessuna stima dal vivo per questo modello.")
    else:
        st.caption("Stime registrate a ogni aggiornamento, non ricalcolate a posteriori.")
        st.dataframe(live.set_index("run_date"), width="stretch")


def page_comparison() -> None:
    st.title("Confronto tra modelli")
    st.warning(BENCHMARK_WARNING)
    window = st.radio("Finestra", list(WINDOWS), horizontal=True)
    exclude = WINDOWS[window]
    if exclude is None:
        st.caption(
            "Attenzione: la colonna a 90 giorni usa 57 trimestri, senza il 2020-Q3, e non è "
            "confrontabile con le altre due."
        )
    data = results()
    st.subheader("Accuratezza dei modelli principali")
    st.dataframe(
        accuracy_by_horizon(data, MAIN_MODELS, BENCHMARK, exclude)
        .rename(index=label)
        .style.format(precision=3)
    )
    st.subheader("Test di Diebold-Mariano contro l'AR(1)")
    st.caption(
        "Errore quadratico. Statistica negativa: errore minore del benchmark. p-value a due code."
    )
    st.dataframe(
        dm_by_horizon(data, MAIN_MODELS, BENCHMARK, exclude, "squared")
        .rename(index=label)
        .style.format(precision=3)
    )
    st.subheader("RMSE per sottoperiodo")
    st.dataframe(subperiod_rmse(data, MAIN_MODELS).rename(index=label).style.format(precision=3))
    with st.expander("Varianti ex post (analisi secondaria)"):
        ex_post = accuracy_by_horizon(data, EX_POST_MODELS, f"{BENCHMARK}_expost", exclude)
        st.dataframe(ex_post.rename(index=label).style.format(precision=3))
    with st.expander("Previsioni mancanti"):
        st.dataframe(failures(data).rename(index=label))


def page_method() -> None:
    st.title("Metodo e limiti")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    st.header("Conclusioni")
    st.markdown(readme_section(readme, "Conclusioni"))
    st.header("Come leggere gli intervalli")
    st.markdown(
        "Gli intervalli sono i quantili empirici degli errori commessi nel backtest dallo stesso "
        "modello allo stesso orizzonte, **esclusi i trimestri 2020-2021**: descrivono periodi "
        "ordinari e non coprono uno shock di quella portata. La copertura è verificata sugli "
        "stessi 50 errori da cui sono calcolati, non su dati nuovi."
    )
    st.header("Limiti")
    st.markdown(readme_section(readme, "Limiti"))
    st.caption("Protocollo di valutazione, dati e codice sono descritti nel README del repository.")
