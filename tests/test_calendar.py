"""I ritardi del registro contro date di pubblicazione reali dei comunicati ISTAT.

La data stimata non deve mai precedere quella reale: sarebbe look-ahead. Può seguirla,
perché un ritardo fisso deve coprire il caso peggiore di un calendario che oscilla; il
margine massimo ammesso è dichiarato qui sotto.
"""

import pandas as pd
import pytest

from nowcast.config import load_series
from nowcast.data.vintages import estimated_release

SPECS = {s.id: s for s in load_series()}
MAX_DELAY = pd.Timedelta(days=12)

REAL_RELEASES = [
    ("gdp", "2011-12-31", "2012-02-15"),  # stima preliminare a 45 giorni
    ("gdp", "2018-03-31", "2018-05-02"),  # primo trimestre con la stima a 30 giorni
    ("retail", "2011-07-31", "2011-09-23"),
    ("retail", "2011-09-30", "2011-11-25"),
    ("retail", "2017-01-31", "2017-03-15"),  # primo mese a circa 40 giorni
    ("retail", "2018-01-31", "2018-03-14"),
    ("retail", "2018-02-28", "2018-04-11"),
    ("retail", "2019-01-31", "2019-03-07"),
    ("retail", "2021-01-31", "2021-03-05"),
    ("retail", "2022-01-31", "2022-03-08"),
    ("retail", "2023-01-31", "2023-03-08"),
    ("retail", "2024-01-31", "2024-03-15"),  # caso peggiore riscontrato: 44 giorni
    ("retail", "2025-01-31", "2025-03-05"),
    ("ip", "2011-07-31", "2011-09-12"),
    ("unemployment", "2011-12-31", "2012-01-31"),
    ("exports", "2011-11-30", "2012-01-18"),
    ("imports", "2011-11-30", "2012-01-18"),
    ("hicp", "2019-01-31", "2019-02-04"),
    ("hicp", "2022-01-31", "2022-02-02"),
    ("hicp", "2023-01-31", "2023-02-01"),
    ("hicp", "2025-01-31", "2025-02-03"),
]


@pytest.mark.parametrize(("series_id", "period", "real"), REAL_RELEASES)
def test_estimated_release_is_not_before_the_real_one(
    series_id: str, period: str, real: str
) -> None:
    estimated = estimated_release(pd.DatetimeIndex([period]), SPECS[series_id])[0]
    assert estimated >= pd.Timestamp(real)


@pytest.mark.parametrize(("series_id", "period", "real"), REAL_RELEASES)
def test_estimated_release_is_not_too_late(series_id: str, period: str, real: str) -> None:
    estimated = estimated_release(pd.DatetimeIndex([period]), SPECS[series_id])[0]
    assert estimated <= pd.Timestamp(real) + MAX_DELAY
