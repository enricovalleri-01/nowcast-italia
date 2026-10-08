"""Rapporto del backtest: tutte le tabelle previste dal protocollo, in Markdown."""

from __future__ import annotations

import pandas as pd

from nowcast.evaluation.backtest import HORIZONS
from nowcast.evaluation.metrics import (
    BENCHMARK,
    CONFIRMATORY,
    COVID_YEARS,
    EX_POST_MODELS,
    MAIN_MODELS,
    SUBPERIODS,
    Window,
    accuracy,
    dm_table,
    error_table,
    failures,
    keep,
    largest_errors,
    max_steps,
)

WINDOWS: dict[str, Window | None] = {"Completa": None, "Senza 2020-2021": COVID_YEARS}
TOP_ERRORS = 10


def _cell(value: object, digits: int) -> str:
    if isinstance(value, pd.Timestamp):
        return f"{value.year}-Q{value.quarter}"
    if isinstance(value, float):
        return "n.d." if pd.isna(value) else f"{value:.{digits}f}"
    return str(value)


def markdown_table(table: pd.DataFrame, digits: int = 3) -> str:
    """Tabella Markdown con l'indice come prima colonna; ogni colonna conserva il suo tipo."""
    header = [str(table.index.name or ""), *map(str, table.columns)]
    columns = [[_cell(v, digits) for v in table[c].tolist()] for c in table.columns]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for i, label in enumerate(table.index):
        lines.append("| " + " | ".join([_cell(label, digits), *(c[i] for c in columns)]) + " |")
    return "\n".join(lines)


def accuracy_by_horizon(
    results: pd.DataFrame, models: list[str], benchmark: str, exclude: Window | None
) -> pd.DataFrame:
    """RMSE, MAE ed errore medio per modello, con gli orizzonti affiancati."""
    blocks = {}
    for horizon in HORIZONS:
        table = accuracy(keep(error_table(results, horizon, models), exclude=exclude), benchmark)
        blocks[horizon] = table
    columns = {
        f"{metric} {h}g": blocks[h][metric]
        for metric in ("RMSE", "RMSE_relativo", "MAE", "errore_medio")
        for h in HORIZONS
    }
    counts = {f"trimestri {h}g": blocks[h]["trimestri"].astype(int) for h in HORIZONS}
    return pd.DataFrame({**counts, **columns}).rename_axis("modello")


def dm_by_horizon(
    results: pd.DataFrame, models: list[str], benchmark: str, exclude: Window | None, loss: str
) -> pd.DataFrame:
    """Statistica e p-value di Diebold-Mariano contro il benchmark, per orizzonte."""
    tested = [m for m in models if m != benchmark]
    columns = {}
    for horizon in HORIZONS:
        errors = keep(error_table(results, horizon, models), exclude=exclude)
        table = dm_table(errors, tested, benchmark, max_steps(results, horizon), loss)
        columns[f"DM {horizon}g"] = table["statistica"]
        columns[f"p {horizon}g"] = table["p_value"]
    return pd.DataFrame(columns).rename_axis("modello")


def subperiod_rmse(results: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """RMSE per sottoperiodo e orizzonte."""
    columns = {}
    for name, window in SUBPERIODS.items():
        for horizon in HORIZONS:
            errors = keep(error_table(results, horizon, models), window=window)
            columns[f"{name} {horizon}g"] = accuracy(errors, models[0])["RMSE"]
    return pd.DataFrame(columns).rename_axis("modello")


def main_versus_ex_post(results: pd.DataFrame, exclude: Window | None) -> pd.DataFrame:
    """RMSE dei modelli principali accanto a quello delle loro varianti ex post."""
    everything = MAIN_MODELS + EX_POST_MODELS
    columns = {}
    for horizon in HORIZONS:
        table = accuracy(
            keep(error_table(results, horizon, everything), exclude=exclude), BENCHMARK
        )
        columns[f"principale {horizon}g"] = table.loc[MAIN_MODELS, "RMSE"]
        ex_post = table.loc[EX_POST_MODELS, "RMSE"]
        columns[f"ex post {horizon}g"] = ex_post.set_axis(MAIN_MODELS)
    return pd.DataFrame(columns).rename_axis("modello")


def _section(title: str, table: pd.DataFrame, note: str = "") -> str:
    body = markdown_table(table)
    return f"### {title}\n\n{note + chr(10) + chr(10) if note else ''}{body}\n"


def build_report(results: pd.DataFrame) -> str:
    """Tutte le tabelle del protocollo. Errore = previsione - realizzato, in punti percentuali."""
    version = results["dataset_version"].iloc[0]
    commit = results["specification_commit"].iloc[0]
    quarters = results["target"].nunique()
    parts = [
        "# Risultati del backtest\n",
        (
            f"Dataset `{version}`, specificazione al commit `{commit}`, {quarters} trimestri, "
            f"orizzonti a {', '.join(map(str, HORIZONS))} giorni dalla pubblicazione del PIL. "
            "Errore = previsione − realizzato, in punti percentuali di crescita t/t. "
            f"I test di Diebold-Mariano sono contro `{BENCHMARK}`; una statistica negativa indica "
            f"un errore minore del benchmark. Confronti confermativi: {', '.join(CONFIRMATORY)}. "
            "Ogni tabella usa solo i trimestri in cui tutti i modelli della tabella hanno una "
            "previsione: il numero è indicato per orizzonte.\n"
        ),
        _section(
            "Previsioni mancanti per modello e orizzonte", failures(results).rename_axis("modello")
        ),
    ]
    for name, exclude in WINDOWS.items():
        parts.append(f"## Finestra: {name}\n")
        parts.append(
            _section(
                "Modelli principali", accuracy_by_horizon(results, MAIN_MODELS, BENCHMARK, exclude)
            )
        )
        for loss, label in (("squared", "errore quadratico"), ("absolute", "errore assoluto")):
            table = dm_by_horizon(results, MAIN_MODELS, BENCHMARK, exclude, loss)
            parts.append(_section(f"Diebold-Mariano, {label}", table))
        parts.append(
            _section(
                "Varianti ex post",
                accuracy_by_horizon(results, EX_POST_MODELS, f"{BENCHMARK}_expost", exclude),
                "Stimate senza marzo-settembre 2020: analisi secondaria.",
            )
        )
        table = dm_by_horizon(results, EX_POST_MODELS, f"{BENCHMARK}_expost", exclude, "squared")
        parts.append(_section("Diebold-Mariano delle varianti ex post, errore quadratico", table))
        parts.append(
            _section("RMSE: principali contro ex post", main_versus_ex_post(results, exclude))
        )
    parts.append("## Dove i modelli falliscono\n")
    parts.append(
        _section("RMSE per sottoperiodo, modelli principali", subperiod_rmse(results, MAIN_MODELS))
    )
    parts.append(
        _section("RMSE per sottoperiodo, varianti ex post", subperiod_rmse(results, EX_POST_MODELS))
    )
    for horizon in HORIZONS:
        table = largest_errors(results, horizon, MAIN_MODELS, TOP_ERRORS).rename_axis("trimestre")
        parts.append(
            _section(
                f"I {TOP_ERRORS} trimestri con gli errori più grandi, a {horizon} giorni", table
            )
        )
    return "\n".join(parts)
