from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import SeriesSpec
from nowcast.data import cache
from nowcast.data.vintages import import_history, update

TODAY = pd.Timestamp("2026-10-08")
SPEC = SeriesSpec("ip", "ip", "eurostat", "M", "none", 40, "real")


def table() -> pd.DataFrame:
    series = pd.Series([1.0, 2.0], index=pd.date_range("2026-06-30", periods=2, freq="ME"))
    first = import_history(series, SPEC, TODAY)
    return update(series + [0.0, 0.5], SPEC, TODAY + pd.Timedelta(days=7), first)


def test_version_ignores_row_order() -> None:
    assert cache.dataset_version(table()) == cache.dataset_version(table().iloc[::-1])


@pytest.mark.parametrize("column", ["value", "release_date", "release_source", "seq"])
def test_version_changes_with_any_content(column: str) -> None:
    changed = table()
    changed.loc[0, column] = {
        "value": 9.0,
        "release_date": pd.Timestamp("2020-01-01"),
        "release_source": "alfred",
        "seq": 5,
    }[column]
    assert cache.dataset_version(changed) != cache.dataset_version(table())


def test_version_rejects_a_wrong_type_instead_of_hashing_it() -> None:
    as_int = table().astype({"value": "int64"})
    with pytest.raises(ValueError, match="tipi inattesi"):
        cache.dataset_version(as_int)


def test_version_rejects_renamed_or_missing_columns() -> None:
    with pytest.raises(ValueError, match="colonne inattese"):
        cache.dataset_version(table().rename(columns={"value": "valore"}))
    with pytest.raises(ValueError, match="colonne inattese"):
        cache.dataset_version(table().drop(columns="seq"))


def test_saved_version_is_kept_and_reloaded_identically(tmp_path: Path) -> None:
    first = table()
    version = cache.save_observations(first, tmp_path / "obs.parquet", tmp_path / "versions")
    later = update(
        pd.Series([7.0], index=[pd.Timestamp("2026-08-31")]),
        SPEC,
        TODAY + pd.Timedelta(days=14),
        first,
    )
    cache.save_observations(later, tmp_path / "obs.parquet", tmp_path / "versions")
    reloaded = cache.load_version(version, tmp_path / "versions")
    assert cache.dataset_version(reloaded) == version
    assert len(reloaded) == len(first) < len(cache.load_observations(tmp_path / "obs.parquet"))


def test_tampered_version_file_is_rejected(tmp_path: Path) -> None:
    version = cache.save_observations(table(), tmp_path / "obs.parquet", tmp_path / "versions")
    tampered = table()
    tampered.loc[0, "value"] = 99.0
    tampered.to_parquet(tmp_path / "versions" / f"{version}.parquet", index=False)
    with pytest.raises(ValueError, match="non corrisponde"):
        cache.load_version(version, tmp_path / "versions")
