"""Grafici della dashboard (Altair).

Forma "enfasi": il benchmark nel colore d'accento, il resto in grigio. Il colore indica
sempre e solo il benchmark o la previsione; i testi restano nel colore del tema.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

ACCENT = "#2a78d6"
NEUTRAL = "#898781"
GRID = "#e1e0d9"
PERCENT = alt.Axis(
    format="+.1f", title="Crescita t/t, %", gridColor=GRID, domain=False, tickCount=8
)
MAX_GAP = pd.Timedelta(days=100)  # oltre un trimestre: la linea si interrompe


def _emphasis() -> alt.Color:
    scale = alt.Scale(domain=[True, False], range=[ACCENT, NEUTRAL])
    return alt.Color("benchmark:N", scale=scale, legend=None)


def interval_chart(estimates: pd.DataFrame) -> alt.LayerChart:
    """Stima puntuale con intervalli al 50% (tratto spesso) e all'80% (tratto sottile)."""
    order = estimates["label"].tolist()
    base = alt.Chart(estimates).encode(
        y=alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=220, ticks=False)),
        color=_emphasis(),
        tooltip=[
            alt.Tooltip("label:N", title="Modello"),
            alt.Tooltip("forecast:Q", title="Stima", format="+.2f"),
            alt.Tooltip("low50:Q", title="50%, da", format="+.2f"),
            alt.Tooltip("high50:Q", title="50%, a", format="+.2f"),
            alt.Tooltip("low80:Q", title="80%, da", format="+.2f"),
            alt.Tooltip("high80:Q", title="80%, a", format="+.2f"),
        ],
    )
    wide = base.mark_rule(strokeWidth=2).encode(x=alt.X("low80:Q", axis=PERCENT), x2="high80:Q")
    narrow = base.mark_bar(height=8, cornerRadius=4).encode(x="low50:Q", x2="high50:Q")
    point = base.mark_point(size=90, filled=True, stroke="white", strokeWidth=2, opacity=1).encode(
        x="forecast:Q"
    )
    zero = (
        alt.Chart(pd.DataFrame({"x": [0.0]}))
        .mark_rule(color=NEUTRAL, strokeWidth=1)
        .encode(x="x:Q")
    )
    layers: alt.LayerChart = zero + wide + narrow + point
    chart: alt.LayerChart = layers.properties(height=44 * len(estimates) + 30)
    return chart


def segments(dates: pd.Series) -> dict[pd.Timestamp, int]:
    """Numero del tratto continuo a cui appartiene ogni data: cambia dopo un periodo mancante."""
    ordered = dates.sort_values()
    breaks = (ordered.diff() > MAX_GAP).cumsum()
    return dict(zip(ordered, breaks.astype(int), strict=True))


def history_chart(history: pd.DataFrame) -> alt.LayerChart:
    """Dato realizzato (linea grigia) e previsione del backtest (punti nel colore d'accento)."""
    long = history.melt(
        id_vars=["target", "quarter"], value_vars=["actual", "forecast"], var_name="serie"
    )
    long["serie"] = long["serie"].map({"actual": "Realizzato", "forecast": "Previsione"})
    long["segment"] = long["target"].map(segments(history["target"]))
    scale = alt.Scale(domain=["Realizzato", "Previsione"], range=[NEUTRAL, ACCENT])
    base = alt.Chart(long).encode(
        x=alt.X("target:T", title=None, axis=alt.Axis(format="%Y", grid=False)),
        y=alt.Y("value:Q", axis=PERCENT),
        color=alt.Color("serie:N", scale=scale, legend=alt.Legend(title=None, orient="top")),
        detail="segment:N",
        tooltip=[
            alt.Tooltip("quarter:N", title="Trimestre"),
            alt.Tooltip("serie:N", title="Serie"),
            alt.Tooltip("value:Q", title="Crescita t/t, %", format="+.2f"),
        ],
    )
    line = base.transform_filter(alt.datum.serie == "Realizzato").mark_line(strokeWidth=2)
    points = base.transform_filter(alt.datum.serie == "Previsione").mark_point(
        size=70, filled=True, opacity=1, stroke="white", strokeWidth=1.5
    )
    chart: alt.LayerChart = (line + points).properties(height=320)
    return chart


def error_chart(history: pd.DataFrame) -> alt.Chart:
    """Errore di previsione per trimestre (previsione meno realizzato)."""
    axis = alt.Axis(format="+.1f", title="Errore, punti percentuali", gridColor=GRID, domain=False)
    bars = (
        alt.Chart(history)
        .mark_bar(color=ACCENT, size=6)
        .encode(
            x=alt.X("target:T", title=None, axis=alt.Axis(format="%Y", grid=False)),
            y=alt.Y("error:Q", axis=axis),
            tooltip=[
                alt.Tooltip("quarter:N", title="Trimestre"),
                alt.Tooltip("error:Q", title="Errore", format="+.2f"),
                alt.Tooltip("forecast:Q", title="Previsione", format="+.2f"),
                alt.Tooltip("actual:Q", title="Realizzato", format="+.2f"),
            ],
        )
    )
    chart: alt.Chart = bars.properties(height=220)
    return chart
