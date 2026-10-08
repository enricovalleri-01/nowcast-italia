"""I ritardi del registro contro date di pubblicazione reali dei comunicati ISTAT.

La data stimata non deve mai precedere quella reale (sarebbe look-ahead) e non deve
superarla di più di qualche giorno.
"""

import pandas as pd
import pytest

from nowcast.config import load_series
from nowcast.data.vintages import estimated_release

SPECS = {s.id: s for s in load_series()}
TOLERANCE = pd.Timedelta(days=5)

REAL_RELEASES = [
    ("gdp", "2011-12-31", "2012-02-15"),  # stima preliminare a 45 giorni
    ("gdp", "2018-03-31", "2018-05-02"),  # primo trimestre con la stima a 30 giorni
    ("retail", "2011-07-31", "2011-09-23"),
    ("retail", "2011-09-30", "2011-11-25"),
    ("retail", "2017-01-31", "2017-03-15"),  # primo mese a 40 giorni
    ("ip", "2011-07-31", "2011-09-12"),
    ("unemployment", "2011-12-31", "2012-01-31"),
    ("exports", "2011-11-30", "2012-01-18"),
    ("imports", "2011-11-30", "2012-01-18"),
]


@pytest.mark.parametrize(("series_id", "period", "real"), REAL_RELEASES)
def test_estimated_release_is_not_before_the_real_one(
    series_id: str, period: str, real: str
) -> None:
    estimated = estimated_release(pd.DatetimeIndex([period]), SPECS[series_id])[0]
    assert pd.Timestamp(real) <= estimated <= pd.Timestamp(real) + TOLERANCE
