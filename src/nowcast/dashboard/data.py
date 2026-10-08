"""Preparazione dei dati mostrati dalla dashboard. Nessuna stima: solo lettura di file."""

from __future__ import annotations

import pandas as pd

from nowcast.evaluation.backtest import OK
from nowcast.evaluation.metrics import BENCHMARK, COVID_YEARS, EX_POST_MODELS, MAIN_MODELS

MODEL_LABELS = {
    "ar1": "AR(1), benchmark",
    "media_storica": "Media storica",
    "ar2": "AR(2)",
    "bridge": "Bridge",
    "dfm_k1": "DFM, 1 fattore",
    "dfm_k2": "DFM, 2 fattori",
}
# Il benchmark per primo, poi gli altri nell'ordine del protocollo.
DISPLAY_ORDER = [BENCHMARK, *[m for m in MAIN_MODELS if m != BENCHMARK]]

BENCHMARK_WARNING = (
    "Nel backtest, nei periodi ordinari (2012-2026 senza il 2020-2021), nessun modello ha "
    "battuto l'AR(1) in modo statisticamente distinguibile. Le altre stime vanno lette come "
    "confronto, non come previsioni più affidabili del benchmark."
)


def label(model: str) -> str:
    """Nome leggibile di un modello; le varianti ex post sono indicate come tali."""
    base = model.removesuffix("_expost")
    name = MODEL_LABELS.get(base, base)
    return f"{name} (ex post)" if model.endswith("_expost") else name


def latest_run(log: pd.DataFrame) -> pd.DataFrame:
    """Le stime dell'esecuzione più recente del registro, una riga per modello."""
    if log.empty:
        return log
    last = log[log["run_date"] == log["run_date"].max()]
    return pd.DataFrame(last.drop_duplicates("model", keep="last").reset_index(drop=True))


def ordered(estimates: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Le righe dei modelli richiesti, nell'ordine dato, con il nome leggibile."""
    rows = estimates.set_index("model").reindex(models).dropna(how="all").reset_index()
    return rows.assign(label=rows["model"].map(label), benchmark=rows["model"] == BENCHMARK)


def main_estimates(estimates: pd.DataFrame) -> pd.DataFrame:
    return ordered(estimates, DISPLAY_ORDER)


def ex_post_estimates(estimates: pd.DataFrame) -> pd.DataFrame:
    return ordered(
        estimates, [f"{m}_expost" for m in DISPLAY_ORDER if f"{m}_expost" in EX_POST_MODELS]
    )


def backtest_history(results: pd.DataFrame, model: str, horizon: int) -> pd.DataFrame:
    """Previsioni del backtest di un modello a un orizzonte, contro il dato realizzato."""
    rows = results[(results["model"] == model) & (results["horizon"] == horizon)]
    rows = rows[rows["status"] == OK].sort_values("target")
    table = rows[["target", "as_of", "forecast", "actual"]].reset_index(drop=True)
    return table.assign(error=table["forecast"] - table["actual"])


def without_covid_years(history: pd.DataFrame) -> pd.DataFrame:
    inside = (history["target"] >= COVID_YEARS[0]) & (history["target"] <= COVID_YEARS[1])
    return history[~inside].reset_index(drop=True)


def quarter_label(date: pd.Timestamp) -> str:
    return f"{date.year}-Q{date.quarter}"


def readme_section(text: str, title: str) -> str:
    """Il contenuto di una sezione di secondo livello del README, senza il titolo."""
    marker = f"## {title}\n"
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    return text[start : end if end != -1 else len(text)].strip()
