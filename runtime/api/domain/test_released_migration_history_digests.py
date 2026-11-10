"""The packaged baseline identity matches current ledger evidence."""

from yoke_core.domain import migrations
from yoke_core.domain.migration_baseline import declared_baseline
from yoke_core.domain.migration_history import history_dir, ordered_entries


def test_packaged_history_has_one_baseline_and_only_subsequent_scripts():
    directory = history_dir(migrations)
    baseline = declared_baseline(directory)
    assert baseline.name == "0106_baseline"
    assert (
        baseline.content_sha256
        == "e186ea2a939a1ae1451e96a69a25c9bfda163f0f92d0e28b48dc89913dea23dc"
    )
    assert tuple(
        entry for entry in ordered_entries(directory) if entry.is_baseline
    ) == (baseline,)
    scripts = [entry for entry in ordered_entries(directory) if not entry.is_baseline]
    assert all(entry.sequence > baseline.sequence for entry in scripts)
    assert {entry.path for entry in scripts} == set(directory.glob("[0-9]*.py"))


def test_validation_database_ledger_matches_current_history(test_db):
    entries = {entry.name: entry for entry in ordered_entries(history_dir(migrations))}
    ledger = dict(
        test_db.execute("SELECT migration_name,content_sha256 FROM applied_migrations")
    )
    assert set(ledger) == set(entries)
    assert all(
        digest == entries[name].content_sha256 for name, digest in ledger.items()
    )
