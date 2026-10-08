"""Controllo che un aggiornamento abbia solo aggiunto righe all'archivio.

Uso: python -m nowcast.ops.archive_check <archivio precedente> <archivio nuovo>

Il workflow automatico lo esegue dopo ogni aggiornamento e prima di salvare: se una riga
esistente è stata modificata o rimossa, l'aggiornamento viene scartato.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from nowcast.data.cache import canonical_order, dataset_version, validate_schema
from nowcast.data.vintages import COLUMNS


def changed_or_removed(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Le righe del vecchio archivio che non compaiono identiche nel nuovo."""
    merged = old.merge(new.drop_duplicates(), on=COLUMNS, how="left", indicator=True)
    return merged.loc[merged["_merge"] == "left_only", COLUMNS]


def assert_append_only(old: pd.DataFrame, new: pd.DataFrame) -> int:
    """Verifica schema e invarianza delle righe esistenti; restituisce le righe aggiunte."""
    validate_schema(old)
    validate_schema(new)
    lost = changed_or_removed(old, new)
    if not lost.empty:
        sample = canonical_order(lost).head(5).to_string(index=False)
        raise ValueError(f"{len(lost)} righe esistenti modificate o rimosse, ad esempio:\n{sample}")
    if new.duplicated(COLUMNS).any():
        raise ValueError("il nuovo archivio contiene righe duplicate")
    return len(new) - len(old)


def main(old_path: str, new_path: str) -> None:
    old, new = pd.read_parquet(Path(old_path)), pd.read_parquet(Path(new_path))
    added = assert_append_only(old, new)
    print(f"archivio: {dataset_version(old)} -> {dataset_version(new)}, {added} righe aggiunte")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
