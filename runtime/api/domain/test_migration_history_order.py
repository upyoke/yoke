"""Declared PRECEDES reorders apply order without touching ordinals."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    HistoryError,
    history_dir,
    ordered_entries,
    ordinal_entries,
)


def _write(directory: Path, name: str, precedes: str = "") -> None:
    header = f"PRECEDES = {precedes}\n" if precedes else ""
    (directory / f"{name}.py").write_text(header + "def apply(conn):\n    pass\n")


def _names(entries) -> list[str]:
    return [entry.name for entry in entries]


def test_declarer_runs_immediately_before_its_target(tmp_path: Path) -> None:
    for name in ("0001_a", "0002_b", "0003_c", "0004_d"):
        _write(tmp_path, name)
    _write(tmp_path, "0005_e", '("0002_b",)')

    assert _names(ordered_entries(tmp_path)) == [
        "0001_a",
        "0005_e",
        "0002_b",
        "0003_c",
        "0004_d",
    ]


def test_ordinal_view_ignores_the_declaration(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a")
    _write(tmp_path, "0002_b", '("0001_a",)')

    assert _names(ordinal_entries(tmp_path)) == ["0001_a", "0002_b"]
    assert _names(ordered_entries(tmp_path)) == ["0002_b", "0001_a"]


def test_chained_and_multiple_targets_resolve(tmp_path: Path) -> None:
    for name in ("0001_a", "0002_b", "0003_c"):
        _write(tmp_path, name)
    _write(tmp_path, "0004_d", '("0003_c", "0002_b")')
    _write(tmp_path, "0005_e", '("0004_d",)')

    assert _names(ordered_entries(tmp_path)) == [
        "0001_a",
        "0005_e",
        "0004_d",
        "0002_b",
        "0003_c",
    ]


@pytest.mark.parametrize(
    "precedes, reason",
    [
        ('"0001_a"', "literal tuple"),
        ("()", "literal tuple"),
        ("(NAME,)", "literal tuple"),
        ('("0009_missing",)', "not an entry in this history"),
        ('("0003_c",)', "does not have a lower ordinal"),
        ('("0002_b",)', "does not have a lower ordinal"),
    ],
)
def test_malformed_declarations_refuse_by_name(
    tmp_path: Path, precedes: str, reason: str
) -> None:
    _write(tmp_path, "0001_a")
    _write(tmp_path, "0002_b", precedes)
    _write(tmp_path, "0003_c")

    with pytest.raises(HistoryError, match=reason):
        ordered_entries(tmp_path)


def test_packaged_repin_runs_immediately_before_retire_advance() -> None:
    names = _names(ordered_entries(history_dir(migration_history_package)))

    position = names.index("0060_repin_advance_bound_items")
    assert names[position + 1] == "0053_retire_advance_skill"
