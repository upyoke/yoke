"""A baseline squash retires dedicated entry tests in the same change."""

from pathlib import Path

import pytest

from runtime.api.domain.migration_entry_test_policy import (
    missing_test_entries,
    obsolete_dedicated_tests,
)
from yoke_core.domain import migrations
from yoke_core.domain.migration_history import history_dir, ordered_entries


@pytest.mark.parametrize(
    "source",
    [
        'entry = importlib.import_module("yoke_core.domain.migrations.0001_old")',
        'ENTRY_NAME = "0001_old"',
        '_ENTRY_SLUG = "old"',
    ],
)
def test_squash_requires_retiring_the_dedicated_test(source):
    assert missing_test_entries(source, {"0002_current"})
    assert not missing_test_entries(source, {"0001_old", "0002_current"})


def test_historical_engine_fixture_names_do_not_require_an_entry():
    assert not missing_test_entries('history = ["0001_old"]', {"0002_current"})


def test_packaged_history_has_no_obsolete_dedicated_tests():
    names = {entry.name for entry in ordered_entries(history_dir(migrations))}
    directory = Path(__file__).resolve().parents[1]
    obsolete = obsolete_dedicated_tests(directory, names)
    assert not obsolete, (
        "migration_entry_test_retirement_required: delete dedicated tests when "
        f"their entries are folded into the baseline: {obsolete}"
    )
