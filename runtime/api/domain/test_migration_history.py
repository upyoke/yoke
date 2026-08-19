"""Coverage for the ordered migration history: discovery, order, and contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_apply_contract import (
    ModuleContractError,
    ModuleResolutionError,
)
from yoke_core.domain.migration_history import (
    HistoryError,
    history_dir,
    load_migration_module,
    ordered_entries,
    validate_psycopg_migration_sql,
)


def _write_entry(directory: Path, name: str, body: str = "") -> Path:
    path = directory / f"{name}.py"
    path.write_text(body or "def apply(conn):\n    pass\n")
    return path


def test_entries_order_by_sequence_not_lexically(tmp_path: Path) -> None:
    # Lexical order would put 0010 before 0009; sequence order must not.
    for name in ("0009_ninth", "0010_tenth", "0001_first"):
        _write_entry(tmp_path, name)

    names = [entry.name for entry in ordered_entries(tmp_path)]

    assert names == ["0001_first", "0009_ninth", "0010_tenth"]


def test_entry_digest_hashes_raw_bytes_without_newline_normalization(
    tmp_path: Path,
) -> None:
    path = tmp_path / "0001_raw.py"
    raw = b"def apply(conn):\r\n    pass\r\n"
    path.write_bytes(raw)

    entry = ordered_entries(tmp_path)[0]

    assert entry.content_sha256 == hashlib.sha256(raw).hexdigest()


def test_sequence_gaps_are_allowed(tmp_path: Path) -> None:
    # Numbers order the history; they do not count it. Gaps are ordinary
    # after a squash or an abandoned sequence number.
    _write_entry(tmp_path, "0001_first")
    _write_entry(tmp_path, "0007_seventh")

    assert [entry.sequence for entry in ordered_entries(tmp_path)] == [1, 7]


def test_established_three_digit_identity_remains_discoverable(
    tmp_path: Path,
) -> None:
    _write_entry(tmp_path, "001_first")
    _write_entry(tmp_path, "005_fifth")

    assert [entry.name for entry in ordered_entries(tmp_path)] == [
        "001_first", "005_fifth",
    ]


def test_supporting_files_are_skipped(tmp_path: Path) -> None:
    _write_entry(tmp_path, "0001_first")
    _write_entry(tmp_path, "__init__")
    _write_entry(tmp_path, "_shared_helpers")
    _write_entry(tmp_path, "test_first")

    assert [entry.name for entry in ordered_entries(tmp_path)] == ["0001_first"]


def test_unrecognized_entry_name_is_an_error_not_a_silent_skip(
    tmp_path: Path,
) -> None:
    # A migration that is quietly not discovered is the exact failure the
    # ordered history exists to remove, so a malformed name fails loudly.
    _write_entry(tmp_path, "0001_first")
    _write_entry(tmp_path, "add_a_column")

    with pytest.raises(HistoryError, match="not a valid entry name"):
        ordered_entries(tmp_path)


def test_duplicate_sequence_is_rejected(tmp_path: Path) -> None:
    # Two work items authoring migrations in parallel is how this happens,
    # and the two entries would have no defined order.
    _write_entry(tmp_path, "0001_first")
    _write_entry(tmp_path, "0001_also_first")

    with pytest.raises(HistoryError, match="duplicate sequence 0001"):
        ordered_entries(tmp_path)


def test_missing_history_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(HistoryError, match="directory not found"):
        ordered_entries(tmp_path / "absent")


def test_history_dir_resolves_the_packaged_history() -> None:
    resolved = history_dir(migration_history_package)

    assert resolved.is_dir()
    assert (resolved / "__init__.py").is_file()


def test_packaged_history_is_well_formed() -> None:
    # The real shipped history must always parse: a malformed entry here
    # would fail every boot, so it is worth asserting directly.
    entries = ordered_entries(history_dir(migration_history_package))

    assert entries, "the packaged migration history should not be empty"
    assert [e.sequence for e in entries] == sorted(e.sequence for e in entries)


def test_packaged_history_passes_psycopg_authoring_check() -> None:
    validate_psycopg_migration_sql(history_dir(migration_history_package))


def test_load_requires_a_callable_apply(tmp_path: Path) -> None:
    path = _write_entry(tmp_path, "0001_no_apply", body="apply = 'not callable'\n")

    with pytest.raises(ModuleContractError, match="no callable 'apply"):
        load_migration_module(path, "0001_no_apply")


def test_load_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ModuleResolutionError, match="not found"):
        load_migration_module(tmp_path / "0001_absent.py", "0001_absent")


def test_load_surfaces_an_import_failure(tmp_path: Path) -> None:
    path = _write_entry(tmp_path, "0001_broken", body="raise ValueError('boom')\n")

    with pytest.raises(ModuleResolutionError, match="failed to import"):
        load_migration_module(path, "0001_broken")


def test_load_rejects_bare_percent_in_parameterized_helper_sql(
    tmp_path: Path,
) -> None:
    path = _write_entry(tmp_path, "0001_filter")
    _write_entry(
        tmp_path,
        "_filter_helpers",
        body=(
            "def rows(conn):\n"
            "    return conn.execute(\"SELECT 1 WHERE 'x' LIKE '%x%'\", (1,))\n"
        ),
    )

    with pytest.raises(
        ModuleContractError,
        match=r"_filter_helpers\.py:2:.*bare '%'",
    ):
        load_migration_module(path, "0001_filter", check_psycopg_sql=True)


def test_load_accepts_escaped_percent_and_named_placeholder(tmp_path: Path) -> None:
    path = _write_entry(
        tmp_path,
        "0001_filter",
        body=(
            "def apply(conn):\n"
            "    conn.execute(\"SELECT 'x' LIKE '%%x%%' AND id=%(item_id)s\", "
            "{'item_id': 1})\n"
        ),
    )

    assert callable(
        load_migration_module(path, "0001_filter", check_psycopg_sql=True).apply
    )


def test_load_skips_psycopg_check_by_default(tmp_path: Path) -> None:
    path = _write_entry(
        tmp_path,
        "0001_literal",
        body=(
            "def apply(conn):\n"
            "    conn.execute(\"SELECT '50%' WHERE id=?\", (1,))\n"
        ),
    )

    assert callable(load_migration_module(path, "0001_literal").apply)


def test_psycopg_check_allows_bare_percent_without_params_argument(
    tmp_path: Path,
) -> None:
    path = _write_entry(
        tmp_path,
        "0001_literal",
        body="def apply(conn):\n    conn.execute(\"SELECT '50%'\")\n",
    )

    assert callable(
        load_migration_module(path, "0001_literal", check_psycopg_sql=True).apply
    )
