import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest
import yaml

from nowcast.config import ROOT, SeriesSpec
from nowcast.data.vintages import import_history, redate, update
from nowcast.ops.archive_check import assert_append_only, changed_or_removed

TODAY = pd.Timestamp("2026-10-08")
WEEK = pd.Timedelta(days=7)
SPEC = SeriesSpec("ip", "ip", "eurostat", "M", "none", 40, "real")


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2026-05-31", periods=len(values), freq="ME"))


def archive() -> pd.DataFrame:
    return import_history(series([1.0, 2.0]), SPEC, TODAY)


def test_ordinary_update_passes_and_counts_added_rows() -> None:
    new = update(series([1.0, 2.5, 3.0]), SPEC, TODAY + WEEK, archive())
    assert assert_append_only(archive(), new) == 2  # una revisione e un periodo nuovo


def test_unchanged_archive_passes_with_zero_rows_added() -> None:
    assert assert_append_only(archive(), archive().iloc[::-1]) == 0


def test_changed_value_is_rejected() -> None:
    tampered = archive()
    tampered.loc[0, "value"] = 9.0
    with pytest.raises(ValueError, match="modificate o rimosse"):
        assert_append_only(archive(), tampered)


def test_removed_row_is_rejected() -> None:
    assert len(changed_or_removed(archive(), archive().iloc[1:])) == 1
    with pytest.raises(ValueError, match="modificate o rimosse"):
        assert_append_only(archive(), archive().iloc[1:])


def test_calendar_correction_is_rejected_as_an_ordinary_update() -> None:
    moved = redate(archive(), SeriesSpec("ip", "ip", "eurostat", "M", "none", 10, "real"))
    with pytest.raises(ValueError, match="modificate o rimosse"):
        assert_append_only(archive(), moved)


def test_duplicated_rows_and_wrong_schema_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        assert_append_only(archive(), pd.concat([archive(), archive()], ignore_index=True))
    with pytest.raises(ValueError, match="colonne inattese"):
        assert_append_only(archive(), archive().drop(columns="seq"))


# --- workflow e script


def workflow() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((ROOT / ".github" / "workflows" / "update.yml").read_text())


def commands() -> str:
    return "\n".join(step.get("run", "") for step in workflow()["jobs"]["update"]["steps"])


def test_workflow_only_ever_runs_the_ordinary_update() -> None:
    assert "nowcast.pipeline update-data" in commands()
    assert "init-data" not in commands() and "redate-data" not in commands()


def test_workflow_checks_the_archive_before_saving_it() -> None:
    text = commands()
    assert text.index("update-data") < text.index("archive_check") < text.index("git push")


def test_workflow_writes_only_to_the_data_branch() -> None:
    steps = workflow()["jobs"]["update"]["steps"]
    code, data = steps[0]["with"], steps[1]["with"]
    assert code == {"ref": "main", "persist-credentials": False}
    assert data == {"ref": "data", "path": "_data"}
    pushes = [line.strip() for line in commands().splitlines() if "git push" in line]
    assert pushes == ["git push origin HEAD:data"]


def test_workflow_takes_the_key_from_secrets_only() -> None:
    text = (ROOT / ".github" / "workflows" / "update.yml").read_text()
    assert "${{ secrets.FRED_API_KEY }}" in text
    assert text.count("FRED_API_KEY") == 2


def test_backup_script_copies_and_verifies(tmp_path: Path) -> None:
    done = subprocess.run(
        [str(ROOT / "scripts" / "backup_data.sh"), str(tmp_path / "copia")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if "Niente da copiare" in done.stderr:
        pytest.skip("nessun dato locale da copiare")
    assert done.returncode == 0, done.stderr
    [created] = list((tmp_path / "copia").iterdir())
    assert (created / "SHA256SUMS").read_text().count("\n") >= 1


def test_backup_script_refuses_a_destination_inside_the_repository() -> None:
    inside = ROOT / "data" / "_backup_di_prova"
    done = subprocess.run(
        [str(ROOT / "scripts" / "backup_data.sh"), str(inside)],
        capture_output=True, text=True, check=False, env={**os.environ},
    )  # fmt: skip
    inside.rmdir()
    assert done.returncode == 1 and "fuori dal repository" in done.stderr
